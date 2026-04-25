# Plan: MAX-бот Фаза 2 — AI Concierge через MCP-сервер

**Версия:** 1.0
**Дата:** 2026-04-25
**Цель:** превратить MAX-бот из меню-навигатора в полноценного AI-помощника, понимающего свободный текст, отвечающего по нашим данным и умеющего записывать клиента сам.

**Связано:**
- `maxbot-phase1.md` — Фаза 1 (DEPLOYED 2026-04-25)
- `memory/project_rag_mcp_backlog.md` — обоснование выбора MCP-архитектуры

---

## 1. Контекст

После деплоя Фазы 1 (5 сценариев на кнопках, FSM-заявки) клиенты пишут свободный текст («болит спина что выбрать?», «как записаться?», «работаете в воскресенье?»). Сейчас fallback-handler даёт generic ответ — клиент уходит. Нужен AI-помощник.

**Технологический выбор (2026-04-25):**
- **MCP** (Model Context Protocol) — отдельный сервис, переиспользуем для всех AI-фич проекта
- **Уровень C** (Full AI concierge) — амбициозный target
- **Бюджет $$$** — без жёсткого лимита, оптимизируем по факту

---

## 2. Целевая архитектура

```
                  ┌──────────────────┐
                  │   MAX user       │
                  └────────┬─────────┘
                           │ /start, callbacks, FREE TEXT
                           ▼
                  ┌──────────────────┐
                  │   maxbot         │   handlers/ai_assistant.py — НОВЫЙ
                  │  (ext'd Phase 1) │   ловит unmatched text → LLM
                  └────────┬─────────┘
                           │ chat completion + tools
                           ▼
                  ┌──────────────────┐
                  │   GPT-4o-mini    │   tool-use API
                  │   (OpenAI)       │   gets tools list from MCP
                  └────────┬─────────┘
                           │ tool calls (MCP)
                           ▼
                  ┌──────────────────┐
                  │  formulatela-mcp │   ← новый сервис в репо
                  │  (FastMCP server)│   tools/, resources/
                  └────────┬─────────┘
                           │ Django ORM + YClients API
                           ▼
        ┌──────────────────┴──────────────────┐
        │ Service / HelpArticle / Master / Bundle │
        │ BookingRequest / BotUser / FAQ          │
        │ embeddings (PgVector? или Chroma?)     │
        │ YClients booking API                    │
        └─────────────────────────────────────┘
```

**Почему MCP, а не inline LLM-tools:**
1. Переиспользуем для всех AI-агентов (`agents/agents/analytics`, `seo_landing`, `smm_growth` могут запрашивать данные через MCP)
2. Стандартный протокол — Claude Code, VS Code, Cursor, любой LLM могут подключаться
3. Чистое разделение: MAX-бот не знает про embeddings/YClients API — только говорит с MCP
4. Тестируется отдельно (mcp-tools-runner)

---

## 3. Декомпозиция на под-фазы

| # | Под-фаза | Что даёт пользователю | Effort | Cost/msg |
|---|---|---:|---:|---:|
| **2.1** | MCP server + RAG over FAQ | «Как записаться?» → бот находит и цитирует HelpArticle | ~15h | $0.0001 |
| **2.2** | MCP tools: услуги | «Болит спина» → бот предлагает массаж спины и приглашает записаться | ~10h | +$0 |
| **2.3** | MCP tools: мастера + слоты + booking | «Запиши к Анне на завтра в 14:00» → бот находит слот, делает запись (YClients API) | ~20h | +$0 |
| **2.4** | Personalization & recommendations | «Первый раз? Попробуйте релакс», upsell на сертификаты, история визитов | ~15h | +$0 |
| **2.5** | Voice (опц.) | голосовые сообщения | ~25h | +$0.006/min |

**Итого 2.1-2.4: ~60h.** 2.5 — отдельный проект.

---

## 4. ПОД-ФАЗА 2.1 — детальный план (стартуем сейчас)

