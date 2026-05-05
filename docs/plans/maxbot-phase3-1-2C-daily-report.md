# MAX-бот Phase 3.1 Part 2C — Daily Report (push 21:00 + /день hybrid format)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать дневной отчёт по Design Doc v2 §6: hybrid format с эмодзи приёмов + вода + БЖУ + edge cases (<50% / ≤2 приёма / eating disorder), доступный через push 21:00 МСК (Celery beat) и `/день` команду / footer-button.

**Architecture:** New `render_daily_full_report(summary, water_today)` в `ai_ui.py` — pure-функция, объединяет food summary + water status. Существующие callers (`/дневник` команда в food_scanner, `on_view_day` footer в food_correction) переключаются с `render_daily_summary` (Part 2A) на новый combined-render. Push 21:00 — `maxbot.tasks.send_daily_reports` Celery beat task (pattern: `send_post_visit_followups` из Phase 2.4 T07). Внутри задачи: 2 async Ayla calls per user (get_water_today + daily_summary) обёрнуты в `asyncio.run(...)` (sync→async bridge), потом `notifications.max_bot.send_max_message(chat_id, text)`. **AI-comment** + **inline trigger после 18:00** + **weekly unlock** + **user-configurable daily_report_time setting** — backlog Part 2D (требуют Ayla `?with_comment=true` extension + complex sequencer + user-settings UI).

**Tech Stack:** Python 3.12 async (`asyncio.run` bridge для Celery), maxapi SDK, Celery beat (`crontab(hour=21, minute=0)` MSK через TIME_ZONE='Europe/Moscow' уже в settings.base), pytest+pytest-asyncio + pytest-django, существующие `nutrition_client.daily_summary/get_water_today`, `notifications.max_bot.send_max_message`, `BotUser.chat_id` + `nutrition_onboarded_at` + `health_flags`.

**Reference:**
- Design: `docs/plans/maxbot-phase3-nutrition-design.md` v2 §6 (дневной отчёт), §6.2 формат, §6.3 eating disorder, §6.4 edge cases
- Plan Part 2A: `maxbot-phase3-1-2A-photo-refactor.md` T11 (`on_view_day` уже calls daily_summary, но через старый `render_daily_summary`)
- Plan Part 2B: `maxbot-phase3-1-2B-water-flow.md` (`get_water_today` integration)
- Existing render: `mysite/maxbot/ai_ui.py:711-757` (`render_daily_summary` v1 — keep as legacy)
- Existing diary handler: `mysite/maxbot/handlers/food_scanner.py:on_diary_command` (/дневник text command)
- Existing view_day handler: `mysite/maxbot/handlers/food_correction.py:on_view_day` (footer click)
- Existing Celery beat patterns: `mysite/maxbot/tasks.py:155-216` (send_post_visit_followups — pattern для async-in-celery)
- Send helper: `mysite/notifications/max_bot.py:send_max_message(chat_id, text, attachments=None)`

**Existing infrastructure (DO NOT recreate):**
- `nutrition_client.daily_summary(*, external_user_id) → SummaryResponse` (date, calories_total, calories_goal, protein_g, fat_g, carbs_g, entries, raw)
- `nutrition_client.get_water_today(*, external_user_id) → WaterTodayResponse` (total_ml, norm_ml, entries, raw)
- `notifications.max_bot.send_max_message(chat_id, text, attachments=None)` — sync, REST API call с `MAX_BOT_TOKEN` proxy
- `BotUser.chat_id` (BigIntegerField) — for проактивных messages (per Phase 1 N2 reminders)
- `BotUser.nutrition_onboarded_at` — gate: don't send to non-onboarded users
- `BotUser.health_flags` (JSONField) — `eating_disorder` key для §6.3 mode
- `NUTRITION_ENABLED` setting (Part 1 hotfix) — global gate
- `DJANGO_TIMEZONE = 'Europe/Moscow'` уже в settings.base — `crontab(hour=21)` означает 21:00 МСК

---

## Architectural decisions baked into plan

1. **Combined render** — новая функция `render_daily_full_report(summary, water_today)` принимает оба response'а. `summary` обязателен; `water_today` опциональный (если `None` — раздел воды просто не рендерится). Это даёт callers гибкость: push 21:00 fetches both, `/день` команда тоже both, но при failure get_water_today можно gracefully degrade.
2. **Existing `render_daily_summary` (v1) сохраняем** — backward compat для тестов; новые callers (food_scanner.on_diary_command, food_correction.on_view_day) переключаются на `_full_report`.
3. **Celery task — sync orchestrator + asyncio.run для Ayla calls** — Celery worker по умолчанию sync. Ayla calls async (через httpx). Pattern: `asyncio.run(_fetch_data(extid))` в sync task body. Existing `send_post_visit_followups` — reference (sync ORM + sync send_max_message).
4. **NUTRITION_ENABLED gate в Celery task** — если флаг false: log + early return. Не итерируем юзеров (Ayla же не работает, бессмысленно).
5. **Per-user filter** — только BotUser с `nutrition_onboarded_at IS NOT NULL` И `chat_id IS NOT NULL`. Не-onboarded users не получают спам, без chat_id некуда слать.
6. **Hardcoded 21:00 МСК** — user-configurable `daily_report_time` (через `BotUser.nutrition_settings["daily_report_time"]`, default "21:00") — **backlog Part 2D**. MVP: все юзеры в 21:00.
7. **AI-comment** — Design §6.2 mock'ает «*Хороший день — почти в норму. Завтра попробуй больше белка...*». Это требует Ayla `GET /summary/?with_comment=true` extension (DRF-303). **Backlog Part 2D**. MVP: render без AI-комментария (только factual data).
8. **Footer buttons [📊 Неделя][⚙️ Время отчёта]** — стабы «Скоро» (week unlock — Design §6.6 backlog Phase 3.3, time setting — backlog Part 2D).
9. **Edge cases** (Design §6.4) — `<50%` или `≤2 приёма` → alternative «*в дневнике сегодня немного: завтрак (320 ккал)... Если что-то ещё ела — добавь*». Render-level routing на основе summary fields.
10. **Eating disorder mode** (Design §6.3) — `bot_user.health_flags.get("eating_disorder")` → отдельный шаблон без чисел калорий («*Сегодня: завтрак, обед, ужин, 1 перекус. 1.8 л воды. Как ты сегодня? День получился?*»). Render принимает optional `eating_disorder=False` kwarg, switching to supportive template.
11. **Inline-после-18:00 trigger при ≥3 приёмов** — Design Doc §6.1 точка #3 — **backlog Part 2D**. Требует event hook в food_scanner.on_log_meal (count entries today, if crosses 3 + after 18:00 + first time evening → push). Сложный sequencer.

