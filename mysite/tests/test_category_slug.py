"""Тесты ЧПУ для ServiceCategory и ревизии id-based ссылок.

Покрывают:
- ServiceCategory.save() автогенерация slug
- View category_services_by_slug: 200/404
- /services/<int:id>/ → 301 на /kategorii/<slug>/
- /services/ содержит ссылки /kategorii/<slug>/ (не /services/<id>/)
- /masters/ содержит ссылки /uslugi/<slug>/
- CategorySitemap отдаёт активные категории со slug
"""
import pytest
from model_bakery import baker

from services_app.models import ServiceCategory, Service


# ── ServiceCategory.save() autoslug ─────────────────────────────────────────

@pytest.mark.django_db
def test_category_save_generates_slug_from_cyrillic_name():
    c = ServiceCategory.objects.create(name="Ручные массажи")
    assert c.slug == "ruchnye-massazhi"


@pytest.mark.django_db
def test_category_save_preserves_existing_slug():
    c = ServiceCategory.objects.create(name="Массажи", slug="my-custom")
    assert c.slug == "my-custom"
    c.name = "Другое"
    c.save()
    assert c.slug == "my-custom"


@pytest.mark.django_db
def test_category_save_dedup_slug_collision():
    c1 = ServiceCategory.objects.create(name="SPA")
    c2 = ServiceCategory(name="SPA-2")  # baker-like workaround для уникальности name
    c2.name = "SPA"  # коллизия по slug (оба → 'spa'), но unique по name разные
    # Поскольку name имеет unique=True — создаём с другим name которое даст тот же slug
    # "SPA" → 'spa', "Spa" → 'spa' тоже
    c2 = ServiceCategory.objects.create(name="Spa")
    assert c1.slug == "spa"
    assert c2.slug == "spa-2"


@pytest.mark.django_db
def test_category_get_absolute_url_uses_slug():
    c = ServiceCategory.objects.create(name="Ручные массажи")
    assert c.get_absolute_url() == "/kategorii/ruchnye-massazhi/"


# ── View category_services_by_slug ─────────────────────────────────────────

@pytest.mark.django_db
def test_category_services_by_slug_200(client):
    c = ServiceCategory.objects.create(name="Ручные массажи")
    resp = client.get(f"/kategorii/{c.slug}/")
    assert resp.status_code == 200
    assert "Ручные массажи" in resp.content.decode("utf-8")


@pytest.mark.django_db
def test_category_services_by_slug_unknown_404(client):
    resp = client.get("/kategorii/neizvestnaya/")
    assert resp.status_code == 404


# ── /services/<id>/ → 301 на /kategorii/<slug>/ ────────────────────────────

@pytest.mark.django_db
def test_category_services_id_redirects_to_slug(client):
    c = ServiceCategory.objects.create(name="Ручные массажи")
    resp = client.get(f"/services/{c.pk}/")
    assert resp.status_code == 301
    assert resp["Location"] == f"/kategorii/{c.slug}/"


@pytest.mark.django_db
def test_category_services_id_without_slug_renders(client):
    c = ServiceCategory.objects.create(name="Тест")
    # Обнуляем slug через update в обход save() — имитируем legacy данные
    ServiceCategory.objects.filter(pk=c.pk).update(slug="")
    resp = client.get(f"/services/{c.pk}/")
    # Без slug — 301 не происходит, рендерится напрямую
    assert resp.status_code == 200


# ── Ссылки в шаблонах ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_services_page_has_slug_category_links(client):
    c = ServiceCategory.objects.create(name="Ручные массажи")
    resp = client.get("/services/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert f"/kategorii/{c.slug}/" in content


@pytest.mark.django_db
def test_masters_page_uses_slug_service_links(client):
    c = ServiceCategory.objects.create(name="Массажи")
    s = Service.objects.create(name="Классический массаж", category=c, is_active=True)
    m = baker.make("services_app.Master", is_active=True)
    m.services.add(s)
    resp = client.get("/masters/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert f"/uslugi/{s.slug}/" in content


# ── CategorySitemap ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_category_sitemap_returns_categories_with_slug(client):
    c1 = ServiceCategory.objects.create(name="Ручные массажи")
    c2 = ServiceCategory.objects.create(name="Аппаратная косметология")

    # Legacy без slug — не попадает
    c3 = ServiceCategory.objects.create(name="Legacy")
    ServiceCategory.objects.filter(pk=c3.pk).update(slug="")

    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert f"/kategorii/{c1.slug}/" in content
    assert f"/kategorii/{c2.slug}/" in content
    # Legacy без slug не должна попасть
    assert "/kategorii//" not in content
