# Ayla Backend — Phase 3 Nutrition Endpoints Spec

**Назначение:** ТЗ для backend-команды Ayla. Описывает 3 новые группы endpoints + расширения существующих, нужные для Phase 3 Nutrition Tracker в MAX-боте «Формула тела». Документ готов к нарезке на DRF-XXX тикеты в Linear.

**Контекст:** MAX-бот сейчас использует существующие endpoints `/scan/`, `/food-log/`, `/summary/`, `/deficits/` через `nutrition_client.py`. Phase 3 расширяет UX — добавляет анкету (BMR/нормы/health flags), учёт воды, pattern detection, returning success detection. Архитектурная договорённость: **вся nutrition-data живёт в Ayla**, MAX-бот — thin UX client. Поэтому новые таблицы/логика нужны на стороне Ayla.

**Связанные документы:**
- Design spec: `docs/plans/maxbot-phase3-nutrition-design.md`
- Implementation plan: `~/.claude/plans/hashed-forging-map.md`

**Используемые конвенции (унаследованы от существующих endpoints):**
- Базовый префикс: `/api/v1/nutrition/internal/`
- Auth: header `X-Service-Token: <NUTRITION_SERVICE_TOKEN>` + `X-External-User-ID: bot:{max_user_id}` (см. `mysite/maxbot/services/ayla_user_proxy.py`)
- Idempotency: header `Idempotency-Key: <UUID5>` для POST'ов (паттерн уже используется для food-log)
- Ошибки: `{"error": {"code": "MACHINE_CODE", "message": "human"}}`, HTTP 400/404/500
- Response envelope: `{"data": {...}}` либо плоский dict (как в существующих endpoints — придерживаться текущего стиля)

---

## 1. Group: Nutrition Profile

### 1.1 `GET /api/v1/nutrition/internal/profile/`

**Назначение:** прочитать профиль пользователя. Используется ботом перед каждым `ai_concierge.send_message()` для рендера health-context в system prompt.

**Headers:**
- `X-Service-Token`
- `X-External-User-ID: bot:{max_user_id}`

**Response 200:**
```json
{
  "external_user_id": "bot:12345",
  "exists": true,
  "gender": "female",                 // "female" | "male" | null
  "age": 42,                          // null если не указан
  "height_cm": 165,
  "weight_kg": 67.0,
  "weight_range": null,               // "65-75" если ввели только диапазон
  "activity_coefficient": 1.4,
  "goal": "lose",                     // "lose" | "maintain" | "gain" | "tone"
  "pace": "moderate",                 // "gentle" | "moderate" | null
  "diet_preference": "none",
  
  "norms": {
    "bmr": 1364,
    "daily_kcal": 1450,
    "daily_protein_g": 110,
    "daily_fat_g": 50,
    "daily_carbs_g": 145,
    "daily_water_ml": 2000
  },
  
  "health_flags": {
    "pregnant": false,
    "breastfeeding": false,
    "diabetes_t1": false,
    "diabetes_t2": false,
    "prediabetes": false,
    "hypertension": false,
    "gi_problems": false,
    "thyroid": false,
    "menopause": false,
    "eating_disorder": false,
    "meds": false,
    "allergies": [
      {"item": "лактоза", "type": "intolerance"},
      {"item": "орехи", "type": "allergy"}
    ],
    "allergies_vague": false,
    
    "gender_skipped": false,
    "age_skipped": false,
    "height_skipped": false,
    "weight_skipped": false
  },
  
  "goal_overridden_by": null,         // "pregnancy"|"breastfeeding"|"low_bmi"|"bmr_floor"|"eating_disorder"|null
  "bmi_warning_overridden_at": null,  // ISO timestamp
  
  "disclaimer_acked": {
    "ts": "2026-04-30T12:34:00Z",
    "version": "v1",
    "screen": "anketa_step4"
  },
  
  "onboarded_at": "2026-04-30T12:35:00Z",
  "first_food_logged_at": "2026-04-30T13:00:00Z",
  "weekly_summary_unlocked_at": null,
  
  "created_at": "2026-04-30T12:00:00Z",
  "updated_at": "2026-05-01T19:00:00Z"
}
```

