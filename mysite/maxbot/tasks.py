"""Celery tasks для MAX-бота — N2 система напоминаний.

Запускаются из Celery beat (см. CELERY_BEAT_SCHEDULE в settings/base.py):
- send_due_reminders — каждые 15 минут
- escalate_stale_reminders — каждый час
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger("maxbot.tasks")


@shared_task(name="maxbot.tasks.send_due_reminders", bind=True, max_retries=2)
def send_due_reminders(self):
    """Отправить все PENDING напоминания у которых scheduled_at <= now.

    T-24h → 3 кнопки [Подтверждаю/Перенести/Отменить] → status=SENT_NO_REPLY.
    T-2h → текст без кнопок → status=SENT.
    Если send_max_message вернул False (token не задан, API упал) — пропускаем,
    статус не меняется. Следующий tick попробует ещё раз.
    Idempotency: только PENDING обрабатываются; ушедшие SENT_NO_REPLY/SENT
    не пытаемся пересылать.
    """
    from notifications.max_bot import send_max_message
    from services_app.models import BookingReminder
    from maxbot.keyboards import reminder_24h_keyboard

    now = timezone.now()
    pending = list(
        BookingReminder.objects
        .filter(status=BookingReminder.Status.PENDING, scheduled_at__lte=now)
        .select_related("bot_user")
        .order_by("scheduled_at")[:100]
    )
    if not pending:
        return {"sent": 0, "checked": 0}

    sent = 0
    failed = 0
    for r in pending:
        if not r.chat_id:
            logger.warning("reminder %s: empty chat_id, marking FAILED", r.id)
            r.status = BookingReminder.Status.FAILED
            r.save(update_fields=["status"])
            continue

        text = _format_reminder_text(r)
        attachments = None
        if r.kind == BookingReminder.Kind.DAY_BEFORE:
            attachments = [reminder_24h_keyboard(str(r.id))]

        ok = send_max_message(chat_id=r.chat_id, text=text, attachments=attachments)
        if ok:
            r.status = (
                BookingReminder.Status.SENT_NO_REPLY
                if r.kind == BookingReminder.Kind.DAY_BEFORE
                else BookingReminder.Status.SENT
            )
            r.sent_at = timezone.now()
            r.save(update_fields=["status", "sent_at"])
            sent += 1
        else:
            failed += 1
            logger.warning(
                "send_due_reminders: send failed for reminder=%s chat_id=%s",
                r.id, r.chat_id,
            )

    logger.info(
        "send_due_reminders: sent=%d failed=%d checked=%d",
        sent, failed, len(pending),
    )
    return {"sent": sent, "failed": failed, "checked": len(pending)}


@shared_task(name="maxbot.tasks.escalate_stale_reminders", bind=True, max_retries=1)
def escalate_stale_reminders(self):
    """Если T-24h отправлено и за 12ч до визита нет ответа → Telegram менеджеру.

    После эскалации статус → ESCALATED, повторно не уведомляем.
    """
    from notifications import send_notification_telegram
    from services_app.models import BookingReminder

    now = timezone.now()
    cutoff = now + timedelta(hours=12)
    stale = list(
        BookingReminder.objects
        .filter(
            kind=BookingReminder.Kind.DAY_BEFORE,
            status=BookingReminder.Status.SENT_NO_REPLY,
            visit_at__lte=cutoff,
            visit_at__gte=now,  # не эскалируем уже прошедшие визиты
        )
        .select_related("bot_user")[:50]
    )
    if not stale:
        return {"escalated": 0, "checked": 0}

    escalated = 0
    for r in stale:
        bu = r.bot_user
        client = bu.client_name or bu.display_name or f"#{bu.max_user_id}"
        phone = bu.client_phone or "—"
        msg = (
            f"⚠️ Клиент НЕ подтвердил запись\n\n"
            f"📅 {r.visit_at.strftime('%d.%m.%Y в %H:%M')}\n"
            f"👤 {client}\n"
            f"📞 {phone}\n"
            f"💆 {r.master_name}\n"
            f"📋 {r.service_name}\n\n"
            f"Позвоните клиенту, чтобы уточнить."
        )
        if send_notification_telegram(msg):
            r.status = BookingReminder.Status.ESCALATED
            r.save(update_fields=["status"])
            escalated += 1
        else:
            logger.warning(
                "escalate_stale_reminders: telegram failed for reminder=%s", r.id,
            )

    logger.info(
        "escalate_stale_reminders: escalated=%d checked=%d",
        escalated, len(stale),
    )
    return {"escalated": escalated, "checked": len(stale)}


def _format_reminder_text(r) -> str:
    """Текст напоминания (зависит от kind)."""
    when = r.visit_at.strftime("%d.%m в %H:%M")
    if r.kind == "day_before":
        return (
            f"📅 Напоминаем: завтра ({when}) у вас запись\n"
            f"💆 Мастер: {r.master_name}\n"
            f"📋 Услуга: {r.service_name}\n\n"
            f"Подтвердите, что придёте 🙏"
        )
    return (
        f"⏰ Через 2 часа ({when}) у вас запись к {r.master_name}\n"
        f"📋 {r.service_name}\n\n"
        f"Ждём вас!"
    )
