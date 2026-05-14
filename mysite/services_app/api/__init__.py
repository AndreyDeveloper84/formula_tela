"""DRF API namespace for ``services_app``.

This package hosts versioned REST endpoints that expose the salon's
catalog (services, masters, FAQs, help articles) for **server-to-server
consumption** by the ai-bot-platform. It is intentionally separate from
the public website views in ``services_app.views`` — the API is meant
to be queried by the AI bot infrastructure, not by browsers.

**FROZEN-EXEMPT** (Sprint 0 / 2026-05-09 decision):
``mysite/maxbot/`` is frozen as the source-of-truth for the
ai-bot-platform extraction. ``services_app/`` (this app) is NOT frozen
and is allowed to grow new endpoints. Each PR touching ``services_app/``
must include the ``[FROZEN-EXEMPT]`` tag in its title so the freeze
policy stays auditable.
"""
