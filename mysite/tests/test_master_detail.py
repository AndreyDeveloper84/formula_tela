"""Тесты персональной страницы мастера /masters/<slug>/ + SEO."""
import pytest
from model_bakery import baker

from services_app.models import Master, Service, ServiceCategory


# ── Master.save() autoslug ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_master_save_generates_slug_from_cyrillic_name():
    m = Master.objects.create(name="Анна Иванова")
    assert m.slug == "anna-ivanova"


@pytest.mark.django_db
def test_master_save_preserves_existing_slug():
    m = Master.objects.create(name="Иван", slug="my-custom")
    assert m.slug == "my-custom"
    m.name = "Пётр"
    m.save()
    assert m.slug == "my-custom"


@pytest.mark.django_db
def test_master_save_dedup_slug_collision():
    m1 = Master.objects.create(name="Иванов")
    m2 = Master.objects.create(name="Иванов")
    assert m1.slug == "ivanov"
    assert m2.slug == "ivanov-2"


@pytest.mark.django_db
def test_master_get_absolute_url_uses_slug():
    m = Master.objects.create(name="Мария Петрова")
    assert m.get_absolute_url() == "/masters/mariia-petrova/"


# ── View master_detail_by_slug ─────────────────────────────────────────────

@pytest.mark.django_db
def test_master_detail_by_slug_200(client):
    m = Master.objects.create(name="Анна", is_active=True, specialization="Массажист")
    resp = client.get(f"/masters/{m.slug}/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert "Анна" in content
    assert "Массажист" in content


@pytest.mark.django_db
def test_master_detail_by_slug_with_services(client):
    cat = ServiceCategory.objects.create(name="Массажи")
    s = Service.objects.create(name="Классический массаж", category=cat, is_active=True)
    m = Master.objects.create(name="Иван", is_active=True)
    m.services.add(s)
    resp = client.get(f"/masters/{m.slug}/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert "Классический массаж" in content
    assert f"/uslugi/{s.slug}/" in content


@pytest.mark.django_db
def test_master_detail_unknown_slug_404(client):
    resp = client.get("/masters/neizvestnyj/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_master_detail_inactive_404(client):
    m = Master.objects.create(name="Тест", is_active=False)
    resp = client.get(f"/masters/{m.slug}/")
    assert resp.status_code == 404


# ── /master/<id>/ → 301 на ЧПУ ─────────────────────────────────────────────

@pytest.mark.django_db
def test_master_detail_id_redirects_to_slug(client):
    m = Master.objects.create(name="Анна", is_active=True)
    resp = client.get(f"/master/{m.pk}/")
    assert resp.status_code == 301
    assert resp["Location"] == f"/masters/{m.slug}/"


@pytest.mark.django_db
def test_master_detail_id_without_slug_renders(client):
    m = Master.objects.create(name="Тест", is_active=True)
    Master.objects.filter(pk=m.pk).update(slug="")
    resp = client.get(f"/master/{m.pk}/")
    assert resp.status_code == 200


# ── /masters/ содержит ссылки на slug ──────────────────────────────────────

@pytest.mark.django_db
def test_masters_page_uses_slug_links(client):
    m = Master.objects.create(name="Анна", is_active=True)
    resp = client.get("/masters/")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert f"/masters/{m.slug}/" in content


# ── Schema.org Person ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_master_detail_schema_org_person(client):
    m = Master.objects.create(
        name="Анна Иванова",
        is_active=True,
        specialization="Массажист",
    )
    resp = client.get(f"/masters/{m.slug}/")
    content = resp.content.decode("utf-8")
    assert '"@type": "Person"' in content
    assert "Анна Иванова" in content


# ── MasterSitemap ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_master_sitemap_contains_active_masters(client):
    m1 = Master.objects.create(name="Анна", is_active=True)
    m2 = Master.objects.create(name="Иван", is_active=True)
    m3 = Master.objects.create(name="Inactive", is_active=False)

    # Legacy без slug — пропускаем
    m4 = Master.objects.create(name="Legacy", is_active=True)
    Master.objects.filter(pk=m4.pk).update(slug="")

    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    content = resp.content.decode("utf-8")
    assert f"/masters/{m1.slug}/" in content
    assert f"/masters/{m2.slug}/" in content
    # Неактивный — не попадает
    assert f"/masters/{m3.slug}/" not in content
    assert "/masters//" not in content
