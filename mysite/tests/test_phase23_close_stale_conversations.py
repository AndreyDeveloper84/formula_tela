"""Phase 1: Celery task close_stale_conversations — закрыть AI-диалоги без активности."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone
from model_bakery import baker

pytestmark = pytest.mark.django_db


def test_closes_conversations_with_old_last_message_at():
    from services_app.tasks import close_stale_conversations
    from services_app.models import BotUser, Conversation

    bu = baker.make(BotUser, max_user_id=85001)
    old_time = timezone.now() - timedelta(days=10)
    conv = Conversation.objects.create(bot_user=bu, is_active=True)
    Conversation.objects.filter(pk=conv.pk).update(last_message_at=old_time)

    result = close_stale_conversations()

    conv.refresh_from_db()
    assert conv.is_active is False
    assert conv.outcome == Conversation.Outcome.ABANDONED.value
    assert result["closed"] == 1


def test_skips_recent_conversations():
    from services_app.tasks import close_stale_conversations
    from services_app.models import BotUser, Conversation

    bu = baker.make(BotUser, max_user_id=85002)
    recent_time = timezone.now() - timedelta(hours=2)  # 2h назад
    conv = Conversation.objects.create(bot_user=bu, is_active=True)
    Conversation.objects.filter(pk=conv.pk).update(last_message_at=recent_time)

    close_stale_conversations()

    conv.refresh_from_db()
    assert conv.is_active is True
    assert conv.outcome == ""


def test_skips_already_closed_conversations():
    """Idempotent: повторный запуск ничего не трогает."""
    from services_app.tasks import close_stale_conversations
    from services_app.models import BotUser, Conversation

    bu = baker.make(BotUser, max_user_id=85003)
    old_time = timezone.now() - timedelta(days=10)
    conv = Conversation.objects.create(
        bot_user=bu, is_active=False,
        outcome=Conversation.Outcome.SUCCESS.value,  # уже закрыт как success
    )
    Conversation.objects.filter(pk=conv.pk).update(last_message_at=old_time)

    close_stale_conversations()

    conv.refresh_from_db()
    # Не перезаписан — outcome остался success, не abandoned
    assert conv.outcome == Conversation.Outcome.SUCCESS.value


def test_closes_conversations_with_null_last_message_at_and_old_created():
    """Conversation создан 8 дней назад, никаких сообщений — closed as abandoned."""
    from services_app.tasks import close_stale_conversations
    from services_app.models import BotUser, Conversation

    bu = baker.make(BotUser, max_user_id=85004)
    old_time = timezone.now() - timedelta(days=8)
    conv = Conversation.objects.create(bot_user=bu, is_active=True)
    Conversation.objects.filter(pk=conv.pk).update(
        last_message_at=None, created_at=old_time,
    )

    close_stale_conversations()

    conv.refresh_from_db()
    assert conv.is_active is False
    assert conv.outcome == Conversation.Outcome.ABANDONED.value


def test_closes_only_stale_returns_count():
    """Mixed batch: 2 stale + 1 recent → returns closed=2."""
    from services_app.tasks import close_stale_conversations
    from services_app.models import BotUser, Conversation

    bu = baker.make(BotUser, max_user_id=85005)
    old = timezone.now() - timedelta(days=10)
    recent = timezone.now() - timedelta(hours=1)
    c1 = Conversation.objects.create(bot_user=bu, is_active=True)
    c2 = Conversation.objects.create(bot_user=bu, is_active=True)
    c3 = Conversation.objects.create(bot_user=bu, is_active=True)
    Conversation.objects.filter(pk=c1.pk).update(last_message_at=old)
    Conversation.objects.filter(pk=c2.pk).update(last_message_at=old)
    Conversation.objects.filter(pk=c3.pk).update(last_message_at=recent)

    result = close_stale_conversations()
    assert result["closed"] == 2
    assert result["stale_days"] == 7
