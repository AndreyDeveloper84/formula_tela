# MAX-бот Phase 3.1 — Part 1: Foundation & TIER-A Анкета

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать TIER-A анкету (5 шагов: gender / age / height / weight / goal+pace) с consent-экраном и BMI<18.5 ladder, интегрированную с Ayla `POST /profile/`. После прохождения юзер видит свою норму ккал/БЖУ/воды и может отправить первое фото.

**Architecture:** FSM `NutritionAnketaStates` через `MemoryContext`. Ayla = source of truth для nutrition data (BMR/нормы/health_flags). Бот = thin UX client: каждый шаг анкеты POST'ит в Ayla `/internal/profile/`, тот считает нормы и возвращает; локальная Django-модель `NutritionProfile` **не создаётся** (отменяет Design Doc v1 §3.2 — после выбора Ayla-side ownership). На `BotUser.nutrition_settings` JSON держим только UI-state (`anketa_consent_acked_at`).

**Tech Stack:** Python 3.12 async, maxapi SDK, pytest+pytest-asyncio+model_bakery, httpx (in `nutrition_client`), `tests/fixtures/ayla_mock.py` для integration-тестов, `maxbot.ai_parsers` (parse_age/height/weight уже готовы).

**Reference docs:**
- Design: `docs/plans/maxbot-phase3-nutrition-design.md` v2 §4 (анкета), §4.4 (BMI ladder), §4.6 (TIER-A финал)
- Reconciliation: `docs/plans/maxbot-phase3-reconciliation.md` R3 (TIER-A vs TIER-B split)
- Ayla contract: `docs/plans/maxbot-phase3-ayla-spec.md` §1.1, §1.2 (GET/POST profile + overrides_applied)
- Mock-server: `mysite/tests/fixtures/ayla_mock.py`

**Key existing code (DO NOT recreate):**
- `maxbot/ai_parsers.py` — `parse_age`, `parse_height`, `parse_weight` (хибрид regex+LLM с REFUSED sentinel) уже готовы и протестированы.
- `maxbot/services/nutrition_client.py:464-560` — `get_profile()` + `upsert_profile()` + dataclass `ProfileResponse` уже реализованы, не трогать.
- `maxbot/services/ayla_user_proxy.py` — `external_user_id_for(bot_user) → "bot:{max_user_id}"`.
- `maxbot/handlers/nutrition_entry.py` — entry-screen с двумя кнопками (`PAYLOAD_NUTRITION_TRY_NOW` заглушка остаётся, `PAYLOAD_NUTRITION_START_ANKETA` заглушка заменяется в Task 14).
- `maxbot/keyboards.py:46-72` — `main_menu_keyboard()` уже включает «🍎 Дневник питания».
- Migration `0068_botuser_nutrition_fields.py` — `health_flags`, `nutrition_settings`, `nutrition_onboarded_at`, `timezone` уже применены.

---

## File Structure

**Create:**
- `mysite/maxbot/handlers/nutrition_anketa.py` — новый Router, ~12 handlers (consent, gender, age, height, weight, goal, pace, gain_clarify, BMI ladder, complete)
- `mysite/maxbot/nutrition_calc.py` — pure-math утилита: `calc_bmi(weight_kg, height_cm) -> float`. **Вся остальная math (BMR/нормы) живёт на Ayla side**, не дублируем.
- `mysite/tests/maxbot/test_nutrition_anketa.py` — unit + e2e тесты handlers (с MemoryContext и monkeypatch на nutrition_client)
- `mysite/tests/maxbot/test_nutrition_calc.py` — тесты BMI

