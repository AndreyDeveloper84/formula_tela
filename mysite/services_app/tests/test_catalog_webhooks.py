"""Tests for the delta-push webhook (Sprint 8 / M3 / DRF-726).

Covers:

- ``sign_body`` produces a deterministic ``sha256=<hex>`` signature
- ``verify_signature`` is the inverse and is constant-time-correct
- ``dispatch_catalog_change`` is a no-op when the URL is empty
- ``dispatch_catalog_change`` is a no-op + ERROR-logs when the URL is
  set but the secret is empty
- ``dispatch_catalog_change`` POSTs the canonical JSON body + signs it
  with the configured secret + uses the configured URL
- 4xx is permanent (no retry, returns ``{"delivered": False}``)
- post_save on a Service enqueues the task via ``transaction.on_commit``
- post_delete on a Service enqueues with ``event="deleted"``
"""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

from django.test import TestCase, TransactionTestCase, override_settings

from services_app.api.v1.catalog.webhooks.signing import (
    sign_body,
    verify_signature,
)
from services_app.api.v1.catalog.webhooks.tasks import dispatch_catalog_change
from services_app.models import Service, ServiceCategory

_URL = "https://platform.example/internal/catalog-webhook"
_SECRET = "shhh-this-is-a-test-secret-not-used-anywhere-real"  # noqa: S105


class SigningTests(TestCase):
    """Pure-function tests for ``signing.py``."""

    def test_sign_body_is_sha256_hmac_of_body(self) -> None:
        body = b'{"a":1}'
        expected_hex = hmac.new(
            _SECRET.encode(), body, hashlib.sha256,
        ).hexdigest()
        self.assertEqual(sign_body(body, _SECRET), f"sha256={expected_hex}")

    def test_sign_body_requires_bytes(self) -> None:
        with self.assertRaises(TypeError):
            sign_body("not bytes", _SECRET)  # type: ignore[arg-type]

    def test_sign_body_rejects_empty_secret(self) -> None:
        with self.assertRaises(ValueError):
            sign_body(b"data", "")

    def test_verify_round_trip(self) -> None:
        body = b'{"event":"created"}'
        sig = sign_body(body, _SECRET)
        self.assertTrue(verify_signature(body, _SECRET, sig))

    def test_verify_rejects_tampered_body(self) -> None:
        sig = sign_body(b"original", _SECRET)
        self.assertFalse(verify_signature(b"tampered", _SECRET, sig))

    def test_verify_rejects_missing_prefix(self) -> None:
        body = b"x"
        # Compute raw hex without ``sha256=`` prefix → must NOT verify.
        raw = hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()
        self.assertFalse(verify_signature(body, _SECRET, raw))


class DispatchTaskNoOpTests(TestCase):
    """The task short-circuits when the webhook is dormant."""

    @override_settings(
        AI_BOT_PLATFORM_WEBHOOK_URL="", AI_BOT_PLATFORM_WEBHOOK_SECRET="",
    )
    def test_dormant_when_url_empty(self) -> None:
        with patch(
            "services_app.api.v1.catalog.webhooks.tasks.requests.post",
        ) as mock_post:
            result = dispatch_catalog_change(
                event="updated", model="Service", pk=1, updated_at=None,
            )
        self.assertIsNone(result)
        mock_post.assert_not_called()

    @override_settings(
        AI_BOT_PLATFORM_WEBHOOK_URL=_URL, AI_BOT_PLATFORM_WEBHOOK_SECRET="",
    )
    def test_dormant_when_secret_missing_but_url_set(self) -> None:
        """Misconfig: URL set, secret missing → log ERROR + skip, don't crash."""
        with patch(
            "services_app.api.v1.catalog.webhooks.tasks.requests.post",
        ) as mock_post:
            with self.assertLogs(
                "services_app.api.catalog.webhooks", level="ERROR",
            ) as cap:
                result = dispatch_catalog_change(
                    event="updated", model="Service", pk=1, updated_at=None,
                )
        self.assertIsNone(result)
        mock_post.assert_not_called()
        self.assertTrue(
            any("no_secret" in line for line in cap.output),
            f"expected no_secret log line in: {cap.output}",
        )


