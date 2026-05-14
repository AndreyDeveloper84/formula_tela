"""Tests for the ``X-Service-Token`` middleware (Sprint 8 / M2 / DRF-725).

The catalog API is a private interface for the ai-bot-platform sync layer.
We gate it with a shared static token compared constant-time against
``settings.AI_BOT_PLATFORM_TOKEN``. These tests cover:

- Missing / wrong / correct token semantics on a real catalog endpoint
- Non-catalog paths (admin login, healthz, robots.txt, root) pass through
  unchanged — middleware must not break unrelated routes
- Deploy with ``AI_BOT_PLATFORM_TOKEN`` empty rejects everything (no
  "open by default" footgun)
- ``hmac.compare_digest`` is used (smoke: prefix-of-the-real-token is
  rejected, not silently accepted)
- Log line on unauth includes a masked token (4-char prefix + ``***``),
  never the full secret
"""
from __future__ import annotations

import logging

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from services_app.models import Service, ServiceCategory

_TOKEN = "s3cret-service-token-aaaaaaa"  # noqa: S105 — test fixture value


@override_settings(AI_BOT_PLATFORM_TOKEN=_TOKEN)
class ServiceTokenGateTests(TestCase):
    """End-to-end behaviour of the gate on a real catalog route."""

    @classmethod
    def setUpTestData(cls) -> None:
        # Seed one active row so a 200 response actually has content; the
        # 401 paths don't care about DB state but having a row makes the
        # tests easier to read.
        cls.category = ServiceCategory.objects.create(name="Массаж", order=0)
        Service.objects.create(
            name="Тестовая услуга", category=cls.category, is_active=True,
        )

    def setUp(self) -> None:
        self.client = APIClient()

    def test_missing_token_returns_401(self) -> None:
        """No header → 401, no DB hit, no leak of catalog contents."""
        response = self.client.get("/api/v1/catalog/services/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "invalid service token"})

    def test_wrong_token_returns_401(self) -> None:
        self.client.credentials(HTTP_X_SERVICE_TOKEN="not-the-real-token")
        response = self.client.get("/api/v1/catalog/services/")
        self.assertEqual(response.status_code, 401)

    def test_correct_token_returns_200(self) -> None:
        self.client.credentials(HTTP_X_SERVICE_TOKEN=_TOKEN)
        response = self.client.get("/api/v1/catalog/services/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_prefix_of_real_token_rejected(self) -> None:
        """``hmac.compare_digest`` semantics: prefix is not a match.

        A plain string equality check would still reject this, but the
        test guards against a future regression where someone uses
        ``startswith`` or ``in`` instead of constant-time compare.
        """
        self.client.credentials(HTTP_X_SERVICE_TOKEN=_TOKEN[:10])
        response = self.client.get("/api/v1/catalog/services/")
        self.assertEqual(response.status_code, 401)

    def test_token_with_trailing_chars_rejected(self) -> None:
        self.client.credentials(HTTP_X_SERVICE_TOKEN=_TOKEN + "extra")
        response = self.client.get("/api/v1/catalog/services/")
        self.assertEqual(response.status_code, 401)

    def test_empty_string_token_rejected(self) -> None:
        self.client.credentials(HTTP_X_SERVICE_TOKEN="")
        response = self.client.get("/api/v1/catalog/services/")
        self.assertEqual(response.status_code, 401)

    def test_unauth_log_masks_token(self) -> None:
        """Log line carries only the 4-char prefix + ``***``, not the full secret."""
        attacker_token = "leaked-attempt-do-not-store-raw"
        self.client.credentials(HTTP_X_SERVICE_TOKEN=attacker_token)
        with self.assertLogs("services_app.api.catalog.auth", level="WARNING") as cap:
            self.client.get("/api/v1/catalog/services/")
        rendered = "\n".join(cap.output)
        # Masked form is present
        self.assertIn("leak***", rendered)
        # Full token is NOT present
        self.assertNotIn(attacker_token, rendered)


class NonCatalogPathsBypassTests(TestCase):
    """Routes outside ``/api/v1/catalog/`` must not be touched by the gate.

    Regression guard: a sloppy middleware that gates ``/api/`` instead of
    ``/api/v1/catalog/`` would break healthz and admin login for every
    operator. We assert the well-known unrelated routes still respond
    with their non-401 status even when the token is unset.
    """

    @override_settings(AI_BOT_PLATFORM_TOKEN="")
    def test_root_path_bypassed(self) -> None:
        # The website root resolves to a landing page handler; with no
        # token configured we must NOT see 401 there.
        response = self.client.get("/")
        self.assertNotEqual(response.status_code, 401)

    @override_settings(AI_BOT_PLATFORM_TOKEN="")
    def test_admin_login_bypassed(self) -> None:
        response = self.client.get("/admin/login/")
        self.assertNotEqual(response.status_code, 401)

    @override_settings(AI_BOT_PLATFORM_TOKEN="")
    def test_robots_txt_bypassed(self) -> None:
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)

    @override_settings(AI_BOT_PLATFORM_TOKEN="")
    def test_healthz_bypassed(self) -> None:
        """healthz must be reachable for the load-balancer probe."""
        response = self.client.get("/healthz/")
        # healthz returns 200 on healthy deps or 503 on failure — either
        # way it must NOT be 401. We only assert "not gated".
        self.assertNotEqual(response.status_code, 401)


@override_settings(AI_BOT_PLATFORM_TOKEN="")
class EmptyTokenRejectsAllCatalogTrafficTests(TestCase):
    """Deploy that forgot to set the secret must not silently authorize.

    The fail-fast guard lives in production.py; this class verifies the
    runtime fallback for non-production settings modules (local, dev,
    staging without override). Even if someone bypasses production
    fail-fast, the middleware still refuses traffic.
    """

    def test_catalog_root_returns_401_even_with_matching_empty_header(self) -> None:
        # Pass an empty header value — empty `expected` must NOT compare
        # equal to empty `provided`, because the middleware short-circuits
        # the empty-expected case.
        client = APIClient()
        client.credentials(HTTP_X_SERVICE_TOKEN="")
        response = client.get("/api/v1/catalog/services/")
        self.assertEqual(response.status_code, 401)

    def test_catalog_root_returns_401_with_any_header(self) -> None:
        client = APIClient()
        client.credentials(HTTP_X_SERVICE_TOKEN="anything")
        response = client.get("/api/v1/catalog/services/")
        self.assertEqual(response.status_code, 401)
