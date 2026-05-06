"""Phase 3.1 Part 1 T03: keyboards для анкеты TIER-A.

Проверяем что у каждого экрана анкеты build'ится keyboard с правильными
payload-константами. Сами payload'ы — статические строки (не payload-builder),
чтобы handlers могли матчиться через `F.callback.payload == PAYLOAD_X`.
"""
from __future__ import annotations


def test_consent_keyboard_two_buttons():
    from maxbot.keyboards import (
        anketa_consent_keyboard,
        PAYLOAD_ANKETA_CONSENT_OK,
        PAYLOAD_ANKETA_CONSENT_DECLINE,
    )

    kb = anketa_consent_keyboard()
    payloads = _flatten_payloads(kb)
    assert PAYLOAD_ANKETA_CONSENT_OK in payloads
    assert PAYLOAD_ANKETA_CONSENT_DECLINE in payloads


def test_gender_keyboard_three_buttons():
    from maxbot.keyboards import (
        anketa_gender_keyboard,
        PAYLOAD_ANKETA_GENDER_FEMALE,
        PAYLOAD_ANKETA_GENDER_MALE,
        PAYLOAD_ANKETA_SKIP,
    )

    payloads = _flatten_payloads(anketa_gender_keyboard())
    assert {
        PAYLOAD_ANKETA_GENDER_FEMALE,
        PAYLOAD_ANKETA_GENDER_MALE,
        PAYLOAD_ANKETA_SKIP,
    } <= payloads


def test_skip_keyboard_one_button():
    """Универсальный keyboard для текстовых шагов (age/height/weight)."""
    from maxbot.keyboards import anketa_skip_keyboard, PAYLOAD_ANKETA_SKIP

    payloads = _flatten_payloads(anketa_skip_keyboard())
    assert payloads == {PAYLOAD_ANKETA_SKIP}


def test_goal_keyboard_three_buttons():
    from maxbot.keyboards import (
        anketa_goal_keyboard,
        PAYLOAD_ANKETA_GOAL_LOSE,
        PAYLOAD_ANKETA_GOAL_MAINTAIN,
        PAYLOAD_ANKETA_GOAL_GAIN,
    )

    payloads = _flatten_payloads(anketa_goal_keyboard())
    assert {
        PAYLOAD_ANKETA_GOAL_LOSE,
        PAYLOAD_ANKETA_GOAL_MAINTAIN,
        PAYLOAD_ANKETA_GOAL_GAIN,
    } <= payloads


def test_pace_keyboard_two_buttons():
    """Темп для goal=lose: gentle (-10%) и moderate (-15%). Fast (-20%)
    скрыт за /настройки (см. Design Doc §4.4)."""
    from maxbot.keyboards import (
        anketa_pace_keyboard,
        PAYLOAD_ANKETA_PACE_GENTLE,
        PAYLOAD_ANKETA_PACE_MODERATE,
    )

    payloads = _flatten_payloads(anketa_pace_keyboard())
    assert {
        PAYLOAD_ANKETA_PACE_GENTLE,
        PAYLOAD_ANKETA_PACE_MODERATE,
    } <= payloads


def test_gain_clarify_keyboard_two_buttons():
    from maxbot.keyboards import (
        anketa_gain_clarify_keyboard,
        PAYLOAD_ANKETA_GAIN_MASS,
        PAYLOAD_ANKETA_GAIN_TONE,
    )

    payloads = _flatten_payloads(anketa_gain_clarify_keyboard())
    assert {
        PAYLOAD_ANKETA_GAIN_MASS,
        PAYLOAD_ANKETA_GAIN_TONE,
    } <= payloads


def test_bmi_ladder_keyboard_three_buttons():
    """BMI<18.5 + goal=lose → 3 кнопки: к врачу / поменять цель /
    всё равно худеть (override). См. Design Doc §4.4."""
    from maxbot.keyboards import (
        anketa_bmi_ladder_keyboard,
        PAYLOAD_ANKETA_BMI_DOCTOR,
        PAYLOAD_ANKETA_BMI_SWITCH_MAINTAIN,
        PAYLOAD_ANKETA_BMI_OVERRIDE,
    )

    payloads = _flatten_payloads(anketa_bmi_ladder_keyboard())
    assert {
        PAYLOAD_ANKETA_BMI_DOCTOR,
        PAYLOAD_ANKETA_BMI_SWITCH_MAINTAIN,
        PAYLOAD_ANKETA_BMI_OVERRIDE,
    } <= payloads


def test_complete_keyboard_first_meal_button():
    """Финал TIER-A: одна кнопка [📸 Сфоткать первый приём]."""
    from maxbot.keyboards import (
        anketa_complete_keyboard,
        PAYLOAD_NUTRITION_FIRST_MEAL,
    )

    payloads = _flatten_payloads(anketa_complete_keyboard())
    assert PAYLOAD_NUTRITION_FIRST_MEAL in payloads


# ─── helper ────────────────────────────────────────────────────────────────


def _flatten_payloads(keyboard) -> set[str]:
    """Извлечь все payload-строки из inline-keyboard markup.

    maxapi.InlineKeyboardBuilder.as_markup() возвращает Attachment объект.
    Структура: attachment.payload.buttons — list[list[CallbackButton]],
    где каждый CallbackButton имеет атрибут .payload (str).

    Для обратной совместимости также пробуем прямые атрибуты .buttons и
    .rows на верхнем уровне (на случай будущих изменений maxapi).
    """
    out: set[str] = set()

    # Основной путь: Attachment → .payload.buttons (maxapi текущая версия)
    inner = getattr(keyboard, "payload", None)
    if inner is not None:
        rows = getattr(inner, "buttons", None) or []
        for row in rows:
            for btn in row:
                payload = getattr(btn, "payload", None)
                if payload:
                    out.add(payload)
        if out:
            return out

    # Запасной путь: прямые .buttons/.rows на верхнем уровне
    rows = getattr(keyboard, "buttons", None) or getattr(keyboard, "rows", None) or []
    for row in rows:
        for btn in row:
            payload = getattr(btn, "payload", None)
            if payload is None:
                callback = getattr(btn, "callback", None)
                payload = getattr(callback, "payload", None) if callback else None
            if payload:
                out.add(payload)
    return out


# ─── Feature flag NUTRITION_ENABLED — main_menu_keyboard ───────────────────


def test_main_menu_hides_nutrition_button_when_disabled(settings):
    """NUTRITION_ENABLED=False → кнопки «🍎 Дневник питания» нет в main_menu."""
    from maxbot.keyboards import main_menu_keyboard, PAYLOAD_MENU_NUTRITION

    settings.NUTRITION_ENABLED = False
    payloads = _flatten_payloads(main_menu_keyboard())
    assert PAYLOAD_MENU_NUTRITION not in payloads


def test_main_menu_shows_nutrition_button_when_enabled(settings):
    """NUTRITION_ENABLED=True → кнопка присутствует."""
    from maxbot.keyboards import main_menu_keyboard, PAYLOAD_MENU_NUTRITION

    settings.NUTRITION_ENABLED = True
    payloads = _flatten_payloads(main_menu_keyboard())
    assert PAYLOAD_MENU_NUTRITION in payloads
