# MAX-бот Phase 3 — Nutrition Tracker (UX & Architecture Design)

**Статус**: Design spec, готов к декомпозиции в план имплементации
**Контекст**: Расширение существующего бота «Формула тела» (не отдельный бот) функцией дневника питания, учёта воды и AI-инсайтов на основе данных
**Аудитория**: женщины 35–45, Пенза, существующие/потенциальные клиенты салона
**Дата**: 2026-05-01

---

## 1. Принципы продукта

1. **Один бот, не два.** Все nutrition-фичи живут внутри `formula-tela-maxbot.service`, ту же `BotUser`, MCP, прокси, YClients-webhook и reminders переиспользуем.
2. **Бесплатно для всех (no gate).** Nutrition — growth-канал в основной бот. Монетизация через апселл услуг салона, не через подписку на калории.
3. **Wow-моменты выше анкет.** Hybrid-онбординг (вариант C): первый wow за 30 секунд, анкета как очевидный апгрейд («*а не средние 2000 ккал*»).
4. **Health screening — gate для советов, не для базового учёта.** Распознавание + калории доступны без screening; персональные рекомендации (БЖУ-советы, витамины, weekly insights) — только после consent.
5. **Dispatcher-driven нуджи, а не календарные push.** Бот сам инициирует разговор только при реальном data signal. Hard cap по классам (service / care / marketing).
6. **Fact-driven, не fantasy.** Все коэффициенты гидратации, калории, нормы — из справочников БД (`Beverage`, `PatternRule`). AI работает внутри жёстких UX-контейнеров с проверяемыми правилами.
7. **Honest doctor referral.** Health-warning'и НЕ конвертируем в кросс-промо салона. Поликлиника / эндокринолог — отдельный путь.
8. **Cross-promo data-driven.** Кнопка в салон появляется по сигналу commitment (3 недели дефицита, цель «подтянуть фигуру»), не на старте.

---

## 2. Архитектура — что это значит для существующего бота

### 2.1 Где живёт код

```
maxbot/
├── ai_concierge.py           ← расширение: ловит фото-сообщения через ai_assistant (Phase 3 target)
├── ai_tools.py               ← новые tools: recognize_food, add_beverage, ack_nutrition_disclaimer, ...
├── ai_parsers.py             ← новый: parse_age, parse_height, parse_weight, parse_allergies, parse_beverage
├── ai_vision.py              ← новый: recognize_food(image_bytes) -> FoodRecognition
├── nutrition_calc.py         ← новый: pure-math (BMR, daily norm, water norm, floor checks)
├── handlers/
│   ├── nutrition.py          ← новый router: анкета FSM, дневник еды, дневной отчёт
│   ├── water.py              ← новый router: ввод воды, undo, milestone-feedback
├── nudges/                   ← новая подсистема (см. §10)
└── states.py                 ← +NutritionAnketaStates
```

### 2.2 Architectural target для фото — Variant B

**MVP** стартует с упрощённого varianta A (фото → жёстко в `recognize_food`), но `recognize_food` пишется **сразу как tool в `ai_tools.py`**, чтобы Phase 3.5 включил Variant B без переписывания: `ai_assistant` получает image+caption как единый user-message, классифицирует intent (food / receipt / random), маршрутизирует в нужный tool.

3 guard'а в MVP-A:
- text caption у фото → конкатенировать в prompt к vision
- vision возвращает `is_food: bool` → если false — fallback "Это не похоже на еду..."
- если FSM в `NutritionAnketaStates.*` → фото игнорируется с подсказкой

### 2.3 Cost & latency budget

| Operation | Model | Latency p50 / p95 | Cost |
|---|---|---|---|
| Распознавание фото | gpt-4o (full) | 4с / 10с | ~$0.01–0.02/фото |
| Free-text парсинг (age/weight) | gpt-4o-mini | 0.3с / 0.8с | ~$0.0001 |
| Парсинг beverage / allergies | gpt-4o-mini | 0.5с / 1.2с | ~$0.0003 |
| Дневной отчёт (генерация) | gpt-4o-mini | 1с / 3с | ~$0.001–0.002 |
| AI-нудж (pattern, health) | gpt-4o-mini | 0.8с / 2с | ~$0.001 |
| Дневной отчёт хранится | cache в `BotUser.context["daily_report"]` | — | один LLM-call в день |

**Vision на full** — намеренно дороже за accuracy. Cost-оптимизация — backlog при >1000 active users.

---

## 3. Модели данных

### 3.1 Расширение `BotUser`

```python
class BotUser(models.Model):
    # ... существующие поля ...
    timezone = models.CharField(max_length=64, default="Europe/Moscow")
    health_flags = models.JSONField(default=dict)
    # health_flags — единый source для AI prompt:
    #   pregnant: bool | _skipped: True
    #   breastfeeding: bool | _skipped
    #   diabetes_t1 / diabetes_t2 / prediabetes: bool
    #   hypertension: bool | _skipped
    #   gi_problems / thyroid / menopause / eating_disorder: bool
    #   meds: bool | _skipped
    #   allergies: list[{"item": "лактоза", "type": "intolerance"}]
    #   allergies_vague: bool
    #   gender_skipped / age_skipped / height_skipped / weight_skipped: bool
    #   weight_range_only: "65-75"
    #   bmi_warning_overridden: ts (если override низкого BMI)
    #   goal_overridden_by: "pregnancy"|"breastfeeding"|"low_bmi"|"bmr_floor"|"eating_disorder"
    #   goal: "lose"|"maintain"|"gain"|"tone"
    #   pace: "gentle"|"moderate"
```

### 3.2 Новая модель `NutritionProfile`

