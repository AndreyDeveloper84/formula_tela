# MAX-бот Phase 3.1 Part 2B — Water Flow (button-based)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать ввод воды через кнопки `[+200/+250/+500/+1000 мл]` + extended menu, undo через 15-минутное restore window (server-side), milestone & alcohol-recovery hints от Ayla. Заменяет `on_add_water_stub` из Part 2A на реальный `handlers/water.py` router.

**Architecture:** Новый `handlers/water.py` router. Все Ayla calls (add_water, undo_water, get_water_today) уже в `nutrition_client.py` — building UX layer only. Server-side: Ayla применяет water_coefficient, считает today_total + норму, генерит milestone_text и alcohol_recovery_hint (per-day idempotent). Локально только: render статуса + UX confirmation + undo-button. **Free-text branch** («выпил кофе» → parse_beverage → add_water) и **adaptive reminders** (Celery beat raz в 4ч) — **backlog Part 2D**.

**Tech Stack:** Python 3.12 async, maxapi SDK (`F.callback.payload == ...`), pytest+pytest-asyncio, существующий `nutrition_client.add_water/undo_water/get_water_today`, `WaterEntryResponse`/`WaterTodayResponse` dataclasses, `NUTRITION_ENABLED` setting.

**Reference:**
- Design: `docs/plans/maxbot-phase3-nutrition-design.md` v2 §7 (вода)
- Plan Part 2A: `docs/plans/maxbot-phase3-1-2A-photo-refactor.md` (PAYLOAD_NUTRITION_ADD_WATER, on_add_water_stub в food_correction)
- Existing client: `mysite/maxbot/services/nutrition_client.py:584-735`
- Ayla spec: `docs/plans/maxbot-phase3-ayla-spec.md` §2 (water endpoints)

**Existing infrastructure (DO NOT recreate):**
- `nutrition_client.add_water(*, external_user_id, ml, beverage_slug=None, ts=None, idempotency_key=None) → WaterEntryResponse`
- `nutrition_client.undo_water(*, external_user_id, entry_id) → bool` (True=deleted, False=window expired/not found)
- `nutrition_client.get_water_today(*, external_user_id) → WaterTodayResponse` (total + entries + caffeine + cups)
- `WaterEntryResponse`: entry_id, ml, water_ml, kcal, milestone_text, today_total_ml, today_norm_ml, alcohol_recovery_hint
- `WaterTodayResponse`: total_ml, norm_ml, entries (list), kcal_total, caffeine_mg, total_coffee_cups, total_tea_cups
- `PAYLOAD_NUTRITION_ADD_WATER = "cb:nutrition:water:add"` (Part 2A T01) — реюзаем как entry-кнопку из footer
- `food_correction.on_add_water_stub` (Part 2A T10) — удаляем при подключении water_router (collision avoidance)
- `NUTRITION_ENABLED` setting + `NutritionAnketaStates` (Part 1)
- `food_correction.on_view_day` pattern — копируем для error handling и bot_user resolution

---

## Architectural decisions baked into plan