---

## File Structure

**Create:**
- `mysite/tests/maxbot/test_render_daily_full_report.py` — render tests (basic, edge cases, eating disorder)
- `mysite/tests/maxbot/test_send_daily_reports.py` — Celery task tests (gate, filter, dispatch)

**Modify:**
- `mysite/maxbot/keyboards.py` — добавить `PAYLOAD_REPORT_WEEKLY`, `PAYLOAD_REPORT_TIME_SETTINGS` + `daily_report_footer_keyboard()` (2 stub-buttons)
- `mysite/maxbot/ai_ui.py` — `render_daily_full_report(summary, water_today=None, *, eating_disorder=False)` + helpers `_render_meal_emoji_for_time`, `_render_water_block`, `_render_eating_disorder_summary`
- `mysite/maxbot/handlers/food_scanner.py:on_diary_command` — fetch water_today + summary, call new render, attach footer keyboard
- `mysite/maxbot/handlers/food_correction.py:on_view_day` — same update
- `mysite/maxbot/handlers/food_correction.py` — добавить `on_report_weekly_stub`, `on_report_time_settings_stub` (backlog placeholders)
- `mysite/maxbot/tasks.py` — добавить `@shared_task(name="maxbot.tasks.send_daily_reports", bind=True, max_retries=1)` с asyncio.run bridge
- `mysite/mysite/settings/base.py` — добавить beat-расписание `maxbot-daily-reports-2100-msk` → `crontab(hour=21, minute=0)`

**Reference (read-only — copy patterns):**
- `mysite/maxbot/tasks.py:send_post_visit_followups` — Celery sync task pattern, ORM filter + send_max_message
- `mysite/maxbot/services/nutrition_client.py:daily_summary` + `get_water_today` — async clients

---

## Task 1: `render_daily_full_report` — base hybrid format

**Files:**
- Modify: `mysite/maxbot/ai_ui.py`
- Create: `mysite/tests/maxbot/test_render_daily_full_report.py`

- [ ] **Step 1: Write failing test**

```python
# mysite/tests/maxbot/test_render_daily_full_report.py
"""Phase 3.1 Part 2C T01: hybrid daily report render."""
from __future__ import annotations

from unittest.mock import MagicMock


def test_render_daily_full_report_includes_meals_water_macros():
    """Базовый формат (Design §6.2): emoji приёмов + ккал + БЖУ + вода."""
    from maxbot.ai_ui import render_daily_full_report

    summary = MagicMock(
        date="30 апреля",
        calories_total=1380, calories_goal=1450,
        protein_g=98, fat_g=52, carbs_g=145,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша с ягодами", "calories": 320},
            {"meal_type": "lunch", "dish_name": "борщ + гречка", "calories": 520},
            {"meal_type": "dinner", "dish_name": "рыба + овощи", "calories": 380},
            {"meal_type": "snack", "dish_name": "яблоко + орехи", "calories": 160},
        ],
    )
    water_today = MagicMock(total_ml=1800, norm_ml=2000)

    text = render_daily_full_report(summary, water_today)

    # Header
    assert "30 апреля" in text or "Итоги" in text or "🌙" in text
    # Calories progress
    assert "1380" in text
    assert "1450" in text
    # Macros
    assert "98" in text and "52" in text and "145" in text
    # Water
    assert "1.8" in text or "1800" in text
    assert "2.0" in text or "2000" in text
    # Meals — emoji per time-of-day (per Design §6.2: 🌅 ☀️ 🌙 🍎)
    assert "каша с ягодами" in text
    assert "борщ" in text
    assert "рыба" in text
    assert "320" in text  # breakfast kcal


def test_render_daily_full_report_without_water_omits_water_section():
    """water_today=None → water раздел просто отсутствует (не падает)."""
    from maxbot.ai_ui import render_daily_full_report

    summary = MagicMock(
        date="2026-05-04",
        calories_total=800, calories_goal=1450,
        protein_g=40, fat_g=20, carbs_g=80,
        entries=[
            {"meal_type": "breakfast", "dish_name": "омлет", "calories": 400},
            {"meal_type": "lunch", "dish_name": "суп", "calories": 400},
        ],
    )

    text = render_daily_full_report(summary, water_today=None)
    # Не должно быть "💧" или "л воды"
    assert "💧" not in text
    assert "омлет" in text
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_render_daily_full_report.py -v`
Expected: ImportError на `render_daily_full_report`.

- [ ] **Step 3: Add render function**

В `mysite/maxbot/ai_ui.py` ДОБАВИТЬ (после существующей `render_daily_summary`, около line 757):

