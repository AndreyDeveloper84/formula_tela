"""Delta-push catalog webhook (Sprint 8 / M3 / DRF-726).

Whenever a catalog row (Service / Master / FAQ / HelpArticle) is created,
updated, or deleted, we fire-and-forget a signed HTTP POST to the
ai-bot-platform sync layer so it can invalidate its cache without
polling. The flow:

    Django post_save/post_delete signal
        → enqueue Celery task ``dispatch_catalog_change``
        → POST JSON body to ``AI_BOT_PLATFORM_WEBHOOK_URL``
        → ``X-Signature: sha256=<hmac>`` over the body verifies the
          payload at the consumer side

Design notes:

- **Dormant by default**: ``AI_BOT_PLATFORM_WEBHOOK_URL`` is an empty
  string unless the operator sets it in ``.env``. With no URL the
  Celery task short-circuits to a no-op log line and returns ``None``.
  This is deliberate — M3 lands ahead of the consumer side, and we do
  not want a missing env var to fail the boot like M2 did.
- **Signal → enqueue, never sync POST**: signals must stay cheap. The
  HTTP call happens in a Celery worker, never in the request thread.
- **Idempotent payload**: the body is `{"event", "model", "pk",
  "updated_at"}`. The consumer is expected to refetch the row from the
  catalog API using ``pk`` if it needs more data — we don't dump full
  rows over the wire to keep the contract narrow and the payload
  signable.
"""