**Response 200 (no profile yet):**
```json
{
  "external_user_id": "bot:12345",
  "exists": false
}
```

Никогда не возвращаем 404 — `exists: false` лучше для UX-кода (избегает branching на статус-кодах).

**Caching:** Ayla может кешировать на 5 минут (профиль редко меняется). Бот не кеширует — каждый user-message требует свежие health_flags.

---

### 1.2 `POST /api/v1/nutrition/internal/profile/`

**Назначение:** создать или обновить профиль (PATCH-семантика — присланные поля обновляются, отсутствующие не трогаются). Используется на каждом шаге анкеты бота.

**Headers:**
- `X-Service-Token`
- `X-External-User-ID: bot:{max_user_id}`
- `Idempotency-Key: <UUID5(external_user_id, step_name)>` — для protect от двойного клика

**Request body (все поля опциональные):**
```json
{
  "gender": "female",
  "age": 42,
  "height_cm": 165,
  "weight_kg": 67.0,
  "weight_range": null,
  "activity_coefficient": 1.4,
  "goal": "lose",
  "pace": "moderate",
  "diet_preference": "none",
  
  "health_flags": {
    "pregnant": false,
    "breastfeeding": false,
    "diabetes_t1": false,
    "diabetes_t2": false,
    "prediabetes": false,
    "hypertension": false,
    "gi_problems": false,
    "thyroid": false,
    "menopause": false,
    "eating_disorder": false,
    "meds": false,
    "allergies": [...],
    "allergies_vague": false
  },
  
  "_skipped_fields": ["weight"],
  
  "disclaimer_acked": {
    "ts": "2026-04-30T12:34:00Z",
    "version": "v1",
    "screen": "anketa_step4"
  },
  
  "complete": false
}
```

`complete: true` указывается только в финальном шаге анкеты — Ayla знает что это full-profile commit (триггерит `onboarded_at` timestamp).

`_skipped_fields` — список полей которые пользователь явно пропустил (превращается в Ayla во флаги `*_skipped: true`).

**Response 200:**
- Возвращает полный профиль (как `GET /profile/`) с обновлёнными полями + рассчитанными нормами.

**Server-side обязанности Ayla:**
1. **Расчёт норм.** При наличии gender + height + weight + age — пересчитывает BMR (Миффлин-Сан-Жеор), daily_kcal (BMR × activity × goal_factor), daily_protein/fat/carbs, daily_water_ml (30 мл/кг + adjustments). Pure-math, без LLM.
2. **Goal override logic.** Если `health_flags.pregnant=true OR breastfeeding=true`:
   - Если `goal=lose` → принудительно `goal=maintain`, `goal_overridden_by="pregnancy"`. Возвращает override в response.
   - При беременности: добавить +200 ккал к норме после 14 недели; +25 г белка; +фолиевая в советах (это для системы deficits).
   - При ГВ: +400 ккал, +25 г белка, +кальций.
3. **BMR floor ladder.** Если goal=lose и pace=moderate, и расчётная норма < BMR + 100 ккал:
   - Сначала пробуем pace=gentle.
   - Если всё равно ниже floor — переключаем на goal=maintain, `goal_overridden_by="bmr_floor"`.
   - Возвращаем какой ladder applied в response (`overrides` блок).
4. **Eating disorder override.** Если `health_flags.eating_disorder=true` → `goal=maintain` всегда, `goal_overridden_by="eating_disorder"`. Бот в этом режиме не показывает цифры калорий.
5. **Defaults для пропущенных полей** — медиана аудитории Пензы 35–45 ж: gender=female, age=40, height=165, weight=70.

**Response 200 dop (overrides блок):**
```json
{
  ...профиль...,
  "overrides_applied": [
    {"reason": "pregnancy", "from": {"goal": "lose"}, "to": {"goal": "maintain"}},
    {"reason": "bmr_floor", "from": {"pace": "moderate"}, "to": {"pace": "gentle"}}
  ]
}
```

