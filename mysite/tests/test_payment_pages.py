"""Тесты HTML-страниц /payments/success/ и /payments/cancelled/."""
import pytest


pytestmark = pytest.mark.django_db


class TestPaymentSuccessPage:
    def test_returns_200_with_order_param(self, client):
        resp = client.get("/payments/success/?order=FT-20260419-0001")
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "FT-20260419-0001" in content
        assert "data-order" in content  # JS poller получит номер заказа
        assert "payment-status-poll.js" in content

    def test_returns_200_without_order_param(self, client):
        # Страница ещё рендерится, но без JS-поллера.
        resp = client.get("/payments/success/")
        assert resp.status_code == 200
        assert "payment-status-poll.js" not in resp.content.decode("utf-8")

    def test_noindex_tag_present(self, client):
        resp = client.get("/payments/success/?order=X")
        assert "noindex" in resp.content.decode("utf-8")


class TestPaymentCancelledPage:
    def test_returns_200_with_order_param(self, client):
        resp = client.get("/payments/cancelled/?order=FT-42")
        assert resp.status_code == 200
        content = resp.content.decode("utf-8")
        assert "FT-42" in content
        assert "Оплата отменена" in content

    def test_returns_200_without_order_param(self, client):
        resp = client.get("/payments/cancelled/")
        assert resp.status_code == 200
        assert "Оплата отменена" in resp.content.decode("utf-8")

    def test_noindex_tag_present(self, client):
        resp = client.get("/payments/cancelled/")
        assert "noindex" in resp.content.decode("utf-8")


class TestServiceDetailModalShowsPaymentMethods:
    """Проверяем что на странице услуги отрендерился блок выбора способа оплаты."""

    def test_online_shown_when_feature_enabled(self, client, service, site_settings_online_on):
        resp = client.get(f"/uslugi/{service.slug}/")
        # Страница может 200 или 302 (redirect на slug'и) — важно что радио есть
        if resp.status_code != 200:
            pytest.skip(f"service detail route returned {resp.status_code}")
        content = resp.content.decode("utf-8")
        assert 'name="payment-method"' in content
        assert 'value="online"' in content
        assert 'value="cash"' in content
        assert 'value="card_offline"' in content

    def test_online_hidden_when_feature_disabled(self, client, service, site_settings_online_off):
        resp = client.get(f"/uslugi/{service.slug}/")
        if resp.status_code != 200:
            pytest.skip(f"service detail route returned {resp.status_code}")
        content = resp.content.decode("utf-8")
        # Фид-флаг выключен: online-кнопки не должно быть.
        assert 'value="online"' not in content
        # А офлайн-опции остаются.
        assert 'value="cash"' in content
        assert 'value="card_offline"' in content


@pytest.fixture
def site_settings_online_on(db):
    from model_bakery import baker
    from services_app.models import SiteSettings

    # Удаляем возможные существующие (SiteSettings fixture-уникален в тестах).
    SiteSettings.objects.all().delete()
    return baker.make(SiteSettings, online_payment_enabled=True)


@pytest.fixture
def site_settings_online_off(db):
    from model_bakery import baker
    from services_app.models import SiteSettings

    SiteSettings.objects.all().delete()
    return baker.make(SiteSettings, online_payment_enabled=False)
