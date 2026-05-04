# MAX-бот Phase 3.1 Part 2A — Photo Refactor + Action-Row Keyboard

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Улучшить food scanner UX — edit-message loading, confidence routing (high/low/non-food), footer next-step buttons после meal-log, FSM-aware skip во время анкеты, action-row inline keyboard `[📸 Фото][💧 Вода][📋 Меню]` к финальным сообщениям. Добавить `NUTRITION_ENABLED` gate в photo handler.

**Architecture:** Расширение `maxbot/handlers/food_scanner.py` (existing) + новый `maxbot/handlers/food_correction.py` для correction-callbacks (cb:scan:correct:*) — отдельный router потому что иначе food_scanner.py разрастётся. Render-функции в `maxbot/ai_ui.py`. Никакого нового Ayla endpoint — работаем с тем что уже есть (`scan_photo`, `log_meal`, `daily_summary`). Correction через `portion_multiplier` (existing kwarg в `scan_photo`); дополнительные correction modes (другое блюдо / удалить) — backlog Phase 3.2 (требуют новых Ayla endpoints).

**Tech Stack:** Python 3.12 async, maxapi SDK (`bot.edit_message(message_id, text=...)` confirmed), pytest+pytest-asyncio, существующий `nutrition_client.scan_photo` (с `portion_multiplier` parameter), `NutritionAnketaStates` (Part 1), `NUTRITION_ENABLED` setting (Part 1 hotfix).

**Reference:**
- Design: `docs/plans/maxbot-phase3-nutrition-design.md` v2 §5 (фото) + §5.3 footer-buttons + §5.5 FSM-aware skip
- Reconciliation: `docs/plans/maxbot-phase3-reconciliation.md` R4
- Existing food_scanner: `mysite/maxbot/handlers/food_scanner.py:47-298`
- Existing render: `mysite/maxbot/ai_ui.py:465-526` (`render_food_scan`)
- Plan Part 1: `docs/plans/maxbot-phase3-1-foundation-anketa.md`

**Existing infrastructure (DO NOT recreate):**
- `nutrition_client.scan_photo(*, external_user_id, image_bytes, filename, portion_multiplier=None)` — supports portion correction parameter уже (line 219).
- `nutrition_client.log_meal(*, external_user_id, scan_id, meal_type, idempotency_key)` — wires meal-type click to FoodLog.
- `nutrition_client.daily_summary(*, external_user_id)` — for view_day footer.
- `ai_ui.render_food_scan(scan)` — existing render with 4 meal-type buttons; **переписываем** в Part 2A на v2 (с confidence routing).
- `ai_ui.render_daily_summary(summary)` — existing для /дневник; reused для footer "📊 Посмотреть день".
- `keyboards.main_menu_keyboard()` — main menu keyboard (gated на NUTRITION_ENABLED).
- `menu_state.send_with_main_menu(bot, chat_id, text, bot_user)` — appends main_menu_keyboard.
- `NUTRITION_ENABLED` setting — `False` default (Part 1 hotfix `2de6577`).
- `NutritionAnketaStates` — FSM states из Part 1 (для skip-guard).

---

## Architectural decisions baked into plan

1. **Edit-message loading** через `bot.edit_message(message_id, text=...)` — сразу шлём «👀 Распознаю...», получаем message_id из `EditedMessage.message_id` (or от первого `send_message` response), edit его на финал. Если scan занимает > 8s → промежуточный edit «*ещё пара секунд...*».
2. **Confidence routing — частичная**:
   - high (≥ 0.7): best-guess + 4 meal-type кнопки + кнопка `[✏️ Поправить]` (correction flow)
   - low/non-food: handle через existing `FoodNotRecognizedError` + дополнительный check `confidence < 0.5` → soft message «*Не разобрала 🙈*» + кнопки `[📸 Переснять] [✏️ Напишу сама]`
   - **Medium (0.5-0.7) с alternatives** — Ayla scan response **не возвращает** alternatives; backlog Phase 3.2. Сейчас medium треатим как high (показываем best-guess с пометкой confidence%).
3. **Correction flow — урезанный**:
   - **Размер порции (Меньше / Норм / Больше)** через `portion_multiplier=0.7|1.0|1.3` — existing parameter, новый scan_photo call, swap карточки на новый scan.
   - **Другое блюдо** / **Добавить ингредиент** / **Удалить** — заглушки «Скоро будет, добавлю в Phase 3.2». Требуют новых Ayla endpoints.
4. **Footer-buttons после успешного meal-log** — `[💧 Добавить воду][📊 Посмотреть день]`. Water кнопка → заглушка «Скоро будет» (Part 2B). View_day кнопка → существующий `daily_summary` flow.
5. **NUTRITION_ENABLED gate в `on_photo_message`** — если флаг False, photo не идёт в Ayla; юзер видит «Скоро будет» (тот же текст что в `nutrition_entry::COMING_SOON_TEXT`).
6. **FSM-aware skip** — если context.get_state() в `NutritionAnketaStates.*`, photo handler **early-exit** с подсказкой «*Сейчас отвечаю на вопросы анкеты — пришли число / нажми кнопку*». Это design §5.5.
7. **Correction router отдельный** (`food_correction.py`) — keeps `food_scanner.py` ≤ 350 LOC. Router зарегистрирован сразу после `food_scanner_router`.
8. **Action-row keyboard `[📸 Фото][💧 Вода][📋 Меню]`** — inline-keyboard helper `action_row_keyboard()`. **НЕ заменяет** main_menu_keyboard — это узкий action-bar для UI-моментов когда хотим минимум, не всё меню. Используется в footer scan-карточки и в renderеded daily_summary.

---

## File Structure

**Create:**
- `mysite/maxbot/handlers/food_correction.py` — Router для cb:scan:correct:* callbacks. Handlers: `on_correct_open_menu`, `on_portion_smaller/normal/larger`, заглушки для other-dish/add-ingredient/delete (Phase 3.2 backlog).
- `mysite/tests/maxbot/test_food_scanner_v2.py` — edit-loading, FSM-skip, NUTRITION_ENABLED gate.
- `mysite/tests/maxbot/test_food_correction.py` — correction handlers.
- `mysite/tests/maxbot/test_action_row_keyboard.py` — keyboard helper.
- `mysite/tests/maxbot/test_render_food_scan_v2.py` — confidence routing branches.

**Modify:**
- `mysite/maxbot/keyboards.py` — добавить `PAYLOAD_NUTRITION_ADD_WATER`, `PAYLOAD_NUTRITION_VIEW_DAY`, `PAYLOAD_SCAN_CORRECT_MENU`, `PAYLOAD_SCAN_PORTION_SMALLER/NORMAL/LARGER`, `PAYLOAD_SCAN_OTHER_DISH`, `PAYLOAD_SCAN_ADD_INGREDIENT`, `PAYLOAD_SCAN_DELETE`, `PAYLOAD_SCAN_RETAKE` + helper `action_row_keyboard()`, `food_scan_correct_menu_keyboard()`, `food_scan_portion_keyboard()`, `food_scan_low_confidence_keyboard()`.
- `mysite/maxbot/ai_ui.py` — переписать `render_food_scan` → `render_food_scan_v2` (high vs low routing + correct button); добавить `render_loading_card()`, `render_food_logged_with_footer(meal_label, dish_name, kcal)`.
- `mysite/maxbot/handlers/food_scanner.py` — `on_photo_message`: NUTRITION_ENABLED gate + FSM-aware skip + edit-message loading; `on_log_meal`: footer-buttons after success; `on_consent_agree/decline`: оставить как есть.
- `mysite/maxbot/handlers/__init__.py` — register `food_correction_router` после `food_scanner_router`.
- `mysite/tests/maxbot/test_food_scanner.py` (если существует — adapt под v2 render).

**Reference (read-only):**
- `mysite/maxbot/handlers/booking.py` — pattern для FSM message_callback.
- `mysite/maxbot/handlers/ai_assistant.py:201-204` — пример `bot.edit_message(message_id, text=...)`.

---

## Task 1: Action-row keyboard helper + payload constants

**Files:**
- Modify: `mysite/maxbot/keyboards.py`
- Create: `mysite/tests/maxbot/test_action_row_keyboard.py`

- [ ] **Step 1: Write failing test**