Бот рендерит блок «*Учла важное*» из этого `overrides_applied`.

**Response 400** (валидация):
```json
{"error": {"code": "INVALID_VALUE", "message": "age must be 16-99", "field": "age"}}
```

**Idempotency:** при повторе того же запроса с тем же `Idempotency-Key` — возврат cached response (24h window).

---

## 2. Group: Water tracking

### 2.1 `POST /api/v1/nutrition/internal/water/`

**Назначение:** записать порцию воды или напитка. Используется ботом при тапе на `+250 мл` или free-text «*выпила стакан кофе*».

**Headers:**
- `X-Service-Token`
- `X-External-User-ID`
- `Idempotency-Key: <UUID5(external_user_id, ts, ml, beverage_slug)>`

**Request:**
```json
{
  "ml": 250,
  "beverage_slug": null,            // null = "вода через кнопку"; "kofe_chernyi"/"sok_apelsinovyi"/...
  "ts": "2026-05-01T15:32:00Z"      // опционально, default = now
}
```

**Server-side Ayla:**
1. Валидация: `ml` в [10, 3000].
2. Если `beverage_slug == null` — считаем как вода (`water_coefficient=1.0`, `kcal=0`).
3. Если `beverage_slug` указан — ищем в каталоге Beverage:
   - `water_ml = ml × water_coefficient` (может быть отрицательным для крепкого алкоголя)
   - `kcal = ml × kcal_per_100ml / 100`
   - `protein/fat/carbs/sugar/caffeine` — рассчитываются аналогично
4. Если категория `alcohol` — set `alcohol_recovery_hint: true` в response (бот покажет soft-hint).
5. **Eating disorder mode:** если профиль имеет `eating_disorder=true` — НЕ возвращать `kcal`, `milestone_text` пустой, `alcohol_recovery_hint: false`.
6. Записать `WaterEntry` (Ayla-side таблица) + `FoodEntry` (если kcal > 0) с одной транзакции.
7. Подсчитать `today_total_water_ml` (сумма water_ml за календарный день в TZ профиля).
8. **Milestone detection (idempotent per-day):** если threshold (50/100/150% от `daily_water_ml`) пробит **впервые сегодня** — set `milestone_text` в response. Хранить в Ayla флаг `milestones_shown_today` чтобы не повторять.
9. **Caffeine warning:** если `pregnant=true` И сумма caffeine_mg сегодня ≥ 200 — set `caffeine_warning: "пограничное значение для беременности"`.

**Response 201:**
```json
{
  "entry_id": "uuid",
  "ml": 250,
  "water_ml": 250,
  "beverage_name": null,
  "beverage_label": null,           // "стакан"/"чашка"/"бутылка" — для подтверждения "+250 мл (стакан)"
  "kcal": 0,
  "protein_g": 0,
  "fat_g": 0,
  "carbs_g": 0,
  "caffeine_mg": 0,
  
  "today_total_water_ml": 1250,
  "today_norm_water_ml": 2000,
  "today_progress_pct": 62,
  
  "milestone_text": "половина дня 💪", // null если не milestone
  "alcohol_recovery_hint": false,
  "caffeine_warning": null,
  
  "ts": "2026-05-01T15:32:00Z"
}
```

**Response 201 (с beverage):**
```json
{
  "entry_id": "uuid",
  "ml": 250,
  "water_ml": 188,                  // 250 × 0.75 для крепкого кофе
  "beverage_name": "Чёрный кофе",
  "beverage_label": "чашка",
  "kcal": 5,
  "caffeine_mg": 95,
  "today_total_water_ml": 1188,
  ...
}
```

**Response 400:**
- `INVALID_ML` — ml вне [10, 3000]
- `UNKNOWN_BEVERAGE` — slug не найден в каталоге

---

### 2.2 `DELETE /api/v1/nutrition/internal/water/{entry_id}/`

