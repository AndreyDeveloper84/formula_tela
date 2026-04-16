"""
Analytics Agent — собирает данные за неделю из YClients API (реальные записи)
и локальных заявок сайта, анализирует через GPT, сохраняет в БД и шлёт в Telegram.
"""
import datetime
import logging

from django.conf import settings
from django.utils import timezone

from agents.agents import get_openai_client
from agents.agents._lifecycle import ensure_task_finalized
from agents.models import AgentReport, AgentTask, DailyMetric
from agents.telegram import send_telegram

logger = logging.getLogger(__name__)

# Статусы записей в YClients
YCLIENTS_STATUS_LABELS = {
    1: "ожидает",
    2: "подтверждена",
    3: "пришёл",
    4: "не пришёл",
    5: "отменена (адм.)",
    6: "отменена (клиент)",
    7: "отменена",
}


def _gather_yclients(start_date: str, end_date: str) -> dict:
    """Получить статистику из YClients API. Возвращает пустой dict при ошибке."""
    try:
        from services_app.yclients_api import YClientsAPIError, get_yclients_api
        api = get_yclients_api()
        records = api.get_records(start_date=start_date, end_date=end_date)
    except Exception as exc:
        logger.warning("YClients get_records недоступен: %s", exc)
        return {}

    if not records:
        return {"yclients_total": 0, "yclients_records": []}

    by_service: dict[str, int] = {}
    by_master: dict[str, int] = {}
    by_status: dict[str, int] = {}
    cancelled = 0
    revenue = 0.0

    for rec in records:
        # Услуги
        for svc in rec.get("services", []):
            name = svc.get("title") or svc.get("name") or "Неизвестная услуга"
            by_service[name] = by_service.get(name, 0) + 1

        # Мастер
        staff = rec.get("staff") or {}
        master_name = staff.get("name", "Неизвестно")
        by_master[master_name] = by_master.get(master_name, 0) + 1

        # Статус
        status = rec.get("status") or {}
        status_id = status.get("id", 0)
        label = YCLIENTS_STATUS_LABELS.get(status_id, f"статус {status_id}")
        by_status[label] = by_status.get(label, 0) + 1
        if status_id in (5, 6, 7):
            cancelled += 1

        # Выручка
        from agents.agents._revenue import extract_record_revenue
        revenue += extract_record_revenue(rec)

    top_services = sorted(by_service.items(), key=lambda x: -x[1])[:10]
    top_masters = sorted(by_master.items(), key=lambda x: -x[1])[:5]

    return {
        "yclients_total": len(records),
        "yclients_cancelled": cancelled,
        "yclients_cancel_rate": round(cancelled / len(records) * 100) if records else 0,
        "yclients_revenue": round(revenue),
        "yclients_top_services": top_services,
        "yclients_top_masters": top_masters,
        "yclients_by_status": by_status,
    }


def _build_prompt(data: dict) -> str:
    # Заявки с сайта
    site_top = "\n".join(
        f"  - {name}: {cnt}" for name, cnt in data.get("top_services", [])
    ) or "  нет данных"

    lines = [
        f"Данные салона красоты «Формула Тела» за период {data['period']}:",
        "",
    ]

    # Блок YClients (реальные визиты)
    if data.get("yclients_total") is not None:
        yc_top = "\n".join(
            f"  - {name}: {cnt}" for name, cnt in data.get("yclients_top_services", [])
        ) or "  нет данных"
        yc_masters = "\n".join(
            f"  - {name}: {cnt} записей" for name, cnt in data.get("yclients_top_masters", [])
        ) or "  нет данных"
        statuses = ", ".join(
            f"{s}: {c}" for s, c in data.get("yclients_by_status", {}).items()
        ) or "нет данных"

        lines += [
            "=== YClients (реальные визиты) ===",
            f"- Всего записей: {data['yclients_total']}",
            f"- Отменены: {data.get('yclients_cancelled', 0)} ({data.get('yclients_cancel_rate', 0)}%)",
            f"- Выручка: {data.get('yclients_revenue', 0):,} руб.",
            f"- Статусы: {statuses}",
            f"- Топ услуг:\n{yc_top}",
            f"- Загрузка мастеров:\n{yc_masters}",
            "",
        ]
    else:
        lines += ["=== YClients: данные недоступны ===", ""]

    # Блок заявок с сайта
    lines += [
        "=== Заявки с сайта (форма) ===",
        f"- Всего: {data['total_requests']}",
        f"- Обработано: {data['processed']} ({data['processed_pct']}%)",
        f"- Не обработано: {data['unprocessed']}",
        f"- Топ услуг:\n{site_top}",
        "",
        f"Активных мастеров в системе: {data['active_masters']}",
        "",
        "Сделай краткий анализ (4-6 предложений): что идёт хорошо, что вызывает опасения, "
        "и 2-3 конкретные рекомендации для улучшения показателей.",
    ]

    return "\n".join(lines)


