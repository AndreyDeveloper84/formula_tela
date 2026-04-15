"""Заполнить пустые ServiceCategory.slug транслитом из name.

После добавления ServiceCategory.save() с автогенерацией slug новые объекты
получают slug автоматически, но существующие legacy-записи (до этого
изменения) могут иметь NULL или пустой slug — тогда URL /kategorii/<slug>/
для них не сгенерируется, и `CategorySitemap` пропустит их.

Эта миграция проходит по всем ServiceCategory с Q(slug__isnull=True) | Q(slug="")
и проставляет им slug через unidecode + django.utils.text.slugify.
"""
from django.db import migrations
from django.db.models import Q


def _generate_unique_slug(ServiceCategory, name: str, exclude_pk: int, max_length: int = 50) -> str:
    from django.utils.text import slugify
    from unidecode import unidecode

    if not name:
        return ""
    base = slugify(unidecode(name))[:max_length]
    if not base:
        return ""

    qs = ServiceCategory.objects.filter(slug=base).exclude(pk=exclude_pk)
    if not qs.exists():
        return base

    n = 2
    while True:
        suffix = f"-{n}"
        candidate = base[: max_length - len(suffix)] + suffix
        if not ServiceCategory.objects.filter(slug=candidate).exclude(pk=exclude_pk).exists():
            return candidate
        n += 1


def forwards(apps, schema_editor):
    ServiceCategory = apps.get_model("services_app", "ServiceCategory")
    empty = ServiceCategory.objects.filter(Q(slug__isnull=True) | Q(slug="")).order_by("pk")
    for category in empty:
        new_slug = _generate_unique_slug(ServiceCategory, category.name or "", exclude_pk=category.pk)
        if not new_slug:
            new_slug = f"category-{category.pk}"
        category.slug = new_slug
        category.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("services_app", "0042_populate_bundle_slugs"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=migrations.RunPython.noop),
    ]
