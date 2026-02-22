"""
Тесты Django-вью: HTTP статусы, контекст шаблонов.
Без реальных вызовов внешних API.
"""
import pytest
from model_bakery import baker


# ─── home ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_home_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_home_popular_services_in_context(client):
    baker.make("services_app.Service", is_active=True, is_popular=True, _quantity=2)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "top_items" in resp.context


# ─── services ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_services_returns_200(client):
    resp = client.get("/services/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_services_categories_in_context(client, category):
    resp = client.get("/services/")
    assert resp.status_code == 200
    assert "categories" in resp.context


# ─── service_detail_by_slug ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_service_detail_valid_slug_200(client, service):
    resp = client.get(f"/uslugi/{service.slug}/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_service_detail_invalid_slug_404(client):
    resp = client.get("/uslugi/ne-sushchestvuet/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_service_detail_inactive_slug_404(client, service):
    """Неактивная услуга → 404."""
    service.is_active = False
    service.save()
    resp = client.get(f"/uslugi/{service.slug}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_service_detail_301_redirect_from_id(client, service):
    """GET /service/<id>/ → 301 на /uslugi/<slug>/."""
    resp = client.get(f"/service/{service.id}/")
    assert resp.status_code == 301
    assert f"/uslugi/{service.slug}/" in resp["Location"]


# ─── masters ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_masters_returns_200(client):
    resp = client.get("/masters/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_masters_only_active_in_context(client):
    baker.make("services_app.Master", is_active=True, _quantity=2)
    baker.make("services_app.Master", is_active=False, _quantity=1)
    resp = client.get("/masters/")
    assert resp.status_code == 200
    masters = resp.context["masters"]
    assert all(m.is_active for m in masters)


# ─── promotions ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_promotions_returns_200(client):
    resp = client.get("/promotions/")
    assert resp.status_code == 200


# ─── bundles ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_bundles_returns_200(client):
    resp = client.get("/bundles/")
    assert resp.status_code == 200


# ─── category_services ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_category_services_valid_200(client, category):
    resp = client.get(f"/services/{category.id}/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_category_services_invalid_404(client):
    resp = client.get("/services/99999/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_category_services_context_has_category(client, category):
    resp = client.get(f"/services/{category.id}/")
    assert resp.context["category"].id == category.id
