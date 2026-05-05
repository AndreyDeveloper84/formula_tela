"""Phase 3.2A T01: TIER-B keyboards + payload constants smoke."""
from __future__ import annotations


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


def test_tier_b_states_exist():
    from maxbot.states import NutritionAnketaStates
    for name in (
        "awaiting_health_consent",
        "awaiting_pregnancy",
        "awaiting_breastfeeding",
        "awaiting_diabetes",
        "awaiting_chronic",
        "awaiting_allergies",
        "awaiting_allergies_text",
        "awaiting_meds",
        "awaiting_menopause",
    ):
        assert hasattr(NutritionAnketaStates, name), f"missing {name}"


def test_tier_b_consent_keyboard_has_2_buttons():
    from maxbot.keyboards import (
        tier_b_consent_keyboard,
        PAYLOAD_TIER_B_CONSENT_OK,
        PAYLOAD_TIER_B_CONSENT_DECLINE,
    )
    payloads = _flatten(tier_b_consent_keyboard())
    assert PAYLOAD_TIER_B_CONSENT_OK in payloads
    assert PAYLOAD_TIER_B_CONSENT_DECLINE in payloads


def test_tier_b_yes_no_keyboard_no_skip():
    """Pregnancy + Diabetes — БЕЗ skip per Design §4.5."""
    from maxbot.keyboards import (
        tier_b_yes_no_keyboard,
        PAYLOAD_TIER_B_YES,
        PAYLOAD_TIER_B_NO,
        PAYLOAD_TIER_B_SKIP,
    )
    payloads = _flatten(tier_b_yes_no_keyboard())
    assert PAYLOAD_TIER_B_YES in payloads
    assert PAYLOAD_TIER_B_NO in payloads
    assert PAYLOAD_TIER_B_SKIP not in payloads


def test_tier_b_yes_no_skip_keyboard():
    """Breastfeeding/Meds — С skip."""
    from maxbot.keyboards import (
        tier_b_yes_no_skip_keyboard,
        PAYLOAD_TIER_B_YES,
        PAYLOAD_TIER_B_NO,
        PAYLOAD_TIER_B_SKIP,
    )
    payloads = _flatten(tier_b_yes_no_skip_keyboard())
    assert {PAYLOAD_TIER_B_YES, PAYLOAD_TIER_B_NO, PAYLOAD_TIER_B_SKIP} <= payloads


def test_tier_b_diabetes_keyboard_4_options_no_skip():
    from maxbot.keyboards import (
        tier_b_diabetes_keyboard,
        PAYLOAD_TIER_B_DIABETES_NO,
        PAYLOAD_TIER_B_DIABETES_T1,
        PAYLOAD_TIER_B_DIABETES_T2,
        PAYLOAD_TIER_B_DIABETES_PRE,
        PAYLOAD_TIER_B_SKIP,
    )
    payloads = _flatten(tier_b_diabetes_keyboard())
    assert {
        PAYLOAD_TIER_B_DIABETES_NO,
        PAYLOAD_TIER_B_DIABETES_T1,
        PAYLOAD_TIER_B_DIABETES_T2,
        PAYLOAD_TIER_B_DIABETES_PRE,
    } <= payloads
    assert PAYLOAD_TIER_B_SKIP not in payloads


def test_tier_b_chronic_keyboard_renders_selected():
    """Multi-select toggle: rebuild с галочками для selected slugs."""
    from maxbot.keyboards import (
        tier_b_chronic_keyboard,
        PAYLOAD_TIER_B_CHRONIC_DONE,
        PAYLOAD_TIER_B_CHRONIC_NONE,
    )
    keyboard = tier_b_chronic_keyboard(selected=set())
    payloads = _flatten(keyboard)
    assert PAYLOAD_TIER_B_CHRONIC_DONE in payloads
    assert PAYLOAD_TIER_B_CHRONIC_NONE in payloads
    # Each chronic slug → its own payload `cb:tier_b:chronic:toggle:<slug>`
    assert any(p.startswith("cb:tier_b:chronic:toggle:") for p in payloads)


def test_tier_b_allergies_choice_keyboard_3_options():
    from maxbot.keyboards import (
        tier_b_allergies_choice_keyboard,
        PAYLOAD_TIER_B_ALLERGIES_NONE,
        PAYLOAD_TIER_B_ALLERGIES_TEXT,
        PAYLOAD_TIER_B_ALLERGIES_VAGUE,
    )
    payloads = _flatten(tier_b_allergies_choice_keyboard())
    assert {
        PAYLOAD_TIER_B_ALLERGIES_NONE,
        PAYLOAD_TIER_B_ALLERGIES_TEXT,
        PAYLOAD_TIER_B_ALLERGIES_VAGUE,
    } <= payloads


def test_tier_b_meds_keyboard_yes_no_skip():
    from maxbot.keyboards import (
        tier_b_meds_keyboard, PAYLOAD_TIER_B_YES, PAYLOAD_TIER_B_NO, PAYLOAD_TIER_B_SKIP,
    )
    payloads = _flatten(tier_b_meds_keyboard())
    assert {PAYLOAD_TIER_B_YES, PAYLOAD_TIER_B_NO, PAYLOAD_TIER_B_SKIP} <= payloads


def test_tier_b_menopause_keyboard_4_options():
    from maxbot.keyboards import (
        tier_b_menopause_keyboard,
        PAYLOAD_TIER_B_MENOPAUSE_NO,
        PAYLOAD_TIER_B_MENOPAUSE_YES,
        PAYLOAD_TIER_B_MENOPAUSE_UNSURE,
        PAYLOAD_TIER_B_SKIP,
    )
    payloads = _flatten(tier_b_menopause_keyboard())
    assert {
        PAYLOAD_TIER_B_MENOPAUSE_NO,
        PAYLOAD_TIER_B_MENOPAUSE_YES,
        PAYLOAD_TIER_B_MENOPAUSE_UNSURE,
        PAYLOAD_TIER_B_SKIP,
    } <= payloads
