"""Phase 2.4 T07 — post-visit follow-up + repeat offer Celery tasks."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone as dj_timezone
from model_bakery import baker

from services_app.models import BookingReminder, BookingRequest, BotUser


# ─── send_post_visit_followups ────────────────────────────────────────────


@pytest.mark.django_db
def test_post_visit_followup_sends_for_yesterday_visits():
    from maxbot.tasks import send_post_visit_followups

    bu = baker.make(BotUser, chat_id=12345, max_user_id=999)
    yesterday = date.today() - timedelta(days=1)
    visit_at = datetime.combine(yesterday, datetime.min.time().replace(hour=14))
    # У клиента был T-24h reminder на вчера
    BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="REC-1", chat_id=12345,
        visit_at=visit_at, kind=BookingReminder.Kind.DAY_BEFORE,
        scheduled_at=visit_at - timedelta(hours=24),
        status=BookingReminder.Status.CONFIRMED,
        master_name="Анна", service_name="Массаж",
    )

    with patch("notifications.max_bot.send_max_message", return_value=True) as mock_send:
        result = send_post_visit_followups()

    assert result["sent"] == 1
    assert mock_send.call_args.kwargs["chat_id"] == 12345
    msg_text = mock_send.call_args.kwargs["text"]
    assert "Анна" in msg_text
    assert "Массаж" in msg_text


@pytest.mark.django_db
def test_post_visit_followup_idempotent():
    """Повторный запуск task'а в тот же день — не дублирует отправку."""
    from maxbot.tasks import send_post_visit_followups

    yesterday = date.today() - timedelta(days=1)
    bu = baker.make(
        BotUser, chat_id=12345, max_user_id=998,
        context={"last_followup_sent_at": yesterday.isoformat()},
    )
    BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="REC-1", chat_id=12345,
        visit_at=datetime.combine(yesterday, datetime.min.time().replace(hour=14)),
        kind=BookingReminder.Kind.DAY_BEFORE,
        scheduled_at=datetime.combine(yesterday, datetime.min.time()),
        status=BookingReminder.Status.CONFIRMED,
    )

    with patch("notifications.max_bot.send_max_message", return_value=True) as mock_send:
        result = send_post_visit_followups()

    assert result["sent"] == 0
    assert result["skipped"] >= 1
    mock_send.assert_not_called()


@pytest.mark.django_db
def test_post_visit_followup_skips_no_chat_id():
    from maxbot.tasks import send_post_visit_followups

    yesterday = date.today() - timedelta(days=1)
    bu = baker.make(BotUser, chat_id=None, max_user_id=997)
    BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="REC-NC", chat_id=0,
        visit_at=datetime.combine(yesterday, datetime.min.time().replace(hour=14)),
        kind=BookingReminder.Kind.DAY_BEFORE,
        scheduled_at=datetime.combine(yesterday, datetime.min.time()),
    )

    with patch("notifications.max_bot.send_max_message", return_value=True) as mock_send:
        result = send_post_visit_followups()

    assert result["sent"] == 0
    mock_send.assert_not_called()


@pytest.mark.django_db
def test_post_visit_followup_skips_today_and_old():
    """Только вчерашние визиты — сегодняшние и >2 дня назад пропускаем."""
    from maxbot.tasks import send_post_visit_followups

    bu = baker.make(BotUser, chat_id=12345, max_user_id=996)
    today = date.today()
    today_visit = datetime.combine(today, datetime.min.time().replace(hour=14))
    old_visit = datetime.combine(today - timedelta(days=5), datetime.min.time())

    BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="R-T", chat_id=12345,
        visit_at=today_visit, kind=BookingReminder.Kind.DAY_BEFORE,
        scheduled_at=today_visit - timedelta(hours=24),
    )
    BookingReminder.objects.create(
        bot_user=bu, yclients_record_id="R-O", chat_id=12345,
        visit_at=old_visit, kind=BookingReminder.Kind.DAY_BEFORE,
        scheduled_at=old_visit - timedelta(hours=24),
    )

    with patch("notifications.max_bot.send_max_message", return_value=True) as mock_send:
        result = send_post_visit_followups()

    assert result["sent"] == 0
    mock_send.assert_not_called()


# ─── send_repeat_offers ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_repeat_offer_sends_for_3_4_weeks_old():
    from maxbot.tasks import send_repeat_offers

    bu = baker.make(BotUser, chat_id=12345, client_name="Алиса", max_user_id=995)
    # Запись 25 дней назад
    br = baker.make(
        BookingRequest, bot_user=bu, is_processed=True,
        master_name="Анна", service_name="Массаж",
    )
    br.created_at = dj_timezone.now() - timedelta(days=25)
    br.save(update_fields=["created_at"])

    with patch("notifications.max_bot.send_max_message", return_value=True) as mock_send:
        result = send_repeat_offers()

    assert result["sent"] == 1
    text = mock_send.call_args.kwargs["text"]
    assert "Алиса" in text
    assert "Анна" in text
    assert "повторить" in text.lower() or "месяц" in text.lower()


@pytest.mark.django_db
def test_repeat_offer_rate_limit_30_days():
    """Если уже отправили repeat-offer < 30 дней назад — не повторяем."""
    from maxbot.tasks import send_repeat_offers

    bu = baker.make(
        BotUser, chat_id=12345, max_user_id=994,
        context={
            "last_repeat_offer_at": (date.today() - timedelta(days=15)).isoformat(),
        },
    )
    br = baker.make(
        BookingRequest, bot_user=bu, is_processed=True,
        master_name="Анна", service_name="Массаж",
    )
    br.created_at = dj_timezone.now() - timedelta(days=25)
    br.save(update_fields=["created_at"])

    with patch("notifications.max_bot.send_max_message", return_value=True) as mock_send:
        result = send_repeat_offers()

    assert result["sent"] == 0
    mock_send.assert_not_called()


@pytest.mark.django_db
def test_repeat_offer_skips_recent_visit():
    """Визит < 21 дней назад — НЕ предлагаем repeat (рано)."""
    from maxbot.tasks import send_repeat_offers

    bu = baker.make(BotUser, chat_id=12345, max_user_id=993)
    br = baker.make(BookingRequest, bot_user=bu, is_processed=True)
    br.created_at = dj_timezone.now() - timedelta(days=10)
    br.save(update_fields=["created_at"])

    with patch("notifications.max_bot.send_max_message", return_value=True) as mock_send:
        result = send_repeat_offers()

    assert result["sent"] == 0
    mock_send.assert_not_called()


@pytest.mark.django_db
def test_repeat_offer_updates_last_offer_timestamp():
    """После успешной отправки — context.last_repeat_offer_at = today."""
    from maxbot.tasks import send_repeat_offers

    bu = baker.make(BotUser, chat_id=12345, max_user_id=992)
    br = baker.make(BookingRequest, bot_user=bu, is_processed=True)
    br.created_at = dj_timezone.now() - timedelta(days=25)
    br.save(update_fields=["created_at"])

    with patch("notifications.max_bot.send_max_message", return_value=True):
        send_repeat_offers()

    bu.refresh_from_db()
    assert bu.context.get("last_repeat_offer_at") == date.today().isoformat()