**Modify:**
- `mysite/maxbot/states.py` — добавить класс `NutritionAnketaStates` (10 state'ов TIER-A)
- `mysite/maxbot/keyboards.py` — добавить `PAYLOAD_ANKETA_*` константы и keyboard-functions: `anketa_consent_keyboard()`, `anketa_gender_keyboard()`, `anketa_skip_keyboard()` (универсальный для текстовых шагов), `anketa_goal_keyboard()`, `anketa_pace_keyboard()`, `anketa_gain_clarify_keyboard()`, `anketa_bmi_ladder_keyboard()`, `anketa_complete_keyboard()`
- `mysite/maxbot/handlers/nutrition_entry.py` — заменить `on_start_anketa_stub` на старт FSM (set state → consent screen)
- `mysite/maxbot/handlers/__init__.py` — добавить `nutrition_anketa.router` в `get_routers()` **перед** ai_assistant (FSM ловит free-text для age/height/weight, не должен попасть в ai_assistant)

**Reference (read-only — не модифицировать):**
- `mysite/maxbot/handlers/booking.py` — паттерн FSM: `MemoryContext.set_state(...)`, `set_data(...)`, `get_data()`, `clear()`, `MessageCreated`/`MessageCallback` обработчики

---

## Architectural decisions baked into plan

1. **`NutritionProfile` модель не создаётся.** Локальная копия не нужна: Ayla = source of truth, бот POST'ит и читает. На `BotUser.nutrition_settings` JSON держим UI-state (`anketa_consent_acked_at`, в Part 2 — `daily_report_time`, `evening_inline_shown_at`). Это отменяет Design Doc v1 §3.2 после Ayla spec.
2. **BMI считаем локально** — для ladder-кнопок до отправки в Ayla. `nutrition_calc.calc_bmi(weight_kg, height_cm)`. Все остальные расчёты (BMR/норма ккал/БЖУ/water_ml) — на Ayla side через `upsert_profile` server-side обязанности (Ayla spec §1.2).
3. **Skip-кнопки** — отправляются в Ayla как `_skipped_fields: ["weight"]` массив. Ayla на server подставляет defaults (медиана Пензы 35-45 ж: female/40/165/70). Это уже описано в Ayla spec §1.2.
4. **`parse_*` функции возвращают "REFUSED"** при явном отказе («не скажу») — в плане трактуется как Skip (тот же путь UI: переход к следующему шагу + добавление в `_skipped_fields`).
5. **`upsert_profile` per step или один раз в финале?** — **per step**. Каждый шаг → POST с partial body + `complete: false`, последний шаг → POST с `complete: true`. Так Ayla накапливает state через `Idempotency-Key` (UUID5 from external_user_id+step), и при abort анкеты на середине state не теряется.
6. **`Idempotency-Key`**: `uuid.uuid5(NAMESPACE_DNS, f"{external_user_id}:anketa:{step_name}")`. Гарантия: повторный клик на «Женский» не создаст 2 записи.
7. **Action-row inline keyboard** прикрепляется через `attachments=[keyboard()]` к каждому ответу бота в анкете (как в `booking.py` уже сделано).
8. **TIER-B (health screening) — НЕ в этом плане.** Только TIER-A. После `complete_tier_a` юзер получает финальный экран с нормой и кнопкой «📸 Сфоткать первый приём» (фото-flow существующий уже работает через `food_scanner.py` без TIER-B).

---

## Task 1: `nutrition_calc.py` + BMI helper

**Files:**
- Create: `mysite/maxbot/nutrition_calc.py`
- Test: `mysite/tests/maxbot/test_nutrition_calc.py`

- [ ] **Step 1: Write the failing test**

```python
# mysite/tests/maxbot/test_nutrition_calc.py
"""Pure-math утилиты для anketa (Phase 3.1 Part 1 T01).

BMR / норма ккал считаются на Ayla side — здесь только локальные
вспомогательные функции (BMI для ladder-кнопок до отправки в Ayla).
"""
from __future__ import annotations

import pytest


def test_calc_bmi_normal_woman():
    """Стандартный случай — норма BMI = 22.0 для 60кг/165см."""
    from maxbot.nutrition_calc import calc_bmi

    bmi = calc_bmi(weight_kg=60, height_cm=165)
    assert 21.9 < bmi < 22.1


def test_calc_bmi_under_18_5_threshold():
    """BMI 18.4 (граница underweight) — для триггера ladder."""
    from maxbot.nutrition_calc import calc_bmi

    bmi = calc_bmi(weight_kg=50, height_cm=165)
    assert bmi < 18.5


def test_calc_bmi_zero_height_raises():
    """Гарда от деления на ноль — height=0 не должен крашить весь handler."""
    from maxbot.nutrition_calc import calc_bmi

    with pytest.raises(ValueError, match="height_cm must be positive"):
        calc_bmi(weight_kg=60, height_cm=0)


def test_calc_bmi_returns_float():
    """Тип результата — float (нам нужно сравнивать с 18.5)."""
    from maxbot.nutrition_calc import calc_bmi

    assert isinstance(calc_bmi(weight_kg=70, height_cm=170), float)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest mysite/tests/maxbot/test_nutrition_calc.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'maxbot.nutrition_calc'`

- [ ] **Step 3: Write minimal implementation**

```python
# mysite/maxbot/nutrition_calc.py
"""Pure-math утилиты для анкеты (Phase 3.1 Part 1).

Вся остальная nutrition-математика (BMR Mifflin-St Jeor / норма ккал /
БЖУ / water_ml) живёт на Ayla side — см. `docs/plans/maxbot-phase3-ayla-spec.md`
§1.2 server-side обязанности. Здесь только локальный BMI для ladder
(нужен ДО отправки в Ayla, чтобы показать предупреждение).
"""
from __future__ import annotations


def calc_bmi(*, weight_kg: float, height_cm: float) -> float:
    """Body Mass Index = weight (kg) / height (m)^2.

    Args:
        weight_kg: Вес в килограммах.
        height_cm: Рост в сантиметрах.

    Returns:
        BMI как float.

    Raises:
        ValueError: если height_cm <= 0 (защита от деления на ноль —
            возможно при invalid FSM state, когда юзер перешёл на goal
            без weight/height).
    """
    if height_cm <= 0:
        raise ValueError("height_cm must be positive")
    height_m = height_cm / 100.0
    return weight_kg / (height_m * height_m)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest mysite/tests/maxbot/test_nutrition_calc.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/nutrition_calc.py mysite/tests/maxbot/test_nutrition_calc.py
git commit -m "feat(maxbot): nutrition_calc.calc_bmi for TIER-A anketa BMI ladder

Pure-math BMI (weight_kg/height_m^2) с гардой от height=0. Остальная
nutrition-математика (BMR/нормы) живёт на Ayla side — см. ayla-spec §1.2."
```

---

## Task 2: `NutritionAnketaStates` FSM (TIER-A only)

**Files:**
- Modify: `mysite/maxbot/states.py`

- [ ] **Step 1: Add states to existing file**

Open `mysite/maxbot/states.py` and append after `class AskStates`:

```python
class NutritionAnketaStates(StatesGroup):
    """FSM TIER-A анкеты дневника питания (Phase 3.1 Part 1).

    Запускается из callback PAYLOAD_NUTRITION_START_ANKETA (entry handler).
    После complete_tier_a → BotUser.nutrition_onboarded_at установлен,
    Ayla профиль создан. TIER-B (health screening) — отдельный sub-flow,
    НЕ в этом FSM (запускается lazy перед первым advice-моментом из
    ai_assistant, см. Design Doc v2 §4.5).

    Все шаги шлют PATCH в Ayla `POST /profile/` с complete=false; последний
    (complete_tier_a) — с complete=true.
    """
    awaiting_consent = State()       # дисклеймер 152-ФЗ обработки ПД для анкеты
    awaiting_gender = State()
    awaiting_age = State()           # text-input или Skip-кнопка
    awaiting_height = State()        # text-input или Skip
    awaiting_weight = State()        # text-input или Skip
    awaiting_goal = State()          # 3 кнопки lose/maintain/gain
    awaiting_pace = State()          # для goal=lose: gentle/moderate
    awaiting_gain_clarify = State()  # для goal=gain: gain/tone
    awaiting_bmi_ladder = State()    # если BMI<18.5 + goal=lose
    complete = State()               # рендер финального экрана с нормой
```

- [ ] **Step 2: Verify compile**

Run: `python -c "from maxbot.states import NutritionAnketaStates; print(list(NutritionAnketaStates.__states__.keys()) if hasattr(NutritionAnketaStates, '__states__') else 'states added')"`

Expected: no error (либо печатает state names — формат зависит от maxapi version, главное чтобы импорт не упал).

- [ ] **Step 3: Commit**

```bash
git add mysite/maxbot/states.py
git commit -m "feat(maxbot): NutritionAnketaStates FSM (10 states TIER-A)

Шаги: consent → gender → age → height → weight → goal → pace/gain_clarify →
bmi_ladder (conditional) → complete. TIER-B health screening — отдельный
sub-flow lazy on-demand (см. Design Doc v2 §4.5)."
```

---

## Task 3: Keyboard payloads + helper functions

**Files:**
- Modify: `mysite/maxbot/keyboards.py`
- Test: `mysite/tests/maxbot/test_anketa_keyboards.py` (новый)

- [ ] **Step 1: Write the failing test**

```python
# mysite/tests/maxbot/test_anketa_keyboards.py
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

    maxapi.InlineKeyboardBuilder.as_markup() возвращает структуру с
    `.payload` (или `.callback.payload`) на каждой CallbackButton — точная
    форма зависит от версии. Делаем best-effort обход.
    """
    out: set[str] = set()
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest mysite/tests/maxbot/test_anketa_keyboards.py -v`
Expected: FAIL with `ImportError` на первом же импорте payload-константы.

- [ ] **Step 3: Add payloads + helpers to keyboards.py**

В `mysite/maxbot/keyboards.py` добавить **после** строки `PAYLOAD_NUTRITION_START_ANKETA`:

```python
# ─── Phase 3.1 Part 1: TIER-A anketa keyboards ─────────────────────────────

PAYLOAD_ANKETA_CONSENT_OK = "cb:anketa:consent:ok"
PAYLOAD_ANKETA_CONSENT_DECLINE = "cb:anketa:consent:decline"

PAYLOAD_ANKETA_GENDER_FEMALE = "cb:anketa:gender:female"
PAYLOAD_ANKETA_GENDER_MALE = "cb:anketa:gender:male"

PAYLOAD_ANKETA_SKIP = "cb:anketa:skip"

PAYLOAD_ANKETA_GOAL_LOSE = "cb:anketa:goal:lose"
PAYLOAD_ANKETA_GOAL_MAINTAIN = "cb:anketa:goal:maintain"
PAYLOAD_ANKETA_GOAL_GAIN = "cb:anketa:goal:gain"

PAYLOAD_ANKETA_PACE_GENTLE = "cb:anketa:pace:gentle"
PAYLOAD_ANKETA_PACE_MODERATE = "cb:anketa:pace:moderate"

PAYLOAD_ANKETA_GAIN_MASS = "cb:anketa:gain:mass"
PAYLOAD_ANKETA_GAIN_TONE = "cb:anketa:gain:tone"

PAYLOAD_ANKETA_BMI_DOCTOR = "cb:anketa:bmi:doctor"
PAYLOAD_ANKETA_BMI_SWITCH_MAINTAIN = "cb:anketa:bmi:switch_maintain"
PAYLOAD_ANKETA_BMI_OVERRIDE = "cb:anketa:bmi:override"

PAYLOAD_NUTRITION_FIRST_MEAL = "cb:nutrition:first_meal"
```

И **в конец файла** (после `nutrition_welcome_keyboard()`) добавить функции:

```python
def anketa_consent_keyboard():
    """TIER-A T04: дисклеймер 152-ФЗ для базовой обработки ПД анкеты."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="✓ Понятно, продолжаем",
                       payload=PAYLOAD_ANKETA_CONSENT_OK),
    )
    builder.row(
        CallbackButton(text="Не сейчас",
                       payload=PAYLOAD_ANKETA_CONSENT_DECLINE),
    )
    return builder.as_markup()


def anketa_gender_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="Женский", payload=PAYLOAD_ANKETA_GENDER_FEMALE),
        CallbackButton(text="Мужской", payload=PAYLOAD_ANKETA_GENDER_MALE),
    )
    builder.row(
        CallbackButton(text="⏭ Пропустить", payload=PAYLOAD_ANKETA_SKIP),
    )
    return builder.as_markup()


def anketa_skip_keyboard():
    """Универсальный 1-кнопочный keyboard для text-input шагов
    (age/height/weight). Юзер пишет число или жмёт пропустить."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="⏭ Пропустить", payload=PAYLOAD_ANKETA_SKIP),
    )
    return builder.as_markup()


def anketa_goal_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="⬇ Похудеть",
                       payload=PAYLOAD_ANKETA_GOAL_LOSE),
    )
    builder.row(
        CallbackButton(text="➡ Держать вес",
                       payload=PAYLOAD_ANKETA_GOAL_MAINTAIN),
    )
    builder.row(
        CallbackButton(text="⬆ Набрать / подтянуть фигуру",
                       payload=PAYLOAD_ANKETA_GOAL_GAIN),
    )
    return builder.as_markup()


def anketa_pace_keyboard():
    """Темп для goal=lose. Fast (-20%) скрыт за /настройки (Design §4.4)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="🐢 Спокойный (-10%)",
                       payload=PAYLOAD_ANKETA_PACE_GENTLE),
        CallbackButton(text="⚖️ Средний (-15%)",
                       payload=PAYLOAD_ANKETA_PACE_MODERATE),
    )
    return builder.as_markup()


def anketa_gain_clarify_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="💪 Набрать вес",
                       payload=PAYLOAD_ANKETA_GAIN_MASS),
    )
    builder.row(
        CallbackButton(text="🌸 Подтянуть фигуру",
                       payload=PAYLOAD_ANKETA_GAIN_TONE),
    )
    return builder.as_markup()


def anketa_bmi_ladder_keyboard():
    """BMI<18.5 + goal=lose. «К врачу» НЕ ведёт в салон (Design §4.4)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="Хочу к врачу",
                       payload=PAYLOAD_ANKETA_BMI_DOCTOR),
    )
    builder.row(
        CallbackButton(text="Поменять на «держать»",
                       payload=PAYLOAD_ANKETA_BMI_SWITCH_MAINTAIN),
    )
    builder.row(
        CallbackButton(text="Всё равно худеть",
                       payload=PAYLOAD_ANKETA_BMI_OVERRIDE),
    )
    return builder.as_markup()


def anketa_complete_keyboard():
    """Финал TIER-A: одна next-step кнопка."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="📸 Сфоткать первый приём",
                       payload=PAYLOAD_NUTRITION_FIRST_MEAL),
    )
    return builder.as_markup()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest mysite/tests/maxbot/test_anketa_keyboards.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/keyboards.py mysite/tests/maxbot/test_anketa_keyboards.py
git commit -m "feat(maxbot): keyboards для TIER-A анкеты (8 экранов)

Payloads cb:anketa:* + 8 keyboard-функций. BMI ladder с 3 кнопками,
goal/pace/gain_clarify multi-row, универсальный skip для text-input."
```

---

## Task 4: Anketa router skeleton + entry from `nutrition_entry`

**Files:**
- Create: `mysite/maxbot/handlers/nutrition_anketa.py`
- Modify: `mysite/maxbot/handlers/nutrition_entry.py:on_start_anketa_stub`
- Modify: `mysite/maxbot/handlers/__init__.py`
- Test: `mysite/tests/maxbot/test_nutrition_anketa.py` (новый)

- [ ] **Step 1: Write the failing test**

```python
# mysite/tests/maxbot/test_nutrition_anketa.py
"""Phase 3.1 Part 1: TIER-A анкета — handlers тесты.

Используем fake-объекты вместо реального MAX SDK runtime: каждому handler'у
передаём (callback|event, MemoryContext). Контролируем `bot.send_message`
через AsyncMock и проверяем (chat_id, text, attachments).

Ayla calls (`upsert_profile`, `get_profile`) мокаем через
monkeypatch.setattr на singleton `get_nutrition_client()`.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from asgiref.sync import sync_to_async


# ─── helpers ───────────────────────────────────────────────────────────────


def _fake_callback(payload: str, chat_id: int = 12345) -> MagicMock:
    """Build minimal MessageCallback double для router-handler'а."""
    cb = MagicMock()
    cb.callback.payload = payload
    cb.message.recipient.chat_id = chat_id
    cb.bot.send_message = AsyncMock()
    return cb


def _fake_message(text: str, chat_id: int = 12345, sender_id: int = 99) -> MagicMock:
    """Build minimal MessageCreated double."""
    msg = MagicMock()
    msg.message.body.text = text
    msg.message.recipient.chat_id = chat_id
    msg.message.sender.user_id = sender_id
    msg.bot.send_message = AsyncMock()
    return msg


# ─── consent step ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_anketa_sets_consent_state_and_renders_disclaimer():
    """Юзер кликнул [📝 Настроить под себя] → state=awaiting_consent,
    бот шлёт текст дисклеймера + 2 кнопки."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_entry import on_start_anketa
    from maxbot.states import NutritionAnketaStates

    cb = _fake_callback("cb:nutrition:start_anketa")
    ctx = MemoryContext()

    await on_start_anketa(cb, ctx)

    state = await ctx.get_state()
    assert state == NutritionAnketaStates.awaiting_consent

    cb.bot.send_message.assert_awaited_once()
    call_kwargs = cb.bot.send_message.await_args.kwargs
    assert "согласен" in call_kwargs["text"].lower() or \
           "обработ" in call_kwargs["text"].lower()
    # Attachments — keyboard с 2 кнопками
    assert call_kwargs.get("attachments") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py::test_start_anketa_sets_consent_state_and_renders_disclaimer -v`

Expected: FAIL — `ImportError: cannot import name 'on_start_anketa' from 'maxbot.handlers.nutrition_entry'` (пока есть только `on_start_anketa_stub`).

- [ ] **Step 3: Create router skeleton + replace stub**

Create `mysite/maxbot/handlers/nutrition_anketa.py`:

```python
"""TIER-A анкета — FSM handlers (Phase 3.1 Part 1).

Точка входа: `on_start_anketa` в nutrition_entry.py (после клика
PAYLOAD_NUTRITION_START_ANKETA). Дальше — chain handlers по state'ам:

    awaiting_consent → awaiting_gender → awaiting_age → awaiting_height →
    awaiting_weight → awaiting_goal → (awaiting_pace | awaiting_gain_clarify) →
    [awaiting_bmi_ladder] → complete

Каждый шаг шлёт PATCH в Ayla `POST /profile/` с complete=false; последний —
с complete=true. Idempotency-Key = uuid5(external_user_id, step_name).

См. `docs/plans/maxbot-phase3-nutrition-design.md` v2 §4 + Ayla spec §1.
"""
from __future__ import annotations

import logging

from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback, MessageCreated

from maxbot import keyboards
from maxbot.states import NutritionAnketaStates


logger = logging.getLogger("maxbot.handlers.nutrition_anketa")
router = Router()


CONSENT_TEXT = (
    "📝 Перед тем как начнём — короткий дисклеймер.\n\n"
    "Я попрошу 5 параметров (пол, возраст, рост, вес, цель), чтобы "
    "посчитать твою норму ккал и БЖУ. Эти данные хранятся в зашифрованном "
    "виде, используются только внутри сервиса (152-ФЗ).\n\n"
    "Любой шаг можно пропустить — тогда применю средние значения."
)


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_CONSENT_OK)
async def on_consent_ok(callback: MessageCallback, context: MemoryContext) -> None:
    """Согласие → переход на awaiting_gender."""
    # Заполнено в Task 5.
    raise NotImplementedError("filled in Task 5")


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_ANKETA_CONSENT_DECLINE,
)
async def on_consent_decline(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """Отказ → state cleared, exit на главное меню."""
    # Заполнено в Task 5.
    raise NotImplementedError("filled in Task 5")
```

Затем в `mysite/maxbot/handlers/nutrition_entry.py` **заменить** `on_start_anketa_stub`:

```python
# (удалить старую функцию on_start_anketa_stub целиком)

@router.message_callback(F.callback.payload == keyboards.PAYLOAD_NUTRITION_START_ANKETA)
async def on_start_anketa(callback: MessageCallback, context: MemoryContext) -> None:
    """Запуск TIER-A анкеты — set state и шлём consent-экран."""
    from maxbot.states import NutritionAnketaStates
    from maxbot.handlers.nutrition_anketa import CONSENT_TEXT

    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    await context.set_state(NutritionAnketaStates.awaiting_consent)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=CONSENT_TEXT,
        attachments=[keyboards.anketa_consent_keyboard()],
    )
```

И **удалить** `STUB_ANKETA_TEXT` константу — больше не используется.

Затем в `mysite/maxbot/handlers/__init__.py` добавить `nutrition_anketa.router` в `get_routers()` **перед** `ai_assistant.router` (FSM ловит free-text для age/height/weight, не должен попасть в ai_assistant):

Открыть файл, найти список router'ов (должен быть похож на `routers = [start.router, services.router, ...]`), и добавить `nutrition_anketa.router` строго **до** `ai_assistant.router`. Если ai_assistant идёт последним — вставить непосредственно перед ним.

- [ ] **Step 4: Run test — должен проходить**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py::test_start_anketa_sets_consent_state_and_renders_disclaimer -v`
Expected: PASS

- [ ] **Step 5: Smoke test полный набор тестов на регрессии**

Run: `pytest mysite/tests/maxbot/ -v --tb=short -x`
Expected: все maxbot-тесты должны проходить (если падают — это либо new test cases в test_nutrition_anketa.py которые мы пишем дальше, либо регрессия от удаления stub текста — нужно поправить).

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/nutrition_anketa.py \
        mysite/maxbot/handlers/nutrition_entry.py \
        mysite/maxbot/handlers/__init__.py \
        mysite/tests/maxbot/test_nutrition_anketa.py
git commit -m "feat(maxbot): TIER-A анкета entry + router skeleton

on_start_anketa_stub заменён на реальный handler: set state =
awaiting_consent, шлёт дисклеймер 152-ФЗ. Router зарегистрирован
перед ai_assistant (FSM ловит свободный текст). Consent handlers —
заглушки NotImplementedError, заполняются в T05."
```

---

## Task 5: Consent handlers (OK / Decline) + переход к gender

**Files:**
- Modify: `mysite/maxbot/handlers/nutrition_anketa.py`
- Modify: `mysite/tests/maxbot/test_nutrition_anketa.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_nutrition_anketa.py`:

```python
# ─── consent OK / decline ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consent_ok_advances_to_gender_step():
    """Клик «✓ Понятно» → state=awaiting_gender, бот шлёт вопрос про пол."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_consent_ok
    from maxbot.states import NutritionAnketaStates

    cb = _fake_callback("cb:anketa:consent:ok")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_consent)

    await on_consent_ok(cb, ctx)

    assert await ctx.get_state() == NutritionAnketaStates.awaiting_gender
    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "пол" in text.lower()


@pytest.mark.asyncio
async def test_consent_decline_clears_state_and_exits():
    """Клик «Не сейчас» → state очищен, бот шлёт 'возвращайся когда будешь готова'."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_consent_decline
    from maxbot.states import NutritionAnketaStates

    cb = _fake_callback("cb:anketa:consent:decline")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_consent)

    await on_consent_decline(cb, ctx)

    assert await ctx.get_state() is None
    cb.bot.send_message.assert_awaited_once()
```

- [ ] **Step 2: Run tests — должны падать**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py::test_consent_ok_advances_to_gender_step \
              mysite/tests/maxbot/test_nutrition_anketa.py::test_consent_decline_clears_state_and_exits -v`

Expected: FAIL with `NotImplementedError("filled in Task 5")` для обоих.

- [ ] **Step 3: Implement handlers**

В `mysite/maxbot/handlers/nutrition_anketa.py` заменить `raise NotImplementedError` в обоих handler'ах:

```python
GENDER_TEXT = (
    "● ○ ○ ○ ○\n\n"
    "Какой у тебя пол?\n\n"
    "Это нужно для расчёта BMR (базового обмена) — у Ж и М разные "
    "коэффициенты. Можно пропустить — тогда возьму средние значения."
)


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_CONSENT_OK)
async def on_consent_ok(callback: MessageCallback, context: MemoryContext) -> None:
    """Согласие → переход на awaiting_gender."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    await context.set_state(NutritionAnketaStates.awaiting_gender)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=GENDER_TEXT,
        attachments=[keyboards.anketa_gender_keyboard()],
    )


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_ANKETA_CONSENT_DECLINE,
)
async def on_consent_decline(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """Отказ от анкеты → state очищен. Юзер может вернуться позже из меню."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "Поняла, без проблем. Когда соберёшься настроить — заходи в "
            "🍎 Дневник питания через главное меню.\n\n"
            "Сейчас можешь просто прислать фото блюда — посчитаю калории "
            "по средним значениям."
        ),
    )