**Цель:** клиент пишет «как записаться?» → бот через MCP+RAG находит соответствующую `HelpArticle` → отдаёт `.answer` + кнопки. Если ни одна FAQ не подходит → честно говорит «не знаю, спрошу менеджера» + создаёт `BotInquiry` для ручного ответа.

### 4.1 Структура нового сервиса

```
mysite/                                    # Django root
└── ...

services/                                  # NEW: top-level каталог сервисов
└── formulatela_mcp/                       # MCP-сервер (отдельный systemd unit)
    ├── pyproject.toml                     # отдельные зависимости (mcp, openai, etc)
    ├── README.md
    ├── src/formulatela_mcp/
    │   ├── __init__.py
    │   ├── main.py                        # FastMCP entrypoint
    │   ├── django_bootstrap.py            # читаем Django ORM из репо проекта
    │   ├── config.py                      # env-config (OPENAI_API_KEY, EMBED_MODEL, etc)
    │   ├── embeddings/
    │   │   ├── store.py                   # абстракция над vector store
    │   │   ├── chroma_backend.py          # local Chroma (default для MVP)
    │   │   └── reindex.py                 # rebuild embeddings → store
    │   ├── tools/
    │   │   ├── search_faq.py              # @mcp.tool find FAQ by query
    │   │   ├── search_services.py         # (Фаза 2.2)
    │   │   └── booking.py                 # (Фаза 2.3)
    │   └── resources/
    │       └── prompts.py                 # system prompts для tool descriptions
    └── tests/
```

И в `mysite/maxbot/handlers/ai_assistant.py` — новый handler который заменяет/дополняет fallback.

### 4.2 Embedding store — выбор

**MVP: Chroma (local, файловый)**
- Бесплатно, без сервера
- ~100 HelpArticle = быстро, без оптимизаций
- `pip install chromadb` (~50MB)
- Плюс: можно потом мигрировать на PgVector/Qdrant без изменения интерфейса

**Альтернатива: pgvector (Postgres extension)**
- Уже есть Postgres на проде
- Поддержка большого scale
- Но: extension нужно ставить через `apt` + GRANT
- Откладываем до Фазы 2.4 если/когда корпус вырастет

### 4.3 LLM-вызов из maxbot

```python
# mysite/maxbot/handlers/ai_assistant.py
from openai import AsyncOpenAI
from mcp.client.session import ClientSession

@router.message_created()  # вместо/после fallback
async def on_free_text(event, context):
    user_text = event.message.body.text

    # 1. Подключаемся к MCP
    async with mcp_client_session("formulatela-mcp") as mcp:
        tools = await mcp.list_tools()

        # 2. GPT-4o-mini с tools
        response = await openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user_text}],
            tools=tools,  # MCP-tools конвертированные в OpenAI tool-spec
        )

        # 3. Если tool-call — выполнить через MCP, дать результат GPT
        ...

    await event.bot.send_message(chat_id=..., text=response_text)
```

### 4.4 Задачи Фазы 2.1

| T | Задача | Effort |
|---|---|---|
| **2.1-T01** | Research spike: FastMCP API, OpenAI tool-use, Chroma embeddings | 2h |
| **2.1-T02** | `services/formulatela_mcp/` skeleton + pyproject.toml + main.py с одним dummy-tool `ping()` | 2h |
| **2.1-T03** | Embedding store: `store.py` + `chroma_backend.py` + `reindex.py`, индексирует HelpArticle | 3h |
| **2.1-T04** | MCP tool `search_faq(query: str, k: int = 3)` — top-k HelpArticle с similarity score | 2h |
| **2.1-T05** | maxbot handler `ai_assistant.py` — OpenAI client + MCP client + системный промпт | 3h |
| **2.1-T06** | Регистрация ai_assistant **перед** fallback в `get_routers()`. Контракт: если LLM решает что вопрос не по FAQ — fallback срабатывает | 1h |
| **2.1-T07** | Тесты: mock OpenAI + mock MCP, проверяем что нужный tool вызван и ответ отрендерен | 2h |
| **2.1-T08** | Infra: `services/formulatela_mcp/` deploy через свой systemd unit, transport=stdio (локально) или streamable-http (для prod) | 3h |
| **2.1-T09** | Docs + smoke на проде | 1h |

