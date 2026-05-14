"""Celery task that delivers a catalog delta to ai-bot-platform.

Signals enqueue ``dispatch_catalog_change`` with a small primitives-only
payload (model name, pk, event, updated_at). The task:

- Reads ``AI_BOT_PLATFORM_WEBHOOK_URL`` / ``_SECRET`` from settings at
  call time (so an operator can flip the URL on without restarting
  workers — Celery is fork-on-prefork, the settings module is re-read).
- If URL is empty → no-op + INFO log (M3 is dormant until consumer side
  is ready; we do NOT want a missing env var to break catalog mutations).
- Builds a canonical JSON body, HMAC-signs it, POSTs with a short
  timeout. Retries with exponential backoff on connection / 5xx errors.
  4xx is permanent — log and stop (a 4xx means the consumer rejected
  the message intentionally, retrying won't help).
"""
from __future__ import annotations

import json
import logging
from typing import Any

import requests
from celery import shared_task
from django.conf import settings

from services_app.api.v1.catalog.webhooks.signing import sign_body

logger = logging.getLogger("services_app.api.catalog.webhooks")

# Short timeout — the consumer is internal infrastructure, anything
# slower than this is "down" and should be retried, not waited on.
_HTTP_TIMEOUT_SECONDS = 5.0


class _PermanentDeliveryError(Exception):
    """Raised on 4xx — Celery will see this and NOT retry."""


@shared_task(
    name="services_app.api.v1.catalog.webhooks.dispatch_catalog_change",
    bind=True,
    autoretry_for=(requests.RequestException,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def dispatch_catalog_change(
    self,
    *,
    event: str,
    model: str,
    pk: int,
    updated_at: str | None,
) -> dict[str, Any] | None:
    """Push a single delta to the ai-bot-platform sync layer.

    Returns a small dict for observability (used by tests, otherwise
    Celery just discards the return). Returns ``None`` when the webhook
    is dormant (no URL configured).
    """
    url = getattr(settings, "AI_BOT_PLATFORM_WEBHOOK_URL", "") or ""
    secret = getattr(settings, "AI_BOT_PLATFORM_WEBHOOK_SECRET", "") or ""

    if not url:
        logger.info(
            "catalog_webhook.dormant event=%s model=%s pk=%s",
            event, model, pk,
        )
        return None
    if not secret:
        # URL set but no secret → operator misconfig. Don't crash the
        # task (catalog mutations would all fail); just log loudly so
        # ops can fix the gap without losing data.
        logger.error(
            "catalog_webhook.no_secret url=%s event=%s model=%s pk=%s "
            "(set AI_BOT_PLATFORM_WEBHOOK_SECRET to enable delivery)",
            url, event, model, pk,
        )
        return None

    payload = {"event": event, "model": model, "pk": pk, "updated_at": updated_at}
    # Use sort_keys + compact separators so the bytes the consumer
    # signs match ours regardless of dict ordering on either side.
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = sign_body(body, secret)

    response = requests.post(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature": signature,
        },
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    if 400 <= response.status_code < 500:
        # Permanent — log body once for diagnosis, stop retrying.
        logger.error(
            "catalog_webhook.permanent_4xx status=%s url=%s event=%s "
            "model=%s pk=%s body=%s",
            response.status_code, url, event, model, pk,
            response.text[:300],
        )
        return {"delivered": False, "status": response.status_code}
    response.raise_for_status()  # 5xx → RequestException → Celery retries
    logger.info(
        "catalog_webhook.delivered status=%s event=%s model=%s pk=%s",
        response.status_code, event, model, pk,
    )
    return {"delivered": True, "status": response.status_code}
