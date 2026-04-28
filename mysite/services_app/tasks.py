"""Celery tasks для services_app — Phase 1 conversation lifecycle.

Beat schedule в settings/base.py::CELERY_BEAT_SCHEDULE.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from services_app.models import Conversation


logger = logging.getLogger("services_app.tasks")

STALE_DAYS = 7


@shared_task(name="services_app.tasks.close_stale_conversations", bind=True, max_retries=1)
def close_stale_conversations(self):
    """Закрыть активные conversations без активности > STALE_DAYS дней.

    Phase 1 Learning Roadmap. Запускается daily в 03:00 (см. CELERY_BEAT_SCHEDULE).

    Логика:
    - is_active=True AND last_message_at < (now - 7 days)
    - is_active=True AND last_message_at IS NULL AND created_at < (now - 7 days)
      (защита от conversations без сообщений)
    - → outcome=abandoned, is_active=False

    Idempotent — повторный запуск ничего не сломает (фильтр is_active=True).
    """
    cutoff = timezone.now() - timedelta(days=STALE_DAYS)

    # Conversation активная + (last_message_at старо ИЛИ NULL и created_at старо)
    stale_qs = Conversation.objects.filter(is_active=True).filter(
        Q(last_message_at__lt=cutoff)
        | Q(last_message_at__isnull=True, created_at__lt=cutoff)
    )

    count = stale_qs.update(
        is_active=False,
        outcome=Conversation.Outcome.ABANDONED.value,
    )
    logger.info(
        "close_stale_conversations: closed %d conversations as abandoned (>%d days inactive)",
        count, STALE_DAYS,
    )
    return {"closed": count, "stale_days": STALE_DAYS}
