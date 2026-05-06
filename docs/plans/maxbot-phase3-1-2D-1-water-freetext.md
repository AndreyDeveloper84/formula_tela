# MAX-бот Phase 3.1 Part 2D.1 — Free-Text Water Entry

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Юзер пишет «выпила стакан кофе» / «вода 500 мл» / «вино бокал» — бот парсит → `add_water(ml, beverage_slug)` → подтверждение «+ml · today/norm · alcohol/caffeine hints» (Design Doc v2 §7.2).

**Architecture:** New `parse_beverage(text)` hybrid regex+LLM в `ai_parsers.py` (15+ hardcoded slug+aliases для 80% coverage, LLM fallback на 5%, `REFUSED`/`None` для остальных). Hook `try_handle_water_text(event, context) → bool` в `water.py` — клиент `on_free_text` (ai_assistant) сначала вызывает hook; если success → early return, иначе → AI. Caffeine warning при pregnant+caffeine_mg≥200 — render extension в `render_water_added`, conditional через дополнительный get_profile call (только для caffeine-bearing beverages).

**Tech Stack:** Python 3.12 async, `re` regex, OpenAI tool-use (gpt-4o-mini fallback per existing parse_age/height/weight pattern), maxapi SDK, existing `nutrition_client.add_water/get_profile`, `WaterEntryResponse.alcohol_recovery_hint` flag, `BotUser.health_flags["pregnant"]`.

**Reference:**
- Design: `docs/plans/maxbot-phase3-nutrition-design.md` v2 §7.2 (free-text branch), §7.4 (alcohol recovery), §7.5 (кофе/чай counters), Caffeine §7.5 («pregnant + caffeine ≥200мг → soft warning»)
- Beverage catalog (mock seed): `mysite/tests/fixtures/ayla_mock.py:75-300` (~25 napitkov с aliases)
- Existing parsers (pattern reference): `mysite/maxbot/ai_parsers.py:72-462` (parse_age/height/weight/allergies — hybrid regex+LLM с REFUSED sentinel)
- Existing water handler: `mysite/maxbot/handlers/water.py` (Part 2B — on_water_menu + on_water_add_quick + on_water_undo + on_water_command)
- Plan Part 2B (foundation): `docs/plans/maxbot-phase3-1-2B-water-flow.md` (T03 _PAYLOAD_TO_ML map, T04 undo, T07 NUTRITION_ENABLED gate, T07 FSM-skip)

**Existing infrastructure (DO NOT recreate):**
- `nutrition_client.add_water(*, external_user_id, ml, beverage_slug=None, ts=None, idempotency_key=None) → WaterEntryResponse` — supports `beverage_slug` kwarg уже!
- `nutrition_client.get_profile(*, external_user_id) → ProfileResponse` (с `.health_flags`)
- `WaterEntryResponse` (4 поля core + flags): entry_id, ml, water_ml, kcal, milestone_text, today_total_ml, today_norm_ml, alcohol_recovery_hint, raw
- `ai_ui.render_water_added(entry)` — Part 2B T03 render с alcohol hint conditional
- `keyboards.water_undo_keyboard(entry_id=...)` — Part 2B T01
- `NUTRITION_ENABLED` setting + `NutritionAnketaStates` (Part 1)
- Existing parsers `parse_age/height/weight/allergies` в ai_parsers.py — regex+LLM hybrid template
- `REFUSED` constant в ai_parsers.py
- Существующий `on_free_text` в `handlers/ai_assistant.py:80` — message_created без filter (catches all free text)

---

## Architectural decisions baked into plan

1. **parse_beverage = hybrid regex+LLM** — pattern from existing parsers. Regex ladder для 15+ hardcoded common beverages (water/coffee/tea/milk/juice/wine/beer/etc.) с aliases — 80% coverage. LLM fallback (gpt-4o-mini) для остальных 15% (только если len(text)<=30 chars — cost guard). REFUSED для отказов, None если совсем не понятно.
2. **Volume parsing** — отдельный sub-parser в той же функции:
   - Number + unit: `«250 мл»`, `«0.5 литра»`, `«2 стакана»` → математика
   - Unit only без числа: `«стакан»` → default 250 мл, `«бутылка»` → 500 мл, `«литр»` → 1000 мл, `«чашка»` → 200 мл
   - Только напиток без объёма: использовать default-serving для slug (kofe_chernyi=200мл, voda=250мл и т.п.)