```python
class NutritionProfile(models.Model):
    bot_user = models.OneToOneField(BotUser, on_delete=models.CASCADE)
    gender = models.CharField(choices=[("female","Ж"),("male","М")], null=True)
    age = models.IntegerField(null=True)
    height_cm = models.IntegerField(null=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1, null=True)
    activity_coefficient = models.DecimalField(default=1.4, max_digits=3, decimal_places=2)

    # вычисленные нормы (сохраняем чтобы не пересчитывать каждый раз)
    bmr = models.IntegerField(null=True)
    daily_kcal = models.IntegerField(null=True)
    daily_protein_g = models.IntegerField(null=True)
    daily_fat_g = models.IntegerField(null=True)
    daily_carbs_g = models.IntegerField(null=True)
    daily_water_ml = models.IntegerField(null=True)

    diet_preference = models.CharField(
        choices=[("none","Нет"),("vegan","Веган"),("vegetarian","Вегетарианка"),
                 ("halal","Халяль"),("kosher","Кошер"),("no_pork","Без свинины")],
        default="none",
    )
    nutrition_disclaimer_acked = models.JSONField(null=True)
    # {"ts": ..., "version": "v1", "screen": "anketa_step4"}

    daily_report_time = models.TimeField(default=time(21, 0))
    daily_report_enabled = models.BooleanField(default=True)
    water_reminders_enabled = models.BooleanField(default=False)

    onboarded_at = models.DateTimeField(null=True)
    first_food_logged_at = models.DateTimeField(null=True)
    weekly_summary_unlocked = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### 3.3 Новая модель `Beverage` (справочник)

```python
class Beverage(models.Model):
    slug = models.SlugField(unique=True)
    aliases = models.JSONField(default=list)
    name_ru = models.CharField(max_length=100)
    category = models.CharField(choices=[
        ("water", "Вода"), ("tea", "Чай"), ("coffee", "Кофе"),
        ("juice", "Сок"), ("soda", "Сладкая газировка"), ("milk", "Молочное"),
        ("alcohol", "Алкоголь"), ("broth", "Бульон"), ("sport", "Спорт-напитки"),
    ])
    water_coefficient = models.DecimalField(max_digits=4, decimal_places=2)
    # 1.00 = 100% к воде, 0.75 для крепкого кофе, -0.50 для крепкого алкоголя

    kcal_per_100ml = models.IntegerField(null=True)
    protein_per_100ml = models.DecimalField(null=True, max_digits=4, decimal_places=1)
    fat_per_100ml = models.DecimalField(null=True, max_digits=4, decimal_places=1)
    carbs_per_100ml = models.DecimalField(null=True, max_digits=4, decimal_places=1)
    sugar_per_100ml = models.DecimalField(null=True, max_digits=4, decimal_places=1)
    caffeine_mg_per_100ml = models.IntegerField(null=True)

    default_serving_ml = models.IntegerField(default=250)
    default_serving_label = models.CharField(default="стакан", max_length=30)

    note = models.TextField(blank=True)
    source = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
```

Seed-команда `seed_beverages` заливает ~50 напитков из USDA + Beverage Hydration Index (Maughan 2016) + Роспотребнадзор.

### 3.4 Новая модель `WaterEntry`

```python
class WaterEntry(models.Model):
    bot_user = models.ForeignKey(BotUser, on_delete=models.CASCADE)
    ts = models.DateTimeField(default=timezone.now)
    ml = models.IntegerField()                                # объём как выпит
    water_ml = models.IntegerField()                          # эквивалент воды (с коэф)
    beverage = models.ForeignKey(Beverage, null=True, blank=True, on_delete=models.SET_NULL)
    # null = "вода через кнопку без указания напитка"

    deleted_at = models.DateTimeField(null=True, blank=True)  # soft-delete
    deleted_reason = models.CharField(choices=[
        ("user_undo", "Отмена пользователем"),
        ("user_correction", "Замена другим вводом"),
    ], null=True, blank=True)

    class Meta:
        indexes = [Index(fields=["bot_user", "-ts"])]
```

`purge_deleted_water_entries` (Celery daily 04:00) физически удаляет с `deleted_at < now-90d`.

### 3.5 Новая модель `FoodEntry`

```python
class FoodEntry(models.Model):
    bot_user = models.ForeignKey(BotUser, on_delete=models.CASCADE)
    ts = models.DateTimeField(default=timezone.now)
    meal_type = models.CharField(choices=[
        ("breakfast","Завтрак"), ("lunch","Обед"),
        ("dinner","Ужин"), ("snack","Перекус"),
    ], null=True)

    name = models.CharField(max_length=200)                   # "Паста с курицей и томатами"
    kcal = models.IntegerField()
    protein_g = models.DecimalField(max_digits=5, decimal_places=1)
    fat_g = models.DecimalField(max_digits=5, decimal_places=1)
    carbs_g = models.DecimalField(max_digits=5, decimal_places=1)

    source = models.CharField(choices=[
        ("photo", "Фото"), ("text", "Текст"), ("manual", "Ручной ввод"),
    ])
    confidence = models.DecimalField(max_digits=3, decimal_places=2, null=True)
    photo_message_id = models.UUIDField(null=True)            # ссылка на Message с фото
    correction_count = models.IntegerField(default=0)         # сколько раз правили

    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_reason = models.CharField(null=True, blank=True, max_length=50)

    class Meta:
        indexes = [Index(fields=["bot_user", "-ts"])]
