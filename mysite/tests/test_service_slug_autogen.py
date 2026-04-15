"""Тесты автогенерации Service.slug.

- Service.save() автоматически генерирует slug из name, если slug пустой
- Транслит кириллицы через unidecode + slugify
- Существующие slug не перезаписываются
- При коллизии добавляется суффикс -2, -3 ...
- Пустое name → пустой slug (не падает)
"""
import pytest

from services_app.models import Service, generate_unique_slug


# ── Service.save() ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_save_generates_slug_from_cyrillic_name():
    s = Service.objects.create(name="Классический массаж")
    assert s.slug == "klassicheskii-massazh"


@pytest.mark.django_db
def test_save_generates_slug_from_latin_name():
    s = Service.objects.create(name="RF-лифтинг — Лицо/шея")
    # "RF-лифтинг — Лицо/шея" → "RF-lifting -- Litso/sheia"
    # slugify удаляет -- и /, схлопывает дефисы
    assert s.slug == "rf-lifting-litsosheia"


@pytest.mark.django_db
def test_save_handles_quotes_and_parens():
    s = Service.objects.create(
        name='Комплекс "Гладкая кожа": массаж (45 мин) + VelaShape'
    )
    # Ожидаем: квадратные скобки/кавычки удалены, цифры и латиница сохранены
    assert "kompleks" in s.slug
    assert "gladkaia-kozha" in s.slug
    assert "velashape" in s.slug
    assert '"' not in s.slug
    assert "(" not in s.slug


@pytest.mark.django_db
def test_save_preserves_existing_slug():
    """Если slug уже задан вручную — save() не перезаписывает."""
    s = Service.objects.create(name="Классический массаж", slug="my-custom-slug")
    assert s.slug == "my-custom-slug"
    s.name = "Новое название"
    s.save()
    assert s.slug == "my-custom-slug"


@pytest.mark.django_db
def test_save_dedup_slug_collision():
    """Два Service с одинаковым name → второй получает суффикс -2."""
    s1 = Service.objects.create(name="Массаж")
    s2 = Service.objects.create(name="Массаж")
    assert s1.slug == "massazh"
    assert s2.slug == "massazh-2"


@pytest.mark.django_db
def test_save_dedup_slug_multiple_collisions():
    """Три одинаковых name → -2, -3."""
    Service.objects.create(name="Массаж")
    s2 = Service.objects.create(name="Массаж")
    s3 = Service.objects.create(name="Массаж")
    assert s2.slug == "massazh-2"
    assert s3.slug == "massazh-3"


@pytest.mark.django_db
def test_save_empty_name_keeps_slug_empty():
    """Service без name и без slug — slug остаётся пустым/None."""
    s = Service.objects.create(name="")
    assert s.slug in (None, "")


@pytest.mark.django_db
def test_save_handles_name_that_slugifies_to_empty():
    """name только из эмодзи/символов → slug пустой, без краша."""
    s = Service.objects.create(name="🔥💪✨")
    # unidecode('🔥💪✨') → '' или '[?][?][?]' → slugify → ''
    assert s.slug in (None, "")


# ── generate_unique_slug утилита ────────────────────────────────────────────

@pytest.mark.django_db
def test_generate_unique_slug_empty_name():
    assert generate_unique_slug(Service, "") == ""
    assert generate_unique_slug(Service, None) == ""


@pytest.mark.django_db
def test_generate_unique_slug_exclude_pk_for_updates():
    """При update объекта сам себя не учитываем как коллизию."""
    s = Service.objects.create(name="Массаж")
    # Симулируем: пересчитываем slug для того же объекта
    new_slug = generate_unique_slug(Service, "Массаж", pk=s.pk)
    assert new_slug == "massazh"  # не massazh-2


@pytest.mark.django_db
def test_generate_unique_slug_respects_max_length():
    long_name = "а" * 500  # после unidecode → "a"*500
    slug = generate_unique_slug(Service, long_name, max_length=50)
    assert len(slug) <= 50
