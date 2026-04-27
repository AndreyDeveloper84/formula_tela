# Plan: MAX-бот Phase 2.3 — Native AI Concierge с booking через YClients

**Версия:** 1.0
**Дата:** 2026-04-26
**Статус:** APPROVED for implementation (decisions baked, ready to start)
**Связано:** `docs/plans/maxbot-phase2-ai-mcp.md` (Phase 2.1 — RAG over FAQ, DEPLOYED 2026-04-26)

---

## 1. Цель

Превратить MAX-бот из «AI-FAQ» (текущий `chat_rag` отвечает по HelpArticle) в **AI Concierge** который:
- Понимает запрос «хочу к Анне на массаж спины завтра в 14:00» и находит мастера/услугу/слот в БД + YClients
- Показывает «карточки» — мастеров с обоснованием, слоты на дату, подтверждение записи
- **Сам делает запись в YClients** после явного «Да» от клиента (callback кнопка)
- Никогда не выдумывает мастеров/услуг/слотов — все ID валидируются по реальным данным
- Сохраняет полную историю диалога в БД для admin/analytics

## 2. Решения зафиксированные user'ом 2026-04-26

| # | Вопрос | Решение |
|---|---|---|
| 1 | Conversation history в админке? | **Да** — модели `Conversation` + `Message` (variant α) |
| 2 | Сохранять `BookingRequest` после AI-записи? | **Да** — оставляем для admin-визуала + связи на `bot_user`, добавляем `yclients_record_id` |
| 3 | Native запись vs полу-автомат заявка? | **Native** — AI делает запись через YClients API после confirmation |
| 4 | Master mapping на YClients staff заполнен? | **Да** — но поля `Master.yclients_staff_id` ещё нет — добавим в T01 |
| 5 | OpenAI бюджет до ~$0.05/день OK? | **Да** |
| 6 | Multi-turn state | **Conversation + Message модели** (variant α — Ayla-pattern) |

---

## 3. Архитектура — high-level

```
┌────────────────────────────────────────────────────────────┐
│  MAX-бот webhook handler `on_free_text` (ai_assistant.py)  │
│                                                             │
│  intent_router (regex) ─→ canned response (fast path)       │
│        │ no match                                           │
│        ▼                                                    │
│  response_cache check ─→ cache hit (instant)                │
│        │ miss                                               │
│        ▼                                                    │
│  AIConcierge.send_message() ◄── НОВЫЙ pipeline              │
│        │                                                    │
│        ├─ get_or_create Conversation для bot_user           │
│        ├─ save Message(role=user)                           │
│        ├─ build context: top-N masters + services + history │
│        ├─ call OpenAI с TOOL_DEFINITIONS                    │
│        ├─ if tool_call:                                     │
│        │     dispatch_tool() → ToolResult(action_type, data)│
│        ├─ save Message(role=assistant, action_type, ...)    │
│        └─ return ChatResponseDTO                            │
│                │                                            │
│                ▼                                            │
│  render_card(action_data) → MAX inline keyboard              │
│        │                                                    │
│        ▼                                                    │
│  bot.send_message с callback кнопками                       │
└────────────────────────────────────────────────────────────┘
                                │
                                ▼
                    клиент кликает [✅ Да] на confirm_booking
                                │
                                ▼
┌────────────────────────────────────────────────────────────┐
│  Callback handler `cb:ai:confirm:{conversation_id}`          │
│                                                             │
│  ActionService.execute_confirm_booking():                    │
│        ├─ idempotency check (cache key ai-{conv}-{slot_iso}) │
│        ├─ YClientsAPI.create_booking(staff, svc, dt, phone)  │
│        ├─ if success: save BookingRequest(yclients_record_id)│
│        ├─ if YClients down: BookingRequest без id + флаг     │
│        ├─ save Message(role=tool, ...)                       │
│        └─ Telegram админу + ответ клиенту с YClients-record  │
└────────────────────────────────────────────────────────────┘
```

---

## 4. Декомпозиция (T01-T12)

### T01 — Pre-requisites + миграции (~2h)

**Что:**
- Поле `Master.yclients_staff_id` (`CharField(blank=True, null=True)`) + admin
- Модели `Conversation` + `Message` в новом app `maxbot` (или в `services_app`)
- Миграция services_app/0059 + maxbot/0001 (если новый app)