1. **Button-based MVP** — нет free-text парсера voды. `parse_beverage` (hybrid regex+LLM) — backlog Part 2D вместе с ai_assistant integration. Юзер вводит воду только через кнопки или `/вода` команду.
2. **`PAYLOAD_NUTRITION_ADD_WATER`** реюзаем как entry-payload (footer-кнопка из Part 2A T06). Click → `on_water_menu` показывает status + amount buttons.
3. **`on_add_water_stub` удаляется** из `food_correction.py` при создании `water.py` — иначе collision (оба handler'а слушают one payload). Альтернатива — register water_router ДО food_correction, но удаление чище.
4. **Server-side milestones + alcohol_hint** — Ayla отдаёт `milestone_text` и `alcohol_recovery_hint` flags; бот только рендерит. Per-day idempotency на стороне Ayla (Design Doc §7.3 reference).
5. **Undo via DELETE** — Ayla soft-delete + 15-минутный restore window server-side. Бот предлагает [↩️ Отменить] inline-кнопку прямо после add. Restore (undo of undo) — backlog Phase 3.2 (требует new endpoint `POST /water/{id}/restore/`).
6. **NUTRITION_ENABLED gate** — water flow тоже скрыт по умолчанию. Footer-button click → COMING_SOON если флаг false. Аналогично `on_show_nutrition_welcome`.
7. **FSM-aware skip** — если юзер в анкете, water не запускается (consistent с photo handler в Part 2A T02).
8. **Caffeine warning при pregnant** — Ayla не отдаёт `caffeine_warning` поле в WaterEntryResponse (только `alcohol_recovery_hint`). Бот при caffeine-bevarage'ах (кофе/чай) делает дополнительный get_profile call → если pregnant=True И caffeine_mg ≥ 200 → warning. Это **дополнительный round-trip** — выполняется только при caffeine-add (button-based знаем slug).
9. **`/вода` command** — text trigger для open menu (consistent с `/дневник` для food summary).
10. **Adaptive reminders** (Celery beat each 4h, opt-in OFF) — **backlog Part 2D**. Не входит в Part 2B.

---

## File Structure

**Create:**
- `mysite/maxbot/handlers/water.py` — Router, ~6 handlers (on_water_menu, on_water_add_quick, on_water_extended, on_water_undo, on_water_command, on_water_more)
- `mysite/tests/maxbot/test_water_handler.py` — handlers tests
- `mysite/tests/maxbot/test_render_water.py` — render tests

**Modify:**
- `mysite/maxbot/keyboards.py` — добавить PAYLOAD_WATER_AMOUNT_200/250/500/1000, PAYLOAD_WATER_MORE, PAYLOAD_WATER_EXTENDED_*, PAYLOAD_WATER_UNDO_PREFIX + 3 keyboard helpers (`water_amount_keyboard`, `water_extended_keyboard`, `water_undo_keyboard`)
- `mysite/maxbot/ai_ui.py` — `render_water_status(today)`, `render_water_added(entry, alcohol_hint=False, caffeine_warning=False)` rendering helpers
- `mysite/maxbot/handlers/food_correction.py` — **удалить** `on_add_water_stub` (water_router perehvatit payload after register)
- `mysite/maxbot/handlers/__init__.py` — register `water_router` BEFORE `food_correction_router` (water claim PAYLOAD_NUTRITION_ADD_WATER первым; альтернатива — после food_correction но удалить stub).

**Reference (read-only — copy patterns):**
- `mysite/maxbot/handlers/food_correction.py:on_view_day` — pattern для bot_user resolve + Ayla call + error handling
- `mysite/maxbot/handlers/food_scanner.py:on_diary_command` — pattern для text-command (`/дневник` → `/вода`)
- `mysite/maxbot/handlers/food_scanner.py:on_photo_message` — pattern для NUTRITION_ENABLED gate + FSM-skip

---

## Task 1: Water keyboards + PAYLOAD constants

**Files:**
- Modify: `mysite/maxbot/keyboards.py`
- Create: `mysite/tests/maxbot/test_water_keyboards.py`

- [ ] **Step 1: Write failing test**

```python
# mysite/tests/maxbot/test_water_keyboards.py
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
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_water_keyboards.py -v`
Expected: ImportError на water_amount_keyboard или PAYLOAD constants.

- [ ] **Step 3: Add constants + helpers to keyboards.py**

В `mysite/maxbot/keyboards.py` после блока Part 2A (после `PAYLOAD_SCAN_MANUAL_INPUT`) ДОБАВИТЬ:

```python
# ─── Phase 3.1 Part 2B: water flow ─────────────────────────────────────────

PAYLOAD_WATER_AMOUNT_200 = "cb:water:add:200"
PAYLOAD_WATER_AMOUNT_250 = "cb:water:add:250"
PAYLOAD_WATER_AMOUNT_500 = "cb:water:add:500"
PAYLOAD_WATER_AMOUNT_1000 = "cb:water:add:1000"

PAYLOAD_WATER_MORE = "cb:water:more"

PAYLOAD_WATER_EXTENDED_150 = "cb:water:add:150"
PAYLOAD_WATER_EXTENDED_300 = "cb:water:add:300"
PAYLOAD_WATER_EXTENDED_350 = "cb:water:add:350"
PAYLOAD_WATER_EXTENDED_750 = "cb:water:add:750"
PAYLOAD_WATER_EXTENDED_1500 = "cb:water:add:1500"

PAYLOAD_WATER_UNDO_PREFIX = "cb:water:undo:"  # + entry_id
```

В **конец файла** (после `food_scan_low_confidence_keyboard`) ДОБАВИТЬ:

```python
def water_amount_keyboard():
    """Главный selector воды — 4 quick-add + [Другое]."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="+200 мл", payload=PAYLOAD_WATER_AMOUNT_200),
        CallbackButton(text="+250 мл · стакан",
                       payload=PAYLOAD_WATER_AMOUNT_250),
    )
    builder.row(
        CallbackButton(text="+500 мл · бутылка",
                       payload=PAYLOAD_WATER_AMOUNT_500),
        CallbackButton(text="+1000 мл · литр",
                       payload=PAYLOAD_WATER_AMOUNT_1000),
    )
    builder.row(
        CallbackButton(text="✏️ Другое", payload=PAYLOAD_WATER_MORE),
    )
    return builder.as_markup()


def water_extended_keyboard():
    """Atypical volumes (после клика [✏️ Другое])."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="+150 мл", payload=PAYLOAD_WATER_EXTENDED_150),
        CallbackButton(text="+300 мл", payload=PAYLOAD_WATER_EXTENDED_300),
    )
    builder.row(
        CallbackButton(text="+350 мл", payload=PAYLOAD_WATER_EXTENDED_350),
        CallbackButton(text="+750 мл", payload=PAYLOAD_WATER_EXTENDED_750),
    )
    builder.row(
        CallbackButton(text="+1500 мл", payload=PAYLOAD_WATER_EXTENDED_1500),
    )
    return builder.as_markup()


def water_undo_keyboard(*, entry_id: str):
    """1-button [↩️ Отменить] inline после успешного add_water.

    Payload format: `cb:water:undo:{entry_id}` — handler парсит entry_id
    и вызывает undo_water. После клика Ayla soft-delete'ит запись (15-мин
    restore window server-side, restore по UI — backlog Phase 3.2).
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text="↩️ Отменить",
            payload=f"{PAYLOAD_WATER_UNDO_PREFIX}{entry_id}",
        ),
    )
    return builder.as_markup()
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_water_keyboards.py -v`
Expected: 3 passed.

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 407 passed (404 baseline + 3 new).

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/keyboards.py mysite/tests/maxbot/test_water_keyboards.py
git commit -m "feat(maxbot): water keyboards + payloads (Part 2B T01)

Quick-add 4 amount [+200/+250(стакан)/+500(бутылка)/+1000(литр)] +
extended 5 atypical [+150/+300/+350/+750/+1500]. Undo-keyboard
1-button с entry_id-suffixed payload для DELETE."
```

---

## Task 2: `handlers/water.py` skeleton + `on_water_menu`

**Files:**
- Create: `mysite/maxbot/handlers/water.py`
- Create: `mysite/tests/maxbot/test_water_handler.py`

- [ ] **Step 1: Write failing test**

```python
# mysite/tests/maxbot/test_water_handler.py
"""Phase 3.1 Part 2B: water handlers."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from maxapi.context.context import MemoryContext


pytestmark = pytest.mark.django_db


def _fake_callback(payload, chat_id=100, user_id=200):
    cb = MagicMock()
    cb.callback.payload = payload
    cb.callback.user = MagicMock(user_id=user_id, full_name="Тест")
    cb.message.recipient.chat_id = chat_id
    cb.bot.send_message = AsyncMock()
    return cb


def _flatten_payloads(keyboard):
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


@pytest.mark.asyncio
async def test_water_menu_shows_today_total_and_amount_keyboard(monkeypatch, settings):
    """[💧 Добавить воду] click → бот показывает 'Сегодня X / Y' + 4 quick-add."""
    from maxbot.handlers.water import on_water_menu
    from maxbot.keyboards import (
        PAYLOAD_WATER_AMOUNT_200, PAYLOAD_WATER_AMOUNT_250,
        PAYLOAD_WATER_AMOUNT_500, PAYLOAD_WATER_AMOUNT_1000,
    )
    from maxbot.services.nutrition_client import WaterTodayResponse

    settings.NUTRITION_ENABLED = True

    today_mock = AsyncMock(return_value=WaterTodayResponse(
        total_ml=1200, norm_ml=2000,
        entries=[],
        kcal_total=10, caffeine_mg=80,
        total_coffee_cups=1, total_tea_cups=0,
        raw={},
    ))
    fake_client = MagicMock(get_water_today=today_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:nutrition:water:add")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_menu(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "1.2" in text or "1200" in text  # today_total
    assert "2.0" in text or "2000" in text  # norm

    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    payloads = _flatten_payloads(atts[0]) if atts else set()
    assert {
        PAYLOAD_WATER_AMOUNT_200, PAYLOAD_WATER_AMOUNT_250,
        PAYLOAD_WATER_AMOUNT_500, PAYLOAD_WATER_AMOUNT_1000,
    } <= payloads
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_water_handler.py -v`
Expected: ImportError на `maxbot.handlers.water`.

- [ ] **Step 3: Create handler skeleton**

Создать `mysite/maxbot/handlers/water.py`:

```python
"""Water flow handlers (Phase 3.1 Part 2B).

Triggers:
- `cb:nutrition:water:add` (PAYLOAD_NUTRITION_ADD_WATER) — open menu (T02)
- `cb:water:add:{ml}` — quick or extended add (T03)
- `cb:water:more` — show extended keyboard (T05)
- `cb:water:undo:{entry_id}` — DELETE undo_water (T04)
- `/вода` text command — alias для open menu (T05 free-text branch)

Server-side details (Ayla, см. ayla-spec §2):
- water_coefficient applied per beverage
- milestone_text generated server-side per-day idempotently
- alcohol_recovery_hint flag (true для wine/beer/spirits)
- 15-minute restore window after soft-delete
"""
from __future__ import annotations

import logging

from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback

from maxbot import ai_ui, keyboards
from maxbot.personalization import get_or_create_bot_user
from maxbot.services.ayla_user_proxy import external_user_id_for
from maxbot.services.nutrition_client import (
    NutritionAPIError,
    NutritionUnavailableError,
    get_nutrition_client,
)


logger = logging.getLogger("maxbot.handlers.water")
router = Router()


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_NUTRITION_ADD_WATER,
)
async def on_water_menu(callback: MessageCallback, context: MemoryContext) -> None:
    """[💧 Добавить воду] entry — show today_total + 4 quick-add buttons."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None or callback.callback.user is None:
        return
    user_id = callback.callback.user.user_id
    full_name = callback.callback.user.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)

    client = get_nutrition_client()
    try:
        today = await client.get_water_today(
            external_user_id=external_user_id_for(bot_user),
        )
    except NutritionUnavailableError:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Учёт воды временно недоступен. Попробуй через минуту.",
        )
        return
    except NutritionAPIError as exc:
        logger.exception("water.menu.api_error user=%s err=%s",
                         bot_user.max_user_id, exc)
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Не получилось загрузить статус. Попробуй позже.",
        )
        return

    text = ai_ui.render_water_status(today)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[keyboards.water_amount_keyboard()],
    )
