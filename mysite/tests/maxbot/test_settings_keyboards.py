"""Phase 3.1 Part 2D.2 T01: settings keyboards (daily report time + water reminders)."""
from __future__ import annotations


def test_daily_report_time_keyboard_4_options():
    from maxbot.keyboards import (
        daily_report_time_keyboard,
        PAYLOAD_REPORT_TIME_18,
        PAYLOAD_REPORT_TIME_21,
        PAYLOAD_REPORT_TIME_23,
        PAYLOAD_REPORT_TIME_OFF,
    )

    payloads = _flatten(daily_report_time_keyboard())
    assert {
        PAYLOAD_REPORT_TIME_18,
        PAYLOAD_REPORT_TIME_21,
        PAYLOAD_REPORT_TIME_23,
        PAYLOAD_REPORT_TIME_OFF,
    } <= payloads


def test_water_reminders_settings_keyboard_toggle_on_off():
    from maxbot.keyboards import (
        water_reminders_settings_keyboard,
        PAYLOAD_WATER_REMINDERS_TOGGLE,
    )

    payloads_on = _flatten(water_reminders_settings_keyboard(currently_enabled=False))
    assert PAYLOAD_WATER_REMINDERS_TOGGLE in payloads_on

    payloads_off = _flatten(water_reminders_settings_keyboard(currently_enabled=True))
    assert PAYLOAD_WATER_REMINDERS_TOGGLE in payloads_off


def test_water_reminder_buttons_keyboard_3_options():
    from maxbot.keyboards import (
        water_reminder_buttons_keyboard,
        PAYLOAD_WATER_AMOUNT_250,
        PAYLOAD_WATER_AMOUNT_500,
        PAYLOAD_WATER_DISMISS,
    )

    payloads = _flatten(water_reminder_buttons_keyboard())
    assert {
        PAYLOAD_WATER_AMOUNT_250,
        PAYLOAD_WATER_AMOUNT_500,
        PAYLOAD_WATER_DISMISS,
    } <= payloads


def test_daily_report_footer_keyboard_includes_water_reminders_button():
    """Existing footer (Part 2C T03): [📊 Неделя][⚙️ Время] — добавляем 3-ю
    кнопку [🔔 Напоминания] для входа в водные настройки."""
    from maxbot.keyboards import (
        daily_report_footer_keyboard,
        PAYLOAD_REPORT_WEEKLY,
        PAYLOAD_REPORT_TIME_SETTINGS,
        PAYLOAD_WATER_REMINDERS_FOOTER,
    )

    payloads = _flatten(daily_report_footer_keyboard())
    assert PAYLOAD_REPORT_WEEKLY in payloads
    assert PAYLOAD_REPORT_TIME_SETTINGS in payloads
    assert PAYLOAD_WATER_REMINDERS_FOOTER in payloads


def _flatten(keyboard) -> set[str]:
    out = set()
    rows = (
        getattr(getattr(keyboard, "payload", None), "buttons", None)
        or getattr(keyboard, "buttons", None)
        or getattr(keyboard, "rows", None)
        or []
    )
    for row in rows:
        for btn in row:
            payload = getattr(btn, "payload", None)
            if payload is None:
                callback = getattr(btn, "callback", None)
                payload = getattr(callback, "payload", None) if callback else None
            if payload:
                out.add(payload)
    return out