**Ayla reference:** `Ayla/djangoproject/ai/models.py:23-92` — структура Conversation+Message.

**Адаптация:**
- Ayla использует `User` (Django auth), у нас — `BotUser` FK
- Ayla использует `is_active` + `deleted_at`, у нас тоже — для soft-delete
- Поля `tokens_in/out + latency_ms` для Telemetry — копируем

**DOD:**
- `python manage.py makemigrations` создаёт ровно ожидаемые миграции
- Admin: список conversations с last_message_at + поиск по bot_user
- Admin для Message: фильтр по action_type, full content viewer

---

### T02 — Tool schemas (~2h)

**Файл:** `mysite/maxbot/ai_tools.py`

**5 tools** (адаптация из `Ayla/djangoproject/ai/tools.py`):

| Tool | Зачем | Args |
|---|---|---|
| `show_masters` | Показать рекомендованных мастеров с match-обоснованием | master_ids[], match_scores[], match_reasons[][], explanation |
| `show_slots` | Свободные слоты на дату | master_id, service_id, date |
| `confirm_booking` | Карточка подтверждения (НЕ создаёт запись!) | master_id, service_id, datetime |
| `show_my_bookings` | История записей клиента (через YClients `get_records`) | filter (upcoming/past/all) |
| `ask_clarification` | Уточняющий вопрос с options[] | question, options[] |

`ActionType` const class — стабильный wire-format.

**Adaption notes vs Ayla:**
- Ayla использует UUID (мульти-салонная платформа), мы — `int` ID из БД
- `specialist_id` → `master_id` (наш термин)
- Никаких `services_preview` (одна организация — один прайс)

**DOD:** unit-тесты на JSON-валидность каждой schema (через `jsonschema` или just dict сравнение).

---

### T03 — Tool handlers (~3h)

**Файл:** `mysite/maxbot/ai_tool_handlers.py`

**Side-effect-free валидаторы** (Ayla pattern: `tools_handlers.py:48-180`):
- `_safe_int(value)` — defensive каст, на bad input возвращает None
- `_fallback_clarification(reason)` — bounce на ask_clarification если LLM gallucinated
- `handle_show_masters(args, context)` — фильтрация ID через `context.candidate_ids`, drop невалидных
- `handle_show_slots(args)` — load Service + Master из БД, validate connection, fetch slots через YClients
- `handle_confirm_booking(args)` — load Service + Master + проверка что слот ещё свободен в YClients
- `handle_show_my_bookings(args, bot_user)` — query YClients `get_records` по client_phone из BotUser
- `handle_ask_clarification(args)` — pass-through

Anti-hallucination: `valid_set = {mid for mid in valid_ids if mid in context.candidate_ids}` — если LLM выдумал ID мастера, он не пройдёт.

**Ayla reference:** `Ayla/djangoproject/ai/tools_handlers.py` — целиком pattern, особенно `_fallback_clarification` + `_safe_uuid`.

**DOD:**
- Unit-тесты на каждый handler с реальными ORM-fixture'ами
- `test_handler_drops_hallucinated_master_id`
- `test_handler_returns_clarification_on_invalid_args`

---

### T04 — Specialist context builder (~2h)

**Файл:** `mysite/maxbot/ai_context.py`

**Что:** при каждом `chat_message` собрать контекст для LLM:
- Top-N мастеров для салона (все active, sorted by rating + experience)
- Их услуги (Service.related_services + Master.services M2M)
- Bot_user.client_name + last_seen + bookings_count

Возвращает `dataclass MasterContext(candidates, candidate_ids, summary_text)`.

**summary_text** идёт в system_prompt как context block:
```
ДОСТУПНЫЕ МАСТЕРА:
1. Анна Иванова (id=42) — массаж спины, классический, лимфодренаж
2. Денис Петров (id=43) — спортивный массаж, мануальная терапия
3. Ирина Сидорова (id=44) — лазерная эпиляция, депиляция воском
...
```

**Ayla reference:** `Ayla/djangoproject/ai/application/services/specialist_context_builder.py` (176 LOC).

**Адаптация:** у нас один салон → drop геолокация / city / radius фильтрация.

