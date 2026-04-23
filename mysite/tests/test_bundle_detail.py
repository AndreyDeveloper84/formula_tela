"""Тесты детальной страницы комплекса /kompleks/<slug>/.

Покрывают:
- Bundle.save() автогенерация slug
- View bundle_detail_by_slug: 200/404/301
- /bundle/<id>/ редиректит на /kompleks/<slug>/
- bundles.html содержит ссылки на /kompleks/<slug>/
- BundleSitemap возвращает только active + slug-заполненные
"""
import pytest
from decimal import Decimal
from model_bakery import baker

from services_app.models import Bundle


# ── Bundle.save() autoslug ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_bundle_save_generates_slug_from_cyrillic_name():
    b = Bundle.objects.create(name="Комплекс из 3 массажей")
    assert b.slug == "kompleks-iz-3-massazhei"


@pytest.mark.django_db
def test_bundle_save_preserves_existing_slug():
    b = Bundle.objects.create(name="Комплекс", slug="my-custom-kompleks")
    assert b.slug == "my-custom-kompleks"
    b.name = "Другое название"
    b.save()
    assert b.slug == "my-custom-kompleks"


@pytest.mark.django_db
def test_bundle_save_dedup_slug():
    b1 = Bundle.objects.create(name="SPA комплекс")
    b2 = Bundle.objects.create(name="SPA комплекс")
    assert b1.slug == "spa-kompleks"
    assert b2.slug == "spa-kompleks-2"


@pytest.mark.django_db
def test_bundle_save_empty_name_keeps_slug_empty():
    b = Bundle.objects.create(name=None)
    assert b.slug in (None, "")


# ── get_absolute_url ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_bundle_get_absolute_url_uses_slug():
    b = Bundle.objects.create(name="Комплекс тест", slug="kompleks-test")
    assert b.get_absolute_url() == "/kompleks/kompleks-test/"


# ── View bundle_detail_by_slug ──────────────────────────────────────────────