```python
# ─── Phase 3.1 Part 2C: hybrid daily report ────────────────────────────────


def render_daily_full_report(
    summary,
    water_today=None,
    *,
    eating_disorder: bool = False,
) -> str:
    """Phase 3.1 Part 2C: дневной отчёт hybrid format (Design §6.2).

    Args:
        summary: SummaryResponse — обязателен (date, calories_*, protein/fat/carbs, entries)
        water_today: WaterTodayResponse | None — если None, water раздел skipped
        eating_disorder: bool — if True, supportive template без чисел калорий (§6.3)

    Returns:
        Multi-line text. Каллер сам прикрепляет attachments (footer keyboard).

    Edge cases:
        - <50% от daily_kcal goal или ≤2 приёма → §6.4 alternative "немного"
        - eating_disorder=True → §6.3 supportive template, no numbers

    NOT included (Part 2D backlog):
        - AI-comment (требует Ayla `?with_comment=true` extension)
        - Weekly unlock indicator (требует tracking 7-day FoodEntry streak)
    """
    if eating_disorder:
        return _render_eating_disorder_summary(summary, water_today)

    entries = list(summary.entries) if summary.entries else []
    cals_total = float(summary.calories_total or 0)
    cals_goal = int(summary.calories_goal or 0)

    # Edge case: very thin day → alternative template
    if _is_thin_day(cals_total, cals_goal, entries):
        return _render_thin_day_summary(summary, water_today)

    return _render_full_day_summary(summary, water_today)


def _is_thin_day(
    cals_total: float, cals_goal: int, entries: list,
) -> bool:
    """Design §6.4 — <50% или ≤2 приёма."""
    if len(entries) <= 2:
        return True
    if cals_goal > 0 and cals_total < 0.5 * cals_goal:
        return True
    return False


def _render_full_day_summary(summary, water_today) -> str:
    """Default daily report — все приёмы + БЖУ + вода + Итого."""
    date_str = getattr(summary, "date", "сегодня") or "сегодня"
    cals_total = int(getattr(summary, "calories_total", 0) or 0)
    cals_goal = int(getattr(summary, "calories_goal", 0) or 0)
    protein = float(getattr(summary, "protein_g", 0) or 0)
    fat = float(getattr(summary, "fat_g", 0) or 0)
    carbs = float(getattr(summary, "carbs_g", 0) or 0)
    entries = list(getattr(summary, "entries", []) or [])

    lines = [f"🌙 Итоги дня — {date_str}", ""]

    # Header: ккал progress + percent
    if cals_goal > 0:
        pct = int(round(100 * cals_total / cals_goal))
        lines.append(f"🎯 {cals_total} / {cals_goal} ккал ({pct}%)")
    else:
        lines.append(f"🎯 {cals_total} ккал")

    # Macros
    lines.append(
        f"🥩 Б {protein:.0f}  🥑 Ж {fat:.0f}  🌾 У {carbs:.0f}"
    )

    # Water (if provided)
    water_block = _render_water_block(water_today)
    if water_block:
        lines.append(water_block)

    # Meals
    if entries:
        lines.append("")
        lines.append("Приёмы:")
        for e in entries:
            meal_type = e.get("meal_type") or "snack"
            dish = e.get("dish_name") or "—"
            kcal = int(e.get("calories") or 0)
            emoji = _meal_emoji(meal_type)
            lines.append(f"{emoji} {dish} — {kcal}")

    return "\n".join(lines)


def _meal_emoji(meal_type: str) -> str:
    """Design §6.2: emoji per meal_type."""
    return {
        "breakfast": "🌅",
        "lunch": "☀️",
        "dinner": "🌙",
        "snack": "🍎",
    }.get(meal_type, "🍽")


def _render_water_block(water_today) -> str:
    """Format «💧 1.8 / 2.0 л» если water_today передан, иначе пустая строка."""
    if water_today is None:
        return ""
    total_ml = int(getattr(water_today, "total_ml", 0) or 0)
    norm_ml = int(getattr(water_today, "norm_ml", 0) or 0)
    total_str = f"{total_ml / 1000:.1f} л" if total_ml >= 1000 else f"{total_ml} мл"
    norm_str = f"{norm_ml / 1000:.1f} л" if norm_ml >= 1000 else f"{norm_ml} мл"
    return f"💧 {total_str} / {norm_str}"


def _render_thin_day_summary(summary, water_today) -> str:
    """Edge case (§6.4): <50% или ≤2 приёма — supportive «немного»."""
    date_str = getattr(summary, "date", "сегодня") or "сегодня"
    entries = list(getattr(summary, "entries", []) or [])

    lines = [f"🌙 Итоги дня — {date_str}", ""]

    if entries:
        # Кратко перечислить что есть
        first = entries[0]
        first_name = first.get("dish_name") or "что-то"
        first_kcal = int(first.get("calories") or 0)
        if len(entries) == 1:
            lines.append(
                f"В дневнике сегодня немного: {first_name} "
                f"({first_kcal} ккал)."
            )
        else:
            lines.append(
                f"В дневнике сегодня {len(entries)} приёма "
                f"(начиная с {first_name})."
            )
        lines.append("Если что-то ещё ела — добавь, посчитаю.")
    else:
        lines.append("Сегодня записей нет.")
        lines.append("Сфоткай еду — добавлю в дневник.")

    water_block = _render_water_block(water_today)
    if water_block:
        lines.append("")
        lines.append(water_block)

    lines.append("")
    lines.append("Если пропустила приёмы — как самочувствие сегодня?")

    return "\n".join(lines)


def _render_eating_disorder_summary(summary, water_today) -> str:
    """§6.3 — supportive template без чисел калорий.

    Считаем приёмы по типам, никаких ккал/БЖУ цифр.
    """
    date_str = getattr(summary, "date", "сегодня") or "сегодня"
    entries = list(getattr(summary, "entries", []) or [])

    lines = [f"🌙 День — {date_str}", ""]

    if entries:
        # Группировка по meal_type
        by_meal: dict[str, int] = {}
        for e in entries:
            mt = e.get("meal_type") or "snack"
            by_meal[mt] = by_meal.get(mt, 0) + 1
        meal_names = {
            "breakfast": "завтрак", "lunch": "обед",
            "dinner": "ужин", "snack": "перекус",
        }
        meal_descriptors = []
        for key in ("breakfast", "lunch", "dinner", "snack"):
            count = by_meal.get(key, 0)
            if count == 0:
                continue
            label = meal_names[key]
            if count > 1 and key == "snack":
                meal_descriptors.append(f"{count} {label}а")
            else:
                meal_descriptors.append(label)
        if meal_descriptors:
            lines.append(f"Сегодня: {', '.join(meal_descriptors)}.")

    # Вода — без процентов
    if water_today is not None:
        total_ml = int(getattr(water_today, "total_ml", 0) or 0)
        if total_ml > 0:
            total_str = f"{total_ml / 1000:.1f} л" if total_ml >= 1000 else f"{total_ml} мл"
            lines.append(f"{total_str} воды.")

    lines.append("")
    lines.append("💬 Как ты сегодня? День получился?")

    return "\n".join(lines)
```

- [ ] **Step 4: Run tests — must pass**

Run: `pytest mysite/tests/maxbot/test_render_daily_full_report.py -v`
Expected: 2 passed.

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 422 passed (420 baseline + 2 new).

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/ai_ui.py mysite/tests/maxbot/test_render_daily_full_report.py
git commit -m "feat(maxbot): render_daily_full_report hybrid format (Part 2C T01)

Design §6.2 hybrid: header + ккал/% + БЖУ + 💧 вода + emoji приёмов.
Helpers: _meal_emoji, _render_water_block, _is_thin_day, _render_full_day,
_render_thin_day, _render_eating_disorder. Thin day (§6.4) и eating
disorder (§6.3) — full implemented в render. AI-comment + weekly unlock —
backlog Part 2D."
```

## Context

- Working dir: `C:\Users\user\PycharmProjects\mysite`
- Working git branch: `dev`
- Base SHA: `5ad964b` (Part 2B HEAD — Part 2C plan тут commit'нется отдельно перед T01)
- Plan source: `docs/plans/maxbot-phase3-1-2C-daily-report.md` Task 1

`SummaryResponse` fields: date, calories_total (float), calories_goal (int), protein_g/fat_g/carbs_g (float), entries (list[dict]).

`WaterTodayResponse` fields: total_ml (int), norm_ml (int), entries, raw.

Existing `render_daily_summary` (v1) НЕ удаляем — backward compat для Part 2A on_view_day тестов. T04 переключит callers на v2.

---

## Task 2: Edge case + eating disorder coverage tests

**Files:**
- Modify: `mysite/tests/maxbot/test_render_daily_full_report.py`

- [ ] **Step 1: Write failing tests**

APPEND:

```python
def test_render_thin_day_with_one_entry_says_only():
    """≤2 entries → §6.4 supportive template."""
    from maxbot.ai_ui import render_daily_full_report

    summary = MagicMock(
        date="2026-05-04",
        calories_total=320, calories_goal=1450,
        protein_g=12, fat_g=8, carbs_g=40,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
        ],
    )
    text = render_daily_full_report(summary, water_today=None)

    # Supportive template
    assert "немного" in text.lower() or "не" in text.lower()
    assert "каша" in text
    # Спрашивает «как самочувствие»
    assert "самочувств" in text.lower() or "пропустила" in text.lower()


