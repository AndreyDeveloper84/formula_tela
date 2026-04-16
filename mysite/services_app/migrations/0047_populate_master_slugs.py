"""Заполнить пустые Master.slug транслитом из name.

После добавления Master.save() с автогенерацией slug новые объекты получают
slug автоматически, но существующие legacy-записи (импорт, raw SQL) могут
иметь NULL или пустой slug — тогда URL /masters/<slug>/ для них не
сгенерируется, и MasterSitemap/шаблоны пропустят их.

Эта миграция проходит по всем Master с пустым slug и заполняет через
unidecode + django.utils.text.slugify с дедупом суффиксом -2, -3, ...
"""
from django.db import migrations
from django.db.models import Q


def _generate_unique_slug(Master, name: str, exclude_pk: int, max_length: int = 100) -> str:
    from django.utils.text import slugify
    from unidecode import unidecode

    if not name:
        return ""
    base = slugify(unidecode(name))[:max_length]
    if not base:
        return ""

    qs = Master.objects.filter(slug=base).exclude(pk=exclude_pk)
    if not qs.exists():
        return base

    n = 2
    while True:
        suffix = f"-{n}"
        candidate = base[: max_length - len(suffix)] + suffix
        if not Master.objects.filter(slug=candidate).exclude(pk=exclude_pk).exists():
            return candidate
        n += 1


def forwards(apps, schema_editor):
    Master = apps.get_model("services_app", "Master")
    empty = Master.objects.filter(Q(slug__isnull=True) | Q(slug="")).order_by("pk")
    for master in empty:
        new_slug = _generate_unique_slug(Master, master.name or "", exclude_pk=master.pk)
        if not new_slug:
            new_slug = f"master-{master.pk}"
        master.slug = new_slug
        master.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("services_app", "0046_master_slug_master_services_ap_slug_e7c705_idx"),
    ]

    operations = [
        migrations.RunPython(forwards, reverse_code=migrations.RunPython.noop),
    ]