@pytest.mark.django_db
def test_bundle_detail_by_slug_200(client):
    b = Bundle.objects.create(
        name="Комплекс премиум",
        description="Описание премиум комплекса",
        fixed_price=Decimal("8000"),
        is_active=True,
    )
    resp = client.get(f"/kompleks/{b.slug}/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert "Комплекс премиум" in content
    assert "8000" in content


@pytest.mark.django_db
def test_bundle_detail_unknown_slug_404(client):
    resp = client.get("/kompleks/neizvestnyj/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_bundle_detail_inactive_404(client):
    b = Bundle.objects.create(name="Неактивный", is_active=False)
    resp = client.get(f"/kompleks/{b.slug}/")
    assert resp.status_code == 404


# ── /bundle/<id>/ → 301 на /kompleks/<slug>/ ───────────────────────────────

@pytest.mark.django_db
def test_bundle_detail_id_redirects_to_slug(client):
    b = Bundle.objects.create(name="Комплекс тест", is_active=True)
    resp = client.get(f"/bundle/{b.pk}/")
    assert resp.status_code == 301
    assert resp["Location"] == f"/kompleks/{b.slug}/"


@pytest.mark.django_db
def test_bundle_detail_id_inactive_404(client):
    b = Bundle.objects.create(name="Неактивный", is_active=False)
    resp = client.get(f"/bundle/{b.pk}/")
    assert resp.status_code == 404


# ── bundles.html содержит ссылки на /kompleks/<slug>/ ──────────────────────

@pytest.mark.django_db
def test_bundles_page_contains_kompleks_link(client):
    b = Bundle.objects.create(
        name="Комплекс из списка",
        fixed_price=Decimal("5000"),
        is_active=True,
    )
    resp = client.get("/bundles/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert f"/kompleks/{b.slug}/" in content


# ── BundleSitemap ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_bundle_sitemap_returns_active_with_slug(client):
    b1 = Bundle.objects.create(name="Активный 1", is_active=True)
    b2 = Bundle.objects.create(name="Активный 2", is_active=True)
    b3 = Bundle.objects.create(name="Неактивный", is_active=False)

    # legacy без slug — пропустить
    b4 = Bundle.objects.create(name="Без slug", is_active=True)
    Bundle.objects.filter(pk=b4.pk).update(slug="")

    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")

    assert f"/kompleks/{b1.slug}/" in content
    assert f"/kompleks/{b2.slug}/" in content
    assert "/kompleks//" not in content


# ── Order.bundle FK ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_order_bundle_fk_optional():
    """Order без bundle создаётся нормально (FK nullable)."""
    from services_app.models import Order
    order = Order.objects.create(
        order_type="certificate",
        client_name="Тест",
        client_phone="+79990000000",
        total_amount=Decimal("1000"),
    )
    assert order.bundle is None


@pytest.mark.django_db
def test_order_bundle_fk_links_to_bundle():
    from services_app.models import Order
    b = Bundle.objects.create(name="Комплекс для заказа", fixed_price=Decimal("5000"))
    order = Order.objects.create(
        order_type="bundle",
        client_name="Иван",
        client_phone="+79991112233",
        total_amount=b.total_price(),
        bundle=b,
    )
    assert order.bundle_id == b.pk
    assert b.orders.count() == 1


# ── Онлайн-оплата комплексов ─────────────────────────────────────────────────


import json
from unittest.mock import MagicMock


@pytest.mark.django_db
class TestBundleOnlinePayment:
    url = "/api/bundle/request/"

    @pytest.fixture
    def bundle(self, db):
        return Bundle.objects.create(
            name="Антицеллюлитный комплекс",
            fixed_price=Decimal("9000"),
            is_active=True,
        )

    @pytest.fixture
    def online_enabled(self, db):
        from model_bakery import baker
        from services_app.models import SiteSettings
        SiteSettings.objects.all().delete()
        return baker.make(SiteSettings, online_payment_enabled=True)

    @pytest.fixture
    def mock_payment_service(self, monkeypatch):
        svc = MagicMock()
        svc.create_for_order.return_value = "https://yookassa.test/confirm/bundle1"
        monkeypatch.setattr("payments.services.PaymentService", MagicMock(return_value=svc))
        return svc

    def _payload(self, bundle_id, **kwargs):
        base = {
            "name": "Клиент",
            "phone": "+79990001122",
            "bundle_id": bundle_id,
            "payment_method": "online",
        }
        base.update(kwargs)
        return base

    def test_online_returns_payment_url(self, client, bundle, online_enabled, mock_payment_service):
        resp = client.post(
            self.url, json.dumps(self._payload(bundle.id)),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["payment_method"] == "online"
        assert data["payment_url"] == "https://yookassa.test/confirm/bundle1"
        assert "order_number" in data

    def test_online_creates_order_with_bundle(self, client, bundle, online_enabled, mock_payment_service):
        resp = client.post(
            self.url, json.dumps(self._payload(bundle.id)),
            content_type="application/json",
        )
        from services_app.models import Order
        order = Order.objects.get(number=resp.json()["order_number"])
        assert order.order_type == "bundle"
        assert order.bundle_id == bundle.pk
        assert order.payment_method == "online"
        assert order.payment_status == "pending"

    def test_online_disabled_returns_error(self, client, bundle, db):
        from model_bakery import baker
        from services_app.models import SiteSettings
        SiteSettings.objects.all().delete()
        baker.make(SiteSettings, online_payment_enabled=False)
        resp = client.post(
            self.url, json.dumps(self._payload(bundle.id)),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "online_payment_disabled"

    def test_online_without_bundle_id_returns_error(self, client, online_enabled, mock_payment_service):
        payload = {"name": "Клиент", "phone": "+79990001122", "payment_method": "online"}
        resp = client.post(self.url, json.dumps(payload), content_type="application/json")
        assert resp.status_code == 400

    def test_cash_flow_creates_bundle_request(self, client, bundle, db):
        from unittest.mock import MagicMock, patch
        payload = {
            "name": "Клиент",
            "phone": "+79990001122",
            "bundle_id": bundle.id,
            "payment_method": "cash",
        }
        with patch("notifications.http_requests.post", MagicMock()):
            resp = client.post(self.url, json.dumps(payload), content_type="application/json")
        assert resp.status_code == 200
        from services_app.models import BundleRequest
        assert BundleRequest.objects.filter(bundle=bundle).exists()


@pytest.mark.django_db
class TestFulfillPaidBundle:
    @pytest.fixture
    def bundle_order(self, db):
        bundle = Bundle.objects.create(name="Спа-комплекс", fixed_price=Decimal("5000"))
        from services_app.models import Order
        return Order.objects.create(
            order_type="bundle",
            bundle=bundle,
            payment_method="online",
            payment_status="succeeded",
            status="pending",
            client_name="Клиент",
            client_phone="+79990001122",
            total_amount=Decimal("5000"),
        )

    def test_sends_telegram(self, bundle_order, monkeypatch):
        mock_tg = MagicMock()
        monkeypatch.setattr("payments.tasks.send_notification_telegram", mock_tg)
        from payments.tasks import fulfill_paid_bundle
        fulfill_paid_bundle(bundle_order.pk)
        assert mock_tg.called
        assert "Комплекс оплачен" in mock_tg.call_args[0][0]

    def test_skips_nonexistent_order(self, db, monkeypatch):
        mock_tg = MagicMock()
        monkeypatch.setattr("payments.tasks.send_notification_telegram", mock_tg)
        from payments.tasks import fulfill_paid_bundle
        fulfill_paid_bundle(99999)
        mock_tg.assert_not_called()