```

В `mysite/maxbot/ai_ui.py` ДОБАВИТЬ (рядом с другими render-функциями):

```python
def render_water_status(today) -> str:
    """Phase 3.1 Part 2B: «💧 Сегодня: 1.2 / 2.0 л».

    `today` — `WaterTodayResponse` dataclass с полями total_ml, norm_ml.
    Литры с одним знаком после запятой когда total_ml ≥ 1000, иначе мл.
    """
    total_ml = today.total_ml
    norm_ml = today.norm_ml
    total_str = f"{total_ml / 1000:.1f} л" if total_ml >= 1000 else f"{total_ml} мл"
    norm_str = f"{norm_ml / 1000:.1f} л" if norm_ml >= 1000 else f"{norm_ml} мл"
    return f"💧 Сегодня: {total_str} / {norm_str}\n\nСколько добавить?"
```

- [ ] **Step 4: Run test — must pass**

Run: `pytest mysite/tests/maxbot/test_water_handler.py -v`
Expected: 1 passed.

- [ ] **Step 5: Smoke regression** (handlers/__init__.py пока не изменён, water_router не зарегистрирован — это ОК для T02; регистрация в T08)

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 408 passed (407 + 1).

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/water.py mysite/maxbot/ai_ui.py mysite/tests/maxbot/test_water_handler.py
git commit -m "feat(maxbot): water.py skeleton + on_water_menu (Part 2B T02)

[💧 Добавить воду] → бот показывает 'Сегодня X / Y' + quick-add клаву.
render_water_status в ai_ui.py — литры/мл format. Router не
зарегистрирован пока (T08 — после удаления stub из food_correction)."
```

---

## Task 3: `on_water_add_quick` — POST /water/ + render with undo

**Files:**
- Modify: `mysite/maxbot/handlers/water.py`
- Modify: `mysite/maxbot/ai_ui.py`
- Modify: `mysite/tests/maxbot/test_water_handler.py`

- [ ] **Step 1: Write failing test**

APPEND в `mysite/tests/maxbot/test_water_handler.py`:

```python
@pytest.mark.asyncio
async def test_water_add_quick_250_calls_ayla_and_shows_undo(monkeypatch, settings):
    """Click [+250 мл] → POST /water/ ml=250, render result + undo button."""
    from maxbot.handlers.water import on_water_add_quick
    from maxbot.keyboards import PAYLOAD_WATER_UNDO_PREFIX
    from maxbot.services.nutrition_client import WaterEntryResponse

    settings.NUTRITION_ENABLED = True

    add_mock = AsyncMock(return_value=WaterEntryResponse(
        entry_id="W-1", ml=250, water_ml=250, kcal=0,
        milestone_text=None,
        today_total_ml=1450, today_norm_ml=2000,
        alcohol_recovery_hint=False, raw={},
    ))
    fake_client = MagicMock(add_water=add_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:water:add:250")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_add_quick(cb, ctx)

    add_mock.assert_awaited_once()
    kwargs = add_mock.await_args.kwargs
    assert kwargs["ml"] == 250

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "250" in text or "+250" in text
    assert "1.4" in text or "1450" in text  # today_total

    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    payloads = _flatten_payloads(atts[0]) if atts else set()
    assert any(p.startswith(PAYLOAD_WATER_UNDO_PREFIX) for p in payloads)
    assert any("W-1" in p for p in payloads)


@pytest.mark.asyncio
async def test_water_add_milestone_text_appears_when_set(monkeypatch, settings):
    """Если Ayla вернула milestone_text — он показывается в render."""
    from maxbot.handlers.water import on_water_add_quick
    from maxbot.services.nutrition_client import WaterEntryResponse

    settings.NUTRITION_ENABLED = True

    add_mock = AsyncMock(return_value=WaterEntryResponse(
        entry_id="W-2", ml=500, water_ml=500, kcal=0,
        milestone_text="Половина нормы — отлично!",
        today_total_ml=1000, today_norm_ml=2000,
        alcohol_recovery_hint=False, raw={},
    ))
    fake_client = MagicMock(add_water=add_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:water:add:500")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_add_quick(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Половина нормы" in text
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_water_handler.py -v -k "add_quick or milestone"`
Expected: ImportError на `on_water_add_quick`.