**Назначение:** soft-delete записи воды (undo).

**Headers:** `X-Service-Token`, `X-External-User-ID`

**Response 200:**
```json
{
  "entry_id": "uuid",
  "deleted": true,
  "today_total_water_ml": 1000,     // пересчитанный счётчик
  "restore_window_expires_at": "2026-05-01T15:47:00Z"  // 15 минут после delete
}
```

**Server-side:**
- Set `deleted_at = now`, `deleted_reason = "user_undo"`
- Записи не учитываются в `today_total` после delete
- Восстановление возможно через `POST /water/{entry_id}/restore/` в течение 15 минут (см. 2.3)
- Через 90 дней — physical purge (Ayla daily Celery task)

**Response 404:** `ENTRY_NOT_FOUND` (никогда не свой entry — security guard через `X-External-User-ID`).

---

### 2.3 `POST /api/v1/nutrition/internal/water/{entry_id}/restore/`

**Назначение:** восстановить soft-deleted entry в restore window.

**Response 200:**
```json
{
  "entry_id": "uuid",
  "restored": true,
  "today_total_water_ml": 1250
}
```

**Response 410** (window expired):
```json
{"error": {"code": "RESTORE_WINDOW_EXPIRED"}}
```

---

### 2.4 `GET /api/v1/nutrition/internal/water/today/`

**Назначение:** список entries за сегодня для UI undo.

**Response 200:**
```json
{
  "date": "2026-05-01",
  "entries": [
    {
      "entry_id": "uuid",
      "ts": "2026-05-01T08:00:00Z",
      "ml": 250,
      "water_ml": 250,
      "beverage_slug": null,
      "beverage_name": null,
      "deleted": false
    },
    {
      "entry_id": "uuid",
      "ts": "2026-05-01T11:00:00Z",
      "ml": 200,
      "water_ml": 188,
      "beverage_slug": "kofe_chernyi",
      "beverage_name": "Чёрный кофе",
      "deleted": false
    }
  ],
  "today_total_water_ml": 438,
  "today_norm_water_ml": 2000,
  "today_kcal_from_beverages": 10,
  "today_caffeine_mg": 95,
  
  "today_total_coffee_cups": 1,
  "today_total_tea_cups": 0
}
```

`today_total_coffee_cups` / `today_total_tea_cups` нужны для дневного отчёта (отдельные счётчики).

---

### 2.5 `GET /api/v1/nutrition/internal/beverages/`

**Назначение:** каталог напитков для autocomplete / валидации в боте.

**Response 200:**
```json
{
  "beverages": [
    {
      "slug": "voda",
      "name_ru": "Вода",
      "category": "water",
      "aliases": ["вода", "water"],
      "default_serving_ml": 250,
      "default_serving_label": "стакан"
    },
    {
      "slug": "kofe_chernyi",
      "name_ru": "Чёрный кофе",
      "category": "coffee",
      "aliases": ["кофе", "coffee", "americano", "американо"],
      "default_serving_ml": 200,
      "default_serving_label": "чашка"
    },
    ...50 напитков
  ]
}
```

**Caching:** бот кеширует ответ на 1 час в memory. Ayla может выдавать `Cache-Control: max-age=3600`.

**Server-side в Ayla:**
- Seed-команда `seed_beverages` заливает ~50 типичных напитков из USDA FoodData Central + Beverage Hydration Index (Maughan 2016, Am J Clin Nutr) + Роспотребнадзор «*Химический состав российских пищевых продуктов*» (Скурихин-Тутельян).
- Полная таблица коэффициентов в design-spec §8.

---

## 3. Group: Pattern detection (Phase 3.3, можно отложить)

### 3.1 `GET /api/v1/nutrition/internal/patterns/`

**Назначение:** возвращает все детектированные паттерны для пользователя за последние 14 дней. Используется bot-side `pattern_engine` для генерации `pattern_detected` нуджей.

**Phase rollout:** Phase 3.3, не блокирует 3.1/3.2.