```

### 3.6 Расширение `Service`

```python
# существующая модель Service в services_app
aftercare_text_immediate = models.TextField(blank=True)  # текст нуджа через 2-3 часа после визита
aftercare_text_next_day = models.TextField(blank=True)   # текст нуджа на следующий день
```

Если поле пустое — after-service-care нудж не отправляется (контент-менеджер контролирует scope через Admin без деплоя).

### 3.7 Новые модели нудж-системы

```python
class NudgeEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    bot_user = models.ForeignKey(BotUser, on_delete=models.CASCADE)
    kind = models.CharField(max_length=50)          # "pattern_detected", "after_service_care", ...
    nudge_class = models.CharField(max_length=20)   # "service" | "care" | "marketing"
    priority = models.IntegerField()

    detected_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True)
    blocked_at = models.DateTimeField(null=True)
    blocked_reason = models.CharField(max_length=50, null=True)
    seen_at = models.DateTimeField(null=True)
    clicked_at = models.DateTimeField(null=True)
    clicked_button = models.CharField(max_length=50, null=True)
    ignored_at = models.DateTimeField(null=True)

    message = models.OneToOneField(Message, null=True, on_delete=models.SET_NULL)
    payload = models.JSONField(default=dict)

    class Meta:
        indexes = [
            Index(fields=["bot_user", "kind", "-detected_at"]),
            Index(fields=["bot_user", "nudge_class", "-sent_at"]),
        ]


class NudgeMute(models.Model):
    bot_user = models.ForeignKey(BotUser, on_delete=models.CASCADE)
    kind = models.CharField(max_length=50, null=True)
    nudge_class = models.CharField(max_length=20, null=True)
    mode = models.CharField(choices=[("off","Не показывать"),("less_often","Реже")])
    reason = models.CharField(choices=[
        ("user_explicit_off", "Кнопка «Не показывай»"),
        ("user_explicit_less", "Кнопка «Реже»"),
        ("user_settings", "Из настроек"),
        ("auto_ignored_twice", "Дважды проигнорирован"),
    ])
    expires_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PatternRule(models.Model):
    slug = models.SlugField(unique=True)
    name_ru = models.CharField(max_length=100)
    detector_function = models.CharField(max_length=200)  # FQN
    min_repeats = models.IntegerField()
    min_active_days = models.IntegerField()
    severity = models.CharField(choices=[("low","Low"),("medium","Medium"),("high","High")])
    advice_template = models.TextField()
    is_active = models.BooleanField(default=True)
    requires_health_flags_absent = models.JSONField(default=list)
    # например ["eating_disorder"] — не показывать если флаг есть
```

---

## 4. Onboarding flow

### 4.1 Welcome (экран 1)

Развилка по `BotUser.bookings_count` + history:

| Профиль | Welcome |
|---|---|
| Новый (никогда не писал) | Полный 3-кнопочный welcome |
| Возвращающийся клиент салона | «*Анна, привет! Кстати, я теперь умею вести дневник — настроим? / Не сейчас*» |
| Молчун (был, но 0 booking) | «*Привет! Я теперь умею не только записывать, но и считать калории — попробуем?*» |

3 кнопки главного меню:
```
[📅 Запись в салон]
[🍎 Дневник питания]
[💬 Задать вопрос]
```

Порядок: запись первой (revenue priority), дневник второй (growth), вопросы третьей (catch-all для тех кто не понимает что можно писать в чат).

### 4.2 Дневник вход (экран 2)

Hybrid (C): минималистичный welcome + 2 кнопки.

```
🍎 Дневник питания

Сфоткай еду — скажу калории, БЖУ
и подскажу как сбалансировать.

Чтобы считать норму под тебя
(а не средние 2000 ккал) — ответь
на 4 вопроса, 30 секунд.

  [📸 Попробовать сразу]
  [📝 Настроить под себя (30 сек)]
```

«*А не средние 2000 ккал*» — конкретика продаёт анкету.

### 4.3 Анкета — FSM `NutritionAnketaStates`

```python
class NutritionAnketaStates(StatesGroup):
    consent = State()  # disclaimer ack
    gender = State()
    age = State()
    height = State()
    weight = State()
    goal = State()
    goal_pace = State()        # для goal=lose
    goal_gain_clarify = State() # для goal=gain (набрать vs подтянуть)
    health_repro_pregnant = State()
    health_repro_breastfeeding = State()
    health_chronic_diabetes = State()
    health_chronic_cardio = State()
    health_chronic_other = State()  # multi-select toggle с edit-on-tap
    health_allergies = State()
    health_allergies_text = State()
    health_meds = State()
    health_menopause = State()       # условный: ж 45+
    complete = State()
