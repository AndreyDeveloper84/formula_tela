# MAX-бот Phase 2.4 — Consultative AI Concierge

**Цель:** превратить бот из "ищет по слову" в "консультирует по цели". Дружелюбная беседа → выяснение пейна/цели → персональная рекомендация → запись с учётом контр-показаний → запоминание клиента → post-visit follow-up.

**Контекст:** Phase 2.3 (PR #109) дал AI Concierge с tools (search_services, show_slots, confirm_booking, my_bookings) + Conversation/outcome + LLM meta-analysis. Сейчас бот реактивный — отвечает на конкретный запрос, но **не консультирует**.

---

## Координация с ayla-ai-core (DRF-237/238/239 — DONE, v0.5.0)

Параллельно идёт разработка `C:\Users\user\PycharmProjects\ayla-ai-core` — shared lib для бота и Ayla marketplace. **Что уже есть в shared (НЕ дублировать):**
- `AIConcierge` orchestrator (11-step async pipeline)
- `BrandVoiceConfig` + `FORMULA_TELA_VOICE` (assistant_name="Алина", business_address, off_topic_redirect, `examples: list[Example]`)
- `render_system_prompt` со всеми 11 правилами + Phase 0 пустые слоты
- 5 tools: `show_masters` / `show_slots` / `confirm_booking` / `show_my_bookings` / `ask_clarification` — generic over int|UUID id
- Anti-hallucination: `SpecialistContext[ID_T]` + `dispatch_tool_call` с ID cross-validation
- DRF-243 (pending): миграция бота на shared lib (бот сейчас имеет свой prompt copy и `search_services` вместо `show_masters`)

**Чего НЕТ в shared (можно делать локально или предложить вынести):**
- `recommend_services` tool по `Service.goals` — bot-specific Domain logic (Django ORM)
- `Service.goals` field (Django ORM бота)
- `Service.contraindications` + health screening flow
- Returning customer enrichment (читает `BookingRequest`, `Conversation` — это бот-БД)
- Post-visit follow-up Celery cron
- `search_masters(criteria)` filter — можно сделать через `BrandVoiceConfig.examples` + `show_masters` ranking в `context_builder`

**Решения:**
- **T04 ОТМЕНЁН** — `FORMULA_TELA_VOICE` уже в shared. Вместо этого мини-task **T04a (~2h):** курировать `examples=[...]` из success conversations и подгружать в bot `ai_concierge.send_message(... voice_config=...)`.
- **T06 пересмотрен** — не делать новый tool `search_masters`. Вместо этого: расширить bot's `context_builder.py` чтобы фильтровать SpecialistCandidate по criteria (опытный/мягкий/женщина), показывать LLM подходящих → LLM вызывает `show_masters` (уже в shared). Меньше кода.
- **T02 (recommend_services)** — делаем локально в боте, после стабилизации предложим вынести в shared (DRF-244+).
- **DRF-243 миграция бота** — отдельный backlog (не часть Phase 2.4), не блокирует consultative work.

---

## Sprint 1 — Discovery + Recommendation + Safety (~15h)

### T01 — Service goal tagging (3-4h) [БЛОКЕР для T02]
**Why:** без поля "цель/пейн" LLM не может рекомендовать услуги "под результат".

**Что делаем:**
- Migration: `Service.goals = ArrayField(CharField, blank=True, default=list)`. Choices: `relax`, `back_pain`, `cellulite`, `weight_loss`, `tone`, `antistress`, `posture`, `recovery`, `beauty_face`, `lymph`, `pregnancy_safe`.
- Admin: `filter_horizontal` на `goals` через `MultiSelectField` (или JSONField + form widget). PostgreSQL prod → ArrayField, SQLite local → JSONField. Решим: **JSONField list[str]** — кросс-платформенно, без миграции типов.
- Helper: `Service.has_goal(goal: str) -> bool` для использования в фильтрах.
- One-shot LLM-скрипт `mysite/services_app/management/commands/tag_services_goals.py` — читает `Service.description + name`, шлёт в LLM (`gpt-4o-mini`), получает list[goal], записывает. Idempotent (skip если goals уже заполнены, `--force` чтобы переписать).
- Manual review через admin — менеджер корректирует.

**Acceptance:**
- Все active Service имеют ≥1 goal в proden seed
- `Service.objects.filter(goals__contains=["relax"])` работает на SQLite + Postgres
- Admin filter "Цель/результат"

**Files:** `services_app/models.py`, `services_app/admin.py`, `services_app/migrations/00XX_service_goals.py`, `services_app/management/commands/tag_services_goals.py`, `tests/test_service_goals.py`.

---

### T02 — Discovery flow в AI Concierge (6-8h) [нужен T01]
**Why:** клиент пишет "хочу массаж" — бот должен спросить "что беспокоит / какой результат?", потом рекомендовать.

**Что делаем:**

1. **Tool `recommend_services(goals: list[str], category: str | null) → list[Service]`** — фильтрует Service по `goals__overlap`, ранжирует по `is_popular` + cosine similarity description к запросу. Возвращает 2-4 топа.

2. **Tool `ask_discovery(goals: list[str] | null)`** — *виртуальный* tool: не делает БД-запросов, просто маркер для LLM что нужно задать вопрос. Возвращает шаблон вопроса по category. Минималка — без tool, через prompt.

3. **Prompt-блок «КОНСУЛЬТАТИВНЫЙ РЕЖИМ»** в `maxbot/ai_concierge/prompts.py`:
   ```
   Если клиент назвал общую категорию ("массаж", "процедура") БЕЗ конкретики:
   — Задай 1 вопрос: что беспокоит / какой результат хочется?
   — Дождись ответа, классифицируй в goals (relax/back_pain/cellulite/...).
   — Вызови recommend_services с этими goals.
   — Ответь 2-3 услугами с краткой персонализацией: "При [пейн] хорошо подходит X, потому что [механизм]".
   НЕ задавай больше 1 вопроса подряд. Если клиент уклоняется — предложи топ-3 популярных.
   ```

4. **Few-shot examples в prompt** — 3 примера правильных консультативных диалогов.

**Acceptance:**
- На "хочу массаж" бот отвечает уточняющим вопросом, не списком услуг
- На "болит спина после офиса" → рекомендует релаксационный/спортивный/классический с обоснованием
- На "просто что-то расслабляющее" → 2-3 услуги с goals=relax
- E2E test: 3 сценария discovery в `tests/maxbot/test_ai_discovery.py`

**Files:** `maxbot/ai_concierge/tools.py`, `maxbot/ai_concierge/handlers.py`, `maxbot/ai_concierge/prompts.py`, `tests/maxbot/test_ai_discovery.py`.

---

### T03 — Контр-показания (3h) [юридический must-have]
**Why:** массаж/обёртывания имеют contraindications (беременность, давление, операции). Сейчас бот молча записывает.

**Что делаем:**
- Migration: `Service.contraindications = TextField(blank=True)` + `Service.requires_health_check = BooleanField(default=False)`.
- Заполнить через admin для всех услуг (антицеллюлитный, баночный, обёртывания, лимфодренаж = `requires_health_check=True`).
- В `confirm_booking` handler: если `service.requires_health_check` И в `Conversation` нет ответа на health-screening → **прервать flow**, задать вопрос: "Перед записью уточним: нет ли у вас беременности, повышенного давления, недавних операций? (это важно для безопасности процедуры)".
- Записать ответ в `Conversation.context.health_screened = True/False/details`.
- Если ответ "да, есть проблема" → бот не записывает, советует созвон с менеджером, создаёт `BookingRequest(source=bot_max, comment="клиент сообщил противопоказание: ...")`, outcome=redirected.

**Acceptance:**
- Запись на антицеллюлитный без health-screening невозможна
- Запись на классический массаж — без вопросов
- Если клиент сказал "беременна" → бот вежливо отказывает + создаёт redirected inquiry для менеджера

**Files:** `services_app/models.py`, `services_app/migrations/00XX_contraindications.py`, `maxbot/ai_concierge/action_service.py`, `maxbot/ai_concierge/prompts.py`, `tests/maxbot/test_health_screening.py`.

---

## Sprint 2 — Few-shot Examples + Customer Memory (~6-8h)

### T04a — Курировать FORMULA_TELA_VOICE.examples (~2h) [REPLACES T04]
**Why:** `FORMULA_TELA_VOICE` уже в shared с `examples: list[Example]` (пустой по дефолту). Нужно собрать 5 эталонных диалогов из успешных conversations и подключить.

**Что делаем:**
- `maxbot/ai_concierge/voice_examples.py` — module с константой `FORMULA_TELA_EXAMPLES: list[Example]` (5 диалогов: greeting, discovery, recommendation, contraindication-handling, post-confirm).
- В bot's `prompts.py` (или where `render_system_prompt` вызывается): 
  ```python
  voice = dataclasses.replace(FORMULA_TELA_VOICE, examples=FORMULA_TELA_EXAMPLES)
  ```
  (FORMULA_TELA_VOICE — frozen dataclass, нужен replace)
- Не дублировать BrandVoiceConfig в боте. Импорт `from ayla_ai_core import FORMULA_TELA_VOICE, Example`.

**Acceptance:**
- 5 examples в prompt после render
- Если ayla-ai-core не установлен (CI без editable install) — graceful fallback на базовый prompt без examples
- Test проверяет что examples_block присутствует в rendered prompt

**Files:** `maxbot/ai_concierge/voice_examples.py`, `maxbot/ai_concierge/prompts.py` (использование), `tests/maxbot/test_voice_examples.py`.

---

### T05 — Returning customer recognition (3h)
**Why:** `BotUser.context` не используется. Возврат клиента → персонализация.

**Что делаем:**
- В `maxbot/ai_concierge/context_builder.py` подгружать:
  - `BookingRequest.objects.filter(bot_user=user, is_processed=True).order_by('-created_at')[:3]` → "последние 3 визита"
  - `Conversation.objects.filter(bot_user=user, outcome='success').count()` → "X успешных записей"
- Передавать в LLM context как блок `## ИСТОРИЯ КЛИЕНТА`.
- Prompt-блок: "Если клиент возвращается — поздоровайся по имени, вспомни последний визит, спроси повторить или попробовать новое".

**Acceptance:**
- Returning user (≥1 success conversation) видит "Здравствуйте, Анна! Прошлый раз был [услуга]..."
- New user — стандартное приветствие
- Тест на 2 кейса в `test_returning_customer.py`

**Files:** `maxbot/ai_concierge/context_builder.py`, `maxbot/ai_concierge/prompts.py`, `tests/maxbot/test_returning_customer.py`.

---

## Sprint 3 — Master Selection + Retention (~10h)

### T06 — Master criteria filtering в context_builder (3-4h) [REVISED]
**Why:** "к кому записаться?" — сейчас не учитывает критерии. Не делаем новый tool — используем shared `show_masters` + ранжирование в `context_builder`.

**Что делаем:**
- `maxbot/ai_concierge/context_builder.py` — расширить функцию подбора SpecialistCandidate:
  - Парсить из user message keywords: "опытный" / "мягкий" / "сильный" / "женщина" / "мужчина".
  - Фильтровать `Master.objects.all()` по: `experience >= 5` для "опытный", keyword match в `approach`, `Master.gender` (добавить поле если нет).
  - Передавать в SpecialistContext только подходящих → LLM вызывает `show_masters` (уже в shared).
- Prompt-блок (через `BrandVoiceConfig.examples`): example "опытный мастер по спортивному массажу" → show_masters с релевантными.

**Acceptance:**
- "Кто специализируется на спортивном массаже?" → context включает только тех + LLM эмиттит show_masters
- Без criteria — топ-5 по rating в context
- E2E test 3 сценария

**Files:** `maxbot/ai_concierge/context_builder.py`, `services_app/models.py` (опц. Master.gender), `maxbot/ai_concierge/voice_examples.py` (example), `tests/maxbot/test_master_filtering.py`.

---

### T07 — Post-visit follow-up Celery (6h)
**Why:** main retention/LTV driver.

**Что делаем:**
- Celery beat: ежедневно в 19:00 — `send_post_visit_followups`:
  - Найти `BookingRequest` где `is_processed=True`, дата визита = вчера, `bot_user__isnull=False`
  - Отправить через `maxbot.bot.send_message`: "Здравствуйте, Анна! Как прошёл массаж у Марии? Будем благодарны за обратную связь 🙏 [👍 / 👎]"
  - Записать в `BotUser.context.last_followup_sent_at`
- Celery beat: еженедельно по понедельникам в 12:00 — `send_repeat_offer`:
  - Найти клиентов с последним визитом 21-28 дней назад → "Время повторить процедуру?"
  - Не чаще 1 раз в 30 дней (`BotUser.context.last_repeat_offer_at`)
- Кнопка ответа → создаёт `Conversation(outcome=новый turn)` с pre-filled goal.

**Acceptance:**
- Post-visit message приходит на следующий день после визита
- Repeat offer — через 3-4 недели, не спамит
- Idempotent (повторный запуск cron не дублирует)
- 2 E2E теста

**Files:** `maxbot/tasks.py` (новый), `mysite/settings/base.py` (CELERY_BEAT_SCHEDULE), `tests/maxbot/test_followups.py`.

---

## Порядок выполнения

T01 → T02 → T03 → T04 → T05 → T06 → T07. Каждая task = отдельный коммит, связанные — отдельный PR.

## Тестирование

Обязательно `pytest mysite/tests/maxbot/` после каждой task. CI на push.

## Риски

- **T01 LLM-tagging может быть неточным** — менеджер должен проверить через admin
- **T03 health screening UX** — слишком частые вопросы раздражают, поэтому только для `requires_health_check=True` услуг
- **T07 спам** — жёсткий rate-limit на followup, 1 на визит max