def test_render_thin_day_under_50_percent_calories():
    """3+ entries но <50% от goal → thin-day template."""
    from maxbot.ai_ui import render_daily_full_report

    summary = MagicMock(
        date="2026-05-04",
        calories_total=600, calories_goal=1500,  # 40% — under 50
        protein_g=30, fat_g=20, carbs_g=60,
        entries=[
            {"meal_type": "breakfast", "dish_name": "тост", "calories": 200},
            {"meal_type": "lunch", "dish_name": "салат", "calories": 250},
            {"meal_type": "snack", "dish_name": "яблоко", "calories": 150},
        ],
    )
    text = render_daily_full_report(summary, water_today=None)

    assert "немного" in text.lower() or "пропустила" in text.lower()


def test_render_eating_disorder_mode_no_calories():
    """eating_disorder=True → нет цифр калорий, supportive «как ты сегодня?»."""
    from maxbot.ai_ui import render_daily_full_report

    summary = MagicMock(
        date="2026-05-04",
        calories_total=1300, calories_goal=1450,
        protein_g=80, fat_g=40, carbs_g=130,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
            {"meal_type": "lunch", "dish_name": "суп", "calories": 450},
            {"meal_type": "dinner", "dish_name": "рыба", "calories": 380},
            {"meal_type": "snack", "dish_name": "орехи", "calories": 150},
        ],
    )
    water_today = MagicMock(total_ml=1800, norm_ml=2000)

    text = render_daily_full_report(
        summary, water_today, eating_disorder=True,
    )

    # No calorie numbers
    assert "1300" not in text
    assert "1450" not in text
    assert "ккал" not in text
    # Supportive vibe
    assert "Как ты сегодня" in text or "День получился" in text
    # Meal mentions без чисел
    assert "завтрак" in text.lower() or "обед" in text.lower()
```

- [ ] **Step 2: Run — must pass (already covered by T01 implementation)**

Run: `pytest mysite/tests/maxbot/test_render_daily_full_report.py -v`
Expected: 5 passed (2 prior + 3 new).

If какой-то тест fails — баг в T01 implementation; fix it inline (не отдельным task).

- [ ] **Step 3: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 425 passed (422 + 3).

- [ ] **Step 4: Commit**

```bash
git add mysite/tests/maxbot/test_render_daily_full_report.py
git commit -m "test(maxbot): edge cases + eating disorder coverage (Part 2C T02)

3 теста: ≤2 entries (thin day), <50% calories (thin day), eating_disorder
(supportive без цифр). Code от T01 уже покрывает все ветки."
```

---

## Task 3: Footer keyboard with stub buttons [📊 Неделя][⚙️ Время]

**Files:**
- Modify: `mysite/maxbot/keyboards.py`
- Create: `mysite/tests/maxbot/test_daily_report_keyboard.py`

- [ ] **Step 1: Write failing test**

```python
# mysite/tests/maxbot/test_daily_report_keyboard.py
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
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_daily_report_keyboard.py -v`
Expected: ImportError.

- [ ] **Step 3: Add constants + helper**

В `mysite/maxbot/keyboards.py` ПОСЛЕ существующего блока Part 2B (после `PAYLOAD_WATER_UNDO_PREFIX`) ДОБАВИТЬ:

```python
# ─── Phase 3.1 Part 2C: daily report footer ────────────────────────────────

PAYLOAD_REPORT_WEEKLY = "cb:report:weekly"
PAYLOAD_REPORT_TIME_SETTINGS = "cb:report:time"
```

В **конец файла** (после `water_undo_keyboard`) ДОБАВИТЬ:

```python
def daily_report_footer_keyboard():
    """Footer для дневного отчёта (Design §6.2): [📊 Неделя][⚙️ Время отчёта].

    Both — stubs до Part 2D / Phase 3.3. [📊 Неделя] требует tracking 7-day
    FoodEntry streak (weekly unlock §6.6). [⚙️ Время отчёта] требует
    user-settings UI for daily_report_time JSON.
    """
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="📊 Неделя", payload=PAYLOAD_REPORT_WEEKLY),
        CallbackButton(text="⚙️ Время отчёта", payload=PAYLOAD_REPORT_TIME_SETTINGS),
    )
    return builder.as_markup()
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_daily_report_keyboard.py -v`
Expected: 1 passed.

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 426 passed (425 + 1).

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/keyboards.py mysite/tests/maxbot/test_daily_report_keyboard.py
git commit -m "feat(maxbot): daily_report_footer_keyboard with 2 stubs (Part 2C T03)

[📊 Неделя][⚙️ Время отчёта] — both stub'ы до Part 2D / Phase 3.3.
Weekly unlock (§6.6) — backlog 3.3. Time settings — backlog 2D."
```

---

## Task 4: Stub handlers for footer buttons

**Files:**
- Modify: `mysite/maxbot/handlers/food_correction.py`
- Modify: `mysite/tests/maxbot/test_food_correction.py`

- [ ] **Step 1: Write failing tests**

APPEND в `mysite/tests/maxbot/test_food_correction.py`:

```python
@pytest.mark.asyncio
async def test_report_weekly_stub_says_coming_soon():
    """[📊 Неделя] → заглушка Phase 3.3."""
    from maxbot.handlers.food_correction import on_report_weekly_stub

    cb = _fake_callback("cb:report:weekly")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_report_weekly_stub(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Скоро" in text or "разработ" in text.lower() or "после 7" in text


@pytest.mark.asyncio
async def test_report_time_settings_stub_says_coming_soon():
    """[⚙️ Время отчёта] → заглушка Part 2D."""
    from maxbot.handlers.food_correction import on_report_time_settings_stub

    cb = _fake_callback("cb:report:time")
    ctx = MemoryContext(chat_id=100, user_id=200)

    await on_report_time_settings_stub(cb, ctx)

    text = cb.bot.send_message.await_args.kwargs["text"]
    assert "Скоро" in text or "21" in text  # 21:00 default mention
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_food_correction.py -v -k "report_weekly_stub or report_time_settings"`
Expected: ImportError.