**Headers:** standard.

**Response 200:**
```json
{
  "active_days": 14,
  "patterns": [
    {
      "slug": "evening_sweets",
      "name_ru": "Вечерние срывы на сладкое",
      "count": 6,
      "active_window_days": 14,
      "severity": "medium",
      "recent_dates": ["2026-04-28", "2026-04-29", "2026-04-30"],
      "advice_template_args": {
        "trigger_time": "после 19:00",
        "weekday_pattern": "будни",
        "frequency_text": "6 раз за 2 недели"
      }
    },
    {
      "slug": "low_protein",
      "count": 5,
      "active_window_days": 7,
      "severity": "medium",
      "advice_template_args": {
        "average_actual": 75,
        "target": 110,
        "deficit_pct": 32
      }
    }
  ]
}
```

**Server-side в Ayla:**
- Реализация detector'ов на основе `FoodEntry` + `WaterEntry` Ayla-side
- Активные правила соответствуют `PatternRule` в Django (бот источник конфигурации):
  - `evening_sweets` — приёмы пищи с `category="sweets"` после 19:00 в будни, ≥4 за 14 дней
  - `low_protein` — белок <70% от daily_protein_g, ≥5 дней из 7
  - `low_water` — вода <70% от daily_water_ml, ≥4 дня из 7
  - `late_dinner` — последний приём пищи >21:00, ≥3 раза за 7 дней
  - `meal_skips` — день с <30% от daily_kcal, 3 дня подряд
  - `late_caffeine` — caffeine после 17:00, ≥3 раза за 7 дней
  - `frequent_alcohol` — категория alcohol ≥2 раза за 7 дней (≥14 дней data)
- Применять `requires_health_flags_absent` фильтр (Ayla знает health_flags из профиля)
- Эту логику Ayla владеет полностью — бот не ре-вычисляет

---

### 3.2 `GET /api/v1/nutrition/internal/insights/returning_success/`

**Назначение:** детекция успешного возврата после провала (для `returning_success` нуджа).

**Phase rollout:** Phase 3.3.

**Response 200:**
```json
{
  "detected": true,
  "failure_streak_days": 4,        // дней подряд <60% от нормы перед восстановлением
  "recovery_days": 2,              // дней подряд в норме [80-110%] после провала
  "since_recovery_started": "2026-04-29"
}
```

**Server-side:** анализ `FoodEntry` за последние 21 день. Trigger = 3+ дня провал → 2 дня в норме.

---

## 4. Расширения существующих endpoints

### 4.1 `POST /api/v1/nutrition/internal/scan/` — добавить `caption` параметр

**Текущий:** photo URL → recognition.

**Расширение:** опциональный `caption` параметр в request body — текст подписи пользователя к фото («*это в гостях у мамы, половина порции*»).

**Server-side:** добавлять caption в LLM prompt для vision recognition, чтобы AI учитывал контекст порции / варианта блюда.

**Backwards compat:** существующий API без caption работает как сейчас.

---

### 4.2 `GET /api/v1/nutrition/internal/summary/` — добавить comment-генерацию

**Текущий:** возвращает структурированный day summary.

**Расширение:** опциональный `?with_comment=true` query param. При наличии Ayla генерирует AI-комментарий для дневного отчёта.

**Response добавляет поле:**
```json
{
  ...существующая структура summary...,
  "ai_comment": "Хороший день — почти в норму. Завтра попробуй больше белка утром: творог или яйца помогут дотянуть."
}
```

**Server-side требования:**
- ≤3 предложения, ≤220 символов (валидация на Ayla, иначе re-prompt)
- Tone tied to `goal` + `health_flags` (как в design §6.3)
- Eating disorder = отдельный template без цифр («*Как ты сегодня? День получился?*»)
- Cache на 6 часов per-user (избегаем повторной генерации при `/день` запросах)

**Backwards compat:** `?with_comment=false` (default) работает как сейчас.

---

## 5. Nice-to-have (можно сделать в любую фазу)

