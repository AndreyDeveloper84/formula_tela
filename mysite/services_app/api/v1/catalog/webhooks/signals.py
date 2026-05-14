"""Bind ``post_save`` / ``post_delete`` for the four catalog models.

The handler is intentionally tiny: it picks ``pk``, ``updated_at``, and
the event type, then enqueues the Celery task. No HTTP, no DB lookup
beyond what's already in the instance. We use ``on_commit`` so the
delta is only published after the surrounding transaction successfully
commits — otherwise a rolled-back save would still trigger a webhook,
which would push the consumer into a state that doesn't match the
producer's database.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from services_app.api.v1.catalog.webhooks.tasks import dispatch_catalog_change
from services_app.models import FAQ, HelpArticle, Master, Service

logger = logging.getLogger("services_app.api.catalog.webhooks.signals")

# Tuple of the four models the catalog API exposes. Anything outside
# this list (ServiceCategory, ServiceMedia, etc.) is internal-only and
# does NOT trigger a delta — the bot only consumes the four primary
# resources, so cross-noise would just waste consumer CPU.
_TRACKED = (Service, Master, FAQ, HelpArticle)


def _enqueue(*, instance, event: str) -> None:
    """Submit the dispatch task once the current transaction commits.

    Short-circuits to a no-op when the webhook is dormant — checking
    ``AI_BOT_PLATFORM_WEBHOOK_URL`` at signal time avoids calling
    ``.delay()`` at all, which matters because Celery's broker
    transport will block-retry the enqueue when the broker isn't
    reachable (local dev / test runs / pre-prod boxes without Redis).
    The task itself has the same check as a defense-in-depth — see
    ``tasks.dispatch_catalog_change``.
    """
    url = getattr(settings, "AI_BOT_PLATFORM_WEBHOOK_URL", "") or ""
    if not url:
        return
    model = type(instance).__name__
    pk = instance.pk
    updated_at = getattr(instance, "updated_at", None)
    updated_at_iso = updated_at.isoformat() if updated_at is not None else None

    def _send() -> None:
        try:
            dispatch_catalog_change.delay(
                event=event, model=model, pk=pk, updated_at=updated_at_iso,
            )
        except Exception:  # noqa: BLE001 — broker unreachable, etc.
            # Never let a webhook-side failure break a catalog mutation
            # that has already committed. Log and move on; the consumer
            # will sync via the M1 ``?since=`` cursor on its next poll.
            logger.exception(
                "catalog_webhook.enqueue_failed model=%s pk=%s event=%s",
                model, pk, event,
            )

    transaction.on_commit(_send)


@receiver(post_save, sender=Service)
@receiver(post_save, sender=Master)
@receiver(post_save, sender=FAQ)
@receiver(post_save, sender=HelpArticle)
def on_catalog_saved(sender, instance, created, **_kwargs) -> None:
    if not isinstance(instance, _TRACKED):  # safety guard
        return
    event = "created" if created else "updated"
    _enqueue(instance=instance, event=event)


@receiver(post_delete, sender=Service)
@receiver(post_delete, sender=Master)
@receiver(post_delete, sender=FAQ)
@receiver(post_delete, sender=HelpArticle)
def on_catalog_deleted(sender, instance, **_kwargs) -> None:
    if not isinstance(instance, _TRACKED):
        return
    _enqueue(instance=instance, event="deleted")