class AnalyticsAgent:
    def gather_data(self) -> dict:
        from services_app.models import BookingRequest, Master

        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        # --- Локальные заявки с сайта ---
        qs = BookingRequest.objects.filter(created_at__date__gte=week_ago)
        total = qs.count()
        processed = qs.filter(is_processed=True).count()
        unprocessed = qs.filter(is_processed=False).count()

        by_service: dict[str, int] = {}
        for name in qs.values_list("service_name", flat=True):
            by_service[name] = by_service.get(name, 0) + 1
        top_services = sorted(by_service.items(), key=lambda x: -x[1])[:10]

        active_masters = Master.objects.filter(is_active=True).count()

        data = {
            "period": f"{week_ago} — {today}",
            "date": today,
            "total_requests": total,
            "processed": processed,
            "unprocessed": unprocessed,
            "processed_pct": round(processed / total * 100) if total else 0,
            "top_services": top_services,
            "active_masters": active_masters,
        }

        # --- Реальные визиты из YClients ---
        yc_data = _gather_yclients(str(week_ago), str(today))
        data.update(yc_data)

        return data

    def run(self) -> AgentTask:
        task = AgentTask.objects.create(
            agent_type=AgentTask.ANALYTICS,
            status=AgentTask.RUNNING,
            triggered_by="scheduler",
        )
        logger.info("AnalyticsAgent: старт (task_id=%s)", task.pk)
        try:
            data = self.gather_data()

            # Сохранить ежедневную метрику
            DailyMetric.objects.update_or_create(
                date=data["date"],
                defaults={
                    "total_requests": data["total_requests"],
                    "processed": data["processed"],
                    "unprocessed": data["unprocessed"],
                    "top_services": [{"name": n, "count": c} for n, c in data["top_services"]],
                    "masters_load": dict(data.get("yclients_top_masters", [])),
                },
            )

            task.input_context = {k: str(v) if isinstance(v, datetime.date) else v
                                  for k, v in data.items() if k != "date"}
            task.save(update_fields=["input_context"])

            client = get_openai_client()
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты аналитик салона красоты. "
                            "Отвечай по-русски, кратко и по делу, без лишних вступлений."
                        ),
                    },
                    {"role": "user", "content": _build_prompt(data)},
                ],
                max_tokens=700,
            )
            text = response.choices[0].message.content.strip()
            task.raw_response = text

            AgentReport.objects.create(
                task=task,
                summary=text,
                recommendations=[],
            )

            task.status = AgentTask.DONE
            task.finished_at = timezone.now()
            task.save(update_fields=["raw_response", "status", "finished_at"])

            send_telegram(
                f"📊 <b>Аналитика салона</b> ({data['period']})\n\n{text[:900]}"
            )
            logger.info("AnalyticsAgent: завершён (task_id=%s)", task.pk)

        except Exception as exc:
            logger.exception("AnalyticsAgent: ошибка (task_id=%s) — %s", task.pk, exc)
            task.status = AgentTask.ERROR
            task.error_message = str(exc)
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "error_message", "finished_at"])
            from agents.telegram import send_agent_error_alert
            send_agent_error_alert(task)
        finally:
            ensure_task_finalized(task)

        return task