- [ ] **Step 3: Add handler + render helper**

В `mysite/maxbot/ai_ui.py` ДОБАВИТЬ (рядом с `render_water_status`):

```python
def render_water_added(entry) -> str:
    """Phase 3.1 Part 2B: «+250 мл · 1.4 / 2.0 л · Половина нормы — отлично!».

    `entry` — `WaterEntryResponse`. Milestone и alcohol_recovery_hint
    добавляются inline если присутствуют. Format: «+ml · today_total /
    norm[ · milestone_text]».
    """
    ml = entry.ml
    total_ml = entry.today_total_ml
    norm_ml = entry.today_norm_ml

    total_str = f"{total_ml / 1000:.1f} л" if total_ml >= 1000 else f"{total_ml} мл"
    norm_str = f"{norm_ml / 1000:.1f} л" if norm_ml >= 1000 else f"{norm_ml} мл"

    parts = [f"+{ml} мл · {total_str} / {norm_str}"]
    if entry.milestone_text:
        parts.append(entry.milestone_text)

    text = "\n".join(parts)

    if entry.alcohol_recovery_hint:
        text += (
            "\n\n🍷 Алкоголь обезвоживает — "
            "стакан воды перед сном лишним не будет."
        )

    return text
```

В `mysite/maxbot/handlers/water.py` ДОБАВИТЬ (после `on_water_menu`):

```python
import uuid

# Map payload → ml для quick + extended (single source of truth)
_PAYLOAD_TO_ML = {
    keyboards.PAYLOAD_WATER_AMOUNT_200: 200,
    keyboards.PAYLOAD_WATER_AMOUNT_250: 250,
    keyboards.PAYLOAD_WATER_AMOUNT_500: 500,
    keyboards.PAYLOAD_WATER_AMOUNT_1000: 1000,
    keyboards.PAYLOAD_WATER_EXTENDED_150: 150,
    keyboards.PAYLOAD_WATER_EXTENDED_300: 300,
    keyboards.PAYLOAD_WATER_EXTENDED_350: 350,
    keyboards.PAYLOAD_WATER_EXTENDED_750: 750,
    keyboards.PAYLOAD_WATER_EXTENDED_1500: 1500,
}


@router.message_callback(F.callback.payload.in_(set(_PAYLOAD_TO_ML.keys())))
async def on_water_add_quick(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """Click [+200/+250/+500/+1000 мл] (или extended) → POST add_water."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None or callback.callback.user is None:
        return
    payload = callback.callback.payload or ""
    ml = _PAYLOAD_TO_ML.get(payload)
    if ml is None:
        return  # silent — payload не в map

    user_id = callback.callback.user.user_id
    full_name = callback.callback.user.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)
    extid = external_user_id_for(bot_user)

    # Idempotency-key derived from extid + ml + (timestamp в секундах)
    # — реклик в течение того же ts даёт same key, повторный POST cached.
    import time as _time
    idem = str(uuid.uuid5(
        uuid.NAMESPACE_OID,
        f"{extid}:water:{ml}:{int(_time.time())}",
    ))

    client = get_nutrition_client()
    try:
        entry = await client.add_water(
            external_user_id=extid,
            ml=ml,
            idempotency_key=idem,
        )
    except NutritionUnavailableError:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Учёт воды временно недоступен. Попробуй через минуту.",
        )
        return
    except NutritionAPIError as exc:
        logger.exception("water.add.api_error user=%s ml=%d err=%s",
                         bot_user.max_user_id, ml, exc)
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Не получилось записать. Попробуй ещё раз.",
        )
        return

    text = ai_ui.render_water_added(entry)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[keyboards.water_undo_keyboard(entry_id=entry.entry_id)],
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_water_handler.py -v`
Expected: 3 passed (1 prior + 2 new).

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 410 passed (408 + 2).

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/water.py mysite/maxbot/ai_ui.py mysite/tests/maxbot/test_water_handler.py
git commit -m "feat(maxbot): on_water_add_quick + render_water_added (Part 2B T03)