### 5.1 Webhook для cross-system events (опционально)

**Назначение:** Ayla уведомляет MAX-бота о событиях (например milestone reached). Сейчас бот pull'ит — это ок для MVP. Webhook ускорит UX в будущем.

**Endpoint:** `POST {MAXBOT_WEBHOOK_URL}/api/maxbot/ayla-events/` (на стороне MAX-бота)

**Phase:** backlog после 3.3.

---

## 6. Acceptance criteria для backend-команды

### Минимум для разблокировки Phase 3.1:

- [ ] `GET /profile/` (1.1) реализован, тесты проходят
- [ ] `POST /profile/` (1.2) с goal override + BMR floor + eating disorder reasoning, тесты на 3 override scenarios
- [ ] `POST /water/` (2.1) с beverage catalog + milestone idempotency
- [ ] `DELETE /water/{id}/` (2.2) + `POST /water/{id}/restore/` (2.3)
- [ ] `GET /water/today/` (2.4) с per-beverage счётчиками
- [ ] `GET /beverages/` (2.5) с seed данных 50 напитков
- [ ] `POST /scan/` (4.1) с caption-параметром
- [ ] `GET /summary/?with_comment=true` (4.2) с AI-комментарием

### Для Phase 3.2 (нудж-механика):

- [ ] AI comment endpoint (4.2) обновлён с tone-rules для всех goal-types

### Для Phase 3.3:

- [ ] `GET /patterns/` (3.1) с 7 правилами
- [ ] `GET /insights/returning_success/` (3.2)

---

## 7. Задачи для Linear (DRF-XXX заводится backend-командой)

Предлагаемая нарезка на тикеты:

1. **DRF-300** — `GET /profile/` + `POST /profile/` (1.1+1.2). Включает: модель `NutritionProfile` в Ayla, BMR calc, override logic, eating disorder mode.
2. **DRF-301** — Beverage catalog (2.5). Модель `Beverage`, seed 50 напитков, `GET /beverages/`.
3. **DRF-302** — Water entry CRUD (2.1+2.2+2.3+2.4). Включает milestone idempotency, alcohol hint, caffeine warning.
4. **DRF-303** — Расширения существующих endpoints (4.1+4.2). Caption в scan, AI comment в summary.
5. **DRF-304** — Pattern detection (3.1). 7 правил, query optimizations.
6. **DRF-305** — Returning success insight (3.2).
7. **DRF-306** — Nice-to-have webhook (5.1) — backlog.

DRF-300, DRF-301, DRF-302, DRF-303 — блокирующие для Phase 3.1.
DRF-304, DRF-305 — блокирующие для Phase 3.3 (но независимы от 3.1/3.2).

---

## 8. Контакты и процесс согласования

**Эта спецификация — draft v1, 2026-05-02.**

**Ожидаемый flow:**
1. Backend-tech-lead читает этот документ → review-комментарии в Linear / inline
2. Согласование контракта (response shapes, error codes, idempotency rules)
3. Создание DRF-XXX тикетов в Linear по нарезке §7
4. Параллельная работа: Ayla делает endpoints, MAX-бот делает T10 + T01 (миграции, persistent keyboard) на mock-server
5. Интеграционное тестирование на staging Ayla перед merge Phase 3.1 в production

**Mock-server для разработки бота параллельно:** будет создан в `mysite/tests/fixtures/ayla_mock.py` со всеми response-shapes из этого документа. Backend-команда может использовать его для контракт-проверки.

**Точки риска:**
- LLM AI-comment в `/summary/` — кто его пишет, OpenAI на Ayla или гибрид? Если Ayla — нужен budget на LLM-token'ы. Обсудить отдельно.
- Pattern detection — performance на 10k+ users? Добавить index hints / batch endpoint если нужно.
- Beverage catalog — кто content-owner? Кто добавляет новые напитки? Django Admin на Ayla или отдельный CMS?

---

*Дата: 2026-05-02. Подготовлен для согласования с Ayla backend-командой.*