```

- [ ] **Step 4: Run tests — должны проходить**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v`
Expected: 3 passed (start_anketa + consent_ok + consent_decline).

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/handlers/nutrition_anketa.py mysite/tests/maxbot/test_nutrition_anketa.py
git commit -m "feat(maxbot): TIER-A consent OK/Decline handlers

OK → state=awaiting_gender, рендер вопроса про пол с прогресс-баром
● ○ ○ ○ ○. Decline → state cleared, soft exit с инструкцией как
вернуться. Юзер не попадает в анкету без явного ack 152-ФЗ."
```

---

## Task 6: Gender step handlers (Female / Male / Skip) + Ayla upsert

**Files:**
- Modify: `mysite/maxbot/handlers/nutrition_anketa.py`
- Modify: `mysite/tests/maxbot/test_nutrition_anketa.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_nutrition_anketa.py`:

```python
# ─── gender step ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gender_female_calls_ayla_upsert_with_gender_field(monkeypatch):
    """Клик «Женский» → upsert_profile вызван с gender=female + complete=False,
    state advances to awaiting_age."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_gender_female
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._client",
        lambda: fake_client,
    )

    # bot_user resolution mock
    bot_user_mock = MagicMock(max_user_id=99)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=bot_user_mock),
    )

    cb = _fake_callback("cb:anketa:gender:female")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_gender)

    await on_gender_female(cb, ctx)

    upsert_mock.assert_awaited_once()
    kwargs = upsert_mock.await_args.kwargs
    assert kwargs["external_user_id"] == "bot:99"
    assert kwargs["data"]["gender"] == "female"
    assert kwargs["data"]["complete"] is False

    assert await ctx.get_state() == NutritionAnketaStates.awaiting_age


@pytest.mark.asyncio
async def test_gender_skip_sends_skipped_field_and_advances(monkeypatch):
    """Клик [⏭ Пропустить] на шаге gender → upsert с _skipped_fields=['gender']."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_skip
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._client",
        lambda: fake_client,
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    cb = _fake_callback("cb:anketa:skip")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_gender)

    await on_skip(cb, ctx)

    kwargs = upsert_mock.await_args.kwargs
    assert kwargs["data"]["_skipped_fields"] == ["gender"]
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_age
```

- [ ] **Step 2: Run tests — должны падать**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v -k "gender or skip"`
Expected: FAIL — `ImportError: cannot import name 'on_gender_female'`.

- [ ] **Step 3: Implement gender + skip handlers**

В `mysite/maxbot/handlers/nutrition_anketa.py` добавить **в конец файла**:

```python
import uuid

from asgiref.sync import sync_to_async

from maxbot.services.ayla_user_proxy import external_user_id_for
from maxbot.services.nutrition_client import (
    NutritionAPIError,
    NutritionUnavailableError,
    get_nutrition_client,
)


# ─── helpers ───────────────────────────────────────────────────────────────


def _client():
    """Indirection чтобы тесты могли monkeypatch'ить."""
    return get_nutrition_client()


async def _resolve_bot_user(callback_or_event):
    """Получить BotUser по sender max_user_id с lazy-create."""
    from maxbot.personalization import get_or_create_bot_user
    if hasattr(callback_or_event, "callback"):
        sender_id = callback_or_event.callback.user.user_id  # MessageCallback
    else:
        sender_id = callback_or_event.message.sender.user_id  # MessageCreated
    return await sync_to_async(get_or_create_bot_user)(sender_id)


def _idempotency_key(external_user_id: str, step: str) -> str:
    """UUID5 — стабилен между ретраями того же шага."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{external_user_id}:anketa:{step}"))


async def _upsert(
    callback_or_event,
    *,
    step: str,
    body: dict,
    advance_to: NutritionAnketaStates,
    context: MemoryContext,
    next_text: str,
    next_keyboard,
    chat_id: int,
) -> None:
    """Общий шаг анкеты: POST в Ayla → если успех, advance state + render
    next screen. На транзиентной ошибке — show retry hint, state не меняем."""
    bot_user = await _resolve_bot_user(callback_or_event)
    extid = external_user_id_for(bot_user)

    try:
        await _client().upsert_profile(
            external_user_id=extid,
            data={**body, "complete": False},
        )
    except NutritionUnavailableError:
        await callback_or_event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Хм, не могу сохранить шаг — попробуй ещё раз через минуту "
                "или нажми «Назад» в меню. Извини 🙏"
            ),
        )
        return
    except NutritionAPIError as exc:
        logger.warning("anketa.upsert_failed step=%s err=%s", step, exc)
        await callback_or_event.bot.send_message(
            chat_id=chat_id,
            text="Не получилось — давай попробуем заново через меню.",
        )
        await context.clear()
        return

    await context.set_state(advance_to)
    await callback_or_event.bot.send_message(
        chat_id=chat_id,
        text=next_text,
        attachments=[next_keyboard()] if next_keyboard else None,
    )


# ─── gender ────────────────────────────────────────────────────────────────


AGE_TEXT = (
    "● ● ○ ○ ○\n\n"
    "Сколько тебе лет? Напиши число (например, 35) или пропусти."
)


async def _ask_age(callback_or_event, ctx: MemoryContext, chat_id: int) -> None:
    await ctx.set_state(NutritionAnketaStates.awaiting_age)
    await callback_or_event.bot.send_message(
        chat_id=chat_id,
        text=AGE_TEXT,
        attachments=[keyboards.anketa_skip_keyboard()],
    )


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_GENDER_FEMALE)
async def on_gender_female(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await _upsert(
        callback,
        step="gender",
        body={"gender": "female"},
        advance_to=NutritionAnketaStates.awaiting_age,
        context=context,
        next_text=AGE_TEXT,
        next_keyboard=keyboards.anketa_skip_keyboard,
        chat_id=chat_id,
    )


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_GENDER_MALE)
async def on_gender_male(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await _upsert(
        callback,
        step="gender",
        body={"gender": "male"},
        advance_to=NutritionAnketaStates.awaiting_age,
        context=context,
        next_text=AGE_TEXT,
        next_keyboard=keyboards.anketa_skip_keyboard,
        chat_id=chat_id,
    )


# ─── universal Skip handler — диспетчер по текущему state ──────────────────


_SKIP_FIELD_BY_STATE = {
    NutritionAnketaStates.awaiting_gender: ("gender", NutritionAnketaStates.awaiting_age, AGE_TEXT, keyboards.anketa_skip_keyboard),
    # остальные пары добавляются в Tasks 7-9
}


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_SKIP)
async def on_skip(callback: MessageCallback, context: MemoryContext) -> None:
    """Универсальный Skip: маппит current state → field name + next state."""
    state = await context.get_state()
    if state not in _SKIP_FIELD_BY_STATE:
        return  # silent ignore — не должно случиться, но safe
    field, advance_to, next_text, next_kb = _SKIP_FIELD_BY_STATE[state]

    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    await _upsert(
        callback,
        step=field,
        body={"_skipped_fields": [field]},
        advance_to=advance_to,
        context=context,
        next_text=next_text,
        next_keyboard=next_kb,
        chat_id=chat_id,
    )
```

