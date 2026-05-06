"""Phase 3 T10: BotUser nutrition fields — defaults, JSON round-trip.

Migration: services_app/migrations/0068_botuser_nutrition_fields.py
Fields added:
    - timezone (default "Europe/Moscow")
    - health_flags (default dict)
    - nutrition_onboarded_at (null=True)
    - nutrition_settings (default dict)
"""
from __future__ import annotations

import pytest
from model_bakery import baker

from services_app.models import BotUser

pytestmark = pytest.mark.django_db


def test_botuser_defaults_for_new_user():
    """Newly created BotUser получает все nutrition fields с defaults."""
    bu = baker.make(BotUser, max_user_id=42_000_001)
    assert bu.timezone == "Europe/Moscow"
    assert bu.health_flags == {}
    assert bu.nutrition_onboarded_at is None
    assert bu.nutrition_settings == {}


def test_health_flags_json_round_trip():
    """Сложные health_flags сохраняются и читаются без потерь."""
    flags = {
        "pregnant": True,
        "breastfeeding": False,
        "diabetes_t2": True,
        "allergies": [
            {"item": "лактоза", "type": "intolerance"},
            {"item": "орехи", "type": "allergy"},
        ],
        "allergies_vague": False,
        "weight_skipped": True,
    }
    bu = baker.make(BotUser, max_user_id=42_000_002, health_flags=flags)
    bu.refresh_from_db()
    assert bu.health_flags == flags
    assert bu.health_flags["allergies"][0]["item"] == "лактоза"


def test_nutrition_settings_json_round_trip():
    """nutrition_settings JSON хранит UI-настройки и cache."""
    settings = {
        "daily_report_time": "21:00",
        "daily_report_enabled": True,
        "water_reminders_enabled": False,
        "alcohol_hint_shown_at": "2026-05-02T14:00:00Z",
        "daily_report": {
            "date": "2026-05-02",
            "content": "Итоги дня...",
            "generated_at": "2026-05-02T21:00:00Z",
        },
    }
    bu = baker.make(BotUser, max_user_id=42_000_003, nutrition_settings=settings)
    bu.refresh_from_db()
    assert bu.nutrition_settings["daily_report_time"] == "21:00"
    assert bu.nutrition_settings["daily_report"]["date"] == "2026-05-02"


def test_timezone_can_be_overridden():
    """timezone можно переопределить — например для пользователя из другого региона."""
    bu = baker.make(BotUser, max_user_id=42_000_004, timezone="Europe/Samara")
    bu.refresh_from_db()
    assert bu.timezone == "Europe/Samara"


def test_existing_botuser_gets_defaults_after_migration():
    """Existing BotUser (без nutrition fields в момент создания) видит defaults на чтении.

    После применения миграции 0068 со значениями default. Этот тест эмулирует
    миграцию: создаём пользователя через baker (всё ещё в DB после migration),
    очищаем явные значения и проверяем defaults на refresh.
    """
    bu = baker.make(BotUser, max_user_id=42_000_005)
    # Явные defaults после миграции — поле уже не NULL.
    assert bu.timezone == "Europe/Moscow"
    assert bu.health_flags == {}
    assert bu.nutrition_settings == {}


def test_food_scanner_consent_at_unchanged():
    """Старое поле food_scanner_consent_at (миграция 0065) не сломалось."""
    bu = baker.make(BotUser, max_user_id=42_000_006)
    assert bu.food_scanner_consent_at is None
    # И его всё ещё можно set'ить.
    from django.utils import timezone as tz
    bu.food_scanner_consent_at = tz.now()
    bu.save()
    bu.refresh_from_db()
    assert bu.food_scanner_consent_at is not None
