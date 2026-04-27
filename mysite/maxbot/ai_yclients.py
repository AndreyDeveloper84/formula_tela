"""Enrichment action_data через YClients API — для show_slots и show_my_bookings.

Phase 2.3 пост-T11. ai_tool_handlers — side-effect-free валидаторы, реальный
fetch slots/records делается здесь на пути render → клиент.

Вызывается из ai_concierge.send_message ПОСЛЕ dispatch_tool_call,
ДО сохранения Message в БД (чтобы action_data в БД сразу содержал slots).

Если YClients staff_id или ServiceOption.yclients_service_id не настроены —
graceful degradation: action_data['slots']=[] → render показывает «слотов нет,
попробуйте другой день?». Менеджер должен заполнить mapping через /admin/.
"""
from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import sync_to_async

from services_app.models import BotUser, Master, Service, ServiceOption


logger = logging.getLogger("maxbot.ai_yclients")


@sync_to_async
def _load_master_and_service(master_id: int, service_id: int):
    """Возвращает (master, service, yclients_service_id из ServiceOption или None)."""
    master = Master.objects.filter(id=master_id, is_active=True).first()
    service = Service.objects.filter(id=service_id, is_active=True).first()
    yc_svc_id = (
        ServiceOption.objects
        .filter(service_id=service_id, yclients_service_id__isnull=False)
        .exclude(yclients_service_id="")
        .order_by("order", "id")
        .values_list("yclients_service_id", flat=True)
        .first()
    )
    return master, service, yc_svc_id


async def enrich_show_slots(action_data: dict[str, Any], *, yclients_api=None) -> dict[str, Any]:
    """Mutates action_data — добавляет master_name, service_name, slots.

    Возвращает мутированный dict (для chain-like usage). На любом fail
    устанавливает slots=[] чтобы render показал «нет слотов».
    """
    master_id = action_data.get("master_id")
    service_id = action_data.get("service_id")
    date_str = action_data.get("date")

    if not master_id or not service_id or not date_str:
        action_data["slots"] = []
        return action_data

    master, service, yc_svc_id = await _load_master_and_service(master_id, service_id)
    action_data["master_name"] = master.name if master else "—"
    action_data["service_name"] = service.name if service else "—"

    # Без mapping native booking невозможен → empty slots, render покажет
    # «нет слотов», потом user через ask_clarification спросит другую дату/услугу.
    if not master or not master.yclients_staff_id or not yc_svc_id:
        logger.info(
            "enrich_show_slots: no yclients mapping, master_id=%s service_id=%s",
            master_id, service_id,
        )
        action_data["slots"] = []
        return action_data

    if yclients_api is None:
        from services_app.yclients_api import get_yclients_api
        yclients_api = get_yclients_api()

    try:
        # YClients get_available_times → List[str] в формате "HH:MM"
        times = await sync_to_async(yclients_api.get_available_times)(
            staff_id=int(master.yclients_staff_id),
            date=date_str,
            service_ids=[int(yc_svc_id)],
        )
        # Берём top-12 чтобы UI не уходил в стену кнопок (3 кнопки/ряд × 4 ряда)
        action_data["slots"] = [str(t) for t in (times or [])][:12]
        logger.info(
            "enrich_show_slots: %d slots for master=%s service=%s date=%s",
            len(action_data["slots"]), master_id, service_id, date_str,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("enrich_show_slots: YClients fetch failed: %s", exc)
        action_data["slots"] = []

    return action_data


@sync_to_async
def _master_name_by_yclients_staff(staff_id) -> str:
    """Резолвит yclients staff_id → наше имя (для записи)."""
    if not staff_id:
        return "—"
    m = Master.objects.filter(yclients_staff_id=str(staff_id)).first()
    return m.name if m else f"staff#{staff_id}"


async def enrich_show_my_bookings(
    action_data: dict[str, Any],
    bot_user: BotUser,
    *,
    yclients_api=None,
) -> dict[str, Any]:
    """Mutates action_data — добавляет bookings (list[dict]) для рендера.

    Если у bot_user нет client_phone — empty list (render: «нет записей»).
    Filter из action_data (upcoming/past/all) применяется на сервере YClients
    параметром start/end дат если возможно, иначе локально.
    """
    filter_value = action_data.get("filter") or "upcoming"
    phone = (bot_user.client_phone or "").strip()
    if not phone:
        action_data["bookings"] = []
        return action_data

    if yclients_api is None:
        from services_app.yclients_api import get_yclients_api
        yclients_api = get_yclients_api()

    try:
        # YClients get_records принимает client_phone (или client_id)
        records = await sync_to_async(yclients_api.get_records)(
            client_phone=phone,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("enrich_show_my_bookings: YClients fetch failed: %s", exc)
        action_data["bookings"] = []
        return action_data

    bookings: list[dict[str, Any]] = []
    for rec in records or []:
        # YClients record shape: {datetime, services: [{title}], staff: {name}, ...}
        services = rec.get("services") or []
        staff = rec.get("staff") or {}
        bookings.append({
            "datetime": rec.get("datetime") or rec.get("date") or "",
            "master_name": staff.get("name") or "—",
            "service_name": services[0].get("title") if services else "—",
        })

    # Filter upcoming/past локально (YClients API не всегда умеет фильтр)
    if filter_value in ("upcoming", "past"):
        from datetime import datetime as dt_cls
        now = dt_cls.now().astimezone()
        filtered: list[dict[str, Any]] = []
        for b in bookings:
            try:
                bdt = dt_cls.fromisoformat(b["datetime"])
                if filter_value == "upcoming" and bdt >= now:
                    filtered.append(b)
                elif filter_value == "past" and bdt < now:
                    filtered.append(b)
            except (ValueError, TypeError):
                if filter_value == "all":
                    filtered.append(b)
        bookings = filtered

    action_data["bookings"] = bookings[:10]
    logger.info(
        "enrich_show_my_bookings: %d bookings filter=%s phone=%s",
        len(bookings), filter_value, phone[:4] + "...",
    )
    return action_data