- [ ] **Step 4: Run tests — должны проходить**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v`
Expected: 5 passed (3 предыдущих + 2 новых).

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/handlers/nutrition_anketa.py mysite/tests/maxbot/test_nutrition_anketa.py
git commit -m "feat(maxbot): gender step handlers + universal Skip dispatcher

Female/Male → upsert_profile с complete=False, advance to awaiting_age.
Skip dispatcher — _SKIP_FIELD_BY_STATE маппит current state → field name
(добавятся пары для age/height/weight/etc. в T07-09). Idempotency через
UUID5(extid:anketa:step). Транзиентные ошибки Ayla → soft retry hint."
```

---

## Task 7: Age step (text-input через `parse_age`) + Skip extension

**Files:**
- Modify: `mysite/maxbot/handlers/nutrition_anketa.py`
- Modify: `mysite/tests/maxbot/test_nutrition_anketa.py`

- [ ] **Step 1: Write the failing tests**

```python
# ─── age step (text-input) ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_age_text_input_parses_and_advances(monkeypatch):
    """Юзер пишет «35» в state=awaiting_age → parse_age=35, upsert(age=35),
    state=awaiting_height."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_age_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    msg = _fake_message("35")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_age)

    await on_age_text(msg, ctx)

    assert upsert_mock.await_args.kwargs["data"]["age"] == 35
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_height


@pytest.mark.asyncio
async def test_age_text_input_refused_treats_as_skip(monkeypatch):
    """parse_age возвращает 'REFUSED' для «не скажу» → upsert как skip."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_age_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    msg = _fake_message("не скажу")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_age)

    await on_age_text(msg, ctx)

    assert upsert_mock.await_args.kwargs["data"]["_skipped_fields"] == ["age"]
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_height


@pytest.mark.asyncio
async def test_age_text_input_unparseable_asks_again(monkeypatch):
    """parse_age возвращает None для «абвгд» → НЕ переходим, просим повторить."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_age_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock()
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)

    msg = _fake_message("абвгд")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_age)

    await on_age_text(msg, ctx)

    upsert_mock.assert_not_awaited()  # NO upsert
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_age  # state same
    msg.bot.send_message.assert_awaited_once()
    text = msg.bot.send_message.await_args.kwargs["text"]
    assert "не понял" in text.lower() or "число" in text.lower()


@pytest.mark.asyncio
async def test_skip_button_works_at_age_state(monkeypatch):
    """Skip-кнопка на awaiting_age → upsert _skipped_fields=['age'],
    advance to awaiting_height."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_skip
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    cb = _fake_callback("cb:anketa:skip")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_age)

    await on_skip(cb, ctx)

    assert upsert_mock.await_args.kwargs["data"]["_skipped_fields"] == ["age"]
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_height
```

- [ ] **Step 2: Run tests — должны падать**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v -k "age or skip_button_works_at_age"`
Expected: FAIL — `ImportError: cannot import name 'on_age_text'`.

- [ ] **Step 3: Implement age handler + extend Skip dispatcher**

В `mysite/maxbot/handlers/nutrition_anketa.py` добавить **после gender handlers**:

```python
# ─── age (text-input) ──────────────────────────────────────────────────────


HEIGHT_TEXT = (
    "● ● ● ○ ○\n\n"
    "Какой у тебя рост в сантиметрах? Напиши число (например, 165) "
    "или пропусти."
)


async def _treat_text_step_as_skip(
    msg, ctx, chat_id, *, field, advance_to, next_text, next_kb,
) -> None:
    """Helper: free-text парсер вернул REFUSED → шлём как skip."""
    await _upsert(
        msg,
        step=field,
        body={"_skipped_fields": [field]},
        advance_to=advance_to,
        context=ctx,
        next_text=next_text,
        next_keyboard=next_kb,
        chat_id=chat_id,
    )


@router.message_created(NutritionAnketaStates.awaiting_age)
async def on_age_text(event: MessageCreated, context: MemoryContext) -> None:
    """Юзер пишет возраст — пытаемся parse_age."""
    from maxbot.ai_parsers import parse_age, REFUSED

    text = (event.message.body.text or "").strip()
    chat_id = event.message.recipient.chat_id

    parsed = await parse_age(text)

    if parsed == REFUSED:
        await _treat_text_step_as_skip(
            event, context, chat_id,
            field="age",
            advance_to=NutritionAnketaStates.awaiting_height,
            next_text=HEIGHT_TEXT,
            next_kb=keyboards.anketa_skip_keyboard,
        )
        return

    if parsed is None:
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Не понял возраст — напиши число от 16 до 99 (например, 35) "
                "или нажми «⏭ Пропустить»."
            ),
            attachments=[keyboards.anketa_skip_keyboard()],
        )
        return

    await _upsert(
        event,
        step="age",
        body={"age": parsed},
        advance_to=NutritionAnketaStates.awaiting_height,
        context=context,
        next_text=HEIGHT_TEXT,
        next_keyboard=keyboards.anketa_skip_keyboard,
        chat_id=chat_id,
    )
```

И **обновить** `_SKIP_FIELD_BY_STATE`:

```python
_SKIP_FIELD_BY_STATE = {
    NutritionAnketaStates.awaiting_gender: ("gender", NutritionAnketaStates.awaiting_age, AGE_TEXT, keyboards.anketa_skip_keyboard),
    NutritionAnketaStates.awaiting_age: ("age", NutritionAnketaStates.awaiting_height, HEIGHT_TEXT, keyboards.anketa_skip_keyboard),
}
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/handlers/nutrition_anketa.py mysite/tests/maxbot/test_nutrition_anketa.py
git commit -m "feat(maxbot): age step + extend Skip dispatcher

on_age_text → parse_age с 3 ветками: int/REFUSED/None. None просит
повторить, REFUSED → skip path. _SKIP_FIELD_BY_STATE расширен awaiting_age."
```

---

## Task 8: Height + Weight steps (text-input через `parse_height` / `parse_weight`)

**Files:**
- Modify: `mysite/maxbot/handlers/nutrition_anketa.py`
- Modify: `mysite/tests/maxbot/test_nutrition_anketa.py`

- [ ] **Step 1: Write the failing tests**

```python
# ─── height + weight (same shape as age) ───────────────────────────────────


@pytest.mark.asyncio
async def test_height_text_input_parses_and_advances(monkeypatch):
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_height_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    msg = _fake_message("165")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_height)

    await on_height_text(msg, ctx)

    assert upsert_mock.await_args.kwargs["data"]["height_cm"] == 165
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_weight


