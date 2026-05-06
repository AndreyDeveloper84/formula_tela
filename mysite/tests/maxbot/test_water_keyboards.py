"""Phase 3.1 Part 2B T01: water keyboards (amount, extended, undo)."""
from __future__ import annotations


def test_water_amount_keyboard_4_buttons():
    from maxbot.keyboards import (
        water_amount_keyboard,
        PAYLOAD_WATER_AMOUNT_200,
        PAYLOAD_WATER_AMOUNT_250,
        PAYLOAD_WATER_AMOUNT_500,
        PAYLOAD_WATER_AMOUNT_1000,
        PAYLOAD_WATER_MORE,
    )

    payloads = _flatten_payloads(water_amount_keyboard())
    assert {
        PAYLOAD_WATER_AMOUNT_200,
        PAYLOAD_WATER_AMOUNT_250,
        PAYLOAD_WATER_AMOUNT_500,
        PAYLOAD_WATER_AMOUNT_1000,
        PAYLOAD_WATER_MORE,
    } <= payloads


def test_water_extended_keyboard_includes_atypical_volumes():
    from maxbot.keyboards import (
        water_extended_keyboard,
        PAYLOAD_WATER_EXTENDED_150,
        PAYLOAD_WATER_EXTENDED_300,
        PAYLOAD_WATER_EXTENDED_350,
        PAYLOAD_WATER_EXTENDED_750,
        PAYLOAD_WATER_EXTENDED_1500,
    )

    payloads = _flatten_payloads(water_extended_keyboard())
    assert {
        PAYLOAD_WATER_EXTENDED_150,
        PAYLOAD_WATER_EXTENDED_300,
        PAYLOAD_WATER_EXTENDED_350,
        PAYLOAD_WATER_EXTENDED_750,
        PAYLOAD_WATER_EXTENDED_1500,
    } <= payloads


def test_water_undo_keyboard_payload_includes_entry_id():
    from maxbot.keyboards import water_undo_keyboard, PAYLOAD_WATER_UNDO_PREFIX

    kb = water_undo_keyboard(entry_id="abc-123")
    payloads = _flatten_payloads(kb)
    assert any(p.startswith(PAYLOAD_WATER_UNDO_PREFIX) for p in payloads)
    assert any("abc-123" in p for p in payloads)


def _flatten_payloads(keyboard) -> set[str]:
    out: set[str] = set()
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