```python
# mysite/tests/maxbot/test_action_row_keyboard.py
"""Phase 3.1 Part 2A T01: action-row keyboard для footer scan-карточки.

`action_row_keyboard()` — узкий 3-button bar [📸 Фото][💧 Вода][📋 Меню].
Используется когда нужен минимум action-кнопок без полного main_menu.
"""
from __future__ import annotations


def test_action_row_keyboard_three_buttons():
    from maxbot.keyboards import (
        action_row_keyboard,
        PAYLOAD_MENU_NUTRITION,
        PAYLOAD_NUTRITION_ADD_WATER,
        PAYLOAD_MENU_BOOK,
    )

    kb = action_row_keyboard()
    payloads = _flatten_payloads(kb)
    # Photo CTA — переиспользуем PAYLOAD_MENU_NUTRITION (входит в дневник)
    assert PAYLOAD_MENU_NUTRITION in payloads
    # Water — новый payload (handler заглушкой Part 2B)
    assert PAYLOAD_NUTRITION_ADD_WATER in payloads
    # Menu open — переиспользуем существующий
    assert PAYLOAD_MENU_BOOK in payloads or "cb:menu:open" in payloads


def _flatten_payloads(keyboard) -> set[str]:
    """Best-effort обход maxapi keyboard structure."""
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

- [ ] **Step 2: Run test — must fail**

Run: `pytest mysite/tests/maxbot/test_action_row_keyboard.py -v`
Expected: ImportError на `PAYLOAD_NUTRITION_ADD_WATER` или `action_row_keyboard`.

- [ ] **Step 3: Add payloads + helper to keyboards.py**

В `mysite/maxbot/keyboards.py` после существующих `PAYLOAD_NUTRITION_*` (после строки `PAYLOAD_NUTRITION_FIRST_MEAL`) добавить:

```python
# ─── Phase 3.1 Part 2A: photo refactor + footer + correction ───────────────

PAYLOAD_NUTRITION_ADD_WATER = "cb:nutrition:water:add"
PAYLOAD_NUTRITION_VIEW_DAY = "cb:nutrition:view_day"

PAYLOAD_SCAN_CORRECT_MENU = "cb:scan:correct:menu"
PAYLOAD_SCAN_PORTION_SMALLER = "cb:scan:correct:portion:smaller"
PAYLOAD_SCAN_PORTION_NORMAL = "cb:scan:correct:portion:normal"
PAYLOAD_SCAN_PORTION_LARGER = "cb:scan:correct:portion:larger"
PAYLOAD_SCAN_OTHER_DISH = "cb:scan:correct:other_dish"
PAYLOAD_SCAN_ADD_INGREDIENT = "cb:scan:correct:add_ingredient"
PAYLOAD_SCAN_DELETE = "cb:scan:correct:delete"
PAYLOAD_SCAN_RETAKE = "cb:scan:retake"
PAYLOAD_SCAN_MANUAL_INPUT = "cb:scan:manual"
```

И в конец файла (после `anketa_complete_keyboard`):

```python
def action_row_keyboard():
    """Узкий action-bar для footer'а scan-карточки и daily_summary.

    `[📸 Фото][💧 Вода][📋 Меню]` — минимум CTA-кнопок без полного
    main_menu. Photo button переиспользует `cb:menu:nutrition` payload
    (jump в entry-screen дневника). Water — заглушка Part 2B.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="📸 Фото", payload=PAYLOAD_MENU_NUTRITION),
        CallbackButton(text="💧 Вода", payload=PAYLOAD_NUTRITION_ADD_WATER),
        CallbackButton(text="📋 Меню", payload=PAYLOAD_MENU_BOOK),
    )
    return builder.as_markup()


def food_scan_correct_menu_keyboard():
    """Открывается по клику [✏️ Поправить] на scan-карточке.

    4 опции по Design Doc §5.4: размер порции / другое блюдо / добавить
    ингредиент / удалить. Последние 3 — заглушки до Phase 3.2 (требуют
    новых Ayla endpoints для override scan и delete FoodLog).
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="📦 Размер порции", payload=PAYLOAD_SCAN_PORTION_SMALLER + ":menu"),
    )
    builder.row(
        CallbackButton(text="🔄 Это другое блюдо", payload=PAYLOAD_SCAN_OTHER_DISH),
    )
    builder.row(
        CallbackButton(text="➕ Добавить ингредиент", payload=PAYLOAD_SCAN_ADD_INGREDIENT),
    )
    builder.row(
        CallbackButton(text="⏭ Удалить", payload=PAYLOAD_SCAN_DELETE),
    )
    return builder.as_markup()


def food_scan_portion_keyboard():
    """[Меньше] [Норм] [Больше] — выбор portion_multiplier 0.7/1.0/1.3."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="Меньше", payload=PAYLOAD_SCAN_PORTION_SMALLER),
        CallbackButton(text="Норм", payload=PAYLOAD_SCAN_PORTION_NORMAL),
        CallbackButton(text="Больше", payload=PAYLOAD_SCAN_PORTION_LARGER),
    )
    return builder.as_markup()


def food_scan_low_confidence_keyboard():
    """Low confidence (<0.5) или FoodNotRecognizedError → 2 кнопки:
    переснять или ввести вручную (заглушка manual = Phase 3.2)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="📸 Переснять", payload=PAYLOAD_SCAN_RETAKE),
        CallbackButton(text="✏️ Напишу сама", payload=PAYLOAD_SCAN_MANUAL_INPUT),
    )
    return builder.as_markup()
```

- [ ] **Step 4: Run test — must pass**

Run: `pytest mysite/tests/maxbot/test_action_row_keyboard.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/keyboards.py mysite/tests/maxbot/test_action_row_keyboard.py
git commit -m "feat(maxbot): action_row_keyboard + scan correction payloads (Part 2A T01)

