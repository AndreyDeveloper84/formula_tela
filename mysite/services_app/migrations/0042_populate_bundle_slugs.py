"""Заполнить пустые Bundle.slug транслитом из name.

После добавления Bundle.save() с автогенерацией slug новые объекты получают
slug автоматически, но существующие записи остаются с пустым slug — URL
/kompleks/<slug>/ для них не сгенерируется.

Эта миграция проходит по всем Bundle с пустым или NULL slug и проставляет
им slug через unidecode + django.utils.text.slugify.
"""
from django.db import migrations
from django.db.models import Q


def _generate_unique_slug(Bundle, name: str, exclude_pk: int, max_length: int = 200) -> str:
    from django.utils.text import slugify
    from unidecode import unidecode

    if not name:
        return ""
    base = slugify(unidecode(name))[:max_length]
    if not base:
        return ""

    qs = Bundle.objects.filter(slug=base).exclude(pk=exclude_pk)
    if not qs.exists():
        return base

    n = 2
    while True:
        suffix = f"-{n}"
        candidate = base[: max_length - len(suffix)] + suffix
        if not Bundle.objects.filter(slug=candidate).exclude(pk=exclude_pk).exists():
            return candidate
        n += 1


def forwards(apps, schema_editor):
    Bundle = apps.get_model("services_app", "Bundle")
    empty = Bundle.objects.filter(Q(slug__isnull=True) | Q(slug="")).order_by("pk")
    for bundle in empty:
        new_slug = _generate_unique_slug(Bundle, bundle.name or "", exclude_pk=bundle.pk)
        if not new_slug:
            new_slug = f"kompleks-{bundle.pk}"
        bundle.slug = new_slug
        bundle.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("services_app", "0041_bundle_seo_description_bundle_seo_h1_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=migrations.RunPython.noop),
    ]
