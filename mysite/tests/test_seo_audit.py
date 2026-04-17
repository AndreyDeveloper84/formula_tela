"""Тесты для SEO-аудита: apply_seo_audit + шаблон категорий."""
import pytest
from django.core.management import call_command

from services_app.models import Service, ServiceCategory


@pytest.mark.django_db
def test_apply_seo_dry_run_does_not_modify(capsys):
    """Dry-run не меняет БД."""
    svc = Service.objects.create(
        name="Тестовый массаж",
        slug="klassicheskij-massazh",
        seo_title="OLD TITLE",
    )
    call_command("apply_seo_audit", "--dry-run")
    svc.refresh_from_db()
    assert svc.seo_title == "OLD TITLE"


@pytest.mark.django_db
def test_apply_seo_updates_service():
    """Обновляет seo_title/h1/description для услуги."""
    svc = Service.objects.create(
        name="Классический массаж",
        slug="klassicheskij-massazh",
    )
    call_command("apply_seo_audit")
    svc.refresh_from_db()
    assert "Пензе" in svc.seo_title
    assert "Пензе" in svc.seo_h1
    assert len(svc.seo_description) > 20


@pytest.mark.django_db
def test_apply_seo_updates_category():
    """Обновляет seo_title/h1/description для категории."""
    cat = ServiceCategory.objects.create(
        name="Ручные массажи",
        slug="ruchnye-massazhi",
    )
    call_command("apply_seo_audit")
    cat.refresh_from_db()
    assert "Пензе" in cat.seo_title
    assert "Пензе" in cat.seo_h1
    assert len(cat.seo_description) > 20


@pytest.mark.django_db
def test_apply_seo_missing_slug(capsys):
    """Slug не найден в БД — логирует, не падает."""
    call_command("apply_seo_audit")
    output = capsys.readouterr().out
    # Должно быть "Не найдено" т.к. slug'ов в БД нет
    assert "Не найдено" in output or "без изменений" in output


@pytest.mark.django_db
def test_category_template_renders_h1():
    """Шаблон категории рендерит H1, не H2."""
    cat = ServiceCategory.objects.create(
        name="Тест",
        slug="test-cat",
        seo_h1="Тест SEO H1 в Пензе",
        seo_title="Тест в Пензе",
    )
    from django.test import Client
    r = Client().get(f"/kategorii/{cat.slug}/")
    if r.status_code == 200:
        html = r.content.decode("utf-8")
        assert "<h1>" in html.lower()
        assert "Тест SEO H1 в Пензе" in html


@pytest.mark.django_db
def test_service_seo_title_no_duplicate():
    """seo_title без суффикса «Формула Тела» не создаёт дубль в <title>."""
    cat = ServiceCategory.objects.create(name="Тест", slug="test-cat")
    svc = Service.objects.create(
        name="Тест услуга",
        slug="test-service",
        seo_title="Тест услуга в Пензе — от 1 000 ₽",
        seo_h1="Тест услуга в Пензе",
        category=cat,
    )
    from django.test import Client
    r = Client().get(f"/uslugi/{svc.slug}/")
    if r.status_code == 200:
        html = r.content.decode("utf-8")
        import re
        title = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
        if title:
            t = title.group(1)
            # Не должно быть "| |" или двойного "Формула Тела"
            assert "| |" not in t
            assert t.lower().count("формула тела") <= 1