```

**Прогресс-бар:** `● ● ○ ○` (точки U+25CF/U+25CB), 4 шага основных, sub-progress внутри health screening не показываем.

**Парсеры (`maxbot/ai_parsers.py`):** гибрид regex (95%) → LLM-fallback (5%) → sentinel `"REFUSED"` для явного отказа («*не скажу*», «*🤷*»).

**Smart-default skip:** на каждом шаге кнопка `[⏭ Пропустить]` ставит `health_flags["X_skipped"]: true` + дефолт (медиана для аудитории Пензы 35-45 ж).

### 4.4 Goal экран (3c) — критичные правила

- 3 кнопки на главном: `[⬇ Похудеть] [➡ Держать вес] [⬆ Набрать / подтянуть фигуру]`
- Темп: только 2 опции — `[🐢 Спокойный (-10%)]` и `[⚖️ Средний (-15%)]`. **«Быстрый» (-20%) скрыт за `/настройки → темп → пользовательский`** (safe by default, expert mode hidden).
- BMI < 18.5 → soft warning ladder с 3 кнопками: `[Хочу к врачу] [Поменять на «держать»] [Всё равно худеть]`. Третья кнопка ставит `bmi_warning_overridden: ts`. **Кнопка «*Хочу к врачу*» НЕ ведёт в салон** — поликлиника / эндокринолог.
- Goal=gain → уточнение «*Набрать вес / Подтянуть фигуру*». Подтянуть → goal=tone, +protein 1.6-1.8 г/кг + cross-promo CTA в финале.
- Pregnancy/breastfeeding в шаге 4 → **прозрачное переопределение** цели:
  ```
  Учла важное:
  • Беременность → дефицит небезопасен.
    Меняю цель на «держать вес».
  
  [Понятно, продолжаем]   [Передумала]
  ```
  «Передумала» — возврат в шаг 4 для снятия флага.
- BMR floor ladder: средний → спокойный → maintain. Каждый шаг с явным объяснением через метафору BMR без термина: «*ниже того, что нужно организму чтобы дышать и думать*».

### 4.5 Health screening (3d) — 6 экранов sequential β

| Экран | Кнопки | Critical |
|---|---|---|
| 0 — Consent | `[✓ Понятно, продолжаем] [Не сейчас, без советов]` | Кнопка отказа обязательна (152-ФЗ). Без ack → AI в degraded mode (нет советов). |
| 1 — Беременность | `[Да] [Нет]` | **БЕЗ `[Пропустить]`** — неопределённость опаснее любого ответа |
| 1b — ГВ | `[Да] [Нет] [⏭ Пропустить]` | |
| 2 — Диабет | `[Нет] [1 типа] [2 типа] [Преддиабет]` | **БЕЗ `[Пропустить]`** |
| 2b — Хронические multi-select | toggle с edit-on-tap: `[Гипертония] [ЖКТ] [Щитовидная] [Менопауза] [РПП в прошлом или сейчас] [✓ Готово] [Ничего]` | **РПП = критично** (eating_disorder flag → отдельный режим) |
| 3 — Аллергии | `[❌ Нет] [📝 Напишу какие] [🤷 Не уверена]` | Free-text → LLM-парсер → русские slug'и |
| 3b — Лекарства | `[Да] [Нет] [⏭ Пропустить]` | Какие — НЕ спрашиваем (не врачи) |
| 4 — Менопауза | `[Нет] [Да] [Не уверена] [⏭ Пропустить]` | **Условный экран** — только ж 45+ |

**Edit-on-tap для 2b мульти-выбора** — race-condition guard через Redis-mutex per-user; visual feedback `bot.send_action(typing)` мгновенный.

### 4.6 Финал анкеты

Два сообщения через 800ms `typing`:

**Сообщение 1:**
```
Готово ✓

🎯 Норма: 1450 ккал
   Б 110 / Ж 50 / У 145
   💧 1900 мл воды

Учла важное:
• Беременность → цель «держать», +200 ккал, +25 г белка, +фолиевая
• Аллергия на лактозу → исключаю из советов

[📸 Сфоткать первый приём]
```

**Сообщение 2 (только если goal=tone или сильный antic-сигнал):**
```
💡 Питание × салон
Антицеллюлитный массаж усиливает
эффект в 2–3 раза. Рассказать?

[Расскажи →]   [Не сейчас]
```

Блок «Учла важное» рендерится только для флагов с реальным advice-impact (см. §4.5 таблицу). Skipped-флаги НЕ отображаются.

---

## 5. Daily flow — фото еды

### 5.1 UX pattern — edit-message loading

Шаг 1: пользователь шлёт фото
Шаг 2: бот мгновенно отправляет:
```
🤖 👀 Распознаю...
```
+ `bot.send_action(typing)` до ответа GPT
Шаг 3: edit того же сообщения на финальный результат

Если LLM-call > 10 сек — промежуточный edit «*ещё пара секунд...*».

### 5.2 Confidence-based routing

GPT-4o-vision возвращает structured output: `{is_food, dish_name, confidence, kcal, protein_g, fat_g, carbs_g}`.

| Confidence | UX ветка |
|---|---|
| ≥ 0.7 (high) | best-guess + кнопка `[✏️ Поправить]` + `[👍 Всё верно]` |
| 0.3–0.7 (medium) | 3-4 варианта на выбор: `[🥔 Картофельная] [🧀 Творожная] [🥩 Мясная] [🥬 Овощная]` + `[✏️ Напишу сама]` |
| < 0.3 (low) | «*Не разобрала что на фото 🙈*» + `[📸 Переснять] [✏️ Напишу]` |
| `is_food=false` | «*Это не похоже на еду. Если хочешь записать приём — фото блюда.*» |

Universal fallback `[✏️ Напишу сама]` доступен всегда.

### 5.3 Формат ответа — hybrid (c)

```
🍝 Паста с курицей и томатами
≈520 ккал · Б 35 · Ж 18 · У 55

📊 Сегодня: 820 / 1450
   Б 58 / 110 · Ж 32 / 50 · У 78 / 145
```

- `≈` перед ккал (не «~», не «±», не «около»)
- Дисклеймер «*Это оценка ±15-20%. Хочешь точнее? Напиши что и сколько съела.*» — **только в первом фото после онбординга**, дальше не повторяем.

### 5.4 Коррекция flow

```
🤖 Что не так?

[📦 Размер порции]   [🔄 Это другое блюдо]
[➕ Добавить ингредиент]   [⏭ Удалить]
```

- **Размер порции** — `[Меньше] [Норм] [Больше]` × {0.7, 1.0, 1.3}
- **Это другое** — free-text «*это был ризотто*» → LLM пересчитывает
- **Добавить ингредиент** — free-text → LLM добавляет
- **Удалить** — soft-delete `FoodEntry`

После любой коррекции — пересчёт + «*Поправила: ≈365 ккал. Ок?*»

### 5.5 FSM-aware skip фото

Если FSM в `NutritionAnketaStates.*` — фото игнорируется с подсказкой «*Сейчас отвечаю на вопросы анкеты — пришли число / нажми кнопку*».

---

## 6. Daily flow — дневной отчёт

### 6.1 Диспетчеризация

3 точки доступа (hybrid δ):
- **Push в 21:00** (настраиваемое время в `/настройки`: 18/21/23/выкл, дефолт 21)
- **Команда `/день`** (всегда)
- **Inline после фото** — после 18:00, при ≥3 приёмов за день, один раз за вечер

**Push только активным сегодня** — иначе бот превращается в «*ещё один спам-канал*».

### 6.2 Формат — hybrid (c)

```
🌙 Итоги дня — 30 апреля