@pytest.mark.asyncio
async def test_weight_text_input_with_range_stores_range_field(monkeypatch):
    """parse_weight возвращает {'value': None, 'range': '65-75', 'exact': False}
    для диапазона → upsert с weight_range, без weight_kg."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_weight_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    msg = _fake_message("65-75")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_weight)

    await on_weight_text(msg, ctx)

    body = upsert_mock.await_args.kwargs["data"]
    assert body.get("weight_range") == "65-75"
    assert "weight_kg" not in body or body["weight_kg"] is None
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_goal


@pytest.mark.asyncio
async def test_weight_text_input_exact_value_advances_to_goal(monkeypatch):
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_weight_text
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    msg = _fake_message("70")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_weight)

    await on_weight_text(msg, ctx)

    assert upsert_mock.await_args.kwargs["data"]["weight_kg"] == 70
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_goal
```

- [ ] **Step 2: Run tests — должны падать**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v -k "height or weight"`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement handlers**

В `mysite/maxbot/handlers/nutrition_anketa.py` добавить **после age handler**:

```python
# ─── height ────────────────────────────────────────────────────────────────


WEIGHT_TEXT = (
    "● ● ● ● ○\n\n"
    "Сколько весишь в кг? Можно точно (70) или диапазоном (65-75). "
    "Или пропусти."
)


@router.message_created(NutritionAnketaStates.awaiting_height)
async def on_height_text(event: MessageCreated, context: MemoryContext) -> None:
    from maxbot.ai_parsers import parse_height, REFUSED

    text = (event.message.body.text or "").strip()
    chat_id = event.message.recipient.chat_id

    parsed = await parse_height(text)

    if parsed == REFUSED:
        await _treat_text_step_as_skip(
            event, context, chat_id,
            field="height",
            advance_to=NutritionAnketaStates.awaiting_weight,
            next_text=WEIGHT_TEXT,
            next_kb=keyboards.anketa_skip_keyboard,
        )
        return

    if parsed is None:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Не понял рост — напиши число в см (например, 165) или пропусти.",
            attachments=[keyboards.anketa_skip_keyboard()],
        )
        return

    await _upsert(
        event,
        step="height",
        body={"height_cm": parsed},
        advance_to=NutritionAnketaStates.awaiting_weight,
        context=context,
        next_text=WEIGHT_TEXT,
        next_keyboard=keyboards.anketa_skip_keyboard,
        chat_id=chat_id,
    )


# ─── weight ────────────────────────────────────────────────────────────────


GOAL_TEXT = (
    "● ● ● ● ●\n\n"
    "Какая цель?"
)


@router.message_created(NutritionAnketaStates.awaiting_weight)
async def on_weight_text(event: MessageCreated, context: MemoryContext) -> None:
    """parse_weight возвращает dict {value: int|None, range: str|None, exact: bool}
    или 'REFUSED' или None."""
    from maxbot.ai_parsers import parse_weight, REFUSED

    text = (event.message.body.text or "").strip()
    chat_id = event.message.recipient.chat_id

    parsed = await parse_weight(text)

    if parsed == REFUSED:
        await _treat_text_step_as_skip(
            event, context, chat_id,
            field="weight",
            advance_to=NutritionAnketaStates.awaiting_goal,
            next_text=GOAL_TEXT,
            next_kb=keyboards.anketa_goal_keyboard,
        )
        return

    if parsed is None:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Не понял вес — напиши число (70) или диапазон (65-75) или пропусти.",
            attachments=[keyboards.anketa_skip_keyboard()],
        )
        return

    body: dict = {}
    if parsed.get("exact"):
        body["weight_kg"] = parsed["value"]
    else:
        body["weight_range"] = parsed["range"]

    await _upsert(
        event,
        step="weight",
        body=body,
        advance_to=NutritionAnketaStates.awaiting_goal,
        context=context,
        next_text=GOAL_TEXT,
        next_keyboard=keyboards.anketa_goal_keyboard,
        chat_id=chat_id,
    )
```

И **обновить** `_SKIP_FIELD_BY_STATE`:

```python
_SKIP_FIELD_BY_STATE = {
    NutritionAnketaStates.awaiting_gender: ("gender", NutritionAnketaStates.awaiting_age, AGE_TEXT, keyboards.anketa_skip_keyboard),
    NutritionAnketaStates.awaiting_age: ("age", NutritionAnketaStates.awaiting_height, HEIGHT_TEXT, keyboards.anketa_skip_keyboard),
    NutritionAnketaStates.awaiting_height: ("height", NutritionAnketaStates.awaiting_weight, WEIGHT_TEXT, keyboards.anketa_skip_keyboard),
    NutritionAnketaStates.awaiting_weight: ("weight", NutritionAnketaStates.awaiting_goal, GOAL_TEXT, keyboards.anketa_goal_keyboard),
}
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/handlers/nutrition_anketa.py mysite/tests/maxbot/test_nutrition_anketa.py
git commit -m "feat(maxbot): height + weight steps with parse_height/parse_weight

Same shape как age. parse_weight даёт {value/range/exact} — exact=True
шлём weight_kg, иначе weight_range='65-75' (Ayla side применяет defaults
по диапазону). _SKIP_FIELD_BY_STATE расширен 4 шагами."
```

---

## Task 9: Goal step (3 кнопки) — branching на pace / gain_clarify / BMI ladder

**Files:**
- Modify: `mysite/maxbot/handlers/nutrition_anketa.py`
- Modify: `mysite/tests/maxbot/test_nutrition_anketa.py`

- [ ] **Step 1: Write the failing tests**

```python
# ─── goal step ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_goal_maintain_skips_pace_goes_to_complete(monkeypatch):
    """goal=maintain → нет pace, нет gain_clarify, нет BMI ladder → complete."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_goal_maintain
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(
        raw={"daily_kcal": 1450, "protein_g": 110, "fat_g": 50,
             "carbs_g": 145, "water_ml": 1900},
    ))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    cb = _fake_callback("cb:anketa:goal:maintain")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_goal)
    await ctx.set_data({"weight_kg": 65, "height_cm": 170})

    await on_goal_maintain(cb, ctx)

    assert upsert_mock.await_args.kwargs["data"]["goal"] == "maintain"
    assert upsert_mock.await_args.kwargs["data"]["complete"] is True
    assert await ctx.get_state() == NutritionAnketaStates.complete


@pytest.mark.asyncio
async def test_goal_lose_normal_bmi_advances_to_pace(monkeypatch):
    """goal=lose, BMI=24 (норма) → state=awaiting_pace, НЕ ladder."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_goal_lose
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._fetch_profile_for_bmi",
        AsyncMock(return_value=(70, 170)),  # weight, height — BMI=24.2
    )

    cb = _fake_callback("cb:anketa:goal:lose")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_goal)

    await on_goal_lose(cb, ctx)

    # upsert НЕ вызван на этом шаге — pace ещё не выбран, отложили
    upsert_mock.assert_not_awaited()
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_pace


@pytest.mark.asyncio
async def test_goal_lose_low_bmi_triggers_ladder(monkeypatch):
    """goal=lose, BMI=17.5 (<18.5) → state=awaiting_bmi_ladder."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_goal_lose
    from maxbot.states import NutritionAnketaStates

    fake_client = MagicMock()
    fake_client.upsert_profile = AsyncMock()
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._fetch_profile_for_bmi",
        AsyncMock(return_value=(48, 165)),  # BMI=17.6
    )

    cb = _fake_callback("cb:anketa:goal:lose")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_goal)

    await on_goal_lose(cb, ctx)

    assert await ctx.get_state() == NutritionAnketaStates.awaiting_bmi_ladder


@pytest.mark.asyncio
async def test_goal_gain_advances_to_clarify(monkeypatch):
    """goal=gain → state=awaiting_gain_clarify (mass vs tone)."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_goal_gain
    from maxbot.states import NutritionAnketaStates

    cb = _fake_callback("cb:anketa:goal:gain")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_goal)

    await on_goal_gain(cb, ctx)

    assert await ctx.get_state() == NutritionAnketaStates.awaiting_gain_clarify
```

- [ ] **Step 2: Run tests — должны падать**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v -k "goal_"`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement goal handlers + BMI helper**

В `mysite/maxbot/handlers/nutrition_anketa.py` добавить **после weight handler**:

```python
# ─── goal step ─────────────────────────────────────────────────────────────


PACE_TEXT = (
    "Темп похудения — какой выбираешь?\n\n"
    "🐢 Спокойный (-10% к норме) — комфортно, медленно.\n"
    "⚖️ Средний (-15%) — баланс между скоростью и комфортом."
)

GAIN_CLARIFY_TEXT = (
    "Что важнее — набрать массу или подтянуть фигуру?"
)

BMI_LADDER_TEXT = (
    "У тебя сейчас вес ниже нормы (BMI < 18.5). Дефицит может быть "
    "опасен — давай решим вместе:"
)


async def _fetch_profile_for_bmi(bot_user) -> tuple[int, int] | None:
    """Получить (weight_kg, height_cm) из текущего Ayla профиля для BMI check.

    Возвращает None если хоть одно поле отсутствует — тогда ladder не
    триггерим (нет данных для расчёта).
    """
    extid = external_user_id_for(bot_user)
    profile = await _client().get_profile(external_user_id=extid)
    if profile is None:
        return None
    if profile.weight_kg <= 0 or profile.height_cm <= 0:
        return None
    return (profile.weight_kg, profile.height_cm)


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_GOAL_MAINTAIN)
async def on_goal_maintain(callback: MessageCallback, context: MemoryContext) -> None:
    """maintain — finalize сразу, нет pace/gain_clarify/BMI ladder."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await _finalize_anketa(callback, context, chat_id, goal="maintain")


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_GOAL_LOSE)
async def on_goal_lose(callback: MessageCallback, context: MemoryContext) -> None:
    """lose — проверяем BMI: если <18.5 → ladder, иначе → pace."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    bot_user = await _resolve_bot_user(callback)
    profile_data = await _fetch_profile_for_bmi(bot_user)

    if profile_data is not None:
        from maxbot.nutrition_calc import calc_bmi
        weight_kg, height_cm = profile_data
        try:
            bmi = calc_bmi(weight_kg=weight_kg, height_cm=height_cm)
        except ValueError:
            bmi = 25.0  # fallback nominal
        if bmi < 18.5:
            await context.set_state(NutritionAnketaStates.awaiting_bmi_ladder)
            await callback.bot.send_message(
                chat_id=chat_id,
                text=BMI_LADDER_TEXT,
                attachments=[keyboards.anketa_bmi_ladder_keyboard()],
            )
            return

    # BMI normal или нет данных — переход на pace
    await context.set_state(NutritionAnketaStates.awaiting_pace)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=PACE_TEXT,
        attachments=[keyboards.anketa_pace_keyboard()],
    )


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_GOAL_GAIN)
async def on_goal_gain(callback: MessageCallback, context: MemoryContext) -> None:
    """gain — уточняем mass vs tone."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await context.set_state(NutritionAnketaStates.awaiting_gain_clarify)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=GAIN_CLARIFY_TEXT,
        attachments=[keyboards.anketa_gain_clarify_keyboard()],
    )


# ─── finalize anketa ───────────────────────────────────────────────────────


async def _finalize_anketa(
    callback_or_event,
    context: MemoryContext,
    chat_id: int,
    *,
    goal: str,
    pace: str | None = None,
) -> None:
    """Финальный POST с complete=true → render финального экрана.

    Заполняется в Task 10 (financial render). Здесь skeleton."""
    bot_user = await _resolve_bot_user(callback_or_event)
    extid = external_user_id_for(bot_user)

    body: dict = {"goal": goal, "complete": True}
    if pace is not None:
        body["pace"] = pace

    try:
        profile = await _client().upsert_profile(
            external_user_id=extid,
            data=body,
        )
    except (NutritionUnavailableError, NutritionAPIError):
        await callback_or_event.bot.send_message(
            chat_id=chat_id,
            text="Не получилось сохранить — попробуй открыть дневник заново.",
        )
        await context.clear()
        return

    await context.set_state(NutritionAnketaStates.complete)
    # Реальный финальный экран — Task 10. Сейчас минимум:
    await callback_or_event.bot.send_message(
        chat_id=chat_id,
        text=f"Готово ✓\n\n🎯 Норма: {profile.daily_kcal} ккал",
        attachments=[keyboards.anketa_complete_keyboard()],
    )
    # Set BotUser.nutrition_onboarded_at — Task 10.
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v`
Expected: 16 passed.

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/handlers/nutrition_anketa.py mysite/tests/maxbot/test_nutrition_anketa.py
git commit -m "feat(maxbot): goal step с branching на pace/gain_clarify/BMI ladder

maintain → finalize. lose → BMI<18.5 ladder | pace. gain → clarify.
_fetch_profile_for_bmi читает из Ayla GET /profile/, calc_bmi локально.
_finalize_anketa skeleton — финальный экран будет в T10."
```

---

## Task 10: Pace + Gain Clarify handlers + финальный экран рендер

**Files:**
- Modify: `mysite/maxbot/handlers/nutrition_anketa.py`
- Modify: `mysite/tests/maxbot/test_nutrition_anketa.py`

- [ ] **Step 1: Write the failing tests**