**DOD:** контекст рендерится в <500 токенов (gpt-4o-mini лучше следует коротким promt'ам).

---

### T05 — System prompt (~1h)

**Файл:** `mysite/maxbot/ai_prompts.py` (новый, заменяет константу `texts.AI_SYSTEM_PROMPT`)

**Адаптация Ayla `prompts.py`:**

```
Ты — Алина, ассистент салона «Формула тела» в Пензе.

КОНТЕКСТ:
- Сегодня: {today}
- Имя клиента: {client_name}
- Прошлых записей: {bookings_count}

ДОСТУПНЫЕ МАСТЕРА:
{masters_summary}

ПРАВИЛА:
1. Кратко (2-4 предложения), вежливо, по-русски
2. Используй ask_clarification если запрос неясен
3. Используй show_masters чтобы показать список
4. Используй show_slots чтобы показать слоты
5. Используй confirm_booking ТОЛЬКО когда явно выбран мастер+услуга+время
6. После confirm_booking ЖДИ подтверждения — НЕ создавай запись
7. show_my_bookings если клиент спрашивает «когда у меня запись»
8. НИКОГДА не выдумывай мастеров вне списка
9. НИКОГДА не выдумывай цены — они только в Service.price_from
10. Off-topic → вежливо верни к услугам
11. Не запрашивай телефон — он у нас в BotUser.client_phone
```

**DOD:** prompt rendering test с моками Master/Service.

---

### T06 — AIConcierge service (~4h)

**Файл:** `mysite/maxbot/ai_concierge.py` (новый, заменяет `chat_rag`)

**Pipeline (Ayla `chat_service.py` pattern):**

```python
async def send_message(*, bot_user, message_text) -> ChatResponseDTO:
    conversation = await _resolve_conversation(bot_user)
    user_msg = await _save_message(conversation, role='user', content=message_text)

    spec_context = await _build_master_context()
    history = await _load_recent_messages(conversation, limit=10)
    system_prompt = render_system_prompt(bot_user, spec_context)

    llm_messages = _compose(system_prompt, history, message_text)

    started = time.monotonic()
    completion = await _call_openai(llm_messages, tools=TOOL_DEFINITIONS)
    latency_ms = int((time.monotonic() - started) * 1000)

    if completion.tool_calls:
        tool_call = completion.tool_calls[0]
        tool_result = dispatch_tool_call(tool_call, spec_context, bot_user)
        action_type, action_data = tool_result.action_type, tool_result.action_data
        content = completion.content or _default_content_for(action_type)
    else:
        action_type, action_data = None, None
        content = completion.content or LLM_GIVEUP_MESSAGE

    asst_msg = await _save_message(
        conversation, role='assistant', content=content,
        action_type=action_type, action_data=action_data,
        tokens_in=completion.usage.prompt_tokens,
        tokens_out=completion.usage.completion_tokens,
        latency_ms=latency_ms,
    )

    return ChatResponseDTO(conversation_id=conversation.id, ..., action_type=..., action_data=...)
```

**DOD:** integration-тесты на 5 интентов:
- «покажи мастеров для массажа спины» → action=show_masters
- «можно к Анне на завтра» → action=show_slots
- «в 14:00» → action=confirm_booking
- «когда у меня записи» → action=show_my_bookings
- «привет» → действие None, обычный текст

---

### T07 — MAX UI rendering (~3h)

**Файл:** `mysite/maxbot/ai_ui.py`

**Что:** превратить `action_data` (dict) в MAX inline keyboard + текст сообщения.

| action_type | Render |
|---|---|
| `show_masters` | Текст «Я нашёл вам:» + список «Анна — массаж спины (★ 4.8)» с CallbackButton'ами `cb:ai:pick_master:{conv}:{master_id}` |
| `show_slots` | Текст «Свободные времена 27 апр:» + кнопки «10:00», «11:30», «14:00» с `cb:ai:pick_slot:{conv}:{slot_iso}` |
| `confirm_booking` | Текст «Анна, массаж спины, 27 апр 14:00 — записать?» + [✅ Да] (POSITIVE) [❌ Нет] (NEGATIVE) [✏️ Изменить] (DEFAULT). Callbacks: `cb:ai:confirm:{conv}` / `cb:ai:cancel:{conv}` / `cb:ai:edit:{conv}` |
| `show_my_bookings` | Список «27 апр 14:00 — Анна, массаж спины» |
| `ask_clarification` | Вопрос + кнопки с options[] (`cb:ai:answer:{conv}:{option_idx}`) |

Везде — главное меню после AI-блока (через `send_with_main_menu`).

**DOD:** snapshot-тесты на каждый action_type → ожидаемая структура attachments.

---

### T08 — Callback handlers (~3h)

**Файл:** `mysite/maxbot/handlers/ai_callbacks.py`

**Callbacks:**
- `cb:ai:pick_master:{conv}:{master_id}` — клиент выбрал из show_masters → продолжить диалог через `_send_user_choice_to_ai("Выбираю мастера #{master_id}", conv)`
- `cb:ai:pick_slot:{conv}:{slot_iso}` — выбрал слот → `_send_user_choice_to_ai("Хочу записаться на {slot_iso}", conv)`
- `cb:ai:confirm:{conv}` — подтверждение → `ActionService.execute_confirm_booking(conv)` (см. T09)
- `cb:ai:cancel:{conv}` — отмена → save Message(role=user, content="Отмена"), close conversation
- `cb:ai:edit:{conv}` — изменить → re-show ask_clarification
- `cb:ai:answer:{conv}:{idx}` — ответ на clarification → передать выбранную option в AI

**Ayla reference:** `Ayla/djangoproject/ai/application/services/action_service.py` — pattern для confirm_booking и selection-flow.

---

### T09 — ActionService — booking creation (~3h)

**Файл:** `mysite/maxbot/ai_action_service.py`

**`execute_confirm_booking(conv)`:**

```python
1. Загрузить последний confirm_booking action_data из conversation
2. Idempotency check: cache.get(f"ai-{conv.id}")
   if cached → return cached BookingRequest (двойной клик)
3. YClientsAPI.create_booking(
     staff_id=Master.yclients_staff_id,
     service_id=Service.yclients_service_id,
     datetime=...,
     client_phone=BotUser.client_phone,
     client_name=BotUser.client_name,
   )
4. Save BookingRequest(
     bot_user=conv.bot_user,
     source='bot_max',
     service_name=Service.name,
     client_name=..., client_phone=...,
     yclients_record_id=record_id_from_api,
     comment=f"AI-запись через conversation {conv.id}",
   )
5. cache.set(f"ai-{conv.id}", booking.id, 3600)
6. Telegram админу: «🤖 AI создал запись #ID для клиента X»
7. save Message(role=tool, content="Booking created", tool_name="confirm_booking")
8. Закрыть conversation (is_active=False)
9. Return success message клиенту: «✅ Записал вас на 27 апр 14:00. Ждём!»
```

**Graceful degradation (YClients API down):**
- catch `BookingClientError` from `YClientsAPI`
- Save BookingRequest **без** `yclients_record_id` + поле `requires_manual_booking=True` (новое)
- Telegram админу: «⚠️ AI не смог записать в YClients (API down) — клиент X, требуется ручное бронирование»
- Клиенту: «Не получилось автоматически записать. Менеджер свяжется в течение часа.»

**Ayla reference:** `Ayla/djangoproject/ai/application/services/action_service.py:60-180`.

---

### T10 — Replace chat_rag in on_free_text (~2h)

**Файл:** `mysite/maxbot/handlers/ai_assistant.py`

**Изменения:**
- Удалить `chat_rag` из импорта, заменить на `AIConcierge.send_message(...)`
- intent-router и response-cache **остаются** (быстрый path для приветствий + повторов)
- Если `action_type` не None → `render_card(action_data)` → send_message с inline keyboard
- Если `action_type` is None → text + `send_with_main_menu`
- giveup detection через `is_giveup` (как сейчас)

**Backward compat:** `chat_rag` остаётся в `llm.py` для warmup (10 hot questions без tools — экономнее).

---

### T11 — Integration tests (~3h)

**Файл:** `mysite/tests/maxbot/test_ai_concierge_e2e.py`

**5 сценариев:**
1. **Полный happy-path:** «хочу записаться к Анне на массаж спины завтра в 14:00» → show_masters → pick → show_slots → pick → confirm → click Да → BookingRequest + YClients-record
2. **Частичный запрос:** «массаж спины» → ask_clarification (день? мастер?)
3. **Занятый слот:** YClients вернул `slot_taken` → show_slots с альтернативами
4. **YClients down:** API throws → graceful BookingRequest без id + Telegram админу
5. **Cancellation:** клиент жмёт ❌ → conversation closed без записи

Mock'и: `YClientsAPI.create_booking`, `OpenAI.chat.completions.create` (с tool_calls).

---

### T12 — Deploy + observability (~2h)

- Логи каждого этапа: intent → entities → context → llm-call → tool_dispatch → action_data → callback → booking
- Структурированные логи (`extra={"conv_id": ..., "action_type": ...}`) для grep по conversation
- Smoke-сценарий на проде: 5 диалогов от моего тестового аккаунта
- Memory entry: `project_maxbot_phase23_deployed.md` с операционными деталями

---

## 5. Что НЕ делаем в этой фазе

- **Voice** — голосовые сообщения. Отдельная фаза 2.5.
- **Personalization** — рекомендации на основе истории. Phase 2.4.
- **Multi-conversation pinning** — например «продолжить вчерашний диалог». Будет если запросят.
- **MCP search_services** — у нас уже есть RAG over HelpArticle, для услуг сделаем через `MasterContext` в system_prompt (уверен что 30 услуг легко влезут в context).

---

## 6. Riski + mitigations

| # | Риск | Mitigation |
|---|---|---|
| R1 | LLM выдумывает master_id | `context.candidate_ids` фильтр в handler'ах |
| R2 | LLM выдумывает цену в content (не в action_data) | System_prompt правило 9 + регулярный prompt-eval |
| R3 | Пользователь спамит messages — много Conversation rows | Cleanup task (cron) удаляет conversations старше 90 дней |
| R4 | Двойной клик [✅ Да] → две записи в YClients | Idempotency cache `ai-{conv}` TTL 1h + check `BookingRequest.yclients_record_id` уникальный |
| R5 | YClients staff_id не заполнен у Master | T01 миграция + админ-алерт «У X мастеров не маппинг» + warning в логах если попытка booking без mapping |
| R6 | OpenAI usage spike (бот в каталоге MAX) | Daily token limit через Redis (Ayla pattern, simple) — пока не нужно, добавим если усе проявится |
| R7 | Conversation never closes (клиент уходит после show_masters) | `is_active=False` через `cron job` если last_message_at > 7 дней OR через `bot_started`/`/start` |
| R8 | Race на confirm_booking — slot занят кем-то другим | YClientsAPI.create_booking вернёт ошибку → catch → show_slots с обновлёнными слотами |
| R9 | Migration на prod ломает существующих BotUser | Conversation + Message — новые таблицы, не трогают BotUser. `Master.yclients_staff_id` — nullable, не ломает |
| R10 | LLM долго отвечает (>10s) | typing_on indicator уже есть, плюс tool-use может быть быстрее RAG (один LLM-call с tools vs два LLM-call в текущем) |

---

## 7. Open items для работы (не блокеры)

- [ ] Кто заполнит `Master.yclients_staff_id` для активных мастеров? — менеджер салона через `/admin/`. Я подготовлю management command `python manage.py audit_master_yclients_mapping` для проверки.
- [ ] Нужен ли отдельный `Conversation.title` (auto-generated «Запись на массаж спины 27 апр»)? — для лучшей admin UX. Откладываем на T01-bonus.
- [ ] Cleanup-cron для conversations >90 дней. Добавим в Celery beat schedule после T11.

---

## 8. Estimated total: ~30h

Разбито на 12 PR'ов (один PR = одна задача T01-T12). Параллельно делать T02+T03 (tools+handlers) и T04+T05 (context+prompt) можно — они не зависят друг от друга.

Минимально blocking path:
```
T01 (models) ─→ T06 (concierge) ─→ T10 (replace chat_rag)
                                            │
                                            ├─→ T07 (UI render)
                                            └─→ T08+T09 (callbacks+booking)
                                                              │
                                                              └─→ T11 (E2E) → T12 (deploy)
```

---

## 9. STATUS

- **APPROVED 2026-04-26** — все decisions baked, Ayla referenced
- Ready to start T01 (migrations) когда user скажет «поехали»