🎯 1380 / 1450 ккал (95%)
🥩 Б 98/110  🥑 Ж 52/50  🌾 У 145/145
💧 1.8 / 2.0 л

Приёмы:
🌅 каша с ягодами — 320
☀️ борщ + гречка — 520
🌙 рыба + овощи — 380
🍎 яблоко + орехи — 160

💬 Хороший день — почти в норму.
   Завтра попробуй больше белка утром:
   творог или яйца помогут дотянуть.

[📊 Неделя]   [⚙️ Время отчёта]
```

**AI-комментарий:** ≤3 предложения, ≤220 символов.

### 6.3 Tone (III + IV)

- День в норме → лёгкое подтверждение + 1 forward-tip
- Одна проблема → факт + конкретное решение, без эмоций
- Несколько дней подряд проблемных → soft escalation «*заметила паттерн... попробуй...*»
- Возврат после провала → искреннее «*заметно, что сегодня лучше*»
- Tone tied to `goal` + `health_flags`

**Eating disorder = отдельный шаблон БЕЗ цифр калорий вообще:**
```
🌙 День — 30 апреля

Сегодня: завтрак, обед, ужин,
1 перекус. 1.8 л воды.

💬 Как ты сегодня? День получился?

[💬 Поговорить]
```

### 6.4 Edge — день не полный

Если `<50%` нормы ИЛИ `≤2 приёма`:
```
🤖 🌙 Итоги дня — 30 апреля

В дневнике сегодня немного: завтрак
(320 ккал). Если что-то ещё ела —
добавь, посчитаю.

Если пропустила приёмы — как
самочувствие сегодня?

[📸 Добавить приём]   [💬 Поговорить]
```

### 6.5 `/день` посреди дня

```
🤖 📋 День сейчас — 30 апреля, 16:32

🎯 820 / 1450 ккал (57%)
🥩 Б 58/110  🥑 Ж 32/50  🌾 У 78/145
💧 1.2 / 2.0 л

Приёмы (пока): ...

До конца дня осталось:
🎯 ≈630 ккал
🥩 52 г белка
```

### 6.6 Weekly unlock

`[📊 Неделя]` disabled с tooltip «*Доступно после 7 дней дневника*» до достижения 7 days с реальными `FoodEntry` (НЕ calendar days).

После unlock — прогрессивный контент:
- ≥7 дней: средние, тренды лёгкие + teaser «*через ещё 7 дней — паттерны*»
- ≥14 дней: + weekday/weekend паттерны, время приёмов, повторы
- ≥28 дней: + месячные тренды, корреляция с записями в салон

---

## 7. Daily flow — вода

### 7.1 UI — hybrid (γ)

**Persistent reply-keyboard внизу экрана:**
```
[ 📸 Фото еды ]   [ 💧 Вода ]
[ 📋 Меню ]
```

Тап `[💧 Вода]` → бот:
```
🤖 💧 Сегодня: 1.0 / 2.0 л

   Сколько добавить?

   [+200 мл]               [+250 мл · стакан]
   [+500 мл · бутылка]   [+1000 мл · литр]

   [✏️ Другое]   [↩️ Отменить]
```

**Подсказки** — устойчивые слова («*стакан*», «*бутылка*», «*литр*», избегаем «*кружка*»). 200 — без подсказки. Длина кнопки ≤25 символов (Android-safe).

`[✏️ Другое]` → расширенный keyboard `[+150] [+300] [+350] [+750] [+1500]` + free-text «*например, 350*».

### 7.2 Free-text branch через `add_beverage` tool

```
👤 выпила стакан кофе с молоком
🤖 +250 мл (стакан) · 1.25 / 2.0 л сегодня
   +30 ккал в дневник.
   [↩️ Отменить]
```

`maxbot/ai_parsers.py::parse_beverage(text) -> {beverage_slug, ml}`:
1. Regex по `Beverage.aliases`
2. Fallback на gpt-4o-mini с tool `parse_beverage_tool`
3. Ответ с serving label из справочника + расчёт `water_ml = ml × water_coefficient`

### 7.3 Visual feedback

Каждый ввод → короткое подтверждение + inline milestone (одной строкой):
```
+250 мл · 1.0 / 2.0 л — половина дня 💪
+500 мл · 2.0 / 2.0 л — норма! 👍
+250 мл · 3.0 / 2.0 л
   Хорошо пьёшь! Если не хочется — на сегодня хватит.
```

Milestone — once per threshold per day.

### 7.4 Алкоголь

```
🤖 🍷 Бокал вина · 150 ккал в дневник.
   Кстати, после вина вода уходит активнее —
   стакан перед сном лишним не будет.
   
   [💧 +250 мл]   [Понятно]
