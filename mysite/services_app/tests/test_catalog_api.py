"""Tests for the v1 catalog API (Sprint 8 / M1 / DRF-724).

Each viewset has the same shape, so we cover one (Service) end-to-end
and add narrower coverage for the cross-cutting features that the
others rely on too (``?since=`` filter behaviour, cursor pagination,
ServiceCategory navigation, M2M ``services`` list on Master). The
goal is to lock in:

- The four URL routes resolve and respond ``200 OK``
- ``is_active=False`` rows never leak into the API
- ``?since=<ISO8601>`` filters correctly when valid; passes through
  unchanged when invalid (per ``filters.py`` policy)
- Cursor pagination orders by ``updated_at`` and produces a ``next``
  link when the page is full
- M2M ``services`` list on Master is the canonical anti-hallucination
  cross-check feed (a master shows up only with the service IDs it
  actually offers)
"""
from __future__ import annotations

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from services_app.models import FAQ, HelpArticle, Master, Service, ServiceCategory

# Sprint 8 / DRF-725: the catalog API now lives behind a static service
# token. The tests below authenticate via the same X-Service-Token header
# the bot's sync layer will send. Keep this constant in lockstep with
# ``services_app/tests/test_service_token_auth.py`` so both files exercise
# the same auth contract.
_TEST_TOKEN = "catalog-test-token-m1"