- [ ] **Step 3: Add handlers**

В `mysite/maxbot/handlers/food_correction.py` ДОБАВИТЬ (после `on_view_day` — последний handler):

```python
@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_REPORT_WEEKLY,
)
async def on_report_weekly_stub(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[📊 Неделя] — заглушка Phase 3.3 (требует tracking 7-day FoodEntry streak)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "📊 Недельный отчёт скоро добавлю — нужно собрать данные за "
            "7 дней с записями. Продолжай вести дневник, и через неделю "
            "покажу тренды."
        ),
    )


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_REPORT_TIME_SETTINGS,
)
async def on_report_time_settings_stub(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """[⚙️ Время отчёта] — заглушка Part 2D (требует user-settings UI)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "⚙️ Настройка времени отчёта скоро будет — пока шлю в 21:00 "
            "по Москве. Если неудобно — напиши, скорректируем."
        ),
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_food_correction.py -v`
Expected: 8 passed (6 prior + 2 new).

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 428 passed (426 + 2).

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/food_correction.py mysite/tests/maxbot/test_food_correction.py
git commit -m "feat(maxbot): footer report stubs (Part 2C T04)

[📊 Неделя] — Phase 3.3 backlog (требует 7-day streak tracking).
[⚙️ Время отчёта] — Part 2D backlog (требует user-settings UI).
Default 21:00 МСК hardcoded в Celery beat (T07)."
```

---

## Task 5: Update `on_diary_command` and `on_view_day` to use new render

**Files:**
- Modify: `mysite/maxbot/handlers/food_scanner.py:on_diary_command`
- Modify: `mysite/maxbot/handlers/food_correction.py:on_view_day`
- Modify: `mysite/tests/maxbot/test_food_scanner_v2.py` или существующий test_food_correction.py

- [ ] **Step 1: Write failing test (for on_view_day с water fetch)**

APPEND в `mysite/tests/maxbot/test_food_correction.py`:

```python
@pytest.mark.asyncio
async def test_view_day_fetches_water_and_renders_full_report(monkeypatch, settings):
    """on_view_day теперь fetch'ит summary + water_today, render через
    render_daily_full_report. Footer-keyboard прикрепляется."""
    from maxbot.handlers.food_correction import on_view_day
    from maxbot.keyboards import (
        PAYLOAD_REPORT_WEEKLY, PAYLOAD_REPORT_TIME_SETTINGS,
    )
    from maxbot.services.nutrition_client import (
        SummaryResponse, WaterTodayResponse,
    )

    settings.NUTRITION_ENABLED = True

    summary_mock = AsyncMock(return_value=SummaryResponse(
        date="2026-05-04",
        calories_total=1100, calories_goal=1450,
        protein_g=65, fat_g=40, carbs_g=110,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
            {"meal_type": "lunch", "dish_name": "суп", "calories": 450},
            {"meal_type": "dinner", "dish_name": "рыба", "calories": 330},
        ],
        raw={},
    ))
    water_mock = AsyncMock(return_value=WaterTodayResponse(
        total_ml=1500, norm_ml=2000,
        entries=[],
        raw={},
    ))
    fake_client = MagicMock(daily_summary=summary_mock, get_water_today=water_mock)
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_nutrition_client",
        lambda: fake_client,
    )
    bot_user = MagicMock(max_user_id=200, health_flags={})
    monkeypatch.setattr(
        "maxbot.handlers.food_correction.get_or_create_bot_user",
        AsyncMock(return_value=(bot_user, False)),
    )

    cb = _fake_callback("cb:nutrition:view_day")
    ctx = MemoryContext(chat_id=100, user_id=200)
    await on_view_day(cb, ctx)

    summary_mock.assert_awaited_once()
    water_mock.assert_awaited_once()

    cb.bot.send_message.assert_awaited_once()
    text = cb.bot.send_message.await_args.kwargs["text"]
    # Combined render — есть и kcal и water
    assert "1100" in text or "1450" in text
    assert "1.5" in text or "1500" in text  # water

    atts = cb.bot.send_message.await_args.kwargs.get("attachments") or []
    payloads = _flatten_payloads(atts[0]) if atts else set()
    assert PAYLOAD_REPORT_WEEKLY in payloads
    assert PAYLOAD_REPORT_TIME_SETTINGS in payloads
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_food_correction.py::test_view_day_fetches_water_and_renders_full_report -v`
Expected: FAIL — текущий on_view_day не вызывает water_mock.assert_awaited_once.

- [ ] **Step 3: Update on_view_day**

В `mysite/maxbot/handlers/food_correction.py` найти `on_view_day` и **переписать** его:

```python
@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_NUTRITION_VIEW_DAY,
)
async def on_view_day(callback: MessageCallback, context: MemoryContext) -> None:
    """[📊 Посмотреть день] из footer scan-карточки → hybrid daily report
    (Part 2C: daily_summary + get_water_today + render_daily_full_report)."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None or callback.callback.user is None:
        return
    user_id = callback.callback.user.user_id
    full_name = callback.callback.user.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)

    extid = external_user_id_for(bot_user)
    client = get_nutrition_client()

    # Fetch both summary + water — water optional (если падает, render skip раздел)
    try:
        summary = await client.daily_summary(external_user_id=extid)
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

    water_today = None
    try:
        water_today = await client.get_water_today(external_user_id=extid)
    except (NutritionUnavailableError, NutritionAPIError):
        # Water optional — silently skip раздел
        logger.info("food_correction.view_day water unavailable for user=%s",
                    bot_user.max_user_id)

    eating_disorder = bool(
        (bot_user.health_flags or {}).get("eating_disorder", False)
    )
    text = ai_ui.render_daily_full_report(
        summary, water_today, eating_disorder=eating_disorder,
    )
    await callback.bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[keyboards.daily_report_footer_keyboard()],
    )
```

В `mysite/maxbot/handlers/food_scanner.py` найти `on_diary_command` и **переписать аналогично**:

```python
@router.message_created(F.message.body.text.lower().in_(("/дневник", "/diary", "дневник")))
async def on_diary_command(event: MessageCreated, context: MemoryContext) -> None:
    """`/дневник` → hybrid daily report (Part 2C: summary + water + render)."""
    if event.message.sender is None:
        return
    chat_id = event.message.recipient.chat_id
    sender = event.message.sender
    bot_user, _ = await get_or_create_bot_user(sender.user_id, sender.full_name)

    extid = external_user_id_for(bot_user)
    client = get_nutrition_client()

    try:
        summary = await client.daily_summary(external_user_id=extid)
    except NutritionUnavailableError:
        await send_with_main_menu(
            bot=event.bot, chat_id=chat_id,
            text="Дневник временно недоступен. Попробуй через минуту.",
            bot_user=bot_user,
        )
        return
    except NutritionAPIError as exc:
        logger.exception("food_scanner.summary.api_error user=%s err=%s",
                         bot_user.max_user_id, exc)
        await send_with_main_menu(
            bot=event.bot, chat_id=chat_id,
            text="Не получилось загрузить дневник.",
            bot_user=bot_user,
        )
        return

    water_today = None
    try:
        water_today = await client.get_water_today(external_user_id=extid)
    except (NutritionUnavailableError, NutritionAPIError):
        logger.info("food_scanner.diary water unavailable for user=%s",
                    bot_user.max_user_id)

    eating_disorder = bool(
        (bot_user.health_flags or {}).get("eating_disorder", False)
    )
    text = ai_ui.render_daily_full_report(
        summary, water_today, eating_disorder=eating_disorder,
    )
    await event.bot.send_message(
        chat_id=chat_id,
        text=text,
        attachments=[keyboards.daily_report_footer_keyboard()],
    )
```

- [ ] **Step 4: Run tests — must pass**

Run: `pytest mysite/tests/maxbot/test_food_correction.py -v`
Expected: 9 passed (8 prior + 1 new).

Run: `pytest mysite/tests/maxbot/test_food_scanner_v2.py -v` (existing tests still pass — `on_log_meal` etc.)

- [ ] **Step 5: Update existing on_view_day test (T11 от Part 2A) если нужно**

Если падает старый `test_view_day_calls_daily_summary` (T11 Part 2A) — там mock не имеет water + не ассертит footer. Adapt: либо удалить (replaced by new), либо добавить water_mock в mock setup.

Простейший подход — **удалить** старый test (replaced by new comprehensive one в этом T05). Найти `test_view_day_calls_daily_summary` в test_food_correction.py и удалить.

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: ~428 passed (вместо 1 удалённого + 1 новый = same count, или + если оба остались).

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/handlers/food_correction.py mysite/maxbot/handlers/food_scanner.py mysite/tests/maxbot/test_food_correction.py
git commit -m "feat(maxbot): on_view_day + on_diary_command use full report (Part 2C T05)

Both fetch'ят summary + water_today (water optional — gracefully skip
если Ayla падает). Eating disorder mode читает bot_user.health_flags.
Footer keyboard [📊 Неделя][⚙️ Время отчёта] прикреплён."
```

---

## Task 6: `keyboards.daily_report_footer_keyboard` import setup verification

This task is QA-only — verify Part 2C-mid state by running всё suite, sanity-check router list integrity. No code changes.

- [ ] **Step 1: Run full suite**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 428+ passed.

- [ ] **Step 2: Verify routers**

```bash
cd mysite && DJANGO_SETTINGS_MODULE=mysite.settings python -c "
import django
django.setup()
from maxbot.handlers import get_routers
routers = get_routers()
print(f'Total: {len(routers)}')
"
```

Expected: Total: 14 (no new router added in Part 2C).

- [ ] **Step 3: Skip commit (no code changes)**

If checks pass, proceed to T07.

---

## Task 7: Celery beat task `send_daily_reports`

**Files:**
- Modify: `mysite/maxbot/tasks.py`
- Modify: `mysite/mysite/settings/base.py` (add beat schedule)
- Create: `mysite/tests/maxbot/test_send_daily_reports.py`

- [ ] **Step 1: Write failing tests**

```python
# mysite/tests/maxbot/test_send_daily_reports.py
"""Phase 3.1 Part 2C T07: Celery beat task для дневного отчёта в 21:00."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from model_bakery import baker

