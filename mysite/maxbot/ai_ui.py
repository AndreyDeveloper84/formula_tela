"""Render action_data → MAX inline keyboard + текст сообщения.

Phase 2.3 §T07. Чистый рендер — никаких network calls / ORM-write'ов.
Принимает action_data dict (готовый, возможно enrich'ed slots/bookings),
возвращает (text, list[Attachment]).

action_type → render function:
  show_masters       → render_show_masters
  show_slots         → render_show_slots
  confirm_booking    → render_confirm_booking
  show_my_bookings   → render_show_my_bookings
  ask_clarification  → render_ask_clarification

Callback payloads (стабильный wire-format для T08 callback handlers):
  cb:ai:pick_master:{conv}:{master_id}
  cb:ai:pick_slot:{conv}:{slot_iso}
  cb:ai:confirm:{conv}
  cb:ai:cancel:{conv}
  cb:ai:edit:{conv}
  cb:ai:answer:{conv}:{option_idx}

Цвета через Intent enum:
  confirm_booking «Да» → POSITIVE (зелёная)
  confirm_booking «Отмена» → NEGATIVE (красная)
  Остальные → DEFAULT (серая)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from maxapi.enums.intent import Intent
from maxapi.types import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


# ─── Callback payload constants ────────────────────────────────────────────


def _payload_pick_master(conv_id: str, master_id: int) -> str:
    return f"cb:ai:pick_master:{conv_id}:{master_id}"


def _payload_pick_slot(conv_id: str, slot_iso: str) -> str:
    return f"cb:ai:pick_slot:{conv_id}:{slot_iso}"


def _payload_confirm(conv_id: str) -> str:
    return f"cb:ai:confirm:{conv_id}"


def _payload_cancel(conv_id: str) -> str:
    return f"cb:ai:cancel:{conv_id}"


def _payload_edit(conv_id: str) -> str:
    return f"cb:ai:edit:{conv_id}"


def _payload_answer(conv_id: str, option_idx: int) -> str:
    return f"cb:ai:answer:{conv_id}:{option_idx}"


def _payload_suggest_date(conv_id: str, offset: str) -> str:
    """Phase 0: fallback при пустых slots → suggest альтернативной даты.

    offset — relative ("+1", "+3", etc) — pseudo-msg «покажи слоты через N дней»
    LLM сам распарсит relative date через today из system_prompt'а.
    """
    return f"cb:ai:suggest_date:{conv_id}:{offset}"


def _payload_suggest_master(conv_id: str) -> str:
    """Phase 0: fallback при пустых slots → подобрать другого мастера."""
    return f"cb:ai:suggest_master:{conv_id}"


# ─── render_action — главный диспетчер ───────────────────────────────────


def render_action(
    *,
    conversation_id: str,
    action_type: str,
    action_data: dict[str, Any],
) -> tuple[str, list]:
    """Возвращает (text, list[Attachment]) для send_message.

    Unknown action_type → safe default (текст + нет attachments). Никогда
    не raise — UI всегда должен что-то отдать клиенту.
    """
    conv_id = str(conversation_id)
    if action_type == "show_masters":
        return render_show_masters(conv_id, action_data)
    if action_type == "show_slots":
        return render_show_slots(conv_id, action_data)
    if action_type == "confirm_booking":
        return render_confirm_booking(conv_id, action_data)
    if action_type == "show_my_bookings":
        return render_show_my_bookings(conv_id, action_data)
    if action_type == "ask_clarification":
        return render_ask_clarification(conv_id, action_data)
    # Unknown — graceful default
    return ("Не получилось разобраться. Попробуйте сформулировать иначе.", [])


# ─── show_masters ──────────────────────────────────────────────────────────


def render_show_masters(conv_id: str, data: dict[str, Any]) -> tuple[str, list]:
    masters = data.get("masters") or []
    explanation = data.get("explanation") or ""

    if not masters:
        all_busy_date = data.get("all_busy_date") or ""
        if all_busy_date:
            text = (
                f"На {all_busy_date} свободных мастеров нет.\n"
                "Попробовать другой день?"
            )
            builder = InlineKeyboardBuilder()
            builder.row(
                CallbackButton(
                    text="📅 Завтра",
                    payload=_payload_suggest_date(conv_id, "+1"),
                ),
                CallbackButton(
                    text="📆 Через 3 дня",
                    payload=_payload_suggest_date(conv_id, "+3"),
                ),
            )
            builder.row(CallbackButton(
                text="📅 Через неделю",
                payload=_payload_suggest_date(conv_id, "+7"),
            ))
            return (text, [builder.as_markup()])
        return ("К сожалению, не нашёл подходящих мастеров под ваш запрос.", [])

    lines: list[str] = []
    if explanation:
        lines.append(explanation)
        lines.append("")
    for idx, item in enumerate(masters, 1):
        m = item.get("master", {})
        name = m.get("name", "—")
        spec = m.get("specialization", "")
        services = m.get("services_preview") or []
        services_text = ", ".join(services[:3]) if services else ""
        score = item.get("match_score")
        reasons = item.get("match_reasons") or []

        line = f"{idx}. {name}"
        if spec:
            line += f" — {spec}"
        if score is not None:
            line += f" (★{score}%)"
        lines.append(line)
        if services_text:
            lines.append(f"   Услуги: {services_text}")
        if reasons:
            lines.append(f"   {'; '.join(reasons[:2])}")

    builder = InlineKeyboardBuilder()
    for item in masters:
        m = item.get("master", {})
        mid = m.get("id")
        name = m.get("name", "—")
        if mid is None:
            continue
        builder.row(CallbackButton(
            text=f"💆 {name}",
            payload=_payload_pick_master(conv_id, mid),
        ))

    return ("\n".join(lines), [builder.as_markup()])


# ─── show_slots ────────────────────────────────────────────────────────────


def render_show_slots(conv_id: str, data: dict[str, Any]) -> tuple[str, list]:
    master_name = data.get("master_name") or "мастер"
    service_name = data.get("service_name") or "услуга"
    date_str = data.get("date") or ""
    slots = data.get("slots")

    # Slots field отсутствует — placeholder (concierge ещё не enrich'ил)
    if slots is None:
        return (
            f"{master_name} — {service_name}, {date_str}.\n"
            "Загружаю свободное время…",
            [],
        )

    # Slots empty — нет свободных. Phase 0: НЕ тупик, а fallback-кнопки.
    if not slots:
        text = (
            f"{master_name} — {service_name}, {date_str}.\n"
            "К сожалению, свободных слотов на эту дату нет.\n"
            "Хотите попробовать другой день или мастера?"
        )
        builder = InlineKeyboardBuilder()
        builder.row(
            CallbackButton(
                text="📅 На завтра",
                payload=_payload_suggest_date(conv_id, "+1"),
            ),
            CallbackButton(
                text="📆 Через 3 дня",
                payload=_payload_suggest_date(conv_id, "+3"),
            ),
        )
        builder.row(CallbackButton(
            text="👥 Другой мастер",
            payload=_payload_suggest_master(conv_id),
        ))
        return (text, [builder.as_markup()])

    lines = [
        f"{master_name} — {service_name}",
        f"Свободное время {date_str}:",
    ]
    builder = InlineKeyboardBuilder()
    # Группируем по 3 кнопки в ряду — компактная сетка времён
    row_buttons: list[CallbackButton] = []
    for slot in slots:
        slot_str = str(slot)
        # slot — может быть "10:00" или ISO. Оба ок для payload.
        row_buttons.append(CallbackButton(
            text=slot_str,
            payload=_payload_pick_slot(conv_id, slot_str),
        ))
        if len(row_buttons) == 3:
            builder.row(*row_buttons)
            row_buttons = []
    if row_buttons:
        builder.row(*row_buttons)

    return ("\n".join(lines), [builder.as_markup()])


# ─── confirm_booking ──────────────────────────────────────────────────────


def render_confirm_booking(conv_id: str, data: dict[str, Any]) -> tuple[str, list]:
    master_name = data.get("master_name") or "мастер"
    service_name = data.get("service_name") or "услуга"
    datetime_str = data.get("datetime") or ""
    price_from = data.get("price_from")
    duration_min = data.get("duration_min")

    # Парсим datetime для вывода — fallback на raw если что-то странное
    pretty_when = datetime_str
    try:
        dt = datetime.fromisoformat(datetime_str)
        pretty_when = dt.strftime("%d.%m.%Y в %H:%M")
    except (ValueError, TypeError):
        pass

    lines = [
        "Проверьте детали записи:",
        "",
        f"💆 Мастер: {master_name}",
        f"📋 Услуга: {service_name}",
        f"📅 Когда: {pretty_when}",
    ]
    if duration_min:
        lines.append(f"⏱️ Длительность: {duration_min} мин")
    if price_from:
        lines.append(f"💰 Стоимость: от {price_from} ₽")
    lines.append("")
    lines.append("Подтвердить запись?")

    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text="✅ Да, записать",
            payload=_payload_confirm(conv_id),
            intent=Intent.POSITIVE,
        ),
        CallbackButton(
            text="❌ Отмена",
            payload=_payload_cancel(conv_id),
            intent=Intent.NEGATIVE,
        ),
    )
    builder.row(CallbackButton(
        text="✏️ Изменить",
        payload=_payload_edit(conv_id),
    ))

    return ("\n".join(lines), [builder.as_markup()])


# ─── show_my_bookings ─────────────────────────────────────────────────────


def render_show_my_bookings(conv_id: str, data: dict[str, Any]) -> tuple[str, list]:
    filter_value = data.get("filter") or "upcoming"
    bookings = data.get("bookings")

    # Поле bookings отсутствует — placeholder
    if bookings is None:
        return ("Загружаю ваши записи…", [])

    if not bookings:
        msg = {
            "upcoming": "У вас пока нет предстоящих записей.",
            "past": "У вас пока нет прошедших записей.",
            "all": "У вас пока нет записей.",
        }.get(filter_value, "У вас пока нет записей.")
        return (msg, [])

    title = {
        "upcoming": "Ваши предстоящие записи:",
        "past": "Ваши прошедшие записи:",
        "all": "Ваши записи:",
    }.get(filter_value, "Ваши записи:")
    lines = [title, ""]

    for b in bookings:
        master_name = b.get("master_name") or "—"
        service_name = b.get("service_name") or "—"
        when = b.get("datetime") or ""
        try:
            dt = datetime.fromisoformat(when)
            pretty = dt.strftime("%d.%m.%Y %H:%M")
        except (ValueError, TypeError):
            pretty = when
        lines.append(f"• {pretty} — {master_name}, {service_name}")

    return ("\n".join(lines), [])


# ─── ask_clarification ────────────────────────────────────────────────────


def render_ask_clarification(conv_id: str, data: dict[str, Any]) -> tuple[str, list]:
    question = (data.get("question") or "Уточните, пожалуйста?").strip()
    options = data.get("options") or []

    if not options:
        # Только текст вопроса, без кнопок — клиент ответит свободно
        return (question, [])

    builder = InlineKeyboardBuilder()
    for idx, opt in enumerate(options[:5]):  # макс 5 опций per схема
        builder.row(CallbackButton(
            text=str(opt),
            payload=_payload_answer(conv_id, idx),
        ))
    return (question, [builder.as_markup()])