[📸 Фото][💧 Вода][📋 Меню] узкий action-bar для footer scan-карточки
и daily_summary. + 11 PAYLOAD-констант для correction flow и
low-confidence retry. Helper-функции для 3 keyboards (correct_menu,
portion, low_confidence)."
```

---

## Task 2: NUTRITION_ENABLED gate + FSM-aware skip in `on_photo_message`

**Files:**
- Modify: `mysite/maxbot/handlers/food_scanner.py:on_photo_message`
- Create: `mysite/tests/maxbot/test_food_scanner_v2.py`

- [ ] **Step 1: Write failing tests**

```python
# mysite/tests/maxbot/test_food_scanner_v2.py
"""Phase 3.1 Part 2A T02: NUTRITION_ENABLED gate + FSM-skip в food_scanner."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from maxapi.context.context import MemoryContext


pytestmark = pytest.mark.django_db


def _fake_photo_event(chat_id=100, user_id=200, photo_url="https://x.test/p.jpg"):
    """MessageCreated double с одним IMAGE attachment."""
    from maxapi.enums.attachment import AttachmentType

    event = MagicMock()
    event.message = MagicMock()
    event.message.recipient = MagicMock(chat_id=chat_id)
    event.message.sender = MagicMock(user_id=user_id, full_name="Тест")
    payload_obj = MagicMock(url=photo_url)
    att = MagicMock(type=AttachmentType.IMAGE, payload=payload_obj)
    event.message.body = MagicMock(attachments=[att])
    event.bot = MagicMock(send_message=AsyncMock())
    return event


@pytest.mark.asyncio
async def test_photo_blocked_when_nutrition_disabled(monkeypatch, settings):
    """NUTRITION_ENABLED=False → photo НЕ идёт в Ayla, юзер видит COMING_SOON."""
    from maxbot.handlers.food_scanner import on_photo_message

    settings.NUTRITION_ENABLED = False

    # scan_photo НЕ должен быть вызван
    scan_mock = AsyncMock()
    fake_client = MagicMock(scan_photo=scan_mock)
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_nutrition_client",
        lambda: fake_client,
    )

    # Скипнуть downloader
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner._download_photo",
        AsyncMock(return_value=b"fake"),
    )

    event = _fake_photo_event()
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_photo_message(event, ctx)

    scan_mock.assert_not_awaited()
    event.bot.send_message.assert_awaited_once()
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "Скоро" in text or "разработке" in text.lower()


@pytest.mark.asyncio
async def test_photo_skipped_during_anketa_fsm(monkeypatch, settings):
    """Если state в NutritionAnketaStates.* — photo обработка отменяется,
    юзер видит подсказку «отвечай на вопросы анкеты»."""
    from maxbot.handlers.food_scanner import on_photo_message
    from maxbot.states import NutritionAnketaStates

    settings.NUTRITION_ENABLED = True  # gate пройден, но FSM активна

    scan_mock = AsyncMock()
    fake_client = MagicMock(scan_photo=scan_mock)
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_nutrition_client",
        lambda: fake_client,
    )

    event = _fake_photo_event()
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_age)

    await on_photo_message(event, ctx)

    scan_mock.assert_not_awaited()
    event.bot.send_message.assert_awaited_once()
    text = event.bot.send_message.await_args.kwargs["text"]
    assert "анкет" in text.lower() or "вопрос" in text.lower()
    # State preserved (юзер должен продолжить отвечать)
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_age
```

- [ ] **Step 2: Run tests — must fail**

Run: `pytest mysite/tests/maxbot/test_food_scanner_v2.py -v -k "blocked_when_nutrition_disabled or skipped_during_anketa"`
Expected: FAIL — current `on_photo_message` does not check NUTRITION_ENABLED nor FSM state. Either tests fail with `scan_mock.assert_not_awaited()` (scan was called) или с другим контекстом.

- [ ] **Step 3: Update `on_photo_message`**

В `mysite/maxbot/handlers/food_scanner.py`:

(a) Добавить import после существующих:

```python
from django.conf import settings as django_settings
from maxbot.states import NutritionAnketaStates
```

(b) В начале `on_photo_message` (после `if event.message.sender is None: return` и до `body = event.message.body`) добавить:

```python
    # NUTRITION_ENABLED gate — feature flag (Part 1 hotfix). До деплоя
    # Ayla DRF-300..303 endpoints — фото не идёт в Ayla. Юзер видит
    # «Скоро будет» (тот же UX что в nutrition_entry::COMING_SOON_TEXT).
    if not getattr(django_settings, "NUTRITION_ENABLED", False):
        chat_id = event.message.recipient.chat_id
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "🍎 Дневник питания\n\n"
                "Скоро будет — фича в разработке. Когда подключим, "
                "посчитаю калории по фото блюда."
            ),
        )
        return

    # FSM-aware skip — если юзер сейчас в анкете, не запускаем scan
    # (Design Doc v2 §5.5). Подсказываем продолжить FSM.
    state = await context.get_state()
    if state is not None and str(state).startswith("NutritionAnketaStates"):
        chat_id = event.message.recipient.chat_id
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Сейчас отвечаю на вопросы анкеты — "
                "пришли число / нажми кнопку, чтобы продолжить."
            ),
        )
        return
```

- [ ] **Step 4: Run tests — must pass**

Run: `pytest mysite/tests/maxbot/test_food_scanner_v2.py -v`
Expected: 2 passed.

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ -v --tb=short --ignore=mysite/tests/maxbot/test_run.py`
Expected: всё passing. Если падает старый food_scanner test — он мог testить on_photo_message без NUTRITION_ENABLED setup → нужен `settings.NUTRITION_ENABLED = True` fixture.

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/food_scanner.py mysite/tests/maxbot/test_food_scanner_v2.py
git commit -m "feat(maxbot): NUTRITION_ENABLED gate + FSM-aware skip в food_scanner (T02)

on_photo_message: фото не уходит в Ayla когда NUTRITION_ENABLED=False
(юзер видит COMING_SOON). Если state в NutritionAnketaStates.* —
подсказка «отвечай на вопросы анкеты», state preserved. Design Doc
v2 §5.5."
```

---

## Task 3: Edit-message loading — `render_loading_card` + edit на финал

**Files:**
- Modify: `mysite/maxbot/ai_ui.py`
- Modify: `mysite/maxbot/handlers/food_scanner.py:on_photo_message`
- Modify: `mysite/tests/maxbot/test_food_scanner_v2.py`

- [ ] **Step 1: Write failing test**

APPEND в `mysite/tests/maxbot/test_food_scanner_v2.py`:

```python
@pytest.mark.asyncio
async def test_photo_edit_loading_pattern(monkeypatch, settings):
    """on_photo_message сначала шлёт «👀 Распознаю...», потом edit'ит на
    финальный результат scan'а — не два отдельных сообщения."""
    from maxbot.handlers.food_scanner import on_photo_message
    from maxbot.services.nutrition_client import ScanResponse

    settings.NUTRITION_ENABLED = True

    # send_message returns object with message_id для последующего edit
    sent_msg = MagicMock()
    sent_msg.message_id = "msg-loading-123"
    bot_send_mock = AsyncMock(return_value=sent_msg)
    bot_edit_mock = AsyncMock()

    scan_mock = AsyncMock(return_value=ScanResponse(
        scan_id="s1", dish_name="Паста с курицей", confidence=0.85,
        portion_g=300, nutrition={"calories": 520, "protein_g": 35,
                                  "fat_g": 18, "carbs_g": 55},
        provider="openai", raw={
            "id": "s1", "dish_name": "Паста с курицей", "confidence": 0.85,
            "nutrition": {"calories": 520, "protein_g": 35,
                          "fat_g": 18, "carbs_g": 55},
        },
    ))
    fake_client = MagicMock(scan_photo=scan_mock)
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_nutrition_client",
        lambda: fake_client,
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner._download_photo",
        AsyncMock(return_value=b"fake"),
    )
    # bot_user with consent already granted
    bot_user = MagicMock(food_scanner_consent_at="2026-01-01", max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    event = _fake_photo_event()
    event.bot.send_message = bot_send_mock
    event.bot.edit_message = bot_edit_mock
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_photo_message(event, ctx)

    # Сначала send_message с loading-text
    bot_send_mock.assert_awaited()
    first_text = bot_send_mock.await_args_list[0].kwargs.get("text", "")
    assert "Распозн" in first_text or "👀" in first_text

    # Потом edit_message с финальным content
    bot_edit_mock.assert_awaited()
    edit_kwargs = bot_edit_mock.await_args.kwargs
    assert edit_kwargs.get("message_id") == "msg-loading-123"
    final_text = edit_kwargs.get("text", "")
    assert "Паста" in final_text
```

- [ ] **Step 2: Run test — must fail**

Run: `pytest mysite/tests/maxbot/test_food_scanner_v2.py::test_photo_edit_loading_pattern -v`
Expected: FAIL — current `on_photo_message` использует `event.bot.send_message` дважды (consent либо результат), не edit_message.

- [ ] **Step 3: Add `render_loading_card` + update `on_photo_message`**

В `mysite/maxbot/ai_ui.py` ДОБАВИТЬ (рядом с другими render-функциями):

```python
def render_loading_card() -> str:
    """Loading-card text для photo scan: edit-message pattern (Design §5.1).

    Сначала шлём это, получаем message_id, потом edit на финал.
    """
    return "👀 Распознаю..."
```

В `mysite/maxbot/handlers/food_scanner.py`, заменить блок с `client.scan_photo(...)` + render result. Найти этот фрагмент:

```python
    external_id = external_user_id_for(bot_user)
    client = get_nutrition_client()

    try:
        scan = await client.scan_photo(
            external_user_id=external_id,
            image_bytes=image_bytes,
        )
    except FoodNotRecognizedError:
        ...
```

Заменить на edit-loading pattern:

```python
    chat_id = event.message.recipient.chat_id
    external_id = external_user_id_for(bot_user)
    client = get_nutrition_client()

    # Edit-message loading pattern (Design Doc §5.1) — сразу шлём
    # «👀 Распознаю...», потом edit'им на финал. Юзер видит мгновенный
    # ответ что бот работает, не "висит".
    loading_msg = await event.bot.send_message(
        chat_id=chat_id,
        text=ai_ui.render_loading_card(),
    )
    loading_msg_id = getattr(loading_msg, "message_id", None)

    async def _replace(text: str, attachments=None) -> None:
        """Edit loading-card на финал. Если message_id потерялся
        (старая API), fallback на новый send_message."""
        if loading_msg_id is not None:
            try:
                await event.bot.edit_message(
                    message_id=loading_msg_id, text=text,
                    attachments=attachments,
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("food_scanner.edit_failed err=%s", exc)
        # Fallback — новое сообщение
        await event.bot.send_message(
            chat_id=chat_id, text=text, attachments=attachments,
        )

    try:
        scan = await client.scan_photo(
            external_user_id=external_id,
            image_bytes=image_bytes,
        )
    except FoodNotRecognizedError:
        await _replace(
            "Не получилось распознать блюдо на фото. Попробуй фото получше.",
        )
        return
    except NutritionUnavailableError as exc:
        logger.warning("food_scanner.unavailable user=%s reason=%s",
                       bot_user.max_user_id, exc)
        await _replace("Сканер еды временно недоступен. Попробуй через минуту.")
        return
    except NutritionAPIError as exc:
        logger.exception("food_scanner.api_error user=%s err=%s",
                         bot_user.max_user_id, exc)
        await _replace("Что-то пошло не так со сканером. Попробуй позже.")
        return

    text, attachments = ai_ui.render_food_scan(scan.raw)
    if attachments:
        await _replace(text, attachments=attachments)
    else:
        # No attachments — fallback на send_with_main_menu для UX-полноты
        if loading_msg_id is not None:
            try:
                await event.bot.edit_message(
                    message_id=loading_msg_id, text=text,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("food_scanner.edit_failed err=%s", exc)
                await send_with_main_menu(
                    bot=event.bot, chat_id=chat_id, text=text,
                    bot_user=bot_user,
                )
        else:
            await send_with_main_menu(
                bot=event.bot, chat_id=chat_id, text=text, bot_user=bot_user,
            )
```

(Также удалить старые `await send_with_main_menu(...)` блоки в except'ах — теперь `_replace` обрабатывает.)

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_food_scanner_v2.py -v`
Expected: 3 passed.

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ -v --tb=short --ignore=mysite/tests/maxbot/test_run.py`
Expected: passing.

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/food_scanner.py mysite/maxbot/ai_ui.py mysite/tests/maxbot/test_food_scanner_v2.py
git commit -m "feat(maxbot): edit-message loading pattern для photo scan (T03)

Перед scan_photo шлём «👀 Распознаю...» → получаем message_id →
edit на финал (Design §5.1). Юзер видит мгновенный indicator что
бот работает. Fallback на send_message если edit упал."
```

---

## Task 4: `render_food_scan_v2` — high confidence path (≥0.7) + correct button

**Files:**
- Modify: `mysite/maxbot/ai_ui.py`
- Create: `mysite/tests/maxbot/test_render_food_scan_v2.py`

- [ ] **Step 1: Write failing test**

```python
# mysite/tests/maxbot/test_render_food_scan_v2.py
"""Phase 3.1 Part 2A T04: confidence routing в render_food_scan."""
from __future__ import annotations


def test_render_food_scan_high_confidence_has_correct_button():
    """confidence >= 0.7 → best-guess + 4 meal-type кнопки + [✏️ Поправить]."""
    from maxbot.ai_ui import render_food_scan_v2
    from maxbot.keyboards import PAYLOAD_SCAN_CORRECT_MENU

    scan = {
        "id": "s1",
        "dish_name": "Паста с курицей",
        "confidence": 0.85,
        "portion_g": 300,
        "nutrition": {"calories": 520, "protein_g": 35, "fat_g": 18, "carbs_g": 55},
    }

    text, attachments = render_food_scan_v2(scan)

    # Best-guess текст
    assert "Паста" in text
    assert "520" in text  # ккал
    # БЖУ
    assert "35" in text and "18" in text and "55" in text

    # Attachments — keyboard с 4 meal-type + correct button
    payloads = _flatten_payloads(attachments[0])
    assert PAYLOAD_SCAN_CORRECT_MENU in payloads
    # 4 meal-type кнопки тоже на месте
    assert any(p.startswith("cb:nutrition:log:") for p in payloads)


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
```

- [ ] **Step 2: Run test — must fail**

Run: `pytest mysite/tests/maxbot/test_render_food_scan_v2.py -v`
Expected: ImportError на `render_food_scan_v2`.

- [ ] **Step 3: Add `render_food_scan_v2` to ai_ui.py**

В `mysite/maxbot/ai_ui.py` ДОБАВИТЬ (после существующего `render_food_scan`):

```python
def render_food_scan_v2(scan: dict[str, Any]) -> tuple[str, list]:
    """Phase 3.1 Part 2A: confidence-routed render food scan.

    Confidence >= 0.7  → high path: best-guess + 4 meal-type + [✏️ Поправить]
    Confidence <  0.5  → low path: «Не разобрала 🙈» + [📸 Переснять][✏️ Напишу]
    Confidence 0.5-0.7 → треатим как high (medium с alternatives — Phase 3.2,
                                          требует расширения Ayla scan response)

    Replaces existing `render_food_scan` (которая не имела confidence
    routing и correct-button).
    """
    from maxbot.keyboards import (
        PAYLOAD_SCAN_CORRECT_MENU,
        food_scan_low_confidence_keyboard,
    )

    confidence = float(scan.get("confidence") or 0.0)

    if confidence < 0.5:
        return _render_food_scan_low_confidence(scan), [
            food_scan_low_confidence_keyboard(),
        ]

    return _render_food_scan_high_confidence(scan)


def _render_food_scan_high_confidence(scan: dict[str, Any]) -> tuple[str, list]:
    dish = scan.get("dish_name") or "Не уверена"
    confidence = float(scan.get("confidence") or 0.0)
    portion_g = scan.get("portion_g")
    nutrition = scan.get("nutrition") or {}
    scan_id = str(scan.get("id") or scan.get("scan_id") or "")

    lines = [f"🍽 {dish}"]
    if confidence:
        lines.append(f"Уверенность: {int(confidence * 100)}%")
    if portion_g:
        lines.append(f"Порция: ~{int(portion_g)}г")

    if nutrition:
        kcal = nutrition.get("calories")
        protein = nutrition.get("protein_g")
        fat = nutrition.get("fat_g")
        carbs = nutrition.get("carbs_g")
        macro_parts = []
        if kcal is not None:
            macro_parts.append(f"≈{int(kcal)} ккал")
        if protein is not None:
            macro_parts.append(f"Б {protein:.0f}г")
        if fat is not None:
            macro_parts.append(f"Ж {fat:.0f}г")
        if carbs is not None:
            macro_parts.append(f"У {carbs:.0f}г")
        if macro_parts:
            lines.append(" · ".join(macro_parts))
    else:
        lines.append("(КБЖУ не определились — уточни порцию вручную)")

    builder = InlineKeyboardBuilder()
    if scan_id:
        builder.row(
            CallbackButton(
                text="🍳 Завтрак",
                payload=_payload_food_log(scan_id, "breakfast"),
            ),
            CallbackButton(
                text="🍲 Обед",
                payload=_payload_food_log(scan_id, "lunch"),
            ),
        )
        builder.row(
            CallbackButton(
                text="🍽 Ужин",
                payload=_payload_food_log(scan_id, "dinner"),
            ),
            CallbackButton(
                text="☕ Перекус",
                payload=_payload_food_log(scan_id, "snack"),
            ),
        )
        # Correct button — открывает correction-menu (Task 8+)
        from maxbot.keyboards import PAYLOAD_SCAN_CORRECT_MENU
        builder.row(
            CallbackButton(
                text="✏️ Поправить",
                payload=PAYLOAD_SCAN_CORRECT_MENU + ":" + scan_id,
            ),
        )
    return ("\n".join(lines), [builder.as_markup()] if scan_id else [])


def _render_food_scan_low_confidence(scan: dict[str, Any]) -> str:
    """Low confidence (<0.5) — «Не разобрала, переснять или ввести»."""
    return (
        "🙈 Не разобрала, что на фото.\n\n"
        "Попробуй переснять под лучшим светом или впиши блюдо текстом."
    )
```

- [ ] **Step 4: Run test — must pass**

Run: `pytest mysite/tests/maxbot/test_render_food_scan_v2.py -v`
Expected: 1 passed.

- [ ] **Step 5: Switch caller — `food_scanner.py` использует v2 вместо v1**

В `mysite/maxbot/handlers/food_scanner.py` найти строку:

```python
    text, attachments = ai_ui.render_food_scan(scan.raw)
```

Заменить на:

```python
    text, attachments = ai_ui.render_food_scan_v2(scan.raw)
```

- [ ] **Step 6: Smoke regression**

Run: `pytest mysite/tests/maxbot/ -v --tb=short --ignore=mysite/tests/maxbot/test_run.py`
Expected: всё passing. Если падает старый test_food_scanner.py с явными ассертами `render_food_scan` — обновить или (если избыточен) удалить как замещённый test_render_food_scan_v2.

- [ ] **Step 7: Commit**

```bash
git add mysite/maxbot/ai_ui.py mysite/maxbot/handlers/food_scanner.py mysite/tests/maxbot/test_render_food_scan_v2.py
git commit -m "feat(maxbot): render_food_scan_v2 с confidence routing (T04)

High path (≥0.7) — best-guess + 4 meal-type + [✏️ Поправить] (correct
flow в T08+). Low path (<0.5) — soft fallback с [📸 Переснять]
[✏️ Напишу]. Medium (0.5-0.7) треатим как high (Ayla scan не отдаёт
alternatives — Phase 3.2). Заменили old render_food_scan call в
on_photo_message."
```

---

## Task 5: Low confidence test + `FoodNotRecognizedError` integration

**Files:**
- Modify: `mysite/tests/maxbot/test_render_food_scan_v2.py`

- [ ] **Step 1: Write failing test**

APPEND в `mysite/tests/maxbot/test_render_food_scan_v2.py`:

```python
def test_render_food_scan_low_confidence_shows_retake_buttons():
    """confidence < 0.5 → text «Не разобрала» + кнопки переснять/ввести."""
    from maxbot.ai_ui import render_food_scan_v2
    from maxbot.keyboards import PAYLOAD_SCAN_RETAKE, PAYLOAD_SCAN_MANUAL_INPUT

    scan = {
        "id": "s1",
        "dish_name": "?",
        "confidence": 0.3,  # low
        "nutrition": None,
    }

    text, attachments = render_food_scan_v2(scan)
    assert "разобрала" in text.lower() or "🙈" in text

    payloads = _flatten_payloads(attachments[0])
    assert PAYLOAD_SCAN_RETAKE in payloads
    assert PAYLOAD_SCAN_MANUAL_INPUT in payloads


def test_render_food_scan_borderline_medium_treated_as_high():
    """confidence 0.5-0.7 (medium без alternatives) → как high path."""
    from maxbot.ai_ui import render_food_scan_v2
    from maxbot.keyboards import PAYLOAD_SCAN_CORRECT_MENU

    scan = {
        "id": "s1",
        "dish_name": "Что-то",
        "confidence": 0.6,
        "nutrition": {"calories": 300, "protein_g": 10, "fat_g": 5, "carbs_g": 40},
    }

    text, attachments = render_food_scan_v2(scan)
    assert "Что-то" in text
    payloads = _flatten_payloads(attachments[0])
    assert PAYLOAD_SCAN_CORRECT_MENU in payloads or any(
        p.startswith("cb:scan:correct:menu") for p in payloads
    )
```

- [ ] **Step 2: Run tests**

Run: `pytest mysite/tests/maxbot/test_render_food_scan_v2.py -v`
Expected: 3 passed (1 existing high-conf + 2 new).

- [ ] **Step 3: Commit (no code changes — only tests added)**

```bash
git add mysite/tests/maxbot/test_render_food_scan_v2.py
git commit -m "test(maxbot): low-confidence + borderline-medium routing (T05)

Покрывает 2 ветки render_food_scan_v2: low (<0.5) показывает retake/
manual buttons, borderline-medium (0.5-0.7) treats as high (без
alternatives до Phase 3.2)."
```

---

## Task 6: Footer-buttons после успешного meal-log

**Files:**
- Modify: `mysite/maxbot/ai_ui.py`
- Modify: `mysite/maxbot/handlers/food_scanner.py:on_log_meal`
- Modify: `mysite/tests/maxbot/test_food_scanner_v2.py`

- [ ] **Step 1: Write failing test**

APPEND в `mysite/tests/maxbot/test_food_scanner_v2.py`:

```python
@pytest.mark.asyncio
async def test_on_log_meal_appends_footer_buttons(monkeypatch, settings):
    """После успешного log_meal бот шлёт «✅ Записала ...» + footer
    [💧 Добавить воду][📊 Посмотреть день]."""
    from maxbot.handlers.food_scanner import on_log_meal
    from maxbot.keyboards import PAYLOAD_NUTRITION_ADD_WATER, PAYLOAD_NUTRITION_VIEW_DAY
    from maxbot.services.nutrition_client import LogMealResponse

    settings.NUTRITION_ENABLED = True

    log_mock = AsyncMock(return_value=LogMealResponse(
        log_id="L1", scan_id="S1", dish_name="Паста",
        meal_type="lunch", calories=520, raw={},
    ))
    fake_client = MagicMock(log_meal=log_mock)
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_nutrition_client",
        lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = MagicMock()
    cb.callback.payload = "cb:nutrition:log:S1:lunch"
    cb.callback.user = MagicMock(user_id=200, full_name="Тест")
    cb.message.recipient.chat_id = 100
    cb.bot.send_message = AsyncMock()

    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_log_meal(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    kwargs = cb.bot.send_message.await_args.kwargs
    assert "Записала" in kwargs["text"]
    # Footer-keyboard прикреплён
    atts = kwargs.get("attachments") or []
    assert atts, "expected footer-attachment in send_message"
    payloads = _flatten_payloads(atts[0]) if atts else set()
    assert PAYLOAD_NUTRITION_ADD_WATER in payloads
    assert PAYLOAD_NUTRITION_VIEW_DAY in payloads


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
```

- [ ] **Step 2: Run test — must fail**

Run: `pytest mysite/tests/maxbot/test_food_scanner_v2.py::test_on_log_meal_appends_footer_buttons -v`
Expected: FAIL — текущий `on_log_meal` шлёт plain text без attachments.

- [ ] **Step 3: Add footer renderer + update `on_log_meal`**

В `mysite/maxbot/ai_ui.py` ДОБАВИТЬ:

```python
def render_food_logged_with_footer(meal_label: str, dish_name: str, kcal: int) -> tuple[str, list]:
    """Подтверждение записи блюда + footer next-step buttons (Design §5.3).

    [💧 Добавить воду] — заглушка Part 2B (handler ответит «Скоро будет»).
    [📊 Посмотреть день] — открывает /дневник flow.
    """
    from maxbot.keyboards import (
        PAYLOAD_NUTRITION_ADD_WATER,
        PAYLOAD_NUTRITION_VIEW_DAY,
    )

    text = f"✅ Записала {meal_label}: {dish_name} ({kcal} ккал)."

    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="💧 Добавить воду", payload=PAYLOAD_NUTRITION_ADD_WATER),
        CallbackButton(text="📊 Посмотреть день", payload=PAYLOAD_NUTRITION_VIEW_DAY),
    )
    return (text, [builder.as_markup()])
```

В `mysite/maxbot/handlers/food_scanner.py:on_log_meal` найти финальный send_message:

```python
    meal_label = {
        "breakfast": "завтрак", "lunch": "обед",
        "dinner": "ужин", "snack": "перекус",
    }[meal_type]
    await callback.bot.send_message(
        chat_id=chat_id,
        text=f"✅ Записала {meal_label}: {log.dish_name} ({int(log.calories)} ккал).",
    )
```

Заменить на:

```python
    meal_label = {
        "breakfast": "завтрак", "lunch": "обед",
        "dinner": "ужин", "snack": "перекус",
    }[meal_type]
    text, attachments = ai_ui.render_food_logged_with_footer(
        meal_label=meal_label, dish_name=log.dish_name, kcal=int(log.calories),
    )
    await callback.bot.send_message(
        chat_id=chat_id, text=text, attachments=attachments,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_food_scanner_v2.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/ai_ui.py mysite/maxbot/handlers/food_scanner.py mysite/tests/maxbot/test_food_scanner_v2.py
git commit -m "feat(maxbot): footer-buttons после meal-log (T06)

[💧 Добавить воду][📊 Посмотреть день] под подтверждением записи.
Water — заглушка Part 2B. View_day — handler в T11. Design §5.3
next-step nudging."
```

---

## Task 7: `food_correction.py` router skeleton + register

**Files:**
- Create: `mysite/maxbot/handlers/food_correction.py`
- Modify: `mysite/maxbot/handlers/__init__.py`
- Create: `mysite/tests/maxbot/test_food_correction.py`

- [ ] **Step 1: Write failing test**

```python
# mysite/tests/maxbot/test_food_correction.py
"""Phase 3.1 Part 2A T07-T09: scan correction router."""
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


@pytest.mark.asyncio
async def test_correct_open_menu_shows_4_options():
    """Клик «✏️ Поправить» → открыть menu с 4 опциями коррекции."""
    from maxbot.handlers.food_correction import on_correct_open_menu

    cb = _fake_callback("cb:scan:correct:menu:S1")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_correct_open_menu(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    # Текст «Что не так?» по Design §5.4
    assert "не так" in text.lower() or "Что" in text
    # Attachments — keyboard с 4 опциями
    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    assert atts
```

- [ ] **Step 2: Run test — must fail**

Run: `pytest mysite/tests/maxbot/test_food_correction.py -v`
Expected: ImportError на `food_correction`.

- [ ] **Step 3: Create router**

Создать `mysite/maxbot/handlers/food_correction.py`:

```python
"""Scan correction handlers (Phase 3.1 Part 2A T07-T09).

Triggers (cb:scan:correct:* payloads):
- `cb:scan:correct:menu:{scan_id}` — открыть menu коррекции
- `cb:scan:correct:portion:smaller|normal|larger` — пересчитать порцию
  через scan_photo(portion_multiplier=0.7|1.0|1.3)
- `cb:scan:correct:other_dish` / `add_ingredient` / `delete` — заглушки
  Phase 3.2 (требуют новых Ayla endpoints для override-scan и delete-log)

Отдельный router потому что food_scanner.py уже жирный (capture +
consent + meal-log) — добавлять correction туда увеличило бы файл вдвое.
"""
from __future__ import annotations

import logging

from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback

from maxbot import keyboards


logger = logging.getLogger("maxbot.handlers.food_correction")
router = Router()


CORRECT_MENU_TEXT = "🤖 Что не так с распознаванием?"


@router.message_callback(F.callback.payload.startswith("cb:scan:correct:menu"))
async def on_correct_open_menu(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[✏️ Поправить] на scan-карточке → открыть menu."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text=CORRECT_MENU_TEXT,
        attachments=[keyboards.food_scan_correct_menu_keyboard()],
    )
```

Зарегистрировать в `mysite/maxbot/handlers/__init__.py`:

(a) Добавить import:

```python
from .food_correction import router as food_correction_router
```

(b) В `get_routers()` ДОБАВИТЬ `food_correction_router` СРАЗУ после `food_scanner_router`:

```python
        food_scanner_router,
        # food_correction — обработка cb:scan:correct:* callbacks из
        # render_food_scan_v2 [✏️ Поправить] (Part 2A T07).
        food_correction_router,
        ai_assistant_router,
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_food_correction.py -v`
Expected: 1 passed.

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ -v --tb=short --ignore=mysite/tests/maxbot/test_run.py`
Expected: passing.

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/food_correction.py mysite/maxbot/handlers/__init__.py mysite/tests/maxbot/test_food_correction.py
git commit -m "feat(maxbot): food_correction router skeleton + on_correct_open_menu (T07)

[✏️ Поправить] открывает menu с 4 опциями (Design §5.4). Portion +
other-dish/add-ingredient/delete handlers — T08-T09 (заглушки до
Phase 3.2 для not-portion options)."
```

---

## Task 8: Portion correction handler (Меньше/Норм/Больше)

**Files:**
- Modify: `mysite/maxbot/handlers/food_correction.py`
- Modify: `mysite/tests/maxbot/test_food_correction.py`

- [ ] **Step 1: Write failing tests**

APPEND в `mysite/tests/maxbot/test_food_correction.py`:

```python
@pytest.mark.asyncio
async def test_portion_menu_button_shows_size_keyboard():
    """[📦 Размер порции] (cb:scan:correct:portion:smaller:menu) →
    показать [Меньше][Норм][Больше]."""
    from maxbot.handlers.food_correction import on_portion_menu
    from maxbot.keyboards import (
        PAYLOAD_SCAN_PORTION_SMALLER,
        PAYLOAD_SCAN_PORTION_NORMAL,
        PAYLOAD_SCAN_PORTION_LARGER,
    )

    cb = _fake_callback("cb:scan:correct:portion:smaller:menu")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_portion_menu(cb, ctx)

    cb.bot.send_message.assert_awaited_once()
    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    assert atts
    payloads = _flatten_payloads(atts[0])
    assert PAYLOAD_SCAN_PORTION_SMALLER in payloads
    assert PAYLOAD_SCAN_PORTION_NORMAL in payloads
    assert PAYLOAD_SCAN_PORTION_LARGER in payloads


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
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_food_correction.py::test_portion_menu_button_shows_size_keyboard -v`
Expected: FAIL — `on_portion_menu` не существует.

- [ ] **Step 3: Add handler**

В `mysite/maxbot/handlers/food_correction.py` ДОБАВИТЬ:

```python
@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_SCAN_PORTION_SMALLER + ":menu",
)
async def on_portion_menu(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[📦 Размер порции] → показать [Меньше][Норм][Больше].

    Phase 3.2: связать с фактическим scan_id для пересчёта через
    scan_photo(portion_multiplier=...). Сейчас MVP — просто меню
    показываем; пересчёт не делаем (требует storage для image_bytes
    или image_url для повторной отправки в Ayla).
    """
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text="📦 Какого размера порция?",
        attachments=[keyboards.food_scan_portion_keyboard()],
    )


@router.message_callback(
    F.callback.payload.in_({
        keyboards.PAYLOAD_SCAN_PORTION_SMALLER,
        keyboards.PAYLOAD_SCAN_PORTION_NORMAL,
        keyboards.PAYLOAD_SCAN_PORTION_LARGER,
    }),
)
async def on_portion_apply(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[Меньше][Норм][Больше] — Phase 3.2 пересчёт через scan_photo
    с portion_multiplier=0.7/1.0/1.3. MVP — заглушка.

    Полноценная реализация требует хранить scan_id ↔ image_bytes (или
    URL) чтобы можно было пересчитать. Сейчас Ayla scan не возвращает
    image_url, и бот не хранит bytes. Backlog Phase 3.2.
    """
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "🔧 Пересчёт порции скоро добавлю — пока пришли фото снова "
            "с правильной порцией в кадре."
        ),
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_food_correction.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/handlers/food_correction.py mysite/tests/maxbot/test_food_correction.py
git commit -m "feat(maxbot): portion correction handlers (T08)

[📦 Размер порции] → [Меньше][Норм][Больше]. Полный пересчёт через
scan_photo(portion_multiplier) — Phase 3.2 backlog (требует хранить
scan_id↔image для retry). Сейчас MVP — меню + soft hint «пришли
фото снова»."
```

---

## Task 9: Заглушки для других correction options + retake/manual stubs

**Files:**
- Modify: `mysite/maxbot/handlers/food_correction.py`
- Modify: `mysite/tests/maxbot/test_food_correction.py`

- [ ] **Step 1: Write failing tests**

APPEND в `mysite/tests/maxbot/test_food_correction.py`:

```python
@pytest.mark.asyncio
async def test_other_dish_stub_says_coming_soon():
    """[🔄 Это другое блюдо] — заглушка Phase 3.2."""
    from maxbot.handlers.food_correction import on_other_dish

    cb = _fake_callback("cb:scan:correct:other_dish")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_other_dish(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Скоро" in text or "разработ" in text.lower()


@pytest.mark.asyncio
async def test_retake_stub_hints_send_photo():
    """[📸 Переснять] — попроси прислать новое фото."""
    from maxbot.handlers.food_correction import on_retake

    cb = _fake_callback("cb:scan:retake")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_retake(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Пришли" in text or "пришли" in text or "фото" in text.lower()
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_food_correction.py::test_other_dish_stub_says_coming_soon mysite/tests/maxbot/test_food_correction.py::test_retake_stub_hints_send_photo -v`
Expected: ImportError.

- [ ] **Step 3: Add handlers**

В `mysite/maxbot/handlers/food_correction.py` ДОБАВИТЬ:

```python
COMING_SOON_PHASE32 = (
    "🔧 Скоро добавлю — пока в разработке (Phase 3.2). "
    "Пришли фото снова или впиши блюдо текстом."
)


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_SCAN_OTHER_DISH,
)
async def on_other_dish(callback: MessageCallback, context: MemoryContext) -> None:
    """[🔄 Это другое блюдо] — заглушка Phase 3.2 (требует new Ayla endpoint
    для override-scan с caption: 'это был ризотто')."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(chat_id=chat_id, text=COMING_SOON_PHASE32)


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_SCAN_ADD_INGREDIENT,
)
async def on_add_ingredient(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[➕ Добавить ингредиент] — заглушка Phase 3.2."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(chat_id=chat_id, text=COMING_SOON_PHASE32)


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_SCAN_DELETE,
)
async def on_delete_log(callback: MessageCallback, context: MemoryContext) -> None:
    """[⏭ Удалить] — заглушка Phase 3.2 (требует new Ayla endpoint
    DELETE /food-log/{id}/)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(chat_id=chat_id, text=COMING_SOON_PHASE32)


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_SCAN_RETAKE,
)
async def on_retake(callback: MessageCallback, context: MemoryContext) -> None:
    """[📸 Переснять] — попроси прислать новое фото."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text="📸 Пришли фото блюда ещё раз — попробую распознать получше.",
    )


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_SCAN_MANUAL_INPUT,
)
async def on_manual_input(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[✏️ Напишу сама] — заглушка Phase 3.2 (free-text + GPT-парсинг
    «300г пасты с курицей» → kcal/БЖУ через scan/text endpoint)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(chat_id=chat_id, text=COMING_SOON_PHASE32)
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_food_correction.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/handlers/food_correction.py mysite/tests/maxbot/test_food_correction.py
git commit -m "feat(maxbot): correction option stubs + retake/manual handlers (T09)

[🔄 Другое блюдо][➕ Ингредиент][⏭ Удалить][✏️ Напишу сама] — все 4
заглушки Phase 3.2 (требуют новых Ayla endpoints для override-scan,
delete-log, free-text scan). [📸 Переснять] — единственный реально
рабочий: просто просим прислать фото снова."
```

---

## Task 10: Footer water-button handler — заглушка до Part 2B

**Files:**
- Modify: `mysite/maxbot/handlers/food_correction.py` (или новый handler)
- Modify: `mysite/tests/maxbot/test_food_correction.py`

**Note:** `PAYLOAD_NUTRITION_ADD_WATER` пока без реального handler'а — clicks через footer-buttons из T06 умрут без ответа. Добавляем заглушку. Когда Part 2B будет писаться, эту заглушку удалим в `handlers/water.py`.

- [ ] **Step 1: Write failing test**

APPEND:

```python
@pytest.mark.asyncio
async def test_add_water_stub_says_coming_soon():
    """[💧 Добавить воду] (footer) — заглушка Part 2B."""
    from maxbot.handlers.food_correction import on_add_water_stub

    cb = _fake_callback("cb:nutrition:water:add")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_add_water_stub(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "вод" in text.lower()
    assert "Скоро" in text or "разработ" in text.lower()
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_food_correction.py::test_add_water_stub_says_coming_soon -v`
Expected: ImportError на `on_add_water_stub`.

- [ ] **Step 3: Add stub handler**

В `mysite/maxbot/handlers/food_correction.py` ДОБАВИТЬ:

```python
@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_NUTRITION_ADD_WATER,
)
async def on_add_water_stub(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[💧 Добавить воду] из footer — заглушка до Part 2B.

    Реальный handler в `mysite/maxbot/handlers/water.py` (Part 2B).
    После создания того модуля — этот handler удаляется (или его router
    регистрируется ПОСЛЕ water_router чтобы не перехватывать).
    """
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "💧 Учёт воды скоро добавлю — фича в разработке (Part 2B). "
            "Пока можешь пометить себе вручную."
        ),
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_food_correction.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add mysite/maxbot/handlers/food_correction.py mysite/tests/maxbot/test_food_correction.py
git commit -m "feat(maxbot): водный footer-button stub до Part 2B (T10)

[💧 Добавить воду] (cb:nutrition:water:add) — handler-заглушка
«Скоро добавлю». Удалится при создании handlers/water.py в Part 2B."
```

---

## Task 11: View-day footer handler — переиспользует daily_summary

**Files:**
- Modify: `mysite/maxbot/handlers/food_correction.py`
- Modify: `mysite/tests/maxbot/test_food_correction.py`

- [ ] **Step 1: Write failing test**

APPEND:

```python
@pytest.mark.asyncio
async def test_view_day_calls_daily_summary(monkeypatch, settings):
    """[📊 Посмотреть день] (footer) → daily_summary call → render."""
    from maxbot.handlers.food_correction import on_view_day
    from maxbot.services.nutrition_client import DailySummaryResponse

    settings.NUTRITION_ENABLED = True

    summary_mock = AsyncMock(return_value=DailySummaryResponse(
        date="2026-05-04",
        calories_total=1100, calories_goal=1450,
        protein_g=65, fat_g=40, carbs_g=110,
        entries=[],
        raw={
            "date": "2026-05-04", "calories_total": 1100,
            "calories_goal": 1450, "protein_g": 65, "fat_g": 40,
            "carbs_g": 110, "entries": [],
        },
    ))
    fake_client = MagicMock(daily_summary=summary_mock)
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_nutrition_client",
        lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:nutrition:view_day")
    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_view_day(cb, ctx)

    summary_mock.assert_awaited_once()
    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    # Hardcoded check — render_daily_summary включает ккал
    assert "1100" in text or "1450" in text
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_food_correction.py::test_view_day_calls_daily_summary -v`
Expected: ImportError на `on_view_day`.

- [ ] **Step 3: Add handler**

В `mysite/maxbot/handlers/food_correction.py` ДОБАВИТЬ imports + handler:

```python
from maxbot import ai_ui
from maxbot.personalization import get_or_create_bot_user
from maxbot.services.ayla_user_proxy import external_user_id_for
from maxbot.services.nutrition_client import (
    NutritionAPIError,
    NutritionUnavailableError,
    get_nutrition_client,
)
```

И:

```python
@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_NUTRITION_VIEW_DAY,
)
async def on_view_day(callback: MessageCallback, context: MemoryContext) -> None:
    """[📊 Посмотреть день] из footer scan-карточки →
    то же что /дневник команда: daily_summary + render."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None or callback.callback.user is None:
        return
    user_id = callback.callback.user.user_id
    full_name = callback.callback.user.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)

    client = get_nutrition_client()
    try:
        summary = await client.daily_summary(
            external_user_id=external_user_id_for(bot_user),
        )
    except NutritionUnavailableError:
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Дневник временно недоступен. Попробуй через минуту.",
        )
        return
    except NutritionAPIError as exc:
        logger.exception("food_correction.summary.api_error user=%s err=%s",
                         bot_user.max_user_id, exc)
        await callback.bot.send_message(
            chat_id=chat_id,
            text="Не получилось загрузить дневник.",
        )
        return

    text = ai_ui.render_daily_summary(summary.raw)
    await callback.bot.send_message(chat_id=chat_id, text=text)
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_food_correction.py -v`
Expected: 6 passed.

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ -v --tb=short --ignore=mysite/tests/maxbot/test_run.py`
Expected: passing.

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/food_correction.py mysite/tests/maxbot/test_food_correction.py
git commit -m "feat(maxbot): view_day footer handler — переиспользует daily_summary (T11)

[📊 Посмотреть день] из footer'а scan-карточки делает то же что
/дневник команда: client.daily_summary → ai_ui.render_daily_summary."
```

---

## Task 12: E2E happy path test — photo → high-conf → log → footer click → /дневник

**Files:**
- Modify: `mysite/tests/maxbot/test_food_scanner_v2.py`

- [ ] **Step 1: Write E2E test**

APPEND:

```python
@pytest.mark.asyncio
async def test_e2e_photo_to_log_to_view_day(monkeypatch, settings):
    """E2E: photo → scan high-conf → meal click → footer view_day → summary.

    Cover главный happy-path: убеждаемся что все 4 handler'а вызываются
    последовательно и состояние/UI прогрессирует ожидаемо."""
    from maxbot.handlers.food_scanner import on_photo_message, on_log_meal
    from maxbot.handlers.food_correction import on_view_day
    from maxbot.services.nutrition_client import (
        ScanResponse, LogMealResponse, DailySummaryResponse,
    )

    settings.NUTRITION_ENABLED = True

    # Mock Ayla calls
    scan_mock = AsyncMock(return_value=ScanResponse(
        scan_id="S1", dish_name="Паста", confidence=0.85,
        portion_g=300, nutrition={"calories": 520, "protein_g": 35,
                                  "fat_g": 18, "carbs_g": 55},
        provider="openai", raw={
            "id": "S1", "dish_name": "Паста", "confidence": 0.85,
            "nutrition": {"calories": 520, "protein_g": 35,
                          "fat_g": 18, "carbs_g": 55},
        },
    ))
    log_mock = AsyncMock(return_value=LogMealResponse(
        log_id="L1", scan_id="S1", dish_name="Паста",
        meal_type="lunch", calories=520, raw={},
    ))
    summary_mock = AsyncMock(return_value=DailySummaryResponse(
        date="2026-05-04", calories_total=520, calories_goal=1450,
        protein_g=35, fat_g=18, carbs_g=55, entries=[],
        raw={"date": "2026-05-04", "calories_total": 520,
             "calories_goal": 1450, "protein_g": 35, "fat_g": 18,
             "carbs_g": 55, "entries": []},
    ))
    fake_client = MagicMock(
        scan_photo=scan_mock, log_meal=log_mock, daily_summary=summary_mock,
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_nutrition_client",
        lambda: fake_client,
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_nutrition_client",
        lambda: fake_client,
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner._download_photo",
        AsyncMock(return_value=b"fake"),
    )
    bot_user = MagicMock(food_scanner_consent_at="2026-01-01", max_user_id=200)
    monkeypatch.setattr(
        "maxbot.handlers.food_scanner.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    ctx = MemoryContext(chat_id=100, user_id=200)

    # Step 1: send photo
    sent_msg = MagicMock(message_id="m-1")
    photo_event = _fake_photo_event()
    photo_event.bot.send_message = AsyncMock(return_value=sent_msg)
    photo_event.bot.edit_message = AsyncMock()
    await on_photo_message(photo_event, ctx)
    scan_mock.assert_awaited_once()

    # Step 2: click meal-type
    cb_log = MagicMock()
    cb_log.callback.payload = "cb:nutrition:log:S1:lunch"
    cb_log.callback.user = MagicMock(user_id=200, full_name="Тест")
    cb_log.message.recipient.chat_id = 100
    cb_log.bot.send_message = AsyncMock()
    await on_log_meal(cb_log, ctx)
    log_mock.assert_awaited_once()
    log_kwargs = cb_log.bot.send_message.await_args.kwargs
    # Footer обозначен
    assert log_kwargs.get("attachments")

    # Step 3: click [📊 Посмотреть день] из footer
    cb_view = MagicMock()
    cb_view.callback.payload = "cb:nutrition:view_day"
    cb_view.callback.user = MagicMock(user_id=200, full_name="Тест")
    cb_view.message.recipient.chat_id = 100
    cb_view.bot.send_message = AsyncMock()
    await on_view_day(cb_view, ctx)
    summary_mock.assert_awaited_once()
    view_text = cb_view.bot.send_message.await_args.kwargs["text"]
    assert "520" in view_text or "1450" in view_text
```

- [ ] **Step 2: Run E2E**

Run: `pytest mysite/tests/maxbot/test_food_scanner_v2.py::test_e2e_photo_to_log_to_view_day -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add mysite/tests/maxbot/test_food_scanner_v2.py
git commit -m "test(maxbot): E2E photo → log → footer view_day (T12)

Покрывает happy path: photo upload → high-conf scan → meal-type click
→ footer [📊 Посмотреть день] click → /дневник render. Все 3 handler'а
дёргаются и состояние прогрессирует ожидаемо."
```

---

## Task 13: Final regression + manual smoke + register router visible end-to-end

**Files:**
- (verify only)

- [ ] **Step 1: Full anketa + scanner suites**

Run: `pytest mysite/tests/maxbot/ -v --tb=short --ignore=mysite/tests/maxbot/test_run.py`
Expected: 380+ passed (from 385 baseline + ~15 new tests).

- [ ] **Step 2: Full repo regression**

Run: `pytest -q --ignore=mysite/tests/maxbot/test_run.py`
Expected: same as Part 1 baseline + Part 2A new tests, no new failures.

- [ ] **Step 3: Manual smoke**

Smoke command from Part 1 still works (`manage.py manual_test_anketa`). For Part 2A — нет аналогичного smoke command'а; вместо этого вручную проверь что:

```bash
python -c "
from maxbot.handlers import get_routers
routers = get_routers()
names = [type(r).__name__ for r in routers]
print(f'Total routers: {len(routers)}')
# Должно быть food_correction в списке
import sys
sys.path.insert(0, 'mysite')
from maxbot.handlers.food_correction import router as fc
print('food_correction registered:', fc in routers)
"
```

(если pythonpath нужен — запусти из `mysite/` директории).

Expected: `food_correction registered: True`.

- [ ] **Step 4: Push**

```bash
git push origin dev
```

- [ ] **Step 5: Verify staging deploy**

```bash
HTTPS_PROXY="$OPENAI_PROXY" gh run list --branch dev --limit 3
```

Expected: 3 ✅ workflows (CI + Deploy DEV bot + Deploy to Staging) for the latest commit.

---

## Self-review checklist (выполнить после Task 13)

**Spec coverage:**
- [x] Edit-message loading — Task 3
- [x] Confidence routing high/low — Tasks 4, 5 (medium = high до Phase 3.2)
- [x] Footer-buttons после meal-log — Task 6
- [x] FSM-aware skip during anketa — Task 2
- [x] NUTRITION_ENABLED gate в photo handler — Task 2
- [x] Action-row keyboard helper — Task 1 (использовать в render_daily_summary — backlog T-2A.next)
- [x] Correction flow open menu — Task 7
- [x] Portion correction (Меньше/Норм/Больше) — Task 8 (полный пересчёт через scan_photo — Phase 3.2 backlog)
- [x] Other-dish/add-ingredient/delete stubs — Task 9
- [x] Retake/manual stubs — Task 9
- [x] Water footer stub — Task 10
- [x] View-day footer — Task 11

**Placeholder scan:** [run after writing] — search for "TBD", "TODO в production коде", "implement later". Tests-stubs с COMING_SOON_PHASE32 явно помечены.

**Type consistency:**
- `render_food_scan_v2(scan: dict) -> tuple[str, list]` — same signature as `render_food_scan`.
- `render_food_logged_with_footer(meal_label, dish_name, kcal)` — kwargs-only.
- `_replace(text, attachments=None)` helper в `on_photo_message` — local closure, signature consistent across except branches.
- All PAYLOAD-strings — defined in `keyboards.py` Task 1 block.

---

## Не в Part 2A (backlog Part 2B/2C/Phase 3.2)

**Part 2B (water flow):**
- Replace `on_add_water_stub` (Task 10) с реальным `handlers/water.py` router
- 4-button water selector + free-text → `parse_beverage` → `add_water` Ayla call
- Soft-delete + 15-min restore window
- Milestones idempotent per-day (50/100/150%)
- Alcohol recovery hint, caffeine warning при pregnant
- Coffee/tea separate counters
- Adaptive water reminders (opt-in OFF, Celery beat)

**Part 2C (daily report):**
- Push 21:00 per-user TZ (Celery beat `send_daily_reports`)
- Inline summary после 18:00 при ≥3 приёмов
- AI-comment generation (требует `?with_comment=true` Ayla extension)
- Eating disorder mode без чисел калорий
- Weekly unlock после 7 дней с FoodEntry

**Phase 3.2 (correction extensions):**
- Polный portion-multiplier пересчёт (Task 8 sub-stub)
- Other-dish override через caption + new Ayla endpoint
- Add-ingredient flow
- Delete FoodLog endpoint
- Manual text-input → GPT-парсинг

---

*Plan v1 закреплён 2026-05-04. Ссылается на Design Doc v2
(`maxbot-phase3-nutrition-design.md`), reconciliation R4
(`maxbot-phase3-reconciliation.md`), Part 1 plan
(`maxbot-phase3-1-foundation-anketa.md`), Ayla spec
(`maxbot-phase3-ayla-spec.md`).*