```

Idempotent через `BotUser.context["alcohol_hint_shown_at"]`, TTL 6 часов.

При `eating_disorder=true` — алкоголь без recovery hint и без cal-цифр («*🍷 записала*»).

### 7.5 Кофе/чай — отдельные счётчики

В дневном отчёте:
```
💧 Вода:  1.8 / 2.0 л
☕ Кофе:  2 чашки (180 мг кофеина)
🍵 Чай:   1 кружка
```

При `pregnant=true` и кофе ≥200 мг/день — soft warning «*близко к лимиту 200 мг*».

### 7.6 Soft-delete + restore window

После `[↩️ Отменить]` бот показывает `[↩️ Восстановить]` в течение **15 минут** или до следующего ввода воды (что раньше). Дальше запись физически живёт 90 дней (для аналитики), потом `purge_deleted_water_entries`.

### 7.7 Reminders — opt-in OFF + adaptive

Дефолт **выкл**. В `/настройки → Уведомления → Напоминать о воде` — toggle.

При вкл — adaptive (III): раз в 4 часа проверка, если выпито <50% от proportional нормы (proportional = норма × прошедшие_часы_бодрствования / 16), nudge:
```
🤖 💧 До нормы 800 мл. До конца дня 5 часов.
[+250 мл]   [+500 мл]   [Уже пью]
```

`[Уже пью]` → silent ack, до завтра молчим.

### 7.8 Норма воды

`calc_water_norm(weight, age, climate="moderate") -> int_ml` — стандарт ВОЗ 30 мл/кг + adjustments. Хранится в `NutritionProfile.daily_water_ml`.

---

## 8. Beverage Hydration coefficients

Seed-данные для `Beverage` (Maughan et al. 2016, Beverage Hydration Index, Am J Clin Nutr):

| Категория | water_coefficient | Источник |
|---|---|---|
| Вода | 1.00 | baseline |
| Чай чёрный/зелёный (умеренно) | 1.00 | BHI Maughan 2016 (миф пересмотрен) |
| Кофе ≤300 мг кофеина/день | 1.00 | BHI Maughan 2016 |
| Кофе крепкий >300 мг/день | 0.75 | BHI |
| Сок 100% | 0.85 | BHI |
| Сладкая газировка | 0.80 | BHI |
| Молоко | 1.50 | BHI (выше воды) |
| Спорт-напитки | 0.95 | BHI |
| Бульон | 0.90 | оценка |
| Пиво (4-5%) | 0.70 | BHI |
| Вино (12-14%) | 0.40 | оценка |
| Крепкий алкоголь (40%) | -0.50 | вычитает воду |

**Калории / БЖУ / кофеин** — Роспотребнадзор «*Химический состав российских пищевых продуктов*» (Скурихин-Тутельян).

---

## 9. AI Tools (новые в `ai_tools.py`)

| Tool | Назначение | Side-effect |
|---|---|---|
| `recognize_food(image_url)` | Распознавание фото → структура | Возвращает FoodRecognition, не пишет в БД |
| `add_food_entry(name, kcal, p, f, c, source)` | Создаёт `FoodEntry` | Пишет в БД, обновляет дневной счётчик |
| `correct_food_entry(entry_id, ...)` | Корректирует существующий FoodEntry | + корректирует counters |
| `add_beverage(beverage_slug, ml)` | Добавляет запись воды/напитка | Пишет `WaterEntry`, при необходимости `FoodEntry` (калории) |
| `undo_last_water()` | Soft-delete последней `WaterEntry` | + restore window |
| `parse_age(text)` | Парсит возраст из free-text | None / int / "REFUSED" |
| `parse_height(text)` | Парсит рост (см / м / см без единиц) | None / int |
| `parse_weight(text)` | Парсит вес (число или диапазон) | `{value, range, exact}` |
| `parse_allergies(text)` | Парсит аллергии в slug-list | `{items, vague, types}` |
| `parse_beverage(text)` | Парсит напиток + объём | `{beverage_slug, ml}` |
| `ack_nutrition_disclaimer()` | Ack дисклеймера inline | Пишет в `NutritionProfile.nutrition_disclaimer_acked` |
| `decline_advice_no_consent()` | Отказ от совета без consent | Inline ack-кнопка |
| `recommend_doctor_visit(reason)` | Honest doctor referral | НЕ кросс-промо, НЕ салон |
| `suggest_salon_service(slug, reason)` | Контекстное кросс-промо в салон | data-driven trigger |
| `update_user_profile(field, value)` | Обновление age/height/weight/gender по явному самоназванию | Пишет в `NutritionProfile` |

---

## 10. Нудж-система

### 10.1 Классификация

```python
class NudgeClass(TextChoices):
    SERVICE = "service"     # ожидаемая коммуникация — soft cap
    CARE = "care"           # доверие — аккуратный cap
    MARKETING = "marketing" # выручка — жёсткий cap
