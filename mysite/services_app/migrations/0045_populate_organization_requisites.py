"""
Заполняет поля реквизитов организации в SiteSettings значениями
из справки АО «ТБанк» по ИП Тихонов А.С.

Идемпотентно: работает при 0 / 1 / N инстансах. Если на проде уже
кто-то заполнил реквизиты вручную — миграция перезапишет, но
`ON CONFLICT` здесь не нужен, т.к. SiteSettings — singleton.
"""
from django.db import migrations


_REQUISITES = {
    "legal_name": "ИП Тихонов Андрей Сергеевич",
    "legal_address": "440007, Россия, Пензенская обл, г. Пенза, ул. Фабричная, д. 11, кв. 87",
    "inn": "583403546770",
    "ogrn": "318583500051257",
    "bank_name": "АО «ТБанк»",
    "bank_account": "40802810700000711032",
    "bank_bik": "044525974",
    "bank_corr_account": "30101810145250000974",
}


def populate(apps, schema_editor):
    SiteSettings = apps.get_model("services_app", "SiteSettings")
    SiteSettings.objects.update(**_REQUISITES)


def rollback(apps, schema_editor):
    SiteSettings = apps.get_model("services_app", "SiteSettings")
    SiteSettings.objects.update(**{k: "" for k in _REQUISITES})


class Migration(migrations.Migration):
    dependencies = [
        ("services_app", "0044_sitesettings_bank_account_sitesettings_bank_bik_and_more"),
    ]
    operations = [
        migrations.RunPython(populate, rollback),
    ]