from services_app.models import BotUser


pytestmark = pytest.mark.django_db


def test_send_daily_reports_skipped_when_nutrition_disabled(settings):
    """NUTRITION_ENABLED=False → task return early, no users iterated."""
    from maxbot.tasks import send_daily_reports

    settings.NUTRITION_ENABLED = False

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        # Even if users exist, send_max_message не должен быть вызван
        baker.make(
            BotUser, max_user_id=99,
            chat_id=100, nutrition_onboarded_at="2026-04-30T12:00:00Z",
        )

        # Run task synchronously
        send_daily_reports()

        send_mock.assert_not_called()
        client_factory.assert_not_called()


def test_send_daily_reports_skips_users_without_chat_id(settings):
    """User без chat_id → пропускается (некуда слать)."""
    from maxbot.tasks import send_daily_reports

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99,
        chat_id=None,  # missing
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
    )

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            daily_summary=AsyncMock(),
            get_water_today=AsyncMock(),
        )

        send_daily_reports()

        send_mock.assert_not_called()


def test_send_daily_reports_skips_non_onboarded_users(settings):
    """User без nutrition_onboarded_at → пропускается."""
    from maxbot.tasks import send_daily_reports

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99, chat_id=100,
        nutrition_onboarded_at=None,
    )

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            daily_summary=AsyncMock(),
            get_water_today=AsyncMock(),
        )

        send_daily_reports()

        send_mock.assert_not_called()


def test_send_daily_reports_dispatches_to_eligible_user(settings):
    """User onboarded + chat_id → daily_summary + get_water_today + send_max_message."""
    from maxbot.tasks import send_daily_reports
    from maxbot.services.nutrition_client import (
        SummaryResponse, WaterTodayResponse,
    )

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99, chat_id=12345,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
        health_flags={},
    )

    summary = SummaryResponse(
        date="2026-05-04",
        calories_total=1380, calories_goal=1450,
        protein_g=98, fat_g=52, carbs_g=145,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
            {"meal_type": "lunch", "dish_name": "борщ", "calories": 520},
            {"meal_type": "dinner", "dish_name": "рыба", "calories": 380},
            {"meal_type": "snack", "dish_name": "яблоко", "calories": 160},
        ],
        raw={},
    )
    water_today = WaterTodayResponse(
        total_ml=1800, norm_ml=2000, entries=[], raw={},
    )

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            daily_summary=AsyncMock(return_value=summary),
            get_water_today=AsyncMock(return_value=water_today),
        )

        send_daily_reports()

        send_mock.assert_called_once()
        args, kwargs = send_mock.call_args
        # send_max_message(chat_id, text, attachments=None) — позиционный chat_id
        assert args[0] == 12345 or kwargs.get("chat_id") == 12345
        text = args[1] if len(args) > 1 else kwargs.get("text", "")
        # Hybrid format — есть kcal + water
        assert "1380" in text or "1450" in text
        assert "1.8" in text or "1800" in text