```python
# ─── pace + gain_clarify + finalize render ─────────────────────────────────


@pytest.mark.asyncio
async def test_pace_moderate_calls_finalize_with_lose_moderate(monkeypatch):
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_pace_moderate
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(
        raw={"daily_kcal": 1450, "protein_g": 110, "fat_g": 50,
             "carbs_g": 145, "water_ml": 1900,
             "goal_overridden_by": None, "overrides_applied": []},
        daily_kcal=1450, protein_g=110, fat_g=50, carbs_g=145, water_ml=1900,
        goal_overridden_by=None,
    ))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._mark_onboarded",
        AsyncMock(),
    )

    cb = _fake_callback("cb:anketa:pace:moderate")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_pace)

    await on_pace_moderate(cb, ctx)

    body = upsert_mock.await_args.kwargs["data"]
    assert body["goal"] == "lose"
    assert body["pace"] == "moderate"
    assert body["complete"] is True
    assert await ctx.get_state() == NutritionAnketaStates.complete


@pytest.mark.asyncio
async def test_gain_tone_finalizes_with_goal_tone(monkeypatch):
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_gain_tone
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(
        raw={}, daily_kcal=1700, protein_g=130, fat_g=60, carbs_g=180,
        water_ml=2000, goal_overridden_by=None,
    ))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._mark_onboarded",
        AsyncMock(),
    )

    cb = _fake_callback("cb:anketa:gain:tone")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_gain_clarify)

    await on_gain_tone(cb, ctx)

    assert upsert_mock.await_args.kwargs["data"]["goal"] == "tone"


@pytest.mark.asyncio
async def test_finalize_renders_full_norms_screen(monkeypatch):
    """Финальный экран показывает: 🎯 ккал · Б Ж У · 💧 ml + кнопка
    [📸 Сфоткать первый приём]."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_pace_gentle
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(
        raw={}, daily_kcal=1305, protein_g=110, fat_g=45, carbs_g=130,
        water_ml=1900, goal_overridden_by=None,
    ))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._mark_onboarded",
        AsyncMock(),
    )

    cb = _fake_callback("cb:anketa:pace:gentle")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_pace)

    await on_pace_gentle(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    # формат: "🎯 Норма: 1305 ккал" + "Б 110" + "💧 1900"
    assert "1305" in text
    assert "Б 110" in text
    assert "1900" in text or "1.9" in text
    # Кнопка фото есть
    assert cb.bot.send_message.await_args.kwargs.get("attachments") is not None


@pytest.mark.asyncio
async def test_finalize_marks_bot_user_onboarded(monkeypatch):
    """После complete — BotUser.nutrition_onboarded_at установлен."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_goal_maintain
    from maxbot.states import NutritionAnketaStates

    bot_user = MagicMock(max_user_id=99, nutrition_onboarded_at=None)
    upsert_mock = AsyncMock(return_value=MagicMock(
        raw={}, daily_kcal=1500, protein_g=100, fat_g=50, carbs_g=150,
        water_ml=2000, goal_overridden_by=None,
    ))
    mark_mock = AsyncMock()

    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=bot_user),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._mark_onboarded", mark_mock,
    )

    cb = _fake_callback("cb:anketa:goal:maintain")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_goal)

    await on_goal_maintain(cb, ctx)

    mark_mock.assert_awaited_once_with(bot_user)
```

- [ ] **Step 2: Run tests — должны падать**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v -k "pace or gain_tone or finalize"`
Expected: FAIL.

- [ ] **Step 3: Implement pace / gain_clarify handlers + render + onboarded mark**

В `mysite/maxbot/handlers/nutrition_anketa.py`:

```python
# ─── pace handlers ─────────────────────────────────────────────────────────


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_PACE_GENTLE)
async def on_pace_gentle(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await _finalize_anketa(callback, context, chat_id, goal="lose", pace="gentle")


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_PACE_MODERATE)
async def on_pace_moderate(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await _finalize_anketa(callback, context, chat_id, goal="lose", pace="moderate")


# ─── gain clarify ──────────────────────────────────────────────────────────


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_GAIN_MASS)
async def on_gain_mass(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await _finalize_anketa(callback, context, chat_id, goal="gain")


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_GAIN_TONE)
async def on_gain_tone(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await _finalize_anketa(callback, context, chat_id, goal="tone")
```

И **переписать** `_finalize_anketa` (был skeleton в Task 9):

```python
async def _finalize_anketa(
    callback_or_event,
    context: MemoryContext,
    chat_id: int,
    *,
    goal: str,
    pace: str | None = None,
) -> None:
    """Финальный POST с complete=true → render финальный экран.

    Mark BotUser.nutrition_onboarded_at, чтобы entry-screen в следующий
    раз сразу вёл в дневник, а не предлагал анкету заново.
    """
    bot_user = await _resolve_bot_user(callback_or_event)
    extid = external_user_id_for(bot_user)

    body: dict = {"goal": goal, "complete": True}
    if pace is not None:
        body["pace"] = pace

    try:
        profile = await _client().upsert_profile(
            external_user_id=extid,
            data=body,
        )
    except (NutritionUnavailableError, NutritionAPIError):
        await callback_or_event.bot.send_message(
            chat_id=chat_id,
            text="Не получилось сохранить — попробуй открыть дневник заново.",
        )
        await context.clear()
        return

    await _mark_onboarded(bot_user)

    await context.set_state(NutritionAnketaStates.complete)
    text = _format_complete_text(profile)
    await callback_or_event.bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[keyboards.anketa_complete_keyboard()],
    )


def _format_complete_text(profile) -> str:
    """Финальный экран TIER-A:

    Готово ✓

    🎯 Норма: 1305 ккал
       Б 110 / Ж 45 / У 130
       💧 1900 мл воды
    """
    water_ml = profile.water_ml or 0
    return (
        "Готово ✓\n\n"
        f"🎯 Норма: {profile.daily_kcal} ккал\n"
        f"   Б {profile.protein_g} / Ж {profile.fat_g} / У {profile.carbs_g}\n"
        f"   💧 {water_ml} мл воды"
    )


async def _mark_onboarded(bot_user) -> None:
    """Записать nutrition_onboarded_at = now на BotUser."""
    from django.utils import timezone

    @sync_to_async
    def _save():
        bot_user.nutrition_onboarded_at = timezone.now()
        bot_user.save(update_fields=["nutrition_onboarded_at"])

    await _save()
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v`
Expected: 20 passed.

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/handlers/nutrition_anketa.py mysite/tests/maxbot/test_nutrition_anketa.py
git commit -m "feat(maxbot): pace + gain_clarify handlers + финальный экран рендер

4 callback'а (pace_gentle/moderate, gain_mass/tone) → _finalize_anketa.
Финальный экран: ккал/БЖУ/water_ml из ProfileResponse + кнопка
[📸 Сфоткать первый приём]. _mark_onboarded ставит nutrition_onboarded_at."
```

---

## Task 11: BMI ladder handlers (Doctor / Switch / Override)

**Files:**
- Modify: `mysite/maxbot/handlers/nutrition_anketa.py`
- Modify: `mysite/tests/maxbot/test_nutrition_anketa.py`

- [ ] **Step 1: Write the failing tests**

```python
# ─── BMI ladder ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bmi_doctor_button_clears_state_with_referral(monkeypatch):
    """[Хочу к врачу] → state cleared, бот шлёт текст референса в поликлинику.
    НЕ ведёт в салон (Design Doc §4.4)."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_bmi_doctor

    cb = _fake_callback("cb:anketa:bmi:doctor")
    ctx = MemoryContext()

    await on_bmi_doctor(cb, ctx)

    assert await ctx.get_state() is None
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "врач" in text.lower() or "поликлин" in text.lower() or \
           "эндокринолог" in text.lower()
    # НЕ должно быть упоминания салона
    assert "салон" not in text.lower()
    assert "массаж" not in text.lower()


@pytest.mark.asyncio
async def test_bmi_switch_maintain_finalizes_as_maintain(monkeypatch):
    """[Поменять на «держать»] → finalize с goal=maintain."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_bmi_switch_maintain
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(
        raw={}, daily_kcal=1500, protein_g=100, fat_g=50, carbs_g=150,
        water_ml=2000, goal_overridden_by=None,
    ))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._mark_onboarded", AsyncMock(),
    )

    cb = _fake_callback("cb:anketa:bmi:switch_maintain")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_bmi_ladder)

    await on_bmi_switch_maintain(cb, ctx)

    assert upsert_mock.await_args.kwargs["data"]["goal"] == "maintain"
    assert await ctx.get_state() == NutritionAnketaStates.complete


@pytest.mark.asyncio
async def test_bmi_override_advances_to_pace_with_warning_flag(monkeypatch):
    """[Всё равно худеть] → advance to pace, помечаем bmi_warning_overridden."""
    from unittest.mock import AsyncMock

    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_bmi_override
    from maxbot.states import NutritionAnketaStates

    upsert_mock = AsyncMock(return_value=MagicMock(raw={}))
    fake_client = MagicMock()
    fake_client.upsert_profile = upsert_mock
    monkeypatch.setattr("maxbot.handlers.nutrition_anketa._client", lambda: fake_client)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=MagicMock(max_user_id=99)),
    )

    cb = _fake_callback("cb:anketa:bmi:override")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.awaiting_bmi_ladder)

    await on_bmi_override(cb, ctx)

    body = upsert_mock.await_args.kwargs["data"]
    # Ayla получит флаг через health_flags.bmi_warning_overridden
    assert body.get("health_flags", {}).get("bmi_warning_overridden") is True
    assert body["complete"] is False
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_pace
```

- [ ] **Step 2: Run tests — должны падать**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v -k "bmi_"`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement BMI ladder handlers**

В `mysite/maxbot/handlers/nutrition_anketa.py` добавить:

```python
# ─── BMI ladder ────────────────────────────────────────────────────────────