**Итого Фаза 2.1: ~19h** (немного больше чем сначала оценивал, потому что MCP + OpenAI integration — новые для нас зависимости).

### 4.5 Open questions до старта 2.1

1. **OPENAI_API_KEY на проде** — есть? (`agents/` его уже использует, должен быть в `.env`)
2. **Транспорт MCP**: stdio (subprocess) — проще, но maxbot должен его spawn'ить; HTTP — гибче, может стоять отдельно. Для MVP — stdio (subprocess locally), позже HTTP когда захотим переиспользовать MCP в других сервисах.
3. **Триггер ai_assistant**: только free-text без active FSM — или ещё и кнопка «❓ Задать вопрос свободно»?
4. **Если LLM не находит ответ**: fallback на текущее меню или создать `BotInquiry` для ручной обработки менеджером?

---

## 5. ПОД-ФАЗЫ 2.2-2.4 — обзор (детальная декомпозиция позже)

### 2.2 — MCP tool `search_services(symptoms: str)` (~10h)
Embeddings для `Service.name` + `Service.short_description` + `Service.description`. Запрос «болит спина» → top-3 услуги. Бот предлагает выбрать одну из них (CallbackButton) → переходит в Фазу 1 booking flow.

### 2.3 — Tools `find_master`, `find_slot`, `book_via_yclients` (~20h)
Использует существующий `services_app/yclients_api.py::YClientsAPI`. LLM умеет:
- «Запиши к Анне» → `find_master(name="Анна")` → master_id
- «На завтра в 14:00» → парсинг даты + `find_slot(staff_id, date, time)` → если свободно
- «Подтверди» → `book_via_yclients(...)` → реальная запись в YClients (не `BookingRequest`!)

Это и есть **нативная запись** из Фазы 2 оригинальной спеки.

### 2.4 — Personalization & recommendations (~15h)
- MCP tool `get_user_history(user_id)` → прошлые записи + viewed services
- System prompt получает контекст: «Это 3-й визит клиента, всегда выбирает массаж спины у Анны, прошлый раз был месяц назад» → LLM умнее предлагает
- Upsell: «Хотите купить абонемент на 5 сеансов?» (Bundle)
- Возврат к нерешённым вопросам: «В прошлый раз спрашивали про лазерную эпиляцию, готовы записаться?»

---

## 6. Риски

| # | Риск | Смягчение |
|---|---|---|
| R1 | MCP — новая технология для проекта, кривая обучения | Research-spike T01 + начать с минимального tool (search_faq) |
| R2 | Стоимость OpenAI растёт с трафиком | gpt-4o-mini для роутинга, gpt-4o только для сложных диалогов; кэш частых вопросов |
| R3 | LLM галлюцинирует про услуги/цены | Tools возвращают только данные из БД, system prompt: «не выдумывай факты» |
| R4 | YClients API падает → бот не может записать | Graceful degradation: вернуться к `BookingRequest` (Фаза 1) с пометкой «технические проблемы, менеджер перезвонит» |
| R5 | MCP-сервис — отдельный systemd → больше операционной нагрузки | Хорошие health-checks + alerts через тот же `notifications/` что у Фазы 1 |

---

## 7. Definition of Done (Фаза 2.1)

- [ ] Запрос «как записаться?» в MAX → бот цитирует FAQ #1
- [ ] Запрос «несвязанный текст» → fallback с меню (не LLM-галлюцинация)
- [ ] MCP-сервер изолированно работает (CLI: `mcp-cli call search_faq query="..."`)
- [ ] Все unit-тесты pass, smoke на проде OK
- [ ] Стоимость замерена и в плане прогноз $$$/месяц для текущего трафика

---

## 8. STATUS

- **DRAFT** 2026-04-25 — план зафиксирован, ожидает approval перед стартом
- Pending answers на 4 open questions §4.5