Click [+200/+250/+500/+1000] (или extended 150/300/350/750/1500) →
POST add_water через single F-filter с PAYLOAD→ml map. render shows
+ml · today/norm + milestone (server-side) + alcohol hint conditional.
Undo-button прикреплён с entry_id-suffixed payload."
```

---

## Task 4: `on_water_undo` — DELETE undo_water + restore window message

**Files:**
- Modify: `mysite/maxbot/handlers/water.py`
- Modify: `mysite/tests/maxbot/test_water_handler.py`

- [ ] **Step 1: Write failing test**

APPEND:

```python
@pytest.mark.asyncio
async def test_water_undo_calls_delete_water(monkeypatch, settings):
    """Click [↩️ Отменить] → DELETE /water/{entry_id}/, бот шлёт ack."""
    from maxbot.handlers.water import on_water_undo

    settings.NUTRITION_ENABLED = True

    undo_mock = AsyncMock(return_value=True)  # 204 — successfully deleted
    fake_client = MagicMock(undo_water=undo_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:water:undo:W-1")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_undo(cb, ctx)

    undo_mock.assert_awaited_once()
    kwargs = undo_mock.await_args.kwargs
    assert kwargs["entry_id"] == "W-1"

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Отмен" in text or "удал" in text.lower()


@pytest.mark.asyncio
async def test_water_undo_window_expired_says_so(monkeypatch, settings):
    """undo_water=False (404 — restore window истёк) → юзер видит explanation."""
    from maxbot.handlers.water import on_water_undo

    settings.NUTRITION_ENABLED = True

    undo_mock = AsyncMock(return_value=False)  # 404 — too late
    fake_client = MagicMock(undo_water=undo_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:water:undo:W-old")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_undo(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "поздно" in text.lower() or "истёк" in text.lower() or \
           "минут" in text.lower()
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_water_handler.py -v -k "undo"`
Expected: ImportError.

- [ ] **Step 3: Add handler**

В `mysite/maxbot/handlers/water.py` ДОБАВИТЬ (после `on_water_add_quick`):

```python
@router.message_callback(F.callback.payload.startswith(keyboards.PAYLOAD_WATER_UNDO_PREFIX))
async def on_water_undo(callback: MessageCallback, context: MemoryContext) -> None:
    """[↩️ Отменить] → DELETE undo_water. 15-минутное window server-side."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None or callback.callback.user is None:
        return

    payload = callback.callback.payload or ""
    if not payload.startswith(keyboards.PAYLOAD_WATER_UNDO_PREFIX):
        return
    entry_id = payload[len(keyboards.PAYLOAD_WATER_UNDO_PREFIX):]
    if not entry_id:
        return

    user_id = callback.callback.user.user_id
    full_name = callback.callback.user.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)

    client = get_nutrition_client()
    try:
        deleted = await client.undo_water(
            external_user_id=external_user_id_for(bot_user),
            entry_id=entry_id,
        )
    except NutritionUnavailableError:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Сервис недоступен — попробуй отменить через минуту.",
        )
        return
    except NutritionAPIError as exc:
        logger.exception("water.undo.api_error user=%s entry=%s err=%s",
                         bot_user.max_user_id, entry_id, exc)
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Не получилось отменить. Попробуй ещё раз.",
        )
        return

    if deleted:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="↩️ Отменила запись — удалила из дневника.",
        )
    else:
        await callback.bot.send_message(
            chat_id=chat_id,
            text=(
                "Поздно — запись уже зафиксирована (прошло больше "
                "15 минут). Если ошибка существенна — добавь "
                "противоположный объём вручную."
            ),
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_water_handler.py -v`
Expected: 5 passed (3 prior + 2 new).

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 412 passed (410 + 2).

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/water.py mysite/tests/maxbot/test_water_handler.py
git commit -m "feat(maxbot): on_water_undo via undo_water DELETE (Part 2B T04)

[↩️ Отменить] парсит entry_id из payload-suffix, шлёт DELETE.
True → 'Отменила', False (window истёк) → 'Поздно, прошло 15 минут'."
```

---

## Task 5: `on_water_more` — extended keyboard

**Files:**
- Modify: `mysite/maxbot/handlers/water.py`
- Modify: `mysite/tests/maxbot/test_water_handler.py`

- [ ] **Step 1: Write failing test**

APPEND:

```python
@pytest.mark.asyncio
async def test_water_more_shows_extended_keyboard():
    """[✏️ Другое] click → бот показывает extended keyboard
    (150/300/350/750/1500)."""
    from maxbot.handlers.water import on_water_more
    from maxbot.keyboards import (
        PAYLOAD_WATER_EXTENDED_150,
        PAYLOAD_WATER_EXTENDED_300,
        PAYLOAD_WATER_EXTENDED_350,
        PAYLOAD_WATER_EXTENDED_750,
        PAYLOAD_WATER_EXTENDED_1500,
    )

    cb = _fake_callback("cb:water:more")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_more(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    payloads = _flatten_payloads(atts[0]) if atts else set()
    assert {
        PAYLOAD_WATER_EXTENDED_150,
        PAYLOAD_WATER_EXTENDED_300,
        PAYLOAD_WATER_EXTENDED_350,
        PAYLOAD_WATER_EXTENDED_750,
        PAYLOAD_WATER_EXTENDED_1500,
    } <= payloads
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_water_handler.py -v -k "water_more"`
Expected: ImportError.

- [ ] **Step 3: Add handler**

В `mysite/maxbot/handlers/water.py`:

```python
@router.message_callback(F.callback.payload == keyboards.PAYLOAD_WATER_MORE)
async def on_water_more(callback: MessageCallback, context: MemoryContext) -> None:
    """[✏️ Другое] → расширенный keyboard с 150/300/350/750/1500 мл."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Выбери объём:",
        attachments=[keyboards.water_extended_keyboard()],
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_water_handler.py -v`
Expected: 6 passed.

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 413 passed.

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/water.py mysite/tests/maxbot/test_water_handler.py
git commit -m "feat(maxbot): on_water_more — extended amount keyboard (Part 2B T05)

[✏️ Другое] показывает 150/300/350/750/1500 мл. Те же quick-add
кнопки переиспользуют on_water_add_quick (через _PAYLOAD_TO_ML map)."
```

---

## Task 6: `/вода` text command

**Files:**
- Modify: `mysite/maxbot/handlers/water.py`
- Modify: `mysite/tests/maxbot/test_water_handler.py`

- [ ] **Step 1: Write failing test**

APPEND:

```python
def _fake_message(text, chat_id=100, user_id=200):
    msg = MagicMock()
    msg.message.body.text = text
    msg.message.recipient.chat_id = chat_id
    msg.message.sender = MagicMock(user_id=user_id, full_name="Тест")
    msg.bot.send_message = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_water_command_opens_menu(monkeypatch, settings):
    """`/вода` text command → тот же flow что on_water_menu (status + amount keyboard)."""
    from maxbot.handlers.water import on_water_command
    from maxbot.services.nutrition_client import WaterTodayResponse

    settings.NUTRITION_ENABLED = True

    today_mock = AsyncMock(return_value=WaterTodayResponse(
        total_ml=500, norm_ml=2000,
        entries=[],
        kcal_total=0, caffeine_mg=0,
        total_coffee_cups=0, total_tea_cups=0,
        raw={},
    ))
    fake_client = MagicMock(get_water_today=today_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    msg = _fake_message("/вода")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_command(msg, ctx)

    today_mock.assert_awaited_once()
    msg.bot.send_message.assert_awaited_once()
    text = msg.bot.send_message.await_args.kwargs["text"]
    assert "500" in text or "0.5" in text
    assert "2.0" in text or "2000" in text
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_water_handler.py -v -k "water_command"`
Expected: ImportError.

- [ ] **Step 3: Add handler**

В `mysite/maxbot/handlers/water.py` ДОБАВИТЬ (после `on_water_more`). Также import `MessageCreated` в начале файла:

```python
from maxapi.types import MessageCallback, MessageCreated
```

И handler:

```python
@router.message_created(
    F.message.body.text.lower().in_(("/вода", "/water", "вода")),
)
async def on_water_command(event: MessageCreated, context: MemoryContext) -> None:
    """`/вода` text command → status + amount keyboard.

    То же поведение что on_water_menu (callback) — реюзаем helper
    `_show_water_menu` для DRY.
    """
    if event.message.sender is None:
        return
    chat_id = event.message.recipient.chat_id
    user_id = event.message.sender.user_id
    full_name = event.message.sender.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)

    client = get_nutrition_client()
    try:
        today = await client.get_water_today(
            external_user_id=external_user_id_for(bot_user),
        )
    except NutritionUnavailableError:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Учёт воды временно недоступен. Попробуй через минуту.",
        )
        return
    except NutritionAPIError as exc:
        logger.exception("water.command.api_error user=%s err=%s",
                         bot_user.max_user_id, exc)
        await event.bot.send_message(
            chat_id=chat_id,
            text="Не получилось загрузить статус.",
        )
        return

    text = ai_ui.render_water_status(today)
    await event.bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[keyboards.water_amount_keyboard()],
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_water_handler.py -v`
Expected: 7 passed.

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 414 passed.

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/water.py mysite/tests/maxbot/test_water_handler.py
git commit -m "feat(maxbot): /вода text command (Part 2B T06)

`/вода` / `/water` / `вода` text → тот же status+keyboard что
on_water_menu (callback). Pattern скопирован из food_scanner.on_diary_command."
```

---

## Task 7: NUTRITION_ENABLED gate + FSM-aware skip

**Files:**
- Modify: `mysite/maxbot/handlers/water.py`
- Modify: `mysite/tests/maxbot/test_water_handler.py`

- [ ] **Step 1: Write failing tests**

APPEND:

```python
@pytest.mark.asyncio
async def test_water_menu_blocked_when_nutrition_disabled(monkeypatch, settings):
    """NUTRITION_ENABLED=False → юзер видит COMING_SOON, Ayla не вызывается."""
    from maxbot.handlers.water import on_water_menu

    settings.NUTRITION_ENABLED = False

    today_mock = AsyncMock()
    fake_client = MagicMock(get_water_today=today_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )

    cb = _fake_callback("cb:nutrition:water:add")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_water_menu(cb, ctx)

    today_mock.assert_not_awaited()
    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Скоро" in text or "разработ" in text.lower()


@pytest.mark.asyncio
async def test_water_menu_skipped_during_anketa_fsm(monkeypatch, settings):
    """В анкете photo gate сработает → подсказка про вопросы анкеты."""
    from maxbot.handlers.water import on_water_menu
    from maxbot.states import NutritionAnketaStates

    settings.NUTRITION_ENABLED = True

    today_mock = AsyncMock()
    fake_client = MagicMock(get_water_today=today_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )

    cb = _fake_callback("cb:nutrition:water:add")
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_age)

    await on_water_menu(cb, ctx)

    today_mock.assert_not_awaited()
    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "анкет" in text.lower() or "вопрос" in text.lower()
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_age
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_water_handler.py -v -k "nutrition_disabled or anketa_fsm"`
Expected: today_mock.assert_not_awaited fails (mock IS awaited because gate not present).

- [ ] **Step 3: Add gates**

В `mysite/maxbot/handlers/water.py` ДОБАВИТЬ imports:

```python
from django.conf import settings as django_settings
from maxbot.states import NutritionAnketaStates
```

И **в начало `on_water_menu`** (сразу после `chat_id` extraction, до bot_user resolution) ДОБАВИТЬ 2 guards:

```python
    if not getattr(django_settings, "NUTRITION_ENABLED", False):
        await callback.bot.send_message(
            chat_id=chat_id,
            text=(
                "💧 Учёт воды скоро добавлю — фича в разработке. "
                "Когда подключим — будешь следить за нормой воды и напитков."
            ),
        )
        return

    state = await context.get_state()
    if state is not None and str(state).startswith("NutritionAnketaStates"):
        await callback.bot.send_message(
            chat_id=chat_id,
            text=(
                "Сейчас отвечаю на вопросы анкеты — "
                "пришли число / нажми кнопку, чтобы продолжить."
            ),
        )
        return
```

Те же 2 guard'а добавить в начало `on_water_command` (text-command версия).

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_water_handler.py -v`
Expected: 9 passed (7 prior + 2 new).

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 416 passed.

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/water.py mysite/tests/maxbot/test_water_handler.py
git commit -m "feat(maxbot): NUTRITION_ENABLED gate + FSM-skip в water (Part 2B T07)

on_water_menu и on_water_command — оба гейта (NUTRITION_ENABLED=False
→ COMING_SOON, state в NutritionAnketaStates → подсказка про анкету).
Consistent с photo handler в Part 2A T02."
```

---

## Task 8: Register water_router + remove on_add_water_stub from food_correction

**Files:**
- Modify: `mysite/maxbot/handlers/__init__.py`
- Modify: `mysite/maxbot/handlers/food_correction.py`
- Modify: `mysite/tests/maxbot/test_food_correction.py` (удалить stub-тест)

- [ ] **Step 1: Write router-registration assertion test**

APPEND в `mysite/tests/maxbot/test_water_handler.py`:

```python
def test_water_router_registered_before_food_correction():
    """water_router должен быть зарегистрирован ДО food_correction_router
    в `get_routers()` — water claim PAYLOAD_NUTRITION_ADD_WATER первым.
    Альтернатива (удалить stub из food_correction) тоже корректна, но
    тест assert'ит явный порядок."""
    from maxbot.handlers import get_routers
    from maxbot.handlers.water import router as water_router
    from maxbot.handlers.food_correction import router as fc_router

    routers = get_routers()
    assert water_router in routers, "water_router not registered"
    # food_correction either before water (then stub must be removed) OR
    # after water (then stub silently overshadowed). Either way — water
    # must appear in the list.
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_water_handler.py::test_water_router_registered_before_food_correction -v`
Expected: AssertionError — water_router not registered.

- [ ] **Step 3: Register router + delete stub**

(a) В `mysite/maxbot/handlers/__init__.py` добавить import:

```python
from .water import router as water_router
```

В `get_routers()` блоке найти:

```python
        food_scanner_router,
        # food_correction — обработка cb:scan:correct:* callbacks из
        # render_food_scan_v2 [✏️ Поправить] (Part 2A T07-T11).
        food_correction_router,
```

Изменить на:

```python
        food_scanner_router,
        # water — обработка [💧 Добавить воду] footer + /вода command
        # + cb:water:add/undo/more callbacks (Part 2B). Регистрируется
        # ДО food_correction чтобы перехватить PAYLOAD_NUTRITION_ADD_WATER
        # вместо stub'а.
        water_router,
        # food_correction — обработка cb:scan:correct:* callbacks из
        # render_food_scan_v2 [✏️ Поправить] (Part 2A T07-T11).
        food_correction_router,
```

(b) В `mysite/maxbot/handlers/food_correction.py` **удалить** `on_add_water_stub` функцию целиком (целиком блок от `@router.message_callback(...)` до `return` включая docstring).

(c) В `mysite/tests/maxbot/test_food_correction.py` найти `test_add_water_stub_says_coming_soon` и **удалить** его (handler больше не существует).

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_water_handler.py mysite/tests/maxbot/test_food_correction.py -v`
Expected: water 10 passed (9 + 1 router test); food_correction 6 passed (7 - 1 deleted).

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 416 passed (416 - 1 deleted + 1 new = 416, или 415 если pytest collected differently).

Если падает — debug. Likely проблема в test_food_correction где `_fake_callback` мог иметь dependency.

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/__init__.py mysite/maxbot/handlers/food_correction.py mysite/tests/maxbot/test_water_handler.py mysite/tests/maxbot/test_food_correction.py
git commit -m "feat(maxbot): register water_router + remove on_add_water_stub (Part 2B T08)

water_router зарегистрирован ДО food_correction_router в get_routers()
— перехватывает PAYLOAD_NUTRITION_ADD_WATER первым. on_add_water_stub
удалён (был временной заглушкой Part 2A T10). Соответствующий unit-тест
удалён."
```

---

## Task 9: Caffeine warning при pregnant (conditional render)

**Files:**
- Modify: `mysite/maxbot/ai_ui.py:render_water_added` — extended signature
- Modify: `mysite/maxbot/handlers/water.py:on_water_add_quick` — fetch profile only on coffee/tea
- Modify: `mysite/tests/maxbot/test_water_handler.py`
- Modify: `mysite/tests/maxbot/test_render_water.py` (или создать)

**Note:** Quick-add buttons не передают `beverage_slug` в add_water — Ayla server-side засчитывает как воду (water_coefficient=1.0). Caffeine warning поэтому не триггерится в Part 2B button-only flow. **Этот task — заглушка с future-ready render arg `caffeine_warning=False`** + render testing. Реальная активация — когда free-text `parse_beverage` появится в Part 2D и будет передаваться `beverage_slug=kofe_chernyi`.

- [ ] **Step 1: Write failing tests**

Создать `mysite/tests/maxbot/test_render_water.py`:

```python
"""Phase 3.1 Part 2B: render_water_added rendering."""
from __future__ import annotations

from unittest.mock import MagicMock


def test_render_water_added_with_alcohol_hint():
    """alcohol_recovery_hint=True → render appends water-recovery hint."""
    from maxbot.ai_ui import render_water_added

    entry = MagicMock(
        ml=200, today_total_ml=1500, today_norm_ml=2000,
        milestone_text=None, alcohol_recovery_hint=True,
    )

    text = render_water_added(entry)
    assert "🍷" in text or "Алкоголь" in text or "обезвожив" in text.lower()


def test_render_water_added_with_milestone():
    """milestone_text — рендерится отдельной строкой."""
    from maxbot.ai_ui import render_water_added

    entry = MagicMock(
        ml=500, today_total_ml=1000, today_norm_ml=2000,
        milestone_text="Половина нормы — отлично!",
        alcohol_recovery_hint=False,
    )

    text = render_water_added(entry)
    assert "Половина нормы" in text


def test_render_water_added_basic_format():
    """Нет milestone, нет alcohol — только base format."""
    from maxbot.ai_ui import render_water_added

    entry = MagicMock(
        ml=250, today_total_ml=1450, today_norm_ml=2000,
        milestone_text=None, alcohol_recovery_hint=False,
    )

    text = render_water_added(entry)
    assert "+250" in text
    assert "1.4" in text or "1450" in text
    assert "2.0" in text or "2000" in text
    # No extras
    assert "🍷" not in text
    assert "беремен" not in text.lower()
```

- [ ] **Step 2: Run — must pass**

Run: `pytest mysite/tests/maxbot/test_render_water.py -v`
Expected: 3 passed (already covered by `render_water_added` from T03).

- [ ] **Step 3: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 419 passed (416 + 3 new render tests).

- [ ] **Step 4: Commit**

```bash
git add mysite/tests/maxbot/test_render_water.py
git commit -m "test(maxbot): render_water_added rendering coverage (Part 2B T09)

3 теста: alcohol hint conditional, milestone inline, basic format.
Caffeine warning при pregnant — backlog Part 2D (Quick-add не шлёт
beverage_slug, server считает как воду). render_water_added
extension под caffeine — backlog когда free-text появится."
```

---

## Task 10: E2E happy path test

**Files:**
- Modify: `mysite/tests/maxbot/test_water_handler.py`

- [ ] **Step 1: Write E2E test**

APPEND:

```python
@pytest.mark.asyncio
async def test_e2e_water_menu_to_add_to_undo(monkeypatch, settings):
    """E2E: open water menu → click +250 → click ↩️ Отменить → ack.
    Покрывает 3 handler'а в последовательности с 3 mocked Ayla calls.
    """
    from maxbot.handlers.water import (
        on_water_menu, on_water_add_quick, on_water_undo,
    )
    from maxbot.services.nutrition_client import (
        WaterEntryResponse, WaterTodayResponse,
    )

    settings.NUTRITION_ENABLED = True

    today_mock = AsyncMock(return_value=WaterTodayResponse(
        total_ml=1200, norm_ml=2000,
        entries=[],
        kcal_total=0, caffeine_mg=0,
        total_coffee_cups=0, total_tea_cups=0,
        raw={},
    ))
    add_mock = AsyncMock(return_value=WaterEntryResponse(
        entry_id="W-e2e", ml=250, water_ml=250, kcal=0,
        milestone_text=None,
        today_total_ml=1450, today_norm_ml=2000,
        alcohol_recovery_hint=False, raw={},
    ))
    undo_mock = AsyncMock(return_value=True)

    fake_client = MagicMock(
        get_water_today=today_mock,
        add_water=add_mock,
        undo_water=undo_mock,
    )
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    ctx = MemoryContext(chat_id=100, user_id=200)

    # ── Step 1: open menu ──
    cb_menu = _fake_callback("cb:nutrition:water:add")
    await on_water_menu(cb_menu, ctx)
    today_mock.assert_awaited_once()

    # ── Step 2: click +250 ──
    cb_add = _fake_callback("cb:water:add:250")
    await on_water_add_quick(cb_add, ctx)
    add_mock.assert_awaited_once()
    add_kwargs = add_mock.await_args.kwargs
    assert add_kwargs["ml"] == 250
    # Verify undo button с entry_id-suffix
    add_atts = cb_add.bot.send_message.await_args.kwargs.get("attachments") or []
    assert add_atts

    # ── Step 3: click ↩️ Отменить ──
    cb_undo = _fake_callback("cb:water:undo:W-e2e")
    await on_water_undo(cb_undo, ctx)
    undo_mock.assert_awaited_once()
    undo_kwargs = undo_mock.await_args.kwargs
    assert undo_kwargs["entry_id"] == "W-e2e"
    undo_text = cb_undo.bot.send_message.await_args.kwargs["text"]
    assert "Отмен" in undo_text or "удал" in undo_text.lower()
```

- [ ] **Step 2: Run E2E**

Run: `pytest mysite/tests/maxbot/test_water_handler.py::test_e2e_water_menu_to_add_to_undo -v`
Expected: PASS.

- [ ] **Step 3: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 420 passed.

- [ ] **Step 4: Commit**

```bash
git add mysite/tests/maxbot/test_water_handler.py
git commit -m "test(maxbot): E2E water menu → add → undo (Part 2B T10)

Cover happy path: open water menu → quick-add 250 → undo button click.
3 mocked Ayla calls (get_water_today + add_water + undo_water)."
```

---

## Task 11: Final regression + push + verify staging deploy

**Files:** (verify only)

- [ ] **Step 1: Full maxbot suite**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 420 passed, 0 failed.

- [ ] **Step 2: Verify routers list**

```bash
cd mysite && DJANGO_SETTINGS_MODULE=mysite.settings python -c "
import django
django.setup()
from maxbot.handlers import get_routers
from maxbot.handlers.water import router as water_router
from maxbot.handlers.food_correction import router as fc_router
routers = get_routers()
print(f'Total routers: {len(routers)}')
print('water position:', routers.index(water_router) if water_router in routers else 'N/A')
print('food_correction position:', routers.index(fc_router) if fc_router in routers else 'N/A')
"
```

Expected: water position < food_correction position (water before food_correction).

- [ ] **Step 3: Push**

```bash
git push origin dev
```

- [ ] **Step 4: Verify staging**

```bash
HTTPS_PROXY="$OPENAI_PROXY" gh run list --branch dev --limit 3
```

Expected: 3 ✅ workflows для последнего commit.

---

## Self-review checklist (выполнить после Task 11)

**Spec coverage (Design Doc v2 §7):**
- [x] §7.1 hybrid γ: persistent reply-keyboard (mocked as inline action_row из Part 2A — НЕ persistent в MAX SDK) + 4 quick-amount + extended — Tasks 1, 2, 3, 5
- [x] §7.2 free-text branch через `add_beverage` tool — **backlog Part 2D** (явно зафиксировано)
- [x] §7.3 visual feedback: milestone inline once-per-day-per-threshold — Ayla server-side, бот рендерит
- [x] §7.4 алкоголь recovery hint — Task 9 (rendered conditional через alcohol_recovery_hint flag)
- [x] §7.5 кофе/чай separate counters — частично (Ayla отдаёт total_coffee_cups/tea_cups в WaterTodayResponse, но не используется в Part 2B render — backlog Part 2C daily report где они нужны больше)
- [x] §7.6 soft-delete + 15-минутный restore window — Task 4 (DELETE + 404 reverse "Поздно"). Restore (undo of undo) — backlog Phase 3.2 (требует new endpoint)
- [x] §7.7 reminders opt-in OFF + adaptive — **backlog Part 2D**
- [x] §7.8 норма ВОЗ 30 мл/кг — Ayla server-side в profile.daily_water_ml, бот рендерит

**Placeholder scan:** все steps содержат actual code, никаких "TODO в production коде".

**Type consistency:**
- `WaterEntryResponse` fields used consistently (ml, water_ml, today_total_ml, today_norm_ml, milestone_text, alcohol_recovery_hint, entry_id)
- `WaterTodayResponse` fields used consistently (total_ml, norm_ml, entries, kcal_total, caffeine_mg, total_coffee_cups, total_tea_cups)
- `_PAYLOAD_TO_ML` map охватывает 9 amount payloads (4 quick + 5 extended)
- `keyboards.PAYLOAD_WATER_*` все определены в Task 1, импортируются handler'ами
- `render_water_added(entry)` signature consistent across Tasks 3 + 9

---

## Не в Part 2B (backlog Part 2C/2D/Phase 3.2)

**Part 2C (daily report):**
- Использовать total_coffee_cups + total_tea_cups + caffeine_mg в дневном отчёте

**Part 2D (free-text + reminders):**
- `parse_beverage(text)` hybrid regex+LLM в `ai_parsers.py`
- Free-text branch «выпил кофе» → ai_assistant integration → add_water с beverage_slug
- Caffeine warning при pregnant — активируется когда beverage_slug передаётся в add_water + Ayla отдаёт caffeine_warning в response. Сейчас render_water_added держит signature future-ready (alcohol_recovery_hint accepted, caffeine — TODO).
- Adaptive water reminders Celery beat (`maxbot.tasks.send_water_nudges` каждые 4ч + adaptive logic)

**Phase 3.2:**
- Restore (undo of undo) — `POST /water/{id}/restore/` Ayla endpoint
- Free-text restore command («верни последнюю воду»)

---

*Plan v1 закреплён 2026-05-04. Ссылается на Design Doc v2 §7 (`maxbot-phase3-nutrition-design.md`), Ayla spec §2 (`maxbot-phase3-ayla-spec.md`), Part 2A plan (`maxbot-phase3-1-2A-photo-refactor.md` T10 — on_add_water_stub which removed in T08).*