```

### 10.2 8 типов нуджей

| Kind | Class | Trigger | Priority |
|---|---|---|---|
| `booking_continuation` | service | viewed_service / viewed_slots / asked_price без записи | 100 |
| `health_concern_high` | care | high-severity health flag mismatch | 90 |
| `health_concern_medium` | care | medium severity | 80 |
| `after_service_care` | service | 2-3h после визита (immediate) + day+1 (next_day) | 70 |
| `weekly_unlock` | care | 7 days с FoodEntry, one-time event | 60 |
| `returning_success` | care | 3+ дней провал → 2 дня в норме | 50 |
| `pattern_detected` | care | PatternRule match | 40 |
| `pattern_followup` | care | через 7d после accepted pattern | 35 |
| `health_concern_low` | care | low severity | 30 |
| `cross_promo` | marketing | commitment 21+d + goal=tone or signal | 20 |
| `reengagement` | care | 3-7d silence (nutrition_active) / 5-7d (salon_lead) | 10 |

### 10.3 Caps

| Class | Per day | Per week |
|---|---|---|
| SERVICE | без жёсткого cap | 5 |
| CARE | 1 | 2 |
| MARKETING | 0 | 0 (1 раз в 60 дней) |

Дневной отчёт, water reminders, ответы AI на user-message — НЕ нуджи, не считаются.

### 10.4 Quiet hours

22:00–09:00 local time (`bot_user.timezone`, default `Europe/Moscow`).

Исключения:
- BookingReminder за 2 часа (visit at 7:00 → reminder at 5:00)
- Подтверждение / отмена / перенос записи
- Ответы AI на user-message

### 10.5 Cooldowns

| Kind | Cooldown |
|---|---|
| reengagement | 30 дней |
| weekly_unlock | one-time |
| pattern_detected | 21 день (45 при mode=less_often) |
| pattern_followup | one-time per pattern |
| health_concern_low | 30 дней |
| health_concern_medium | 14 дней |
| health_concern_high | 7 дней |
| cross_promo | 60 дней (90 при less_often, forever при «не показывай») |
| returning_success | 30 дней |
| after_service_care_immediate | one per visit |
| after_service_care_next_day | one per visit |
| booking_continuation_initial | 2-6 часов после signal |
| booking_continuation_repeat | 24 часа после initial |
| booking_continuation_silence | 14 дней после repeat |

### 10.6 Mute (3 уровня)

| Level | Effect |
|---|---|
| `[Не показывай такое]` | Forever mute этого kind |
| `[Показывать реже]` | Cooldown × 2 |
| Settings menu | Per-kind toggle |
| Auto-mute | После 2 ignored (где ignored = seen + 24h без клика + user активен после) |

**Health-flag mute** для критичных (pregnancy, diabetes_t1, eating_disorder, severe_allergies) — 3 опции вместо 2:
```
[Показывать реже] [Отключить] [Оставить как есть]
```

### 10.7 AI vs Templates

| Kind | Mode |
|---|---|
| reengagement, weekly_unlock, returning_success, booking_continuation, after_service_care | Templates |
| pattern_detected, health_concern, cross_promo | AI с жёстким контейнером |

**`NUDGE_AI_CONTAINER`** prompt: max chars per kind, тон «*заботливый, спокойный*», запрет «ты должна», обязательно конкретный data-signal.

### 10.8 Dispatcher schedule

| Task | Frequency | Kinds |
|---|---|---|
| `nudge_dispatcher_general` | 1/час (`:15`) | reengagement, weekly, pattern, health, cross_promo, success |
| `nudge_dispatcher_booking` | каждые 15 мин | booking_continuation |
| `nudge_dispatcher_aftercare` | каждые 30 мин | after_service_care |
| `water_nudge` | существующий | water reminders (не нудж формально) |
| `daily_report_dispatcher` | per-user time | дневной отчёт |

### 10.9 Pattern rules (seed для `PatternRule`)

| slug | min_repeats | min_active_days | severity | requires_health_flags_absent |
|---|---|---|---|---|
| evening_sweets | 4 | 14 | medium | `eating_disorder` |
| low_protein | 5 of 7 | 7 | medium | `eating_disorder` |
| low_water | 4 of 7 | 7 | low | — |
| late_dinner | 3 of 7 | 7 | low | `eating_disorder` |
| meal_skips | 3 in row | 3 | high | — |
| late_caffeine | 3 of 7 | 7 | low | — |
| frequent_alcohol | 2-3 of 7 | 14 | low | `eating_disorder`, `pregnant`, `breastfeeding` |

`frequent_alcohol` — показывается **один раз навсегда** (cooldown=forever после первого показа). Без морализаторства.

### 10.10 Race-condition guards

- Перед отправкой нуджа: если user-message за последние 5 минут → отмена нуджа
- Если `Conversation.last_message_at` за последние 10 минут → отмена нуджа
- Несколько candidates одного цикла → только highest priority. Остальные не копятся.

### 10.11 Ignored detection

```python
def is_ignored(message: Message) -> bool:
    return (
        message.seen_at
        and hours_since(message.seen_at) >= 24
        and not message.action_data.get("clicked_button")
        and Message.objects.filter(
            conversation__bot_user=message.conversation.bot_user,
            role="user",
            created_at__gt=message.seen_at,
        ).exists()
    )
```

Ключевое — пользователь должен быть **активен после** seen_at, иначе это просто отсутствие.

---

## 11. Telemetry

| Event | Where | Why |
|---|---|---|
| `NudgeEvent.detected_at` | NudgeEvent | детектор сработал |
| `NudgeEvent.sent_at` | NudgeEvent | отправлено в MAX |
| `NudgeEvent.blocked_at` + reason | NudgeEvent | отклонено диспетчером |
| `NudgeEvent.seen_at` | NudgeEvent | MARK_SEEN |
| `NudgeEvent.clicked_at` + button | NudgeEvent | юзер кликнул |
| `Message.tokens_in/out` (есть) | Message | LLM cost |
| `Message.action_data["vision_cost_usd"]` | Message | per-photo cost |
| `Message.action_data["vision_confidence"]` | Message | accuracy tracking |
| `FoodEntry.correction_count` | FoodEntry | UX quality (high count = плохое распознавание) |

**Дашборды** (Django Admin custom views или metabase):
- Funnel: detected → sent → seen → clicked per kind
- CTR per kind, per class за 30 дней
- Mute-rate per kind
- Median time-to-click
- Vision cost per active user / month
- Correction rate per food (top 20 «проблемных» блюд)

**Триггеры на ревью:**
- CTR одного kind <10% → kind на ревью
- Mute-rate одного kind >30% → удаление или переписать
- Vision cost >$2/user/month → cost optimization sprint

---

## 12. Privacy & Compliance

### 12.1 152-ФЗ

- **Consent** до сбора health data (экран 3d.0). Кнопка отказа `[Не сейчас, без советов]` обязательна — иначе принуждение, юр-неполноценный ack.
- **Version-aware ack:** `nutrition_disclaimer_acked: {ts, version, screen}`. Bump version → re-ack у активных пользователей.
- **Soft-delete с покрытием 90 дней** — для аудита и аналитики, после physical purge.

### 12.2 Health safety

- **Eating disorder = silent режим:** никаких цифр калорий в дневном отчёте, supportive tone, при упоминании веса/срыва — переадресация специалиста.
- **Pregnancy override:** дефицит → принудительно maintain, +фолиевая в советах, кофеин ≥200 мг/день → warning.
- **Honest doctor referral:** `recommend_doctor_visit()` НЕ ведёт в салон. Поликлиника / эндокринолог / психотерапевт.
- **Health-warning mute** с двойным confirm для критичных flags.

### 12.3 BMI/BMR safety nets

- BMI < 18.5 + цель «похудеть» → soft warning ladder (3 опции)
- BMR floor (BMR + 100 ккал) — auto-ladder pace → goal с прозрачным объяснением
- Hard floor никогда не молчит — всегда явное сообщение

---

## 13. Целевая FSM-диаграмма (сокращённо)

```
[BotUser нажал /start или 📅/🍎/💬]
   │
   ▼