3. **Hook через early-return в on_free_text** — minimal coupling. `try_handle_water_text(event, context)` живёт в water.py, возвращает `True` если handled (parse_beverage hit + add_water success). on_free_text получает hook первым; на False → продолжает в AIConcierge.
4. **Caffeine warning при pregnant** — после успешного add_water, если beverage_slug в `{kofe_*, chai_*}` (caffeine-bearing) и `entry.raw["caffeine_mg"]` exists → fetch profile → check `health_flags.pregnant` AND today_caffeine ≥ 200 → render hint. Дополнительный round-trip только в edge-case. Если Ayla scan response не отдаёт caffeine_mg flag — handler skipped silently.
5. **Beverage catalog — hardcoded в bot** (не fetch'ит из Ayla `/beverages/`) — для MVP simplicity. 15 slugs покрывает 80% common cases. Расширение catalog'а — Phase 3.2 если нужно.
6. **NUTRITION_ENABLED gate** — try_handle_water_text early-return False если флаг false (free-text «выпил кофе» **не должен** показывать «Скоро будет»; пусть просто провалится в AI который тоже сообразит). Альтернатива: full COMING_SOON message — слишком инвазивно для случайной фразы.
7. **FSM-aware skip** — try_handle_water_text early-return False если в `NutritionAnketaStates.*` (юзер должен ответить вопрос анкеты, не парсить как воду).
8. **Undo button через water_undo_keyboard** (Part 2B T01) — same pattern, переиспользуем.

---

## File Structure

**Modify:**
- `mysite/maxbot/ai_parsers.py` — add `parse_beverage(text, *, openai_client=None) → dict | str | None` (returns `{"beverage_slug": str, "ml": int}` on success, `"REFUSED"` on explicit refusal, `None` on unparseable)
- `mysite/maxbot/handlers/water.py` — add `try_handle_water_text(event, context) → bool` async function + register integration с on_free_text
- `mysite/maxbot/handlers/ai_assistant.py:on_free_text` — добавить early-return hook
- `mysite/maxbot/ai_ui.py` — extend `render_water_added(entry, caffeine_warning=False)` signature + helper `_render_caffeine_warning()`

**Create:**
- `mysite/tests/maxbot/test_parse_beverage.py` — unit tests на regex ladder + LLM fallback
- `mysite/tests/maxbot/test_water_freetext.py` — handler integration tests (try_handle_water_text + on_free_text hook)

---

## Beverage catalog — 15 slugs + aliases (hardcoded)

Минимально достаточно для 80% coverage в общении на русском. Full catalog (~50 slugs из ayla_mock seed) — Phase 3.2.

```python
_BEVERAGE_PATTERNS = [
    # slug, aliases (lowercase substring match), default_serving_ml
    ("voda", ["вода", "water", "h2o"], 250),
    ("voda_mineralnaya", ["минералка", "минеральная вода", "боржоми"], 250),
    ("chai_chernyi", ["чёрный чай", "черный чай", "чай"], 250),
    ("chai_zelenyi", ["зелёный чай", "зеленый чай"], 250),
    ("chai_travyanoi", ["травяной чай", "ромашка", "мята"], 250),
    ("kofe_chernyi", ["чёрный кофе", "черный кофе", "американо", "кофе"], 200),
    ("kofe_espresso", ["эспрессо", "espresso"], 30),
    ("kofe_kapuchino", ["капучино", "cappuccino"], 250),
    ("kofe_latte", ["латте", "latte"], 350),
    ("sok_apelsinovyi", ["апельсиновый сок", "апельсиновый"], 200),
    ("sok_yablochnyi", ["яблочный сок", "яблочный"], 200),
    ("moloko", ["молоко"], 250),
    ("pivo", ["пиво", "beer"], 500),
    ("vino", ["вино", "wine"], 150),
    ("kompot", ["компот"], 250),
]

_VOLUME_UNITS = {
    "мл": 1, "ml": 1,
    "л": 1000, "литр": 1000, "литра": 1000, "литров": 1000, "liter": 1000,
    "стакан": 250, "стакана": 250, "стаканов": 250,
    "бутылка": 500, "бутылки": 500, "бутылок": 500, "бутылку": 500,
    "чашка": 200, "чашки": 200, "чашек": 200, "чашку": 200,
    "бокал": 150, "бокала": 150,
    "кружка": 250, "кружки": 250,
    "банка": 330, "банки": 330,
    "порция": 30,  # эспрессо
}
```

(Order matters — более специфичные паттерны раньше: «зелёный чай» до «чай».)

---

## Task 1: `parse_beverage` regex ladder

**Files:**
- Modify: `mysite/maxbot/ai_parsers.py`
- Create: `mysite/tests/maxbot/test_parse_beverage.py`

- [ ] **Step 1: Write failing tests**

```python
# mysite/tests/maxbot/test_parse_beverage.py
"""Phase 3.1 Part 2D.1 T01: parse_beverage hybrid regex+LLM parser."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_parse_beverage_water_with_volume():
    """«250 мл воды» → {voda, 250}."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("250 мл воды")
    assert result == {"beverage_slug": "voda", "ml": 250}


@pytest.mark.asyncio
async def test_parse_beverage_coffee_no_volume_uses_default():
    """«выпила кофе» → {kofe_chernyi, 200} (default serving)."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("выпила кофе")
    assert result == {"beverage_slug": "kofe_chernyi", "ml": 200}


@pytest.mark.asyncio
async def test_parse_beverage_glass_unit():
    """«стакан воды» → {voda, 250} (стакан = 250 мл)."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("стакан воды")
    assert result == {"beverage_slug": "voda", "ml": 250}


@pytest.mark.asyncio
async def test_parse_beverage_bottle_water():
    """«бутылка воды» → {voda, 500}."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("бутылка воды")
    assert result == {"beverage_slug": "voda", "ml": 500}


@pytest.mark.asyncio
async def test_parse_beverage_wine_glass():
    """«бокал вина» → {vino, 150} (бокал=150)."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("бокал вина")
    assert result == {"beverage_slug": "vino", "ml": 150}


@pytest.mark.asyncio
async def test_parse_beverage_litre_explicit():
    """«1 литр воды» → {voda, 1000}."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("1 литр воды")
    assert result == {"beverage_slug": "voda", "ml": 1000}


@pytest.mark.asyncio
async def test_parse_beverage_two_glasses_coffee():
    """«2 чашки кофе» → {kofe_chernyi, 400} (2×чашка(200))."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("2 чашки кофе")
    assert result == {"beverage_slug": "kofe_chernyi", "ml": 400}


@pytest.mark.asyncio
async def test_parse_beverage_unrelated_text_returns_none():
    """«как погода» → None (не напиток)."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("как погода")
    assert result is None


@pytest.mark.asyncio
async def test_parse_beverage_empty_returns_none():
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("")
    assert result is None


@pytest.mark.asyncio
async def test_parse_beverage_specific_pattern_first():
    """«зелёный чай» НЕ должен match'иться на «чай» — более специфичный паттерн."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("зелёный чай")
    assert result == {"beverage_slug": "chai_zelenyi", "ml": 250}


@pytest.mark.asyncio
async def test_parse_beverage_capuccino_specific():
    """«капучино» → kofe_kapuchino (не kofe_chernyi)."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("капучино")
    assert result == {"beverage_slug": "kofe_kapuchino", "ml": 250}
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_parse_beverage.py -v`
Expected: ImportError на `parse_beverage`.

- [ ] **Step 3: Add parse_beverage**

В `mysite/maxbot/ai_parsers.py` ДОБАВИТЬ (в конец файла):

```python
# ─── parse_beverage (Phase 3.1 Part 2D.1) ───────────────────────────────────


# Beverage catalog — hardcoded для regex matching. 15 slugs покрывают ~80%
# common cases в русскоязычном общении. Полный catalog (~50 slugs) — Ayla
# server side, MVP не нуждается в них для parse'инга.
#
# Order matters: более специфичные паттерны — раньше («зелёный чай» до «чай»).

_BEVERAGE_PATTERNS: list[tuple[str, list[str], int]] = [
    # (slug, aliases (lowercase substring match), default_serving_ml)

    # Tea — specific первыми
    ("chai_zelenyi", ["зелёный чай", "зеленый чай", "green tea"], 250),
    ("chai_travyanoi", ["травяной чай", "ромашка", "мята", "иван-чай"], 250),
    ("chai_chernyi", ["чёрный чай", "черный чай", "чай", "tea"], 250),

    # Coffee — specific первыми
    ("kofe_kapuchino", ["капучино", "cappuccino"], 250),
    ("kofe_latte", ["латте", "latte"], 350),
    ("kofe_espresso", ["эспрессо", "espresso"], 30),
    ("kofe_chernyi", ["чёрный кофе", "черный кофе", "американо", "americano", "кофе", "coffee"], 200),

    # Water
    ("voda_mineralnaya", ["минералка", "минеральная вода", "боржоми", "ессентуки"], 250),
    ("voda", ["воды", "вода", "water", "h2o"], 250),

    # Juice
    ("sok_apelsinovyi", ["апельсиновый сок", "апельсиновый"], 200),
    ("sok_yablochnyi", ["яблочный сок", "яблочный"], 200),

    # Other
    ("moloko", ["молоко"], 250),
    ("pivo", ["пиво", "beer"], 500),
    ("vino", ["вино", "wine"], 150),
    ("kompot", ["компот"], 250),
]


# Volume unit aliases → ml conversion
_VOLUME_UNITS: dict[str, int] = {
    "мл": 1,
    "ml": 1,
    "л": 1000,
    "литр": 1000, "литра": 1000, "литров": 1000, "литры": 1000,
    "liter": 1000,
    "стакан": 250, "стакана": 250, "стаканов": 250,
    "бутылка": 500, "бутылки": 500, "бутылок": 500, "бутылку": 500,
    "чашка": 200, "чашки": 200, "чашек": 200, "чашку": 200,
    "бокал": 150, "бокала": 150, "бокалов": 150,
    "кружка": 250, "кружки": 250, "кружек": 250, "кружку": 250,
    "банка": 330, "банки": 330, "банок": 330, "банку": 330,
    "порция": 30, "порций": 30, "порции": 30,
}


_NUM_RE = re.compile(r"(?:^|\s)(\d+(?:[.,]\d+)?)(?=\s|$|[а-яёa-z])")


async def parse_beverage(text: str, *, openai_client: Any = None) -> dict | str | None:
    """Phase 3.1 Part 2D.1: hybrid regex+LLM beverage parser.

    Returns:
        - dict {"beverage_slug": str, "ml": int} on successful parse
        - "REFUSED" on explicit refusal («не скажу», «не пил», etc.)
        - None if cannot parse (let caller fall through to AI или ignore)

    Strategy:
        1. Refusal markers → REFUSED
        2. Regex ladder over _BEVERAGE_PATTERNS — first match wins
        3. Volume extraction (number + unit, OR unit-only, OR default serving)
        4. LLM fallback (gpt-4o-mini) если regex не сработал И len(text)<=30

    Examples:
        «250 мл воды» → {voda, 250}
        «выпила кофе» → {kofe_chernyi, 200}  (default serving)
        «бутылка воды» → {voda, 500}
        «2 чашки кофе» → {kofe_chernyi, 400}
        «как погода» → None
    """
    if not text or not text.strip():
        return None

    if _is_refusal(text):
        return REFUSED

    normalized = text.lower().strip()

    # 1. Beverage match — first specific pattern wins
    found_slug = None
    found_default_serving = None
    for slug, aliases, default_serving in _BEVERAGE_PATTERNS:
        for alias in aliases:
            if alias in normalized:
                found_slug = slug
                found_default_serving = default_serving
                break
        if found_slug:
            break

    if not found_slug:
        # 2. LLM fallback only if short text
        if len(text) <= 30 and openai_client is not None:
            return await _llm_parse_beverage(text, openai_client=openai_client)
        return None

    # 3. Volume extraction
    ml = _extract_volume(normalized, found_default_serving)
    return {"beverage_slug": found_slug, "ml": ml}


def _extract_volume(normalized: str, default_serving_ml: int) -> int:
    """Extract volume from normalized text. Returns ml as int.

    Patterns:
        «250 мл» → 250
        «0.5 л» → 500
        «1 литр» → 1000
        «2 чашки» → 2 × 200 = 400
        «стакан» (no number) → 250
        «» (no unit, no number) → default_serving_ml
    """
    # Find number (optional)
    num_match = _NUM_RE.search(normalized)
    num: float | None = None
    if num_match:
        try:
            num = float(num_match.group(1).replace(",", "."))
        except ValueError:
            num = None

    # Find unit (optional)
    found_unit_ml: int | None = None
    for unit, multiplier in _VOLUME_UNITS.items():
        # Word boundary — substring check fine if order'ы learned: попробуем
        # match всё слово целиком. Use regex с границами слов для unit.
        pattern = rf"(?:^|\s){re.escape(unit)}(?:\s|$|[^а-яё])"
        if re.search(pattern, normalized):
            found_unit_ml = multiplier
            break

    if num is not None and found_unit_ml is not None:
        return int(round(num * found_unit_ml))
    if num is not None:
        # Number без unit — assume мл
        return int(round(num))
    if found_unit_ml is not None:
        return found_unit_ml
    return default_serving_ml


_LLM_BEVERAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "parse_beverage_value",
        "description": (
            "Извлечь напиток и объём из свободного текста на русском. "
            "beverage_slug должен быть из списка: voda, voda_mineralnaya, "
            "chai_chernyi, chai_zelenyi, chai_travyanoi, kofe_chernyi, "
            "kofe_espresso, kofe_kapuchino, kofe_latte, sok_apelsinovyi, "
            "sok_yablochnyi, moloko, pivo, vino, kompot. ml — объём в "
            "миллилитрах (10..3000). Если не понятно — null."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "beverage_slug": {
                    "type": ["string", "null"],
                    "description": "Slug из списка или null если не понятно.",
                },
                "ml": {
                    "type": ["integer", "null"],
                    "description": "Объём в мл (10..3000) или null.",
                },
            },
            "required": ["beverage_slug", "ml"],
        },
    },
}


async def _llm_parse_beverage(text: str, *, openai_client: Any) -> dict | None:
    """LLM fallback. Cost guard: вызывается только если len(text) <= 30."""
    try:
        completion = await openai_client.chat.completions.create(
            model=_LLM_MODEL,
            messages=[{"role": "user", "content": text}],
            tools=[_LLM_BEVERAGE_TOOL],
            tool_choice={"type": "function", "function": {"name": "parse_beverage_value"}},
            temperature=0,
            max_tokens=50,
        )
        tool_calls = completion.choices[0].message.tool_calls
        if not tool_calls:
            return None
        args = json.loads(tool_calls[0].function.arguments)
        slug = args.get("beverage_slug")
        ml = args.get("ml")
        if not slug or not isinstance(ml, int) or not (10 <= ml <= 3000):
            return None
        return {"beverage_slug": slug, "ml": ml}
    except Exception as exc:  # noqa: BLE001
        logger.warning("parse_beverage.llm_failed err=%s", exc)
        return None
```

(`re` уже imported в ai_parsers.py header.)

- [ ] **Step 4: Run tests — must pass**

Run: `pytest mysite/tests/maxbot/test_parse_beverage.py -v`
Expected: 11 passed.

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 445 passed (434 baseline + 11 new).

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/ai_parsers.py mysite/tests/maxbot/test_parse_beverage.py
git commit -m "feat(maxbot): parse_beverage hybrid regex+LLM parser (Part 2D.1 T01)

15 hardcoded slugs+aliases (water/coffee/tea/etc.) + 17 volume units.
LLM fallback (gpt-4o-mini) only if len(text)≤30 — cost guard. REFUSED
sentinel + None для unparseable. Pattern из existing parse_age/height/
weight (ai_parsers.py:72-462)."
```

---

## Task 2: `try_handle_water_text` helper в `water.py`

**Files:**
- Modify: `mysite/maxbot/handlers/water.py`
- Create: `mysite/tests/maxbot/test_water_freetext.py`

- [ ] **Step 1: Write failing tests**

```python
# mysite/tests/maxbot/test_water_freetext.py
"""Phase 3.1 Part 2D.1 T02: try_handle_water_text — free-text water entry."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from maxapi.context.context import MemoryContext


pytestmark = pytest.mark.django_db


def _fake_message(text, chat_id=100, user_id=200):
    msg = MagicMock()
    msg.message.body.text = text
    msg.message.recipient.chat_id = chat_id
    msg.message.sender = MagicMock(user_id=user_id, full_name="Тест")
    msg.bot.send_message = AsyncMock()
    return msg


@pytest.mark.asyncio
async def test_try_handle_water_text_recognizes_coffee_and_calls_add_water(
    monkeypatch, settings,
):
    """«выпила стакан кофе» → parse_beverage hit → add_water → render + undo."""
    from maxbot.handlers.water import try_handle_water_text
    from maxbot.services.nutrition_client import WaterEntryResponse

    settings.NUTRITION_ENABLED = True

    add_mock = AsyncMock(return_value=WaterEntryResponse(
        entry_id="W-fr1", ml=250, water_ml=250, kcal=10,
        milestone_text=None,
        today_total_ml=1450, today_norm_ml=2000,
        alcohol_recovery_hint=False, raw={"caffeine_mg": 95},
    ))
    fake_client = MagicMock(add_water=add_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    msg = _fake_message("выпила стакан кофе")
    ctx = MemoryContext(chat_id=100, user_id=200)

    handled = await try_handle_water_text(msg, ctx)

    assert handled is True
    add_mock.assert_awaited_once()
    kwargs = add_mock.await_args.kwargs
    assert kwargs["beverage_slug"] == "kofe_chernyi"
    assert kwargs["ml"] == 250  # стакан кофе = 250 мл (стакан unit, не default 200)

    msg.bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_try_handle_water_text_returns_false_on_unrelated_text(
    monkeypatch, settings,
):
    """«как погода» → не водный текст → return False, add_water not called."""
    from maxbot.handlers.water import try_handle_water_text

    settings.NUTRITION_ENABLED = True

    add_mock = AsyncMock()
    fake_client = MagicMock(add_water=add_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )

    msg = _fake_message("как погода")
    ctx = MemoryContext(chat_id=100, user_id=200)

    handled = await try_handle_water_text(msg, ctx)

    assert handled is False
    add_mock.assert_not_awaited()
    msg.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_try_handle_water_text_skipped_when_nutrition_disabled(
    monkeypatch, settings,
):
    """NUTRITION_ENABLED=False → return False (без перехвата)."""
    from maxbot.handlers.water import try_handle_water_text

    settings.NUTRITION_ENABLED = False

    add_mock = AsyncMock()
    fake_client = MagicMock(add_water=add_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )

    msg = _fake_message("выпила кофе")
    ctx = MemoryContext(chat_id=100, user_id=200)

    handled = await try_handle_water_text(msg, ctx)

    assert handled is False
    add_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_try_handle_water_text_skipped_during_anketa_fsm(
    monkeypatch, settings,
):
    """В FSM анкеты → return False (юзер должен отвечать вопрос анкеты)."""
    from maxbot.handlers.water import try_handle_water_text
    from maxbot.states import NutritionAnketaStates

    settings.NUTRITION_ENABLED = True

    add_mock = AsyncMock()
    fake_client = MagicMock(add_water=add_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )

    msg = _fake_message("выпила кофе")
    ctx = MemoryContext(chat_id=100, user_id=200)
    await ctx.set_state(NutritionAnketaStates.awaiting_age)

    handled = await try_handle_water_text(msg, ctx)

    assert handled is False
    add_mock.assert_not_awaited()
    # State preserved
    assert await ctx.get_state() == NutritionAnketaStates.awaiting_age
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_water_freetext.py -v`
Expected: ImportError на `try_handle_water_text`.

- [ ] **Step 3: Add helper в water.py**

В `mysite/maxbot/handlers/water.py` ДОБАВИТЬ (после существующего `on_water_command` — последний handler от Part 2B):

```python
import time
import uuid as _uuid


async def try_handle_water_text(event, context: MemoryContext) -> bool:
    """Phase 3.1 Part 2D.1: попытка обработать free-text как ввод напитка.

    Called от `on_free_text` (ai_assistant.py) ДО маршрутизации в AIConcierge.

    Returns:
        True — текст распознан как напиток, add_water вызван, юзеру отправлена
              карточка confirmation с undo button.
        False — текст НЕ напиток (или disabled / в анкете) — caller продолжает
              в AI Concierge (default route).

    Gates:
        - NUTRITION_ENABLED=False → False (silent — пусть AI отвечает на текст)
        - state ∈ NutritionAnketaStates.* → False (юзер в анкете, не парсим)
        - parse_beverage returns None или REFUSED → False (не напиток)

    Errors:
        - add_water падает → юзер видит soft error, return True (handled).
    """
    from django.conf import settings as django_settings
    from maxbot.ai_parsers import parse_beverage, REFUSED
    from maxbot.states import NutritionAnketaStates

    if not getattr(django_settings, "NUTRITION_ENABLED", False):
        return False

    state = await context.get_state()
    if state is not None and str(state).startswith("NutritionAnketaStates"):
        return False

    if event.message.sender is None:
        return False
    text = (event.message.body.text or "").strip() if event.message.body else ""
    if not text:
        return False

    parsed = await parse_beverage(text)
    if parsed is None or parsed == REFUSED:
        return False

    chat_id = event.message.recipient.chat_id
    user_id = event.message.sender.user_id
    full_name = event.message.sender.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)
    extid = external_user_id_for(bot_user)

    beverage_slug = parsed["beverage_slug"]
    ml = parsed["ml"]

    idem = str(_uuid.uuid5(
        _uuid.NAMESPACE_OID,
        f"{extid}:water_freetext:{beverage_slug}:{ml}:{int(time.time())}",
    ))

    client = get_nutrition_client()
    try:
        entry = await client.add_water(
            external_user_id=extid,
            ml=ml,
            beverage_slug=beverage_slug,
            idempotency_key=idem,
        )
    except NutritionUnavailableError:
        await event.bot.send_message(
            chat_id=chat_id,
            text="Учёт воды временно недоступен. Попробуй через минуту.",
        )
        return True
    except NutritionAPIError as exc:
        logger.exception(
            "water.freetext.api_error user=%s slug=%s ml=%d err=%s",
            bot_user.max_user_id, beverage_slug, ml, exc,
        )
        await event.bot.send_message(
            chat_id=chat_id,
            text="Не получилось записать. Попробуй ещё раз.",
        )
        return True

    text_render = ai_ui.render_water_added(entry)
    await event.bot.send_message(
        chat_id=chat_id,
        text=text_render,
        attachments=[keyboards.water_undo_keyboard(entry_id=entry.entry_id)],
    )
    return True
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_water_freetext.py -v`
Expected: 4 passed.

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 449 passed (445 + 4).

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/water.py mysite/tests/maxbot/test_water_freetext.py
git commit -m "feat(maxbot): try_handle_water_text helper (Part 2D.1 T02)

Hook для on_free_text: parse_beverage → add_water+beverage_slug → render
с undo. NUTRITION_ENABLED gate + FSM-skip → return False (caller продолжает
в AI Concierge). Idempotency-key UUID5 для replay safety."
```

---

## Task 3: Hook в `ai_assistant.on_free_text`

**Files:**
- Modify: `mysite/maxbot/handlers/ai_assistant.py`
- Modify: `mysite/tests/maxbot/test_water_freetext.py`

- [ ] **Step 1: Write failing test**

APPEND в `mysite/tests/maxbot/test_water_freetext.py`:

```python
@pytest.mark.asyncio
async def test_on_free_text_intercepts_water_text_before_ai(monkeypatch, settings):
    """on_free_text вызывает try_handle_water_text первым; если True →
    AIConcierge не вызывается."""
    from maxbot.handlers.ai_assistant import on_free_text

    settings.NUTRITION_ENABLED = True

    # Mock try_handle_water_text → True (handled)
    handler_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.try_handle_water_text", handler_mock,
    )

    # AIConcierge.send_message — should NOT be called when water handled
    concierge_send_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant._concierge_send_message",
        concierge_send_mock,
    )

    msg = _fake_message("выпила кофе")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_free_text(msg, ctx)

    handler_mock.assert_awaited_once()
    concierge_send_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_on_free_text_falls_through_to_ai_when_water_returns_false(
    monkeypatch, settings,
):
    """try_handle_water_text=False → AIConcierge вызывается (default route)."""
    from maxbot.handlers.ai_assistant import on_free_text

    settings.NUTRITION_ENABLED = True

    handler_mock = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant.try_handle_water_text", handler_mock,
    )

    concierge_send_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant._concierge_send_message",
        concierge_send_mock,
    )

    msg = _fake_message("как погода")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_free_text(msg, ctx)

    handler_mock.assert_awaited_once()
    concierge_send_mock.assert_awaited_once()
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_water_freetext.py -v -k "on_free_text"`
Expected: ImportError на `try_handle_water_text` или `_concierge_send_message` в ai_assistant module (depending on existing structure — adapt mock target).

- [ ] **Step 3: Update `on_free_text`**

Read `mysite/maxbot/handlers/ai_assistant.py:on_free_text` (около line 80-200) — find текущую structure. Should look like:

```python
@router.message_created()
async def on_free_text(event: MessageCreated, context: MemoryContext) -> None:
    if event.message.sender is None:
        return
    chat_id = event.message.recipient.chat_id
    user_text = (...).strip() if event.message.body else ""
    if not user_text:
        return
    # MARK_SEEN + TYPING_ON
    # ... existing AIConcierge call ...
```

ADD import + early-return в начало handler'а ПОСЛЕ initial guards `if event.message.sender is None: return` и `if not user_text: return`:

```python
from maxbot.handlers.water import try_handle_water_text


@router.message_created()
async def on_free_text(event: MessageCreated, context: MemoryContext) -> None:
    if event.message.sender is None:
        return

    chat_id = event.message.recipient.chat_id
    user_text = (event.message.body.text or "").strip() if event.message.body else ""
    if not user_text:
        return

    # Phase 3.1 Part 2D.1: попытка обработать как water entry ДО AI.
    # Если parse_beverage hit → handled=True, AI не вызывается.
    if await try_handle_water_text(event, context):
        return

    # ... existing MARK_SEEN + TYPING_ON + AIConcierge ...
```

(Adapt to actual existing code structure. Insert hook AFTER initial guards, BEFORE TYPING_ON / AIConcierge — это позволяет water-handler владеть всем UX без typing-индикатора который сразу показывается.)

If существующий `on_free_text` извлекает AIConcierge call в helper типа `_concierge_send_message` — test mocks targeting that helper. If нет — adapt test to mock `ai_concierge.send_message` или подобное actual entrypoint.

**Important:** Тесты в Step 1 mock'ат `_concierge_send_message`. If actual ai_assistant.py uses different name (e.g. inline `await ai_concierge.send_message(...)` без helper) — tests тоже не пройдут. **Adapt test mock paths to match actual code.** Если AIConcierge не extracted — extract в mockable indirection (helper function `_concierge_send_message(event, context, user_text)` который оборачивает existing inline-логику).

If extraction needed — make minimal change. Existing inline AIConcierge call → wrap in async helper:

```python
async def _concierge_send_message(event, context, user_text):
    """Helper для on_free_text — обёртка над AIConcierge.send_message
    + MARK_SEEN/TYPING_ON. Извлечено из inline кода для testability
    (Part 2D.1 T03 hook needs to mock this)."""
    # ... move existing inline code here ...
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_water_freetext.py -v`
Expected: 6 passed (4 prior + 2 new).

If хитрая mocking — adapt. Цель: assert handler_mock awaited once + concierge мock not awaited (when handled=True), vice versa (when handled=False).

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 451 passed (449 + 2).

If существующие ai_assistant тесты падают из-за extracted helper — adapt их (либо mock new helper, либо restructure tests).

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/ai_assistant.py mysite/tests/maxbot/test_water_freetext.py
git commit -m "feat(maxbot): on_free_text hook → try_handle_water_text first (Part 2D.1 T03)

Перед маршрутизацией в AIConcierge — пробуем parse как напиток.
Если success → render+undo, AI не вызывается. Иначе — fall through
в AI (default route)."
```

---

## Task 4: Caffeine warning extension

**Files:**
- Modify: `mysite/maxbot/ai_ui.py:render_water_added`
- Modify: `mysite/maxbot/handlers/water.py:try_handle_water_text` (compute caffeine_warning kwarg)
- Modify: `mysite/tests/maxbot/test_water_freetext.py`

- [ ] **Step 1: Write failing test**

APPEND в `mysite/tests/maxbot/test_water_freetext.py`:

```python
@pytest.mark.asyncio
async def test_caffeine_warning_when_pregnant_and_high_caffeine(
    monkeypatch, settings,
):
    """Беременная + кофе с накопленным caffeine_mg≥200 → render показывает
    предостережение."""
    from maxbot.handlers.water import try_handle_water_text
    from maxbot.services.nutrition_client import (
        WaterEntryResponse, ProfileResponse,
    )

    settings.NUTRITION_ENABLED = True

    add_mock = AsyncMock(return_value=WaterEntryResponse(
        entry_id="W-caf", ml=250, water_ml=250, kcal=10,
        milestone_text=None,
        today_total_ml=1450, today_norm_ml=2000,
        alcohol_recovery_hint=False,
        raw={"caffeine_mg": 95, "today_caffeine_mg": 220},  # 220 ≥ 200
    ))
    profile_mock = AsyncMock(return_value=ProfileResponse(
        gender="female", age=32, height_cm=165, weight_kg=65,
        goal="maintain", goal_pace="", activity="1.4",
        diet_preference="none",
        daily_kcal=1900, protein_g=110, fat_g=55, carbs_g=200,
        water_ml=2000, bmr=1364,
        health_flags={"pregnant": True},
        disclaimer_acked=None, goal_overridden_by="pregnancy", raw={},
    ))
    fake_client = MagicMock(add_water=add_mock, get_profile=profile_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200, health_flags={"pregnant": True})
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    msg = _fake_message("выпила кофе")
    ctx = MemoryContext(chat_id=100, user_id=200)

    handled = await try_handle_water_text(msg, ctx)

    assert handled is True
    text = msg.bot.send_message.await_args.kwargs["text"]
    # Caffeine warning hint
    assert "кофеин" in text.lower() or "200" in text or "пограничн" in text.lower()
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_water_freetext.py::test_caffeine_warning_when_pregnant_and_high_caffeine -v`
Expected: FAIL — caffeine warning не рендерится.

- [ ] **Step 3: Extend render + handler**

В `mysite/maxbot/ai_ui.py` найти `render_water_added` (Part 2B T03) и **расширить signature**:

```python
def render_water_added(entry, *, caffeine_warning: bool = False) -> str:
    """Phase 3.1 Part 2B/2D.1: ...

    Args:
        entry: WaterEntryResponse — обязателен
        caffeine_warning: bool — true если pregnant + today_caffeine_mg ≥ 200,
            добавляет soft warning «близко к лимиту 200 мг» (Design §7.5).
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

    if caffeine_warning:
        text += (
            "\n\n☕ Кофеин сегодня близко к лимиту 200 мг — "
            "при беременности рекомендуют не больше."
        )

    return text
```

В `mysite/maxbot/handlers/water.py` обновить `try_handle_water_text` — после успешного `add_water`, ДО render, проверить caffeine warning:

```python
    text_render = ai_ui.render_water_added(
        entry,
        caffeine_warning=await _should_show_caffeine_warning(
            client, extid, beverage_slug, entry, bot_user,
        ),
    )
```

И ДОБАВИТЬ helper в water.py (рядом с try_handle_water_text):

```python
_CAFFEINE_BEARING_PREFIXES = ("kofe_", "chai_")


async def _should_show_caffeine_warning(
    client, external_user_id: str, beverage_slug: str,
    entry, bot_user,
) -> bool:
    """Phase 3.1 Part 2D.1 §7.5: pregnant + caffeine ≥ 200 мг сегодня.

    Conditions:
        1. beverage_slug starts with kofe_ or chai_ (caffeine-bearing)
        2. bot_user.health_flags["pregnant"] OR get_profile.health_flags["pregnant"]
        3. entry.raw["today_caffeine_mg"] >= 200

    Returns False (no warning) если any condition fails или Ayla не отдаёт
    caffeine_mg в response.
    """
    if not any(beverage_slug.startswith(p) for p in _CAFFEINE_BEARING_PREFIXES):
        return False

    today_caffeine = (entry.raw or {}).get("today_caffeine_mg") or 0
    if today_caffeine < 200:
        return False

    # Check pregnant flag — local cache OR fetch fresh
    pregnant = bool((bot_user.health_flags or {}).get("pregnant", False))
    if not pregnant:
        try:
            profile = await client.get_profile(external_user_id=external_user_id)
            if profile is not None:
                pregnant = bool(profile.health_flags.get("pregnant", False))
        except (NutritionUnavailableError, NutritionAPIError):
            return False

    return pregnant
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_water_freetext.py -v`
Expected: 7 passed (6 prior + 1 new).

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 452 passed.

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/ai_ui.py mysite/maxbot/handlers/water.py mysite/tests/maxbot/test_water_freetext.py
git commit -m "feat(maxbot): caffeine warning при pregnant+caffeine≥200 (Part 2D.1 T04)

render_water_added расширен caffeine_warning kwarg. Helper
_should_show_caffeine_warning читает beverage_slug prefix +
bot_user.health_flags / get_profile fallback + entry.raw.today_caffeine_mg.
Design §7.5 «близко к лимиту 200 мг при беременности»."
```

---

## Task 5: E2E test happy path

**Files:**
- Modify: `mysite/tests/maxbot/test_water_freetext.py`

- [ ] **Step 1: Write E2E test**

APPEND:

```python
@pytest.mark.asyncio
async def test_e2e_freetext_water_through_ai_assistant(monkeypatch, settings):
    """E2E: «выпила стакан кофе» через on_free_text → водный handler
    перехватывает → add_water → render. AIConcierge не вызывается."""
    from maxbot.handlers.ai_assistant import on_free_text
    from maxbot.services.nutrition_client import WaterEntryResponse

    settings.NUTRITION_ENABLED = True

    add_mock = AsyncMock(return_value=WaterEntryResponse(
        entry_id="W-e2e", ml=250, water_ml=250, kcal=10,
        milestone_text="Хорошо пьёшь!",
        today_total_ml=1450, today_norm_ml=2000,
        alcohol_recovery_hint=False, raw={},
    ))
    fake_client = MagicMock(add_water=add_mock)
    monkeypatch.setattr(
        "maxbot.handlers.water.get_nutrition_client", lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.water.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    # AIConcierge mock — should NOT be called
    concierge_send_mock = AsyncMock()
    monkeypatch.setattr(
        "maxbot.handlers.ai_assistant._concierge_send_message",
        concierge_send_mock,
    )

    msg = _fake_message("выпила стакан кофе")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_free_text(msg, ctx)

    # add_water called с beverage_slug=kofe_chernyi, ml=250 (стакан)
    add_mock.assert_awaited_once()
    add_kwargs = add_mock.await_args.kwargs
    assert add_kwargs["beverage_slug"] == "kofe_chernyi"
    assert add_kwargs["ml"] == 250

    # render отправлен
    msg.bot.send_message.assert_awaited_once()
    text = msg.bot.send_message.await_args.kwargs["text"]
    assert "+250" in text or "250 мл" in text
    assert "Хорошо пьёшь" in text

    # AIConcierge не вызвался
    concierge_send_mock.assert_not_awaited()
```

- [ ] **Step 2: Run E2E**

Run: `pytest mysite/tests/maxbot/test_water_freetext.py::test_e2e_freetext_water_through_ai_assistant -v`
Expected: PASS.

- [ ] **Step 3: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 453 passed.

- [ ] **Step 4: Commit**

```bash
git add mysite/tests/maxbot/test_water_freetext.py
git commit -m "test(maxbot): E2E free-text water through ai_assistant (Part 2D.1 T05)

Cover full path: «выпила стакан кофе» → on_free_text → try_handle_water_text →
parse_beverage hit → add_water+beverage_slug+ml → render с milestone.
AIConcierge не вызывается."
```

---

## Task 6: Documentation update + check ai_parsers helper

**Files:**
- Modify: `mysite/maxbot/ai_parsers.py` (если ещё нет — verify imports)
- Modify: any docstring updates

- [ ] **Step 1: Verify imports**

Read top-of-file `mysite/maxbot/ai_parsers.py` — verify `re`, `json`, `logger`, `Any`, `_LLM_MODEL`, `REFUSED`, `_is_refusal` все determined. Existing parsers used them, so should be fine. If any missing — add.

Run quick smoke:
```bash
cd mysite && DJANGO_SETTINGS_MODULE=mysite.settings python -c "
import django
django.setup()
from maxbot.ai_parsers import parse_beverage, REFUSED
print('parse_beverage importable')
print('REFUSED:', REFUSED)
"
```

Expected: `parse_beverage importable`, `REFUSED: REFUSED`.

- [ ] **Step 2: No commit if no changes**

If imports ok and smoke passes, skip commit.

---

## Task 7: Final regression + push + verify staging

**Files:** (verify only)

- [ ] **Step 1: Full maxbot suite**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 453+ passed, 0 failed.

- [ ] **Step 2: Verify on_free_text intercepts водный текст**

```bash
cd mysite && DJANGO_SETTINGS_MODULE=mysite.settings python -c "
import django
django.setup()
from maxbot.handlers.water import try_handle_water_text
from maxbot.handlers.ai_assistant import on_free_text
print('try_handle_water_text:', try_handle_water_text.__module__)
print('on_free_text:', on_free_text.__module__)
import inspect
src = inspect.getsource(on_free_text)
print('hook present:', 'try_handle_water_text' in src)
"
```

Expected: `hook present: True`.

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

## Self-review checklist (после Task 7)

**Spec coverage (Design Doc v2 §7.2 + §7.4 + §7.5):**
- [x] §7.2 free-text branch «выпил кофе» → parse_beverage → add_water+beverage_slug — Tasks 1-3
- [x] §7.2 stакан/бутылка/литр serving labels — Task 1 (`_VOLUME_UNITS`)
- [x] §7.4 alcohol recovery hint — Part 2B T03 уже (через alcohol_recovery_hint flag)
- [x] §7.5 caffeine warning при pregnant + ≥200мг — Task 4
- [x] §7.5 кофе/чай separate counters в render → backlog Part 2C+ (требует дополнительные fields в WaterTodayResponse — flagged ранее)

**Placeholder scan:** все steps содержат actual code.

**Type consistency:**
- `parse_beverage(text: str, *, openai_client=None) -> dict | str | None` consistent через все callers
- Return shape: `{"beverage_slug": str, "ml": int}` или `"REFUSED"` или `None`
- `try_handle_water_text(event, context) -> bool` — boolean return для caller routing
- `render_water_added(entry, *, caffeine_warning=False)` extension consistent
- `_should_show_caffeine_warning` signature documented

---

## Не в Part 2D.1 (backlog Part 2D.2 / 2D.3 / Phase 3.2)

**Part 2D.2 (адаптивные напоминания + user-configurable time):**
- Adaptive water reminders Celery beat (4ч проверка proportional norm, opt-in OFF)
- User-configurable `daily_report_time` setting (BotUser.nutrition_settings JSON + UI keyboard)

**Part 2D.3 (daily report enhancements):**
- AI-comment ≤220 chars в daily report (требует Ayla `?with_comment=true` extension — DRF-303)
- Inline-after-18:00 trigger при ≥3 приёмов (sequencer hook в food_scanner.on_log_meal)

**Phase 3.2:**
- Расширенный beverage catalog (full ~50 slugs из Ayla, fetch + cache 1h client-side)
- Free-text restore command («верни последнюю воду»)

---

*Plan v1 закреплён 2026-05-05. Ссылается на Design Doc v2 §7.2/§7.4/§7.5
(`maxbot-phase3-nutrition-design.md`), Part 2B (`maxbot-phase3-1-2B-water-flow.md`)
foundation handlers + render_water_added, existing parse_age/height/weight
hybrid-parser pattern в ai_parsers.py.*