@override_settings(
    AI_BOT_PLATFORM_WEBHOOK_URL=_URL, AI_BOT_PLATFORM_WEBHOOK_SECRET=_SECRET,
)
class DispatchTaskHttpTests(TestCase):
    """Verify the over-the-wire shape when the webhook is enabled."""

    def _ok_response(self, status: int = 200) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status
        resp.text = ""
        resp.raise_for_status = MagicMock()
        return resp

    def test_posts_canonical_json_with_signature(self) -> None:
        with patch(
            "services_app.api.v1.catalog.webhooks.tasks.requests.post",
            return_value=self._ok_response(),
        ) as mock_post:
            result = dispatch_catalog_change(
                event="updated", model="Service", pk=42,
                updated_at="2026-05-14T12:00:00+00:00",
            )

        self.assertEqual(result, {"delivered": True, "status": 200})
        self.assertEqual(mock_post.call_count, 1)

        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], _URL)
        # Canonical body — sort_keys + tight separators
        expected_body = json.dumps(
            {
                "event": "updated", "model": "Service", "pk": 42,
                "updated_at": "2026-05-14T12:00:00+00:00",
            },
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        self.assertEqual(kwargs["data"], expected_body)
        # Signature matches the body it was computed over
        self.assertEqual(
            kwargs["headers"]["X-Signature"],
            sign_body(expected_body, _SECRET),
        )
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertEqual(kwargs["timeout"], 5.0)

    def test_4xx_is_permanent_no_retry(self) -> None:
        """4xx from the consumer → log + give up, never retry."""
        with patch(
            "services_app.api.v1.catalog.webhooks.tasks.requests.post",
            return_value=self._ok_response(status=400),
        ) as mock_post:
            with self.assertLogs(
                "services_app.api.catalog.webhooks", level="ERROR",
            ):
                result = dispatch_catalog_change(
                    event="updated", model="Service", pk=1, updated_at=None,
                )

        self.assertEqual(result, {"delivered": False, "status": 400})
        self.assertEqual(mock_post.call_count, 1)


@override_settings(
    AI_BOT_PLATFORM_WEBHOOK_URL=_URL,
    AI_BOT_PLATFORM_WEBHOOK_SECRET=_SECRET,
    # eager mode: .delay() runs synchronously, so we can assert on the
    # task call without a real Celery worker.
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)
class SignalIntegrationTests(TransactionTestCase):
    """``post_save`` / ``post_delete`` must enqueue the task on commit.

    Uses ``TransactionTestCase`` because ``transaction.on_commit``
    callbacks only fire when the surrounding transaction actually
    commits. Plain ``TestCase`` wraps each test in a rollback, so the
    callbacks would silently never run.
    """

    def setUp(self) -> None:
        self.category = ServiceCategory.objects.create(name="Массаж", order=0)

    def test_post_save_enqueues_with_correct_payload(self) -> None:
        with patch(
            "services_app.api.v1.catalog.webhooks.tasks.requests.post",
            return_value=MagicMock(
                status_code=200, text="", raise_for_status=MagicMock(),
            ),
        ) as mock_post:
            service = Service.objects.create(
                name="Test service", is_active=True, category=self.category,
            )

        self.assertEqual(mock_post.call_count, 1)
        body = json.loads(mock_post.call_args.kwargs["data"])
        self.assertEqual(body["event"], "created")
        self.assertEqual(body["model"], "Service")
        self.assertEqual(body["pk"], service.pk)

    def test_post_save_on_update_uses_updated_event(self) -> None:
        service = Service.objects.create(
            name="Existing", is_active=True, category=self.category,
        )
        with patch(
            "services_app.api.v1.catalog.webhooks.tasks.requests.post",
            return_value=MagicMock(
                status_code=200, text="", raise_for_status=MagicMock(),
            ),
        ) as mock_post:
            service.name = "Renamed"
            service.save()

        self.assertEqual(mock_post.call_count, 1)
        body = json.loads(mock_post.call_args.kwargs["data"])
        self.assertEqual(body["event"], "updated")

    def test_post_delete_enqueues_deleted_event(self) -> None:
        service = Service.objects.create(
            name="Going away", is_active=True, category=self.category,
        )
        with patch(
            "services_app.api.v1.catalog.webhooks.tasks.requests.post",
            return_value=MagicMock(
                status_code=200, text="", raise_for_status=MagicMock(),
            ),
        ) as mock_post:
            service.delete()

        self.assertEqual(mock_post.call_count, 1)
        body = json.loads(mock_post.call_args.kwargs["data"])
        self.assertEqual(body["event"], "deleted")
        self.assertEqual(body["model"], "Service")