DOCTOR_REFERRAL_TEXT = (
    "Низкий BMI часто связан с гормонами или дефицитами — лучше "
    "разобраться с врачом, чем гадать.\n\n"
    "Запишись к терапевту в поликлинике или эндокринологу — они "
    "проверят анализы и подскажут план. Я буду здесь, когда вернёшься."
)


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_BMI_DOCTOR)
async def on_bmi_doctor(callback: MessageCallback, context: MemoryContext) -> None:
    """[Хочу к врачу] — НЕ кросс-промо в салон (Design Doc §4.4 honest doctor referral)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text=DOCTOR_REFERRAL_TEXT,
    )


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_ANKETA_BMI_SWITCH_MAINTAIN,
)
async def on_bmi_switch_maintain(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[Поменять на «держать»] — finalize как maintain."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await _finalize_anketa(callback, context, chat_id, goal="maintain")


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_BMI_OVERRIDE)
async def on_bmi_override(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[Всё равно худеть] — overrides помечаем флагом, advance to pace."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    bot_user = await _resolve_bot_user(callback)
    extid = external_user_id_for(bot_user)

    try:
        await _client().upsert_profile(
            external_user_id=extid,
            data={
                "health_flags": {"bmi_warning_overridden": True},
                "complete": False,
            },
        )
    except (NutritionUnavailableError, NutritionAPIError):
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Не получилось сохранить — попробуй ещё раз.",
        )
        return

    await context.set_state(NutritionAnketaStates.awaiting_pace)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=PACE_TEXT,
        attachments=[keyboards.anketa_pace_keyboard()],
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v`
Expected: 23 passed.

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/handlers/nutrition_anketa.py mysite/tests/maxbot/test_nutrition_anketa.py
git commit -m "feat(maxbot): BMI<18.5 ladder handlers (Doctor/Switch/Override)

[Хочу к врачу] → soft exit с поликлиника-referral (НЕ салон,
honest doctor referral §4.4). [Поменять на держать] → finalize maintain.
[Всё равно худеть] → bmi_warning_overridden=true в health_flags,
advance to pace."
```

---

## Task 12: «Учла важное» блок при `goal_overridden_by` от Ayla

**Files:**
- Modify: `mysite/maxbot/handlers/nutrition_anketa.py:_format_complete_text`
- Modify: `mysite/tests/maxbot/test_nutrition_anketa.py`

- [ ] **Step 1: Write the failing tests**

```python
# ─── overrides_applied render ──────────────────────────────────────────────


def test_format_complete_text_with_pregnancy_override():
    """Если ProfileResponse.goal_overridden_by='pregnancy' и goal стал
    maintain (был lose) — показываем блок 'Учла важное'."""
    from unittest.mock import MagicMock

    from maxbot.handlers.nutrition_anketa import _format_complete_text

    profile = MagicMock(
        daily_kcal=1650, protein_g=135, fat_g=55, carbs_g=160, water_ml=2000,
        goal_overridden_by="pregnancy",
        raw={
            "overrides_applied": [
                {"reason": "pregnancy",
                 "from": {"goal": "lose"},
                 "to": {"goal": "maintain"}},
            ],
        },
    )

    text = _format_complete_text(profile)
    assert "1650" in text
    assert "Учла важное" in text
    assert "беременн" in text.lower()


def test_format_complete_text_no_overrides_no_block():
    """Без overrides — нет блока 'Учла важное', только норма."""
    from unittest.mock import MagicMock

    from maxbot.handlers.nutrition_anketa import _format_complete_text

    profile = MagicMock(
        daily_kcal=1450, protein_g=110, fat_g=50, carbs_g=145, water_ml=1900,
        goal_overridden_by=None,
        raw={"overrides_applied": []},
    )

    text = _format_complete_text(profile)
    assert "Учла важное" not in text


def test_format_complete_text_with_bmr_floor_override():
    """goal_overridden_by='bmr_floor' → объяснение что подняли норму."""
    from unittest.mock import MagicMock

    from maxbot.handlers.nutrition_anketa import _format_complete_text

    profile = MagicMock(
        daily_kcal=1300, protein_g=110, fat_g=45, carbs_g=130, water_ml=1900,
        goal_overridden_by="bmr_floor",
        raw={
            "overrides_applied": [
                {"reason": "bmr_floor",
                 "from": {"pace": "moderate"},
                 "to": {"pace": "gentle"}},
            ],
        },
    )

    text = _format_complete_text(profile)
    assert "Учла важное" in text
    # Без термина BMR — метафора (Design Doc §4.4)
    assert "организм" in text.lower() or "ниже" in text.lower()
```

- [ ] **Step 2: Run tests — должны падать**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v -k "format_complete"`
Expected: FAIL — текущий `_format_complete_text` не рендерит overrides.

- [ ] **Step 3: Update `_format_complete_text`**

В `mysite/maxbot/handlers/nutrition_anketa.py` заменить функцию:

```python
def _format_complete_text(profile) -> str:
    """Финальный экран TIER-A с опциональным блоком «Учла важное».

    Блок рендерится только если Ayla вернула overrides_applied (см.
    `maxbot-phase3-ayla-spec.md` §1.2). В TIER-A overrides могут быть
    только bmr_floor (BMI<18.5+lose без override → ladder, но если юзер
    нажал [Всё равно худеть] и Ayla подняла pace до gentle = bmr_floor) —
    pregnancy/breastfeeding собирается в TIER-B, не здесь.
    """
    water_ml = profile.water_ml or 0
    base = (
        "Готово ✓\n\n"
        f"🎯 Норма: {profile.daily_kcal} ккал\n"
        f"   Б {profile.protein_g} / Ж {profile.fat_g} / У {profile.carbs_g}\n"
        f"   💧 {water_ml} мл воды"
    )

    overrides = (profile.raw or {}).get("overrides_applied") or []
    if not overrides:
        return base

    lines = ["", "Учла важное:"]
    for ov in overrides:
        reason = ov.get("reason", "")
        if reason == "pregnancy":
            lines.append("• Беременность → дефицит небезопасен, цель «держать вес»")
        elif reason == "breastfeeding":
            lines.append("• Грудное вскармливание → +400 ккал, +25 г белка")
        elif reason == "eating_disorder":
            lines.append("• Учитываю особенности — без цифр калорий в советах")
        elif reason == "bmr_floor":
            lines.append(
                "• Подняла норму — она была ниже того, что нужно "
                "организму чтобы дышать и думать"
            )
        elif reason == "low_bmi":
            lines.append("• BMI ниже нормы — рекомендую обсудить с врачом")
        # неизвестные reasons silent skip

    return base + "\n" + "\n".join(lines)
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v -k "format_complete"`
Expected: 3 passed.

- [ ] **Step 5: Run all anketa tests for regression**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v`
Expected: 26 passed.

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/nutrition_anketa.py mysite/tests/maxbot/test_nutrition_anketa.py
git commit -m "feat(maxbot): «Учла важное» блок при overrides_applied от Ayla

5 reasons → русские формулировки без термина BMR (метафора §4.4
«ниже того, что нужно организму чтобы дышать и думать»). Pregnancy
показывается только в TIER-B (тут только bmr_floor / low_bmi обычно).
Skipped overrides — silent."
```

---

## Task 13: First-meal callback (после complete) → exit FSM + hint про фото

**Files:**
- Modify: `mysite/maxbot/handlers/nutrition_anketa.py`
- Modify: `mysite/tests/maxbot/test_nutrition_anketa.py`

- [ ] **Step 1: Write the failing test**

```python
# ─── first meal CTA ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_meal_clears_state_and_hints_photo():
    """[📸 Сфоткать первый приём] → state cleared, бот шлёт hint про фото."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_anketa import on_first_meal
    from maxbot.states import NutritionAnketaStates

    cb = _fake_callback("cb:nutrition:first_meal")
    ctx = MemoryContext()
    await ctx.set_state(NutritionAnketaStates.complete)

    await on_first_meal(cb, ctx)

    assert await ctx.get_state() is None
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "фото" in text.lower() or "сфотограф" in text.lower() or "пришли" in text.lower()
```

- [ ] **Step 2: Run test — должен падать**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py::test_first_meal_clears_state_and_hints_photo -v`
Expected: FAIL.

- [ ] **Step 3: Implement first_meal handler**

В `mysite/maxbot/handlers/nutrition_anketa.py`:

```python
# ─── first meal CTA ────────────────────────────────────────────────────────


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_NUTRITION_FIRST_MEAL)
async def on_first_meal(callback: MessageCallback, context: MemoryContext) -> None:
    """[📸 Сфоткать первый приём] — exit FSM, hint про фото.

    Сам food scanner работает через handlers/food_scanner.py — нам тут
    нужно только закрыть FSM (чтобы юзер мог свободно слать фото) и
    дать инструкцию.
    """
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "📸 Пришли фото блюда — распознаю и посчитаю калории.\n\n"
            "Можешь добавить подпись («половина порции», «у мамы в гостях») — "
            "учту в расчёте."
        ),
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py -v`
Expected: 27 passed.

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/handlers/nutrition_anketa.py mysite/tests/maxbot/test_nutrition_anketa.py
git commit -m "feat(maxbot): first_meal CTA — exit FSM + hint про фото

[📸 Сфоткать первый приём] на финальном экране TIER-A → state cleared,
юзер может слать фото. Реальный food scanner — handlers/food_scanner.py
(не Part 1)."
```

---

## Task 14: Resume previously-onboarded user — entry shortcut

**Files:**
- Modify: `mysite/maxbot/handlers/nutrition_entry.py:on_show_nutrition_welcome`
- Modify: `mysite/tests/maxbot/test_nutrition_entry.py` (если файла нет — создать)

- [ ] **Step 1: Write the failing test**

```python
# mysite/tests/maxbot/test_nutrition_entry.py — append OR create

