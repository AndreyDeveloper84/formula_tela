"""Phase 3.1 Part 2C T03: daily report footer keyboard."""
from __future__ import annotations


def test_daily_report_footer_has_2_stub_buttons():
    from maxbot.keyboards import (
        daily_report_footer_keyboard,
        PAYLOAD_REPORT_WEEKLY,
        PAYLOAD_REPORT_TIME_SETTINGS,
    )

    payloads = _flatten(daily_report_footer_keyboard())
    assert PAYLOAD_REPORT_WEEKLY in payloads
    assert PAYLOAD_REPORT_TIME_SETTINGS in payloads


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
