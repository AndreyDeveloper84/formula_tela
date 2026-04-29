"""N2 — тесты для BookingReminder + Celery tasks + hook _create_reminders."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone as dj_timezone
from model_bakery import baker

from services_app.models import BookingReminder, BookingRequest, BotUser

MSK = ZoneInfo("Europe/Moscow")


# ─── Model basics ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_booking_reminder_unique_kind_per_record():
    """Нельзя создать 2 напоминания одного kind для одной YClients-записи."""
    bu = baker.make(BotUser, chat_id=999)
    BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="REC-1", chat_id=999,
        visit_at=dj_timezone.now() + timedelta(days=2),
        kind=BookingReminder.Kind.DAY_BEFORE,
        scheduled_at=dj_timezone.now() + timedelta(days=1),
        master_name="Анна", service_name="Массаж",
    )
    with pytest.raises(Exception):
        BookingReminder.objects.create(
            bot_user=bu, yclients_record_id="REC-1", chat_id=999,
            visit_at=dj_timezone.now() + timedelta(days=2),
            kind=BookingReminder.Kind.DAY_BEFORE,
            scheduled_at=dj_timezone.now() + timedelta(days=1),
            master_name="Анна", service_name="Массаж",
        )


@pytest.mark.django_db
def test_booking_reminder_two_kinds_same_record_ok():
    """Один record_id с разными kind (T-24h + T-2h) — ок."""
    bu = baker.make(BotUser, chat_id=999)
    BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="REC-2", chat_id=999,
        visit_at=dj_timezone.now() + timedelta(days=2),
        kind=BookingReminder.Kind.DAY_BEFORE,
        scheduled_at=dj_timezone.now() + timedelta(days=1),
    )
    BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="REC-2", chat_id=999,
        visit_at=dj_timezone.now() + timedelta(days=2),
        kind=BookingReminder.Kind.TWO_HOURS,
        scheduled_at=dj_timezone.now() + timedelta(days=2, hours=-2),
    )
    assert BookingReminder.objects.filter(yclients_record_id="REC-2").count() == 2


# ─── _create_reminders hook ───────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_create_reminders_creates_two():
    """Visit через 5 дней — оба reminder'а создаются."""
    from maxbot.ai_action_service import _create_reminders

    bu = await sync_to_async(baker.make)(BotUser, chat_id=12345)
    booking = await sync_to_async(baker.make)(BookingRequest)
    visit = (dj_timezone.now() + timedelta(days=5)).astimezone(MSK).replace(
        hour=14, minute=0, second=0, microsecond=0,
    )

    await _create_reminders(
        bot_user=bu, booking=booking,
        master_name="Анна", service_name="Массаж",
        yclients_record_id="REC-CR-1", slot_iso=visit.isoformat(),
    )

    qs = await sync_to_async(list)(
        BookingReminder.objects.filter(yclients_record_id="REC-CR-1").order_by("kind")
    )
    assert len(qs) == 2
    kinds = {r.kind for r in qs}
    assert kinds == {"day_before", "two_hours"}


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_create_reminders_skips_past():
    """Visit через 30 минут — T-24h в прошлом, не создаётся; T-2h тоже в прошлом."""
    from maxbot.ai_action_service import _create_reminders

    bu = await sync_to_async(baker.make)(BotUser, chat_id=12345)
    booking = await sync_to_async(baker.make)(BookingRequest)
    visit = dj_timezone.now() + timedelta(minutes=30)

    await _create_reminders(
        bot_user=bu, booking=booking,
        master_name="Анна", service_name="Массаж",
        yclients_record_id="REC-PAST", slot_iso=visit.isoformat(),
    )

    qs = await sync_to_async(list)(
        BookingReminder.objects.filter(yclients_record_id="REC-PAST")
    )
    assert qs == []


@pytest.mark.django_db
@pytest.mark.asyncio
async def test_create_reminders_only_two_hours_when_visit_tomorrow_morning():
    """Visit завтра в 09:00 → T-24h = сегодня в 19:00 (может быть в прошлом или
    будущем в зависимости от времени запуска), T-2h = завтра в 07:00 (в будущем).
    Должен создаться минимум T-2h."""
    from maxbot.ai_action_service import _create_reminders

    bu = await sync_to_async(baker.make)(BotUser, chat_id=12345)
    booking = await sync_to_async(baker.make)(BookingRequest)
    visit = dj_timezone.now() + timedelta(hours=30)  # ~30h forward

    await _create_reminders(
        bot_user=bu, booking=booking,
        master_name="Анна", service_name="Массаж",
        yclients_record_id="REC-30H", slot_iso=visit.isoformat(),
    )

    qs = await sync_to_async(list)(
        BookingReminder.objects.filter(yclients_record_id="REC-30H")
    )
    # Минимум T-2h всегда есть (visit > now+2h)
    kinds = {r.kind for r in qs}
    assert "two_hours" in kinds


# ─── send_due_reminders task ──────────────────────────────────────────────


@pytest.mark.django_db
def test_send_due_reminders_sends_pending_t24():
    """PENDING с scheduled_at <= now → SENT_NO_REPLY (для T-24h) с 3 кнопками."""
    from maxbot.tasks import send_due_reminders

    bu = baker.make(BotUser, chat_id=12345)
    r = BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="REC-S1", chat_id=12345,
        visit_at=dj_timezone.now() + timedelta(days=1),
        kind=BookingReminder.Kind.DAY_BEFORE,
        scheduled_at=dj_timezone.now() - timedelta(minutes=5),
        master_name="Анна", service_name="Массаж",
    )

    with patch("notifications.max_bot.send_max_message", return_value=True) as mock_send:
        result = send_due_reminders()

    assert result["sent"] == 1
    r.refresh_from_db()
    assert r.status == BookingReminder.Status.SENT_NO_REPLY
    assert r.sent_at is not None
    # Должны были передать attachments (для T-24h)
    call_kwargs = mock_send.call_args.kwargs
    assert call_kwargs["chat_id"] == 12345
    assert call_kwargs["attachments"] is not None