"""Phase 3.1 Part 1 T14: nutrition_entry — resume для onboarded юзера."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def _fake_callback(payload: str, chat_id: int = 12345, sender_id: int = 99):
    cb = MagicMock()
    cb.callback.payload = payload
    cb.callback.user.user_id = sender_id
    cb.message.recipient.chat_id = chat_id
    cb.bot.send_message = AsyncMock()
    return cb


@pytest.mark.asyncio
async def test_onboarded_user_sees_resume_screen_not_anketa(monkeypatch):
    """Юзер с nutrition_onboarded_at != None → бот шлёт «Дневник готов,
    пришли фото» вместо welcome-screen."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_entry import on_show_nutrition_welcome

    bot_user = MagicMock(
        nutrition_onboarded_at="2026-05-03T12:00:00Z",
        max_user_id=99,
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_entry._resolve_bot_user_for_entry",
        AsyncMock(return_value=bot_user),
    )

    cb = _fake_callback("cb:menu:nutrition")
    ctx = MemoryContext()

    await on_show_nutrition_welcome(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    # Resume-сообщение, не welcome
    assert "Дневник" in text
    # Welcome-text про «4 вопроса 30 секунд» НЕ показывается
    assert "30 сек" not in text and "анкет" not in text.lower()


@pytest.mark.asyncio
async def test_new_user_sees_welcome_screen(monkeypatch):
    """Юзер с nutrition_onboarded_at=None → стандартный welcome с 2 кнопками."""
    from maxapi.context.context import MemoryContext

    from maxbot.handlers.nutrition_entry import on_show_nutrition_welcome

    bot_user = MagicMock(nutrition_onboarded_at=None, max_user_id=99)
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_entry._resolve_bot_user_for_entry",
        AsyncMock(return_value=bot_user),
    )

    cb = _fake_callback("cb:menu:nutrition")
    ctx = MemoryContext()

    await on_show_nutrition_welcome(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "30 сек" in text or "Сфоткай" in text  # текст из WELCOME_TEXT
    assert cb.bot.send_message.await_args.kwargs.get("attachments") is not None
```

- [ ] **Step 2: Run test — должен падать**

Run: `pytest mysite/tests/maxbot/test_nutrition_entry.py -v`
Expected: FAIL — `_resolve_bot_user_for_entry` не существует.

- [ ] **Step 3: Update entry handler**

В `mysite/maxbot/handlers/nutrition_entry.py`:

Добавить в начало файла (после impors):

```python
from asgiref.sync import sync_to_async


RESUME_TEXT = (
    "🍎 Дневник питания\n\n"
    "Дневник уже настроен ✓\n\n"
    "📸 Пришли фото блюда — посчитаю калории.\n"
    "💧 Напиши «вода» или «выпила кофе» — добавлю.\n"
    "📊 Команда /день покажет сегодняшние итоги."
)


async def _resolve_bot_user_for_entry(callback):
    """Lazy-load BotUser для проверки nutrition_onboarded_at."""
    from maxbot.personalization import get_or_create_bot_user

    sender_id = callback.callback.user.user_id
    return await sync_to_async(get_or_create_bot_user)(sender_id)
```

Затем заменить `on_show_nutrition_welcome`:

```python
@router.message_callback(F.callback.payload == keyboards.PAYLOAD_MENU_NUTRITION)
async def on_show_nutrition_welcome(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """Главный entry-screen дневника. Если юзер уже прошёл анкету —
    показываем resume вместо welcome (Design Doc v2 §4.1 учёт history)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    bot_user = await _resolve_bot_user_for_entry(callback)
    if bot_user.nutrition_onboarded_at is not None:
        await callback.bot.send_message(
            chat_id=chat_id,
            text=RESUME_TEXT,
        )
        return

    # Новый юзер — welcome с 2 кнопками
    await callback.bot.send_message(
        chat_id=chat_id,
        text=WELCOME_TEXT,
        attachments=[keyboards.nutrition_welcome_keyboard()],
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_nutrition_entry.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/handlers/nutrition_entry.py mysite/tests/maxbot/test_nutrition_entry.py
git commit -m "feat(maxbot): resume-screen для onboarded user (skip welcome)

Если BotUser.nutrition_onboarded_at != None — entry показывает RESUME_TEXT
с подсказками про фото/вода/день вместо welcome-screen с кнопкой анкеты.
Учёт history из Design Doc v2 §4.1."
```

---

## Task 15: E2E happy path test через ayla_mock

**Files:**
- Modify: `mysite/tests/maxbot/test_nutrition_anketa.py`

- [ ] **Step 1: Write the failing E2E test**

```python
# ─── E2E happy path с ayla_mock ────────────────────────────────────────────


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_e2e_anketa_happy_path_female_30_165_60_lose_moderate(monkeypatch):
    """Полный TIER-A flow: consent → female → 30 → 165 → 60 → lose → moderate.
    Используем in-memory ayla_mock как backend, проверяем что профиль
    в state.profiles содержит всё ожидаемое."""
    from asgiref.sync import sync_to_async

    from maxapi.context.context import MemoryContext
    from model_bakery import baker

    from maxbot.handlers.nutrition_anketa import (
        on_consent_ok,
        on_gender_female,
        on_age_text,
        on_height_text,
        on_weight_text,
        on_goal_lose,
        on_pace_moderate,
    )
    from maxbot.handlers.nutrition_entry import on_start_anketa
    from maxbot.states import NutritionAnketaStates
    from services_app.models import BotUser
    from tests.fixtures.ayla_mock import AylaMockState, install_mock_transport

    # Ayla mock setup
    state = AylaMockState()
    install_mock_transport(monkeypatch, state)

    # BotUser fixture
    bot_user = await sync_to_async(baker.make)(
        BotUser, max_user_id=99, nutrition_onboarded_at=None,
    )
    monkeypatch.setattr(
        "maxbot.handlers.nutrition_anketa._resolve_bot_user",
        AsyncMock(return_value=bot_user),
    )

    ctx = MemoryContext()

    # Step 1: enter anketa
    await on_start_anketa(_fake_callback("cb:nutrition:start_anketa"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_consent

    # Step 2: consent
    await on_consent_ok(_fake_callback("cb:anketa:consent:ok"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_gender

    # Step 3: gender
    await on_gender_female(_fake_callback("cb:anketa:gender:female"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_age

    # Step 4: age
    await on_age_text(_fake_message("30"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_height

    # Step 5: height
    await on_height_text(_fake_message("165"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_weight

    # Step 6: weight
    await on_weight_text(_fake_message("60"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_goal

    # Step 7: goal=lose (BMI=22 → норма, нет ladder)
    await on_goal_lose(_fake_callback("cb:anketa:goal:lose"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_pace

    # Step 8: pace=moderate → finalize
    await on_pace_moderate(_fake_callback("cb:anketa:pace:moderate"), ctx)
    assert await ctx.get_state() == NutritionAnketaStates.complete

    # Verify Ayla state
    profile = state.profiles.get("bot:99")
    assert profile is not None
    assert profile.gender == "female"
    assert profile.age == 30
    assert profile.height_cm == 165
    assert profile.weight_kg == 60
    assert profile.goal == "lose"
    assert profile.pace == "moderate"

    # Verify BotUser.nutrition_onboarded_at установлен
    await sync_to_async(bot_user.refresh_from_db)()
    assert bot_user.nutrition_onboarded_at is not None
```

- [ ] **Step 2: Run E2E**

Run: `pytest mysite/tests/maxbot/test_nutrition_anketa.py::test_e2e_anketa_happy_path_female_30_165_60_lose_moderate -v`

Expected: PASS. Если PADAET с ошибкой `AylaMockState`/`install_mock_transport` — проверить что `mysite/tests/fixtures/ayla_mock.py` существует (он закоммичен в `efd00db`) и его API совпадает с ожидаемым (`state.profiles[external_user_id]` dict). Если интерфейс отличается — adapt тест к актуальному API mock'а.

- [ ] **Step 3: Commit**

```bash
git add mysite/tests/maxbot/test_nutrition_anketa.py
git commit -m "test(maxbot): E2E TIER-A happy path через ayla_mock

Покрывает 8 шагов: enter → consent → female → 30 → 165 → 60 → lose →
moderate. Проверяет state advance + Ayla profile data + BotUser
.nutrition_onboarded_at установлен."
```

---

## Task 16: Manual smoke-test script + final regression run

**Files:**
- Create: `mysite/maxbot/management/commands/manual_test_anketa.py`

- [ ] **Step 1: Create smoke script**

```python
# mysite/maxbot/management/commands/manual_test_anketa.py
"""Manual smoke-test для TIER-A anketa (Phase 3.1 Part 1).

Не запускает реальный бот — просто прогоняет все handler'ы синхронно
с realистичными данными и печатает state transitions + Ayla calls.

Usage:
    python manage.py manual_test_anketa --max-user-id 999
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Smoke-test TIER-A anketa без MAX SDK runtime"

    def add_arguments(self, parser):
        parser.add_argument("--max-user-id", type=int, default=999)

    def handle(self, *args, max_user_id, **options):
        async def run():
            from maxapi.context.context import MemoryContext
            from maxbot.handlers import nutrition_anketa, nutrition_entry
            from maxbot.states import NutritionAnketaStates

            ctx = MemoryContext()

            def cb(payload):
                m = MagicMock()
                m.callback.payload = payload
                m.callback.user.user_id = max_user_id
                m.message.recipient.chat_id = max_user_id
                m.bot.send_message = AsyncMock(side_effect=lambda **kw: print(
                    f"[bot.send] {kw['text'][:80]}",
                ))
                return m

            def msg(text):
                m = MagicMock()
                m.message.body.text = text
                m.message.sender.user_id = max_user_id
                m.message.recipient.chat_id = max_user_id
                m.bot.send_message = AsyncMock(side_effect=lambda **kw: print(
                    f"[bot.send] {kw['text'][:80]}",
                ))
                return m

            steps = [
                ("entry", nutrition_entry.on_start_anketa, cb("cb:nutrition:start_anketa")),
                ("consent", nutrition_anketa.on_consent_ok, cb("cb:anketa:consent:ok")),
                ("gender", nutrition_anketa.on_gender_female, cb("cb:anketa:gender:female")),
                ("age", nutrition_anketa.on_age_text, msg("30")),
                ("height", nutrition_anketa.on_height_text, msg("165")),
                ("weight", nutrition_anketa.on_weight_text, msg("60")),
                ("goal", nutrition_anketa.on_goal_lose, cb("cb:anketa:goal:lose")),
                ("pace", nutrition_anketa.on_pace_moderate, cb("cb:anketa:pace:moderate")),
            ]

            for label, handler, event in steps:
                print(f"\n=== {label} ===")
                try:
                    await handler(event, ctx)
                    state = await ctx.get_state()
                    print(f"  → state = {state}")
                except Exception as exc:
                    print(f"  ✗ FAILED: {type(exc).__name__}: {exc}")
                    return

            print("\n✓ Smoke complete — TIER-A flow прошёл без exceptions.")

        asyncio.run(run())
```

- [ ] **Step 2: Run smoke (требует Ayla запущенную или mock — пропусти если нет stage)**

Run: `cd mysite && python manage.py manual_test_anketa --max-user-id 999`

Expected: либо все 8 шагов проходят, либо явная ошибка про Ayla connection (ОК — это значит что код запускается, network — проблема среды).

- [ ] **Step 3: Run full test regression**

Run: `pytest mysite/tests/maxbot/ -v --tb=short`

Expected: все maxbot-тесты passed (включая новые TIER-A тесты + предыдущие phase 1/2/2.3/2.4).

- [ ] **Step 4: Run full test suite**

Run: `pytest -q`

Expected: ничего не сломалось в других модулях (сильно вряд ли — мы добавляли только новые файлы и трогали 3 существующих в narrow scope).

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/management/commands/manual_test_anketa.py
git commit -m "chore(maxbot): manual_test_anketa management command

Smoke-test TIER-A flow без MAX SDK runtime. Прогоняет 8 шагов
(entry → consent → gender → age → height → weight → goal → pace) с
mock callback/message объектами и печатает state transitions."
```

---

## Self-review checklist (выполнить после Task 16)

**Spec coverage:**
- [x] Welcome 3-кнопочный — **НЕТ в Part 1** (отложено в Part 2 — будет вместе с persistent action-row keyboard)
- [x] TIER-A анкета (5 шагов) — Tasks 5-10
- [x] Consent с обязательной кнопкой отказа — Task 5
- [x] BMI<18.5 ladder — Task 11
- [x] Goal override (pregnancy/breastfeeding) — **НЕТ в Part 1** (TIER-B = Part 2/3)
- [x] BMR floor ladder — выполняется на Ayla side, бот рендерит overrides_applied — Task 12
- [x] Финальный экран с нормой + кнопка [📸 Сфоткать первый приём] — Task 10, 13
- [x] «Учла важное» блок — Task 12
- [x] Resume для onboarded user — Task 14
- [x] Idempotency — Task 6 (UUID5)

**Placeholder scan:**
- [x] Никаких "TODO", "TBD", "implement later" — все steps содержат actual code/text
- [x] Нет "Add appropriate error handling" — каждый handler имеет explicit try/except
- [x] Все упомянутые функции / payload-константы определены в этом плане или существующем коде

**Type consistency:**
- [x] `_upsert` signature идентична во всех вызовах (Tasks 6, 7, 8)
- [x] `_finalize_anketa` signature идентична (Tasks 9, 10, 11)
- [x] `_format_complete_text` принимает ProfileResponse — поля совпадают с `nutrition_client.py:497-560`
- [x] `parse_age` / `parse_height` / `parse_weight` сигнатуры из `ai_parsers.py` (existing code) использованы корректно
- [x] State names в `NutritionAnketaStates` consistent через все Tasks

---

## Не в Part 1 (видим в backlog Part 2 + 3)

**Part 2 — Daily loop:**
- Persistent action-row keyboard (`[📸 Фото][💧 Вода][📋 Меню]`)
- Photo refactor (edit-loading + confidence routing + footer-buttons + correction flow + FSM-aware skip)
- Water flow (handlers + Ayla integration + soft-delete/restore + alcohol hint + caffeine warning + milestones)
- Daily report (push 21:00 + /день + inline + Ayla summary integration with AI-comment)
- Re-write welcome 3-кнопочный (`[📅 Запись][🍎 Дневник][💬 Спросить]`) с целевым хуком — пока остаётся существующее main_menu

**Part 3 — Nudges:**
- `NudgeEvent` модель + `NudgeMute`
- 3 нуджа: `weekly_unlock`, `reengagement`, `booking_continuation`
- `nudges/dispatcher_general.py` Celery beat task

**TIER-B (Phase 3.2 — отдельный plan-doc):**
- Health screening (6 экранов sequential β: pregnancy, ГВ, диабет, хронические, аллергии, лекарства, менопауза)
- AI trigger conditions для запуска screening lazy
- pregnancy/breastfeeding/eating_disorder override flow с «Передумала» loop

---

*Plan v1 закреплён 2026-05-04. Ссылается на Design Doc v2 (`maxbot-phase3-nutrition-design.md`) и Ayla spec (`maxbot-phase3-ayla-spec.md`) как single source of truth для контракта и UX-правил.*