```

- [ ] **Step 2: Run — must fail**

Run: `pytest mysite/tests/maxbot/test_send_daily_reports.py -v`
Expected: ImportError на `maxbot.tasks.send_daily_reports`.

- [ ] **Step 3: Add Celery task**

В `mysite/maxbot/tasks.py` ДОБАВИТЬ (в конец файла):

```python
# ─── Phase 3.1 Part 2C: daily report push 21:00 МСК ────────────────────────


from notifications.max_bot import send_max_message
from maxbot import ai_ui
from maxbot.services.ayla_user_proxy import external_user_id_for
from maxbot.services.nutrition_client import (
    NutritionAPIError,
    NutritionUnavailableError,
    get_nutrition_client,
)


@shared_task(name="maxbot.tasks.send_daily_reports", bind=True, max_retries=1)
def send_daily_reports(self):
    """Phase 3.1 Part 2C: push дневного отчёта в 21:00 МСК.

    Filter:
      - settings.NUTRITION_ENABLED == True (global gate)
      - BotUser.nutrition_onboarded_at IS NOT NULL (анкета пройдена)
      - BotUser.chat_id IS NOT NULL (есть куда слать)

    Per-user:
      - Fetch daily_summary + get_water_today (asyncio.run bridge).
      - Render через render_daily_full_report (eating_disorder из health_flags).
      - send_max_message(chat_id, text, attachments=keyboard).

    Errors:
      - Per-user (Ayla unavailable / API error): log + skip (next user).
      - Глобал ошибка (DB / Redis / Celery): retry до max_retries=1.
    """
    import asyncio

    from django.conf import settings as django_settings
    from services_app.models import BotUser

    if not getattr(django_settings, "NUTRITION_ENABLED", False):
        logger.info("daily_reports.skipped — NUTRITION_ENABLED=False")
        return

    eligible = BotUser.objects.filter(
        nutrition_onboarded_at__isnull=False,
        chat_id__isnull=False,
    )
    sent = 0
    skipped = 0

    client = get_nutrition_client()

    for bot_user in eligible.iterator():
        extid = external_user_id_for(bot_user)
        try:
            summary, water_today = asyncio.run(_fetch_daily_data(client, extid))
        except (NutritionUnavailableError, NutritionAPIError) as exc:
            logger.warning(
                "daily_reports.fetch_failed user=%s err=%s",
                bot_user.max_user_id, exc,
            )
            skipped += 1
            continue
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "daily_reports.fetch_unexpected user=%s err=%s",
                bot_user.max_user_id, exc,
            )
            skipped += 1
            continue

        eating_disorder = bool(
            (bot_user.health_flags or {}).get("eating_disorder", False)
        )
        text = ai_ui.render_daily_full_report(
            summary, water_today, eating_disorder=eating_disorder,
        )
        try:
            send_max_message(bot_user.chat_id, text, attachments=None)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "daily_reports.send_failed user=%s chat=%s err=%s",
                bot_user.max_user_id, bot_user.chat_id, exc,
            )
            skipped += 1

    logger.info("daily_reports.done sent=%d skipped=%d", sent, skipped)
    return {"sent": sent, "skipped": skipped}


async def _fetch_daily_data(client, external_user_id):
    """Fetch summary + water_today concurrently. Water — optional."""
    summary = await client.daily_summary(external_user_id=external_user_id)
    water_today = None
    try:
        water_today = await client.get_water_today(external_user_id=external_user_id)
    except (NutritionUnavailableError, NutritionAPIError):
        # Water gracefully skipped
        pass
    return summary, water_today
```

В `mysite/mysite/settings/base.py` найти существующий `CELERY_BEAT_SCHEDULE` блок (около line 240-290) и ДОБАВИТЬ:

```python
    "maxbot-daily-reports-2100-msk": {
        "task": "maxbot.tasks.send_daily_reports",
        "schedule": crontab(hour=21, minute=0),
    },
```

- [ ] **Step 4: Run tests**

Run: `pytest mysite/tests/maxbot/test_send_daily_reports.py -v`
Expected: 4 passed.

- [ ] **Step 5: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 432+ passed (428 + 4).

- [ ] **Step 6: Commit**

```bash
git add mysite/maxbot/tasks.py mysite/mysite/settings/base.py mysite/tests/maxbot/test_send_daily_reports.py
git commit -m "feat(maxbot): send_daily_reports Celery beat 21:00 МСК (Part 2C T07)

Push дневного отчёта (hybrid format) onboarded users с chat_id.
NUTRITION_ENABLED gate, asyncio.run bridge для Ayla calls,
per-user error handling. send_max_message via notifications.max_bot.
Beat schedule maxbot-daily-reports-2100-msk."
```

## Context

- Working dir: `C:\Users\user\PycharmProjects\mysite`
- Existing `send_post_visit_followups` (line 155-216 в tasks.py) — pattern reference.
- `notifications.max_bot.send_max_message(chat_id, text, attachments=None)` — sync, REST API.
- TIME_ZONE='Europe/Moscow' уже set в settings.base — `crontab(hour=21)` означает 21:00 МСК.

## Self-Review

- send_daily_reports Celery task с `@shared_task(name=..., bind=True, max_retries=1)`
- NUTRITION_ENABLED gate first thing
- Filter: nutrition_onboarded_at + chat_id NOT NULL
- asyncio.run для Ayla calls
- Per-user error handling (Nutrition* errors logged, skip к next)
- send_max_message wrap в try/except
- Beat schedule `maxbot-daily-reports-2100-msk`
- 4 tests pass

## Report Format

- Status, files changed, test results, new commit SHA, self-review

---

## Task 8: E2E test — full daily report flow

**Files:**
- Modify: `mysite/tests/maxbot/test_send_daily_reports.py`

- [ ] **Step 1: Add E2E test**

APPEND:

```python
def test_send_daily_reports_eating_disorder_mode_omits_calories(settings):
    """User с eating_disorder=True → render без чисел калорий."""
    from maxbot.tasks import send_daily_reports
    from maxbot.services.nutrition_client import (
        SummaryResponse, WaterTodayResponse,
    )

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99, chat_id=12345,
        nutrition_onboarded_at="2026-04-30T12:00:00Z",
        health_flags={"eating_disorder": True},
    )

    summary = SummaryResponse(
        date="2026-05-04",
        calories_total=1300, calories_goal=1450,
        protein_g=80, fat_g=40, carbs_g=130,
        entries=[
            {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
            {"meal_type": "lunch", "dish_name": "суп", "calories": 450},
            {"meal_type": "dinner", "dish_name": "рыба", "calories": 380},
        ],
        raw={},
    )
    water_today = WaterTodayResponse(
        total_ml=1800, norm_ml=2000, entries=[], raw={},
    )

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            daily_summary=AsyncMock(return_value=summary),
            get_water_today=AsyncMock(return_value=water_today),
        )

        send_daily_reports()

        send_mock.assert_called_once()
        args = send_mock.call_args.args
        text = args[1] if len(args) > 1 else send_mock.call_args.kwargs.get("text", "")
        # No calorie numbers
        assert "1300" not in text
        assert "1450" not in text
        # Supportive vibe
        assert "Как ты сегодня" in text or "День получился" in text