@pytest.mark.django_db
def test_send_due_reminders_t2h_no_attachments():
    """T-2h отправляется БЕЗ attachments (status → SENT)."""
    from maxbot.tasks import send_due_reminders

    bu = baker.make(BotUser, chat_id=12345)
    r = BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="REC-S2", chat_id=12345,
        visit_at=dj_timezone.now() + timedelta(hours=2, minutes=5),
        kind=BookingReminder.Kind.TWO_HOURS,
        scheduled_at=dj_timezone.now() - timedelta(minutes=2),
        master_name="Анна", service_name="Массаж",
    )

    with patch("notifications.max_bot.send_max_message", return_value=True) as mock_send:
        send_due_reminders()

    r.refresh_from_db()
    assert r.status == BookingReminder.Status.SENT
    assert mock_send.call_args.kwargs["attachments"] is None


@pytest.mark.django_db
def test_send_due_reminders_skips_future():
    """PENDING с scheduled_at в будущем — не трогаем."""
    from maxbot.tasks import send_due_reminders

    bu = baker.make(BotUser, chat_id=12345)
    r = BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="REC-FUT", chat_id=12345,
        visit_at=dj_timezone.now() + timedelta(days=2),
        kind=BookingReminder.Kind.DAY_BEFORE,
        scheduled_at=dj_timezone.now() + timedelta(hours=5),
    )

    with patch("notifications.max_bot.send_max_message", return_value=True) as mock_send:
        result = send_due_reminders()

    assert result["checked"] == 0
    mock_send.assert_not_called()
    r.refresh_from_db()
    assert r.status == BookingReminder.Status.PENDING


@pytest.mark.django_db
def test_send_due_reminders_keeps_pending_on_send_failure():
    """Если send_max_message вернул False — статус НЕ меняется (retry на след. tick)."""
    from maxbot.tasks import send_due_reminders

    bu = baker.make(BotUser, chat_id=12345)
    r = BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="REC-FAIL", chat_id=12345,
        visit_at=dj_timezone.now() + timedelta(days=1),
        kind=BookingReminder.Kind.DAY_BEFORE,
        scheduled_at=dj_timezone.now() - timedelta(minutes=5),
    )

    with patch("notifications.max_bot.send_max_message", return_value=False):
        result = send_due_reminders()

    assert result["sent"] == 0
    assert result["failed"] == 1
    r.refresh_from_db()
    assert r.status == BookingReminder.Status.PENDING


# ─── escalate_stale_reminders task ────────────────────────────────────────


@pytest.mark.django_db
def test_escalate_stale_sends_telegram():
    """SENT_NO_REPLY с visit_at <= now+12h → ESCALATED + Telegram."""
    from maxbot.tasks import escalate_stale_reminders

    bu = baker.make(
        BotUser, chat_id=12345, client_name="Алиса", client_phone="+79001112233",
    )
    r = BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="REC-ESC", chat_id=12345,
        visit_at=dj_timezone.now() + timedelta(hours=8),
        kind=BookingReminder.Kind.DAY_BEFORE,
        scheduled_at=dj_timezone.now() - timedelta(hours=4),
        status=BookingReminder.Status.SENT_NO_REPLY,
        master_name="Анна", service_name="Массаж",
    )

    with patch("notifications.send_notification_telegram", return_value=True) as mock_tg:
        result = escalate_stale_reminders()

    assert result["escalated"] == 1
    r.refresh_from_db()
    assert r.status == BookingReminder.Status.ESCALATED
    msg = mock_tg.call_args.args[0]
    assert "Алиса" in msg
    assert "+79001112233" in msg


@pytest.mark.django_db
def test_escalate_skips_confirmed():
    """CONFIRMED — не эскалируется."""
    from maxbot.tasks import escalate_stale_reminders

    bu = baker.make(BotUser, chat_id=12345)
    BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="REC-CONF", chat_id=12345,
        visit_at=dj_timezone.now() + timedelta(hours=6),
        kind=BookingReminder.Kind.DAY_BEFORE,
        scheduled_at=dj_timezone.now() - timedelta(hours=8),
        status=BookingReminder.Status.CONFIRMED,
    )

    with patch("notifications.send_notification_telegram", return_value=True) as mock_tg:
        result = escalate_stale_reminders()

    assert result["escalated"] == 0
    mock_tg.assert_not_called()


@pytest.mark.django_db
def test_escalate_skips_past_visit():
    """visit_at в прошлом — не эскалируем (поздно звонить)."""
    from maxbot.tasks import escalate_stale_reminders

    bu = baker.make(BotUser, chat_id=12345)
    BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="REC-PAST-V", chat_id=12345,
        visit_at=dj_timezone.now() - timedelta(hours=2),
        kind=BookingReminder.Kind.DAY_BEFORE,
        scheduled_at=dj_timezone.now() - timedelta(hours=26),
        status=BookingReminder.Status.SENT_NO_REPLY,
    )

    with patch("notifications.send_notification_telegram", return_value=True):
        result = escalate_stale_reminders()

    assert result["escalated"] == 0
