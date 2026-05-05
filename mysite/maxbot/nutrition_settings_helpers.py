"""Phase 3.1 Part 2D.2: helpers для BotUser.nutrition_settings JSON.

Schema (per BotUser model docstring):
    {
        "daily_report_time": "18:00" | "21:00" | "23:00" | "off",
        "daily_report_enabled": bool,  # legacy, не используется в Part 2D.2 (off=disable)
        "water_reminders_enabled": bool,
        "last_water_dismissed_at": ISO timestamp | None,
        # ... другие keys из ранних phases
    }

Все функции — sync ORM. Async caller'ы оборачивают в `sync_to_async`.
"""
from __future__ import annotations

from typing import Any


def get_setting(bot_user, key: str, *, default: Any = None) -> Any:
    """Return value из nutrition_settings или default."""
    settings = bot_user.nutrition_settings or {}
    return settings.get(key, default)


def set_setting(bot_user, key: str, value: Any) -> None:
    """Set value в nutrition_settings + save (только это поле).

    Other keys (food_disclaimer_shown_at, etc.) preserved.
    """
    settings = dict(bot_user.nutrition_settings or {})
    settings[key] = value
    bot_user.nutrition_settings = settings
    bot_user.save(update_fields=["nutrition_settings"])