def test_send_daily_reports_continues_after_user_failure(settings):
    """Если Ayla падает на user A — task продолжает с user B."""
    from maxbot.tasks import send_daily_reports
    from maxbot.services.nutrition_client import (
        SummaryResponse, WaterTodayResponse, NutritionUnavailableError,
    )

    settings.NUTRITION_ENABLED = True

    baker.make(
        BotUser, max_user_id=99, chat_id=12345,
        nutrition_onboarded_at="2026-04-30T12:00:00Z", health_flags={},
    )
    baker.make(
        BotUser, max_user_id=100, chat_id=12346,
        nutrition_onboarded_at="2026-04-30T12:00:00Z", health_flags={},
    )

    # User 99 — Ayla падает; user 100 — успех
    call_count = 0

    async def flaky_summary(*, external_user_id):
        nonlocal call_count
        call_count += 1
        if external_user_id == "bot:99":
            raise NutritionUnavailableError("simulated")
        return SummaryResponse(
            date="2026-05-04", calories_total=1100, calories_goal=1450,
            protein_g=65, fat_g=40, carbs_g=110,
            entries=[
                {"meal_type": "breakfast", "dish_name": "каша", "calories": 320},
                {"meal_type": "lunch", "dish_name": "суп", "calories": 450},
                {"meal_type": "dinner", "dish_name": "рыба", "calories": 330},
            ],
            raw={},
        )

    water_today = WaterTodayResponse(
        total_ml=1500, norm_ml=2000, entries=[], raw={},
    )

    with patch("maxbot.tasks.send_max_message") as send_mock, \
         patch("maxbot.tasks.get_nutrition_client") as client_factory:
        client_factory.return_value = MagicMock(
            daily_summary=flaky_summary,
            get_water_today=AsyncMock(return_value=water_today),
        )

        result = send_daily_reports()

        # User 99 skipped, user 100 sent
        assert send_mock.call_count == 1
        assert result == {"sent": 1, "skipped": 1}
```

- [ ] **Step 2: Run tests**

Run: `pytest mysite/tests/maxbot/test_send_daily_reports.py -v`
Expected: 6 passed (4 prior + 2 new).

- [ ] **Step 3: Smoke regression**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 434+ passed.

- [ ] **Step 4: Commit**

```bash
git add mysite/tests/maxbot/test_send_daily_reports.py
git commit -m "test(maxbot): E2E daily report — eating disorder + continue-on-failure (Part 2C T08)

Eating disorder user → render без чисел. Per-user failure (Ayla падает) →
task продолжает с next user, return {sent, skipped} dict."
```

---

## Task 9: Final regression + push + verify staging

**Files:** (verify only)

- [ ] **Step 1: Full maxbot suite**

Run: `pytest mysite/tests/maxbot/ --ignore=mysite/tests/maxbot/test_run.py 2>&1 | tail -3`
Expected: 434+ passed, 0 failed.

- [ ] **Step 2: Verify Celery beat schedule entry**

```bash
cd mysite && DJANGO_SETTINGS_MODULE=mysite.settings python -c "
import django
django.setup()
from django.conf import settings
beat = settings.CELERY_BEAT_SCHEDULE
print('daily_reports entry:' , beat.get('maxbot-daily-reports-2100-msk'))
"
```

Expected: dict with `task: 'maxbot.tasks.send_daily_reports'` + crontab.

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

## Self-review checklist (выполнить после Task 9)

**Spec coverage (Design Doc v2 §6):**
- [x] §6.1 диспетчеризация — push 21:00 (T07), `/день` команда (T05) — ✅ MVP. Inline после 18:00 при ≥3 приёмов — **backlog Part 2D**
- [x] §6.2 hybrid format — emoji приёмов + ккал/% + БЖУ + 💧 вода — T01 ✅
- [x] §6.3 eating disorder — без чисел калорий, supportive — T01 + T05 (через bot_user.health_flags) ✅
- [x] §6.4 edge case <50% или ≤2 приёма — supportive «немного» — T01 ✅
- [x] §6.5 `/день` посреди дня — same render через `/дневник` команду — T05 (no separate handler needed)
- [x] §6.6 weekly unlock — **backlog Phase 3.3** (требует tracking 7-day FoodEntry streak)
- [x] AI-comment ≤3 предложения ≤220 chars — **backlog Part 2D** (требует Ayla `?with_comment=true`)

**Placeholder scan:** все steps содержат actual code, никаких "TODO" в production коде.

**Type consistency:**
- `render_daily_full_report(summary, water_today=None, *, eating_disorder=False)` signature consistent через все callers
- `summary.entries` — list[dict]; `summary.calories_total/goal` — float/int; `summary.protein_g/fat_g/carbs_g` — float
- `water_today.total_ml/norm_ml` — int (используем 4 поля как в Part 2B T02 finding)
- `bot_user.health_flags.get("eating_disorder")` — bool flag
- `BotUser.chat_id` — BigIntegerField, может быть None
- `BotUser.nutrition_onboarded_at` — DateTimeField, может быть None
- `send_max_message(chat_id, text, attachments=None)` sync signature — kwargs/args usage consistent across tests
- `daily_report_footer_keyboard()` — same call signature в `on_view_day` (T05) + `on_diary_command` (T05)

---

## Не в Part 2C (backlog Part 2D / Phase 3.3)

**Part 2D:**
- AI-comment generation (Ayla `GET /summary/?with_comment=true` extension + prompt template)
- User-configurable `daily_report_time` setting (BotUser.nutrition_settings JSON + settings handler/keyboard)
- Inline-after-18:00 trigger при ≥3 приёмов — event hook в `food_scanner.on_log_meal` (sequencer logic)
- `parse_beverage` free-text branch (Part 2B holdover)
- Adaptive water reminders Celery beat
- Caffeine warning при pregnant

**Phase 3.3:**
- Weekly unlock indicator + content (после 7-day FoodEntry streak)
- Pattern engine (PatternRule seed) — `evening_sweets`, `low_protein`, etc.
- `returning_success` insight + nudge

---

*Plan v1 закреплён 2026-05-05. Ссылается на Design Doc v2 §6 (`maxbot-phase3-nutrition-design.md`), Part 2A T11 (on_view_day обновляется), Part 2B T02 (WaterTodayResponse 4-fields finding).*
