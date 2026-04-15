"""Заполнить пустые Service.slug транслитом из name.

После добавления Service.save() с автогенерацией slug новые объекты получают
slug автоматически, но существующие записи (импорт из CSV, скрипты) могут
иметь пустой slug — URL /uslugi/<slug>/ для них возвращает 404 nginx, а
кнопки «Подробнее» на страницах рендерятся как /uslugi/None/.

Эта миграция проходит по всем Service с пустым или NULL slug и проставляет
им slug на основе name через unidecode + django.utils.text.slugify.
"""
from django.db import migrations
from django.db.models import Q


def _generate_unique_slug(Service, name: str, exclude_pk: int, max_length: int = 200) -> str:
    """Локальная копия services_app.models.generate_unique_slug для миграции.

    Миграции должны быть независимы от текущего состояния моделей, поэтому
    функция дублируется здесь. Если в будущем логика изменится, эта миграция
    продолжит работать с зафиксированной версией.
    """
    from django.utils.text import slugify
    from unidecode import unidecode

    if not name:
        return ""
    base = slugify(unidecode(name))[:max_length]
    if not base:
        return ""

    qs = Service.objects.filter(slug=base).exclude(pk=exclude_pk)
    if not qs.exists():
        return base

    n = 2
    while True:
        suffix = f"-{n}"
        candidate = base[: max_length - len(suffix)] + suffix
        if not Service.objects.filter(slug=candidate).exclude(pk=exclude_pk).exists():
            return candidate
        n += 1


def forwards(apps, schema_editor):
    Service = apps.get_model("services_app", "Service")
    empty = Service.objects.filter(Q(slug__isnull=True) | Q(slug="")).order_by("pk")
    for service in empty:
        new_slug = _generate_unique_slug(Service, service.name or "", exclude_pk=service.pk)
        if not new_slug:
            # Fallback: если name пустой — используем pk
            new_slug = f"service-{service.pk}"
        service.slug = new_slug
        service.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("services_app", "0038_remove_bundle_discount"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=migrations.RunPython.noop),
    ]