@override_settings(AI_BOT_PLATFORM_TOKEN=_TEST_TOKEN)
class ServiceListEndpointTests(TestCase):
    """The list endpoint and its filters / pagination plumbing."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.category = ServiceCategory.objects.create(
            name="Массаж", order=0,
        )
        cls.service_active = Service.objects.create(
            name="Массаж спины",
            description="60-минутный массаж",
            duration_min=60,
            price_from=Decimal("2500.00"),
            is_active=True,
            is_popular=True,
            category=cls.category,
        )
        cls.service_inactive = Service.objects.create(
            name="Снят с продажи",
            description="—",
            is_active=False,
            category=cls.category,
        )

    def setUp(self) -> None:
        self.client = APIClient()
        self.client.credentials(HTTP_X_SERVICE_TOKEN=_TEST_TOKEN)

    def test_list_returns_only_active(self) -> None:
        response = self.client.get("/api/v1/catalog/services/")
        self.assertEqual(response.status_code, 200)
        names = [item["name"] for item in response.json()["results"]]
        self.assertIn("Массаж спины", names)
        self.assertNotIn("Снят с продажи", names)

    def test_serializer_shape_is_flat(self) -> None:
        response = self.client.get("/api/v1/catalog/services/")
        item = response.json()["results"][0]
        expected_keys = {
            "id", "updated_at", "name", "short", "description",
            "duration_min", "price_from", "is_active", "is_popular",
            "category_name",
        }
        self.assertEqual(set(item.keys()), expected_keys)
        # category is exposed as a string label, not an FK object.
        self.assertEqual(item["category_name"], "Массаж")

    def test_since_filter_skips_older_rows(self) -> None:
        """``?since=`` returns only rows mutated after the cursor.

        Note: we pass ``since`` via the ``data`` kwarg so DRF / Django
        URL-encodes the ``+`` in the timezone offset correctly. In a raw
        URL string ``+`` would be parsed as a space (per
        application/x-www-form-urlencoded), and the consumer's
        ``parse_datetime`` would return ``None`` and silently disable
        the filter. Real consumers (the bot's sync layer) must URL-encode
        ``+`` to ``%2B`` themselves — a separate doc-level invariant.
        """
        # Touch the service to bump updated_at to "now".
        self.service_active.description = "updated"
        self.service_active.save()

        # Query for rows newer than tomorrow → empty.
        future = (datetime.now(dt_timezone.utc) + timedelta(days=1)).isoformat()
        response = self.client.get(
            "/api/v1/catalog/services/", {"since": future},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])

    def test_since_filter_ignores_invalid_value(self) -> None:
        """Malformed ``?since=`` is silently dropped (see filters.py policy).

        Rationale: the bot's sync cursor is a consumer-side concern; a
        typo there shouldn't 400 the whole sync cycle. Worst case we
        return a slightly larger page than needed.
        """
        response = self.client.get("/api/v1/catalog/services/?since=not-an-iso-date")
        self.assertEqual(response.status_code, 200)
        # No filter applied → at least one active service comes back.
        self.assertGreaterEqual(len(response.json()["results"]), 1)

    def test_response_envelope_carries_next_when_page_size_exceeded(self) -> None:
        """Cursor pagination yields a ``next`` link once the page is full."""
        # Default page_size is 200; create 250 to force a next page.
        for i in range(250):
            Service.objects.create(
                name=f"Bulk service {i}",
                is_active=True,
                category=self.category,
            )
        response = self.client.get("/api/v1/catalog/services/")
        body = response.json()
        self.assertEqual(len(body["results"]), 200)
        self.assertIsNotNone(body["next"])


@override_settings(AI_BOT_PLATFORM_TOKEN=_TEST_TOKEN)
class MasterListEndpointTests(TestCase):
    """Master.services M2M is the anti-hallucination feed."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.category = ServiceCategory.objects.create(name="Массаж", order=0)
        cls.svc_back = Service.objects.create(
            name="Массаж спины", category=cls.category, is_active=True,
        )
        cls.svc_face = Service.objects.create(
            name="Массаж лица", category=cls.category, is_active=True,
        )
        cls.master = Master.objects.create(
            name="Анна Иванова",
            slug="anna-ivanova",
            specialization="массажист",
            bio="10 лет опыта",
            is_active=True,
        )
        cls.master.services.add(cls.svc_back, cls.svc_face)
        cls.master_inactive = Master.objects.create(
            name="Уволенный мастер",
            slug="ex-master",
            is_active=False,
        )

    def setUp(self) -> None:
        self.client = APIClient()
        self.client.credentials(HTTP_X_SERVICE_TOKEN=_TEST_TOKEN)

    def test_master_endpoint_returns_services_as_id_list(self) -> None:
        """``services`` is a list of service PKs — flat anti-hallucination feed."""
        response = self.client.get("/api/v1/catalog/masters/")
        self.assertEqual(response.status_code, 200)
        items = response.json()["results"]
        self.assertEqual(len(items), 1)  # inactive master excluded
        item = items[0]
        self.assertEqual(item["name"], "Анна Иванова")
        self.assertEqual(
            set(item["services"]),
            {self.svc_back.id, self.svc_face.id},
        )

    def test_inactive_master_not_listed(self) -> None:
        response = self.client.get("/api/v1/catalog/masters/")
        names = [item["name"] for item in response.json()["results"]]
        self.assertNotIn("Уволенный мастер", names)


@override_settings(AI_BOT_PLATFORM_TOKEN=_TEST_TOKEN)
class FaqAndHelpArticleEndpointsTests(TestCase):
    """Smoke-level coverage for the two FAQ-shaped endpoints."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.category = ServiceCategory.objects.create(name="Общее", order=0)
        FAQ.objects.create(
            question="Какие услуги вы предоставляете?",
            answer="Массаж, СПА, лимфодренаж.",
            category=cls.category,
            order=0,
            is_active=True,
        )
        FAQ.objects.create(
            question="Скрытый FAQ",
            answer="—",
            is_active=False,
            category=cls.category,
        )
        HelpArticle.objects.create(
            question="Как записаться?",
            answer="Через бот в MAX.",
            order=0,
            is_active=True,
        )

    def setUp(self) -> None:
        self.client = APIClient()
        self.client.credentials(HTTP_X_SERVICE_TOKEN=_TEST_TOKEN)

    def test_faqs_only_active(self) -> None:
        response = self.client.get("/api/v1/catalog/faqs/")
        items = response.json()["results"]
        questions = [item["question"] for item in items]
        self.assertIn("Какие услуги вы предоставляете?", questions)
        self.assertNotIn("Скрытый FAQ", questions)

    def test_help_articles_endpoint_responds(self) -> None:
        response = self.client.get("/api/v1/catalog/help-articles/")
        self.assertEqual(response.status_code, 200)
        items = response.json()["results"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["question"], "Как записаться?")


class RoutingTests(TestCase):
    """The four URL routes resolve through DRF's DefaultRouter."""

    def test_routes_named_for_reverse(self) -> None:
        # `basename` on register() → `<basename>-list` reverse name.
        self.assertEqual(
            reverse("catalog-service-list"),
            "/api/v1/catalog/services/",
        )
        self.assertEqual(
            reverse("catalog-master-list"),
            "/api/v1/catalog/masters/",
        )
        self.assertEqual(
            reverse("catalog-faq-list"),
            "/api/v1/catalog/faqs/",
        )
        self.assertEqual(
            reverse("catalog-help-article-list"),
            "/api/v1/catalog/help-articles/",
        )
