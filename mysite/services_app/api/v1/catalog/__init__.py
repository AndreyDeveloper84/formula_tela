"""Catalog endpoints — read-only API for the AI bot infrastructure.

Exposes four resources:

- ``GET /api/v1/catalog/services/``       — active services
- ``GET /api/v1/catalog/masters/``        — active masters
- ``GET /api/v1/catalog/faqs/``           — service-category FAQs
- ``GET /api/v1/catalog/help-articles/``  — MAX-bot help articles

Each endpoint supports:

- **Cursor pagination** ordered by ``updated_at`` (stable on growing
  data; unlike offset pagination, never skips a row when new ones
  appear).
- **``?since=<ISO8601>`` filter** — incremental sync cursor. The bot
  stores the last seen ``updated_at`` and replays only deltas, avoiding
  full-table pulls on every sync cycle.

Authentication: M1 (this PR) ships unauthenticated for the initial
deployment. M2 (DRF-725) wraps these endpoints with the
``X-Service-Token`` middleware before production exposure. Until M2
lands the endpoints are reachable internally only.
"""