[main_menu_keyboard 3 кнопки]
   │
   ├── [📅 Запись в салон] → существующий booking flow
   ├── [💬 Задать вопрос]   → ai_assistant
   └── [🍎 Дневник питания]
         │
         ▼
   [welcome_nutrition_keyboard]
         │
         ├── [📸 Попробовать сразу] → photo flow (с дефолтом 2000 ккал)
         └── [📝 Настроить под себя] → NutritionAnketaStates.consent
                   │
                   ├── [✓ Понятно]      → gender → age → height → weight → goal → ...
                   └── [Не сейчас]      → degraded mode (no advice)

[После анкеты complete]
   │
   ▼
[final_screen with kcal/БЖУ/Учла важное + 📸 первое фото]
   │
   ▼
[Daily loop]
   ├── Reply-keyboard [📸 Фото][💧 Вода][📋 Меню] всегда внизу
   ├── Фото → ai_assistant → recognize_food tool → FoodEntry
   ├── 💧 Вода → water_keyboard → WaterEntry
   ├── Free-text → ai_assistant (parse_beverage / answer / suggest)
   ├── 21:00 → daily_report
   └── Async nudge_dispatcher → NudgeEvent
```

---

## 14. Celery beat schedule (новые задачи)

```python
CELERY_BEAT_SCHEDULE.update({
    "maxbot-daily-report-dispatcher": {
        "task": "maxbot.tasks.send_daily_reports",
        "schedule": crontab(minute="0,15,30,45"),  # каждые 15 минут — каждый user в свой timezone hour
    },
    "maxbot-water-nudge-every-4h": {
        "task": "maxbot.tasks.send_water_nudges",
        "schedule": crontab(minute=0, hour="*/4"),
    },
    "maxbot-nudge-dispatcher-general": {
        "task": "maxbot.nudges.dispatcher_general.run",
        "schedule": crontab(minute=15),  # каждый час в :15
    },
    "maxbot-nudge-dispatcher-booking": {
        "task": "maxbot.nudges.dispatcher_booking.run",
        "schedule": crontab(minute="*/15"),
    },
    "maxbot-nudge-dispatcher-aftercare": {
        "task": "maxbot.nudges.dispatcher_aftercare.run",
        "schedule": crontab(minute="0,30"),
    },
    "maxbot-purge-deleted-water-entries": {
        "task": "maxbot.tasks.purge_deleted_water_entries",
        "schedule": crontab(hour=4, minute=0),
    },
    "maxbot-purge-deleted-food-entries": {
        "task": "maxbot.tasks.purge_deleted_food_entries",
        "schedule": crontab(hour=4, minute=15),
    },
})
```

---

## 15. Migration list (high-level)

| # | Migration | Models / fields |
|---|---|---|
| 0067 | `add_nutrition_profile_and_botuser_fields` | `NutritionProfile`, `BotUser.timezone`, `BotUser.health_flags` |
| 0068 | `add_beverage_catalog` | `Beverage` |
| 0069 | `add_water_entry` | `WaterEntry` |
| 0070 | `add_food_entry` | `FoodEntry` |
| 0071 | `add_aftercare_to_service` | `Service.aftercare_text_immediate`, `Service.aftercare_text_next_day` |
| 0072 | `add_nudge_event` | `NudgeEvent` |
| 0073 | `add_nudge_mute` | `NudgeMute` |
| 0074 | `add_pattern_rule` | `PatternRule` |

Data migrations:
- `seed_beverages` — 50 типичных напитков
- `seed_pattern_rules` — 7 правил из §10.9

---

## 16. Open questions (для плана имплементации)

1. **MVP-scope cut.** Что попадает в первый release vs follow-ups?
   - MVP: онбординг + фото + дневной отчёт + вода + 3-4 базовых нуджа
   - Phase 3.5: weekly summary, pattern engine, after_service_care, cross_promo
   - Phase 4: Variant B (vision через ai_assistant), advanced nutrition (микронутриенты)
2. **Воркфлоу контента.** Кто пишет `Service.aftercare_text_*`? Нужен ли preview-mode для контент-менеджера?
3. **Тестовая стратегия для AI-nudges.** Как проверять `NUDGE_AI_CONTAINER` валидацию? Snapshot-тесты с фиксированными prompt → expected pattern?
4. **A/B testing infra.** Хотим ли проверять CTR разных формулировок template'ов? Если да — нужен `NudgeTemplate` с variants.
5. **Vision cost monitoring.** Алерт когда `vision_cost_usd > X / day / total`?
6. **Backup mode при OpenAI outage.** Если vision не отвечает 60s — fallback на «*Запиши приём текстом — сейчас фото-распознавание недоступно*»?
7. **Existing user migration.** Как обрабатывать BotUser без `NutritionProfile` (все существующие)? Lazy-create при первом hit на nutrition flow.
8. **GDPR / 152-ФЗ data export.** `/настройки → Скачать мои данные` — JSON со всеми FoodEntry, WaterEntry, health_flags. Backlog или MVP?

---

## 17. Дальше

- **Шаг 1:** декомпозиция в `docs/plans/maxbot-phase3-nutrition.md` по T01-Tn задачам (аналогично `maxbot-phase24-consultative.md`)
- **Шаг 2:** seed-материалы — список из 50 Beverage + 7 PatternRule с конкретными формулировками advice_template
- **Шаг 3:** AI-prompt прототипы — `NUDGE_AI_CONTAINER`, `daily_report_prompt`, vision recognition prompt
- **Шаг 4:** UX-копи в финале — все exact texts welcome / disclaimer / errors / milestones
- **Шаг 5:** Implementation в TDD по плану

---

*Дизайн закреплён 2026-05-01 после 4 раундов UX-walk-through:
welcome → nutrition entry → анкета (gender/age/height/weight/goal/health) →
daily flow (фото → дневной отчёт → вода → нуджи).*
