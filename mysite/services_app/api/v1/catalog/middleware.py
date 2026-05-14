"""Server-to-server auth middleware for ``/api/v1/catalog/*``.

The catalog API is a **private** interface for the ai-bot-platform
sync layer — never reached by browsers, never authenticated against a
user session. We gate it with a shared static token (the
``X-Service-Token`` header) compared constant-time against
:setting:`AI_BOT_PLATFORM_TOKEN`.

Why a Django middleware (and not DRF's
:class:`~rest_framework.authentication.TokenAuthentication`):

- DRF auth runs **inside** the view dispatch, after URL routing. A
  request to a non-existent catalog path would still trigger Django's
  404 view without the token being verified. With middleware we reject
  unauthenticated traffic **before** routing — the catalog surface
  becomes opaque to scanners.
- Middleware applies to **all** catalog paths uniformly without
  per-view registration. M3 will add webhook endpoints under the same
  prefix; they inherit the auth automatically.

The middleware is scoped strictly to ``/api/v1/catalog/`` — everything
else (admin, healthz, public website, booking, payments, yclients
webhook) passes through unchanged so existing prod paths are not
disrupted by this PR.

Security notes:

- ``hmac.compare_digest`` is used (not ``==``) so an attacker cannot
  probe the token byte-by-byte via response-time differences.
- If :setting:`AI_BOT_PLATFORM_TOKEN` is unset (empty string), **all**
  catalog requests are rejected (we don't treat unset as "allow"). The
  production settings module additionally fails fast on startup so a
  misconfigured deploy never reaches a real client.
- The unauth log line includes only the first 4 chars of the supplied
  token + ``***`` so logs don't leak a guessable secret while still
  surfacing the attack-pattern signal.
"""
from __future__ import annotations

import hmac
import logging
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse

logger = logging.getLogger("services_app.api.catalog.auth")


# Prefix of the protected catalog surface. Everything else passes through.
PROTECTED_PREFIX = "/api/v1/catalog/"


def _mask_token(token: str) -> str:
    """Return a log-safe representation of the supplied token.

    Empty / very short tokens render as ``(empty)`` / their full content
    (already not a secret); longer tokens show the first 4 chars + `***`
    so operators can correlate repeated attack attempts without the log
    line itself becoming a credential leak.
    """
    if not token:
        return "(empty)"
    if len(token) <= 4:
        return token
    return f"{token[:4]}***"


class ServiceTokenAuthMiddleware:
    """Gate ``/api/v1/catalog/*`` behind a static ``X-Service-Token``.

    Register in :setting:`MIDDLEWARE` **after** ``CommonMiddleware`` (so
    the request path is already normalised) and **before**
    ``RatelimitMiddleware`` (so unauthenticated traffic doesn't consume
    rate-limit budget). Order is enforced by the order in the list, not
    by code.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not request.path.startswith(PROTECTED_PREFIX):
            return self.get_response(request)

        provided = request.headers.get("X-Service-Token", "") or ""
        expected = getattr(settings, "AI_BOT_PLATFORM_TOKEN", "") or ""

        # Empty `expected` blocks all access — a deployment that forgot
        # to set the secret must not silently authorize everything.
        # Production settings additionally fail-fast on startup (see
        # ``mysite/mysite/settings/production.py``).
        if not expected or not hmac.compare_digest(provided, expected):
            logger.warning(
                "catalog_api.unauth path=%s remote=%s token=%s",
                request.path,
                request.META.get("REMOTE_ADDR", "?"),
                _mask_token(provided),
            )
            return _unauthorized()

        return self.get_response(request)


def _unauthorized() -> JsonResponse:
    """Stable 401 JSON envelope.

    The body shape is part of the API contract with the bot's sync
    layer. Changing it is a v2 endpoint, not a v1 patch.
    """
    payload: dict[str, Any] = {"detail": "invalid service token"}
    return JsonResponse(payload, status=401)
