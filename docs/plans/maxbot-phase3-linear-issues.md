# Linear issues — Ayla backend Phase 3 backlog

**Назначение:** ready-to-paste тексты для 7 Linear issues (DRF-300..DRF-306) для backend-команды Ayla. Каждый блок ниже = одна issue. Скопировать title + description, поставить team `DRF`, priority по таблице ниже.

**Spec:** [Notion — Ayla Backend Phase 3 Nutrition Endpoints Spec](https://www.notion.so/Ayla-Backend-Phase-3-Nutrition-Endpoints-Spec-354b0dab295581da9456ebadf8e15192)

**Зависимости:**
- DRF-300, DRF-301, DRF-302, DRF-303 — **блокирующие для Phase 3.1** в MAX-боте.
- DRF-304, DRF-305 — блокирующие для Phase 3.3.
- DRF-306 — backlog, можно когда угодно.

---

## DRF-300 — NutritionProfile API (GET/POST /profile/)

**Priority:** High (blocking 3.1)
**Estimate:** 5–8 days
**Labels:** `phase-3.1`, `api`, `nutrition`

### Description

Реализовать профиль пользователя с расчётом BMR/нутриционных норм + override-ladder для health flags.

**Endpoints:**
- `GET /api/v1/nutrition/internal/profile/` — чтение
- `POST /api/v1/nutrition/internal/profile/` — upsert (PATCH-семантика, идемпотентно через `Idempotency-Key`)

**Response shape, server-side override ladder, validation rules:** см. spec §1 в Notion.

**Acceptance:**
- [ ] Модель `NutritionProfile` (1:1 с user через `external_user_id`)
- [ ] BMR через Mifflin-St Jeor + activity coefficient + goal factor
- [ ] Override priority: `eating_disorder` → `pregnancy/breastfeeding` → `BMR floor ladder`
- [ ] Pure-math расчёты, без LLM
- [ ] Pregnancy/breastfeeding: lose → maintain, +200/+400 kcal, +25g protein, +фолиевая в hint
- [ ] BMR floor ladder: middle → gentle → maintain (с явным `overrides_applied` array)
- [ ] Защита от переопределения если `eating_disorder=true` (всегда maintain)
- [ ] Валидация: age 16-99, height 120-220, weight 30-200
- [ ] Idempotency-Key cache 24h
- [ ] `disclaimer_acked: {ts, version, screen}` хранится с version-aware замером
- [ ] Unit-тесты на 4 override scenario + edge cases (skipped fields → defaults Пензы 35-45 ж)

---

## DRF-301 — Beverage catalog (GET /beverages/)

**Priority:** High (blocking 3.1, blocks DRF-302)
**Estimate:** 2–3 days
**Labels:** `phase-3.1`, `api`, `nutrition`, `seed-data`

### Description

Каталог напитков с гидратационными коэффициентами + seed-команда.

**Endpoint:** `GET /api/v1/nutrition/internal/beverages/`

**Response shape, full seed данные (50 напитков):** см. spec §2.5 + §8 в Notion.

**Источники для seed:**
- USDA FoodData Central (calories / protein / fat / carbs / sugar / caffeine)
- Beverage Hydration Index (Maughan et al. 2016, Am J Clin Nutr) — water_coefficient
- Роспотребнадзор «Химический состав российских пищевых продуктов» (Скурихин-Тутельян) — для русских блюд (бульон, ряженка)

**Acceptance:**
- [ ] Модель `Beverage` со всеми полями spec
- [ ] Management command `seed_beverages` (idempotent через `update_or_create(slug=)`)
- [ ] Минимум 50 напитков, покрывающие категории: water, tea, coffee, juice, soda, milk, alcohol, broth, sport
- [ ] `aliases` массив для парсинга free-text («кофе» / «coffee» / «americano» все → kofe_chernyi)
- [ ] HTTP cache header `Cache-Control: max-age=3600`
- [ ] Django Admin для контент-менеджера (добавление новых, корректировка коэффициентов без деплоя)
- [ ] Mock в `mysite/tests/fixtures/ayla_mock.py` уже содержит 24 напитка — используй как reference subset

---

## DRF-302 — Water tracking (POST/DELETE/GET /water/)

**Priority:** High (blocking 3.1, depends on DRF-301)
**Estimate:** 5–7 days
**Labels:** `phase-3.1`, `api`, `nutrition`

### Description

Учёт воды и напитков с server-side применением водного коэффициента, milestone-detection, soft-delete + restore window.

**Endpoints:**
- `POST /api/v1/nutrition/internal/water/`
- `DELETE /api/v1/nutrition/internal/water/{entry_id}/`
- `POST /api/v1/nutrition/internal/water/{entry_id}/restore/`
- `GET /api/v1/nutrition/internal/water/today/`

**Response shapes, milestone idempotency rules, alcohol hint, caffeine warning:** см. spec §2 в Notion.

**Acceptance:**
- [ ] Модель `WaterEntry` (user, ts, ml, water_ml, beverage FK nullable, soft-delete)
- [ ] Server-side: `water_ml = ml × water_coefficient` (поддержка отрицательных коэф для крепкого алкоголя)
- [ ] Калории/БЖУ/кофеин рассчитываются в одной транзакции (создаётся `WaterEntry` + `FoodEntry` если kcal>0)
- [ ] `today_total_water_ml` агрегат в TZ профиля (`NutritionProfile.timezone`)
- [ ] **Milestone idempotency per-day per-threshold** — 50/100/150% впервые в день → `milestone_text` в response, последующие записи в этот день не возвращают тот же milestone
- [ ] **Alcohol recovery hint** — для категории `alcohol` (eating_disorder mode → не показываем)
- [ ] **Caffeine warning** при `pregnant=true` и сумма caffeine ≥ 200мг/день
- [ ] **Eating disorder mode**: strip `kcal`, `milestone_text`, `alcohol_recovery_hint` (см. spec §14 в Notion)
- [ ] **Soft-delete + restore window 15 минут** — `deleted_at`/`deleted_reason`, `restore_window_expires_at` в response
- [ ] Daily Celery purge >90 дней
- [ ] Idempotency-Key (UUID5(user, ts, ml, slug)) — повтор → cached response
- [ ] Валидация: `ml` ∈ [10, 3000]
- [ ] Unit-тесты на milestone-idempotency, alcohol hint, eating_disorder mode, soft-delete + restore

---

## DRF-303 — Расширения существующих endpoints (caption + AI comment)

**Priority:** High (blocking 3.1)
**Estimate:** 3–4 days
**Labels:** `phase-3.1`, `api`, `nutrition`, `llm`

### Description

Два расширения в существующих endpoints для поддержки нового UX в MAX-боте.

**1. `POST /scan/` — поддержка `caption` параметра.**
Опциональное поле в request body — текст подписи пользователя к фото («это в гостях у мамы, половина порции»). Передаётся в LLM vision prompt чтобы AI учитывал контекст порции/варианта блюда. Backwards compatible.

**2. `GET /summary/?with_comment=true` — AI-генерируемый комментарий.**
Опциональный query-param. При `true` Ayla генерирует AI-комментарий для дневного отчёта (≤3 предложения, ≤220 символов).

**Tone rules + eating disorder template:** см. spec §4 + §10 (LLM usage policy) в Notion.

**Acceptance:**
- [ ] `POST /scan/` принимает `caption` field, добавляет в vision LLM prompt
- [ ] `GET /summary/?with_comment=true` возвращает `ai_comment` field
- [ ] Длина: ≤220 chars, ≤3 sentences (валидация на Ayla с re-prompt при превышении)
- [ ] Tone tied to `goal` + `health_flags` (см. design `docs/plans/maxbot-phase3-nutrition-design.md` §6.3)
- [ ] **Eating disorder = отдельный template без цифр калорий** (только supportive question «Как ты сегодня? День получился?»)
- [ ] Server-side cache на 6 часов per-user-per-day (см. spec §13)
- [ ] Backwards compat: без query param работает как сейчас
- [ ] LLM cost limit alert при > $30/день только на comment-генерацию

---

## DRF-304 — Pattern detection (GET /patterns/)

**Priority:** Medium (blocking Phase 3.3, не блокирует 3.1/3.2)
**Estimate:** 7–10 days
**Labels:** `phase-3.3`, `api`, `nutrition`, `analytics`

### Description

Server-side детекция поведенческих паттернов для bot-side `pattern_detected` нуджей.

**Endpoint:** `GET /api/v1/nutrition/internal/patterns/`

**Response shape + 7 правил с порогами:** см. spec §3.1 + design §10.9 в Notion.

**Acceptance:**
- [ ] 7 detector-правил реализованы:
  - `evening_sweets` — sweets after 19:00 в будни, ≥4/14 дней
  - `low_protein` — белок <70% от daily_protein_g, ≥5/7 дней
  - `low_water` — вода <70%, ≥4/7 дней
  - `late_dinner` — последний приём >21:00, ≥3/7 дней
  - `meal_skips` — день с <30% от daily_kcal, 3 дня подряд
  - `late_caffeine` — caffeine после 17:00, ≥3/7 дней
  - `frequent_alcohol` — alcohol ≥2/7 дней (≥14 дней истории)
- [ ] Применение `requires_health_flags_absent` фильтра
- [ ] `display_hint: "primary"|"secondary"|"hidden"` в response для UX-приоритизации
- [ ] `advice_template_args: dict` с конкретными числами для подстановки в bot-side template
- [ ] Performance: query optimizations, индексы на `FoodEntry(user_id, ts::date)` и `WaterEntry(user_id, ts::date)`
- [ ] Server-side cache на 12 часов per-user (см. spec §13)
- [ ] Unit-тесты для каждого detector + edge case (eating_disorder → frequent_alcohol суппресится)

---

## DRF-305 — Returning success insight

**Priority:** Medium (blocking Phase 3.3)
**Estimate:** 2–3 days
**Labels:** `phase-3.3`, `api`, `nutrition`, `analytics`

### Description

Детекция возврата пользователя в режим после провала (для bot-side `returning_success` нуджа).

**Endpoint:** `GET /api/v1/nutrition/internal/insights/returning_success/`

**Response shape:** см. spec §3.2 в Notion.

**Acceptance:**
- [ ] Анализ FoodEntry за последние 21 день
- [ ] Trigger: 3+ дней подряд провал (<60% от daily_kcal) → 2 дня подряд в норме (80-110%)
- [ ] Response: `{detected, failure_streak_days, recovery_days, since_recovery_started}`
- [ ] Eating disorder mode: returns `{detected: false}` всегда (не подкрепляем числовое улучшение)
- [ ] Unit-тесты на edge cases (нет провала, прерванное восстановление, слишком короткий streak)

---

## DRF-306 — Webhook для cross-system events (nice-to-have)

**Priority:** Low (backlog Phase 3.4)
**Estimate:** 5–7 days
**Labels:** `phase-3.4`, `events`, `infrastructure`

### Description

Push-уведомления от Ayla → MAX-боту для real-time UX (вместо текущего pull-paradigm).

**Endpoint (на стороне MAX-бота):** `POST {MAXBOT_WEBHOOK_URL}/api/maxbot/ayla-events/`

**Domain events (Phase 3.4):**
- `profile_updated` — после `POST /profile/`
- `water_logged` — после `POST /water/` (опционально)
- `milestone_reached` — отдельный event для real-time (сейчас в response `/water/`)
- `pattern_detected` — впервые за 14 дней
- `recognition_completed` — после `/scan/` (для async-режима в будущем)

**Acceptance:**
- [ ] Outbox pattern в Ayla (event записывается в transaction с change)
- [ ] Async delivery worker
- [ ] Retry с exponential backoff (1s, 2s, 4s, 8s) до 5 попыток
- [ ] HMAC signature header для верификации на стороне receiver
- [ ] DLQ для failed events после 5 retries → admin alert
- [ ] Webhook contract: `{event_type, ts, external_user_id, payload}`
- [ ] Idempotency через `event_id` UUID4

---

## Что делать после ревью backend-команды

1. Прочитать spec в Notion (link в описании issue)
2. Inline-комментарии в Notion-странице к спорным местам
3. Принять/изменить acceptance criteria
4. Проставить estimates по своему опыту
5. Запланировать на спринт

**Координация:** Andrey (PM/MAX-bot) — по nutrition design + UX-вопросам. Backend-tech-lead — по acceptance + estimates.

**Sequencing для Phase 3.1 launch:**
1. DRF-301 (beverages seed) — самое лёгкое, делается первым
2. DRF-302 (water) — depends on DRF-301
3. DRF-300 (profile) — параллельно с DRF-302
4. DRF-303 (scan caption + summary comment) — параллельно
5. **Все 4 готовы → MAX-бот merge'ит Phase 3.1** (T10..T12 в `~/.claude/plans/hashed-forging-map.md`)
