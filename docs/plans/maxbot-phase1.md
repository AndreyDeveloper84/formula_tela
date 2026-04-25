# Plan: MAX Bot Фаза 1 — MVP с нативным приёмом заявок и персонализацией

**Версия:** 1.0
**Дата:** 2026-04-24
**Автор:** AI-assisted, owner: @AndreyDeveloper84
**Связанные документы:**
- `PHASE1_TECHNICAL_SPEC.docx` (исходная спека от Макса — частично устаревшая, см. ниже)
- `CLAUDE.md` — проектные конвенции

---

## 1. Контекст и почему

Макс передал `PHASE1_TECHNICAL_SPEC.docx` с планом MVP бота для MAX (web.max.ru). Спека предполагала «встроенный бот без сервера + одна Django-команда для экспорта JSON с контентом».

**После ресёрча MAX Bot API и отдельного разговора с владельцем** определили:
1. У MAX **нет нативного no-code конструктора** — сценарии настраиваются либо через сторонние SaaS (BotHelp, Watbot), либо через официальный Bot API (webhook/long-poll) + свой сервер.
2. Выбран путь **Bot API + свой Python-сервис** — без подписок, с realtime-синхронизацией с Django-моделями и приёмом заявок прямо в БД.
3. Владелец подтвердил расширение скоупа: нужна **персонализация** (бот запоминает клиента, при повторном обращении ведёт диалог как со знакомым) и **нативный сбор заявок** прямо в боте, без YClients-iframe.

---

## 2. Scope Фазы 1

### В scope
- Standalone Python-сервис `maxbot/` на базе `maxapi` SDK (async, webhook)
- 2 новые Django-модели (`BotUser`, `HelpArticle`) + миграция существующего `BookingRequest`
- 5 сценариев бота: `/start`, каталог услуг, FAQ, контакты, заявка (с FSM: имя → телефон → комментарий)
- Персонализация: при повторном визите бот узнаёт пользователя по `max_user_id`, обращается по имени, подтягивает историю
- Инфраструктура: systemd-unit `formula-tela-maxbot.service` на том же prod-сервере, nginx-location `/api/maxbot/webhook/`
- Тесты: mock-based unit-тесты handler'ов, FSM, keyboard-factories, персонализация
- Админка: `HelpArticle` редактируется через Django admin

### Вне scope (Фаза 2+)
- Нативная запись прямо в YClients через API (пока — только заявка на перезвон в `BookingRequest`)
- SMS-напоминания, чеки
- Отзывы через бот
- Рекомендации на основе истории (ML)
- Telegram/WhatsApp версии
- Multimedia (видео, голосовые, карусели)
- **NLP-роутинг свободного текста на FAQ** (см. backlog ниже)

### Backlog: NLP free-text → FAQ routing (после Фазы 1)

Сейчас `fallback.py::on_fallback` ловит ВСЕ нематченные text-сообщения и отвечает «Не совсем понял» — без проверки против `HelpArticle`. Это intentional для MVP, но клиенты пишут естественные вопросы. Опции по нарастанию сложности:

1. **Keyword-match** — нормализация через `pymorphy3` (уже в requirements) + intersect слов с `HelpArticle.question`. ~30 мин, бесплатно. Низкий precision на сложных формулировках.
2. **LLM-router** — GPT-4o-mini выбирает `HelpArticle.id` или null. ~1 час, ~$0.0001/запрос. Хороший precision.
3. **LLM + answer-generation fallback** — если ни одна FAQ не подошла, GPT генерирует ответ. Рискованно (галлюцинации про услуги/цены). Нужны guardrails.
4. **RAG через embeddings** — векторизуем `HelpArticle` (`text-embedding-3-small`), косинусная близость с эмбеддингом ввода → top-1 article. ~3 часа, дешёвый embedding ($0.02/1M tokens) + retrieval offline. Лучший precision/cost.
5. **🎯 RAG MCP-сервер** — отдельный MCP (Model Context Protocol) сервис который держит embedding-store, отвечает агентам/боту через единый интерфейс. **Обязательно разобрать как технологию** — переиспользуется для всех будущих ботов и AI-агентов в проекте (analytics, seo_landing, smm и т.д. могут таскать FAQ/документы через него). Сложнее (~6+ часов на основу), но архитектурный выигрыш долгосрочный.

---

## 3. Критерии приёмки (должны выполняться перед merge в main)

- [ ] Бот отвечает на `/start` менее чем за 2 секунды
- [ ] Все 4 кнопки главного меню работают и ведут на правильные сценарии
- [ ] Каталог услуг читается из `Service.objects.active()` в realtime (admin изменил → бот сразу видит)
- [ ] FAQ читается из `HelpArticle.objects.active()` в realtime
- [ ] Заявка через бот создаёт `BookingRequest(source='bot_max', bot_user=<fk>)` + Telegram + email менеджеру
- [ ] При повторном `/start` бот приветствует по имени если `BotUser.client_name` заполнен
- [ ] Все unit-тесты проходят (`pytest tests/maxbot/`)
- [ ] `python manage.py check` — 0 issues
- [ ] Локальный smoke через long-polling или ngrok: прошли все 7 тест-кейсов ниже
- [ ] Production smoke: ещё раз 7 тест-кейсов

### Smoke тест-кейсы (выполняются вручную)
- T-01: `/start` → главное меню с 4 кнопками
- T-02: «Услуги» → список 9 услуг с ценами из БД
- T-03: «Услуги» → клик на услугу → FSM: «Как к вам обращаться?» → ввод имени → «Ваш телефон?» → ввод → подтверждение → заявка в БД + Telegram
- T-04: «Контакты» → адрес, телефон, режим работы (из `SiteSettings`)
- T-05: «FAQ» → список + клик на вопрос → ответ
- T-06: После T-03 новый `/start` → приветствие «Здравствуйте, <имя>!»
- T-07: Произвольный текст в состоянии без FSM → fallback-сообщение с меню

---

## 4. Архитектура

### 4.1 Топология на prod-сервере
```
┌─────────────────────────────────────────────────────────────┐
│ nginx (443)                                                 │
│   formulatela58.ru/                                         │
│     ├─ /static/, /media/      → filesystem                  │
│     ├─ /api/maxbot/webhook/   → 127.0.0.1:8003  (NEW)       │
│     └─ /                      → 127.0.0.1:8001 (formula_tela)│
└─────────────────────────────────────────────────────────────┘
         │
         ├── formula_tela.service         gunicorn :8001  (Django web)
         ├── formula-tela-worker.service  celery worker
         ├── formula-tela-beat.service    celery beat
         └── formula-tela-maxbot.service  python -m maxbot.main :8003  (NEW)
```

### 4.2 Пакет `mysite/maxbot/`
```
mysite/maxbot/
├── __init__.py
├── main.py                 # asyncio entry; django.setup() → Bot → Dispatcher → webhook
├── django_bootstrap.py     # обёртка вокруг django.setup() (идемпотентная)
├── config.py               # чтение env: MAX_BOT_TOKEN, MAX_WEBHOOK_PORT, MAX_WEBHOOK_HOST
├── handlers/
│   ├── __init__.py         # регистрирует все routers
│   ├── start.py            # /start + главное меню
│   ├── services.py         # список услуг + callback на выбор услуги
│   ├── booking.py          # FSM: awaiting_name → awaiting_phone → awaiting_confirm
│   ├── contacts.py         # контакты из SiteSettings
│   ├── faq.py              # список HelpArticle + ответы
│   └── fallback.py         # любой текст в stateless → главное меню
├── keyboards.py            # фабрики InlineKeyboard через InlineKeyboardBuilder
├── states.py               # StatesGroup для booking FSM (на базе SDK)
├── personalization.py      # get_or_create_bot_user, greet_by_name, update_context
├── texts.py                # статичные строки (приветствия, форматы сообщений)
├── middleware.py           # logging + error-alerts + bot_user injection
└── notifications.py        # thin wrapper поверх notifications.send_notification_telegram/email
```

**FSM:** используем встроенный `MemoryContext` из maxapi SDK + `StatesGroup`
(см. `maxbot-phase1-research.md` §5). In-memory ограничение приемлемо для MVP
(state теряется при рестарте процесса — для 10-минутного booking-флоу OK).
Миграция на Redis-backed — Фаза 2.

### 4.3 Модели (services_app)
Новые модели в `services_app/models.py`:

```python
class BotUser(models.Model):
    """Пользователь MAX-бота для персонализации."""
    max_user_id = models.BigIntegerField(unique=True, db_index=True)
    display_name = models.CharField(max_length=200, blank=True)  # от MAX
    client_name = models.CharField(max_length=150, blank=True)   # как назвался боту
    client_phone = models.CharField(max_length=20, blank=True)   # +7XXXXXXXXXX
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    context = models.JSONField(default=dict, blank=True)
    # Примеры полей внутри context:
    # {"services_viewed": ["massazh-spiny"], "faqs_viewed": [1,3], "bookings_count": 2}

    class Meta:
        verbose_name = "Пользователь MAX-бота"
        verbose_name_plural = "Пользователи MAX-бота"


class HelpArticle(models.Model):
    """FAQ-статья для MAX-бота (отдельно от FAQ по услугам)."""
    question = models.CharField(max_length=255)
    answer = models.TextField()
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "Статья помощи"
        verbose_name_plural = "Статьи помощи"
```

Существующая `BookingRequest` расширяется:
```python
# + 2 новых поля
source = models.CharField(
    max_length=20,
    choices=[("wizard", "Форма-мастер"), ("bot_max", "MAX-бот"), ("other", "Другое")],
    default="wizard",
)
bot_user = models.ForeignKey(BotUser, on_delete=models.SET_NULL, null=True, blank=True)
```

### 4.4 FSM (state machine) — на основе SDK

**Используем встроенный `MemoryContext` из `maxapi.context`** — отдельный stateменеджер не пишем.

```python
# mysite/maxbot/states.py
from maxapi.context.state_machine import State, StatesGroup

class BookingStates(StatesGroup):
    awaiting_name = State()
    awaiting_phone = State()
    awaiting_confirm = State()
```

В handler'ах `MemoryContext` инжектится автоматически:
```python
@dp.message_callback()
async def on_service_pick(callback, context: MemoryContext):
    await context.set_state(BookingStates.awaiting_name)
    await context.update_data(service_id=service_id)
```

**Хранилище:** in-memory в самом Dispatcher'е (per-process). Для одного uvicorn-worker'а
работает корректно. При рестарте сервиса все активные диалоги (state) теряются —
для booking-флоу с TTL 10 минут это маловероятный edge-case (OK для MVP).

TTL не задаётся явно — SDK не делает GC, но мы тоже не делаем persist'a; разовые
restart'ы при деплое — единственная причина потери state.

---

## 5. Декомпозиция на задачи (TDD-ready)

Каждая задача — атомарный коммит. Формат:
```
T-XX. Заголовок
Файлы: перечень
RED: какие тесты пишем первыми (и что они проверяют)
GREEN: минимальная реализация
REFACTOR: уборка
Acceptance: как понять что задача завершена
```

### T-01. Research spike: examples/ в max-botapi-python

**Файлы:** `docs/plans/maxbot-phase1-research.md` (заметки)

**Цель:** руками склонировать репу, прочитать 4 ключевых примера: `keyboard`, `webhook`, `middleware_for_router`, `magic_filters`. Зафиксировать:
- Точные имена классов для `InlineKeyboard` и 7 типов кнопок
- Сигнатуру webhook-handler'а
- Как передать signature secret (если SDK поддерживает)
- Зависимости pip (точные версии)

**Acceptance:** в `docs/plans/maxbot-phase1-research.md` зафиксированы 5 конкретных сниппетов кода, которые дальше используются как cargo.

---

### T-02. Модели `BotUser` и `HelpArticle` + расширение `BookingRequest`

**Файлы:**
- `mysite/services_app/models.py` — +2 модели, +2 поля
- `mysite/services_app/admin.py` — admin-классы для BotUser (readonly) и HelpArticle (редактируемый)
- `mysite/services_app/migrations/00XX_maxbot_models.py` — автогенерация

**RED (тесты первыми):**
- `tests/test_bot_models.py::test_bot_user_creation` — `baker.make(BotUser, max_user_id=123)` создаётся
- `tests/test_bot_models.py::test_bot_user_context_defaults_to_empty_dict`
- `tests/test_bot_models.py::test_help_article_ordering` — две статьи с order=2 и order=1 возвращаются в правильном порядке
- `tests/test_bot_models.py::test_booking_request_source_default` — default=`wizard` не ломает существующий код
- `tests/test_bot_models.py::test_booking_request_with_bot_user_fk` — создание `BookingRequest(source='bot_max', bot_user=...)`

**GREEN:** объявить модели, `makemigrations`, `migrate`, прогнать существующие 675 тестов — ничего не сломалось.

**REFACTOR:** admin-классы для BotUser/HelpArticle.

**Acceptance:**
- Миграция применяется чисто
- 5 новых тестов pass
- 675 существующих pass
- `/admin/services_app/helparticle/` доступен, создаётся/редактируется статья
- `/admin/services_app/botuser/` readonly-вид: list + detail

**Оценка:** 2h

---

### T-03. Пакет `maxbot/` skeleton + bootstrap

**Файлы:**
- `mysite/maxbot/__init__.py`
- `mysite/maxbot/config.py` — чтение `MAX_BOT_TOKEN` из env, error если отсутствует
- `mysite/maxbot/django_bootstrap.py` — идемпотентный `django.setup()`
- `mysite/maxbot/main.py` — entrypoint, `asyncio.run(run())`, инициализирует Bot + Dispatcher
- `mysite/maxbot/texts.py` — статичные строки (приветствие по умолчанию)
- `.env.example` — `MAX_BOT_TOKEN=` (пустое, документируем)

**RED:**
- `tests/maxbot/test_config.py::test_config_raises_without_token` — `MAX_BOT_TOKEN` отсутствует → `ImproperlyConfigured`
- `tests/maxbot/test_config.py::test_config_reads_token_from_env`
- `tests/maxbot/test_main.py::test_main_module_importable` — `from maxbot import main` не падает

**GREEN:** минимальные скелеты.

**Acceptance:** `python -m maxbot.main` запускается (с валидным токеном из `.env`), подключается к API, ничего не делает кроме `bot_started` handler'а-заглушки.

**Оценка:** 2h

---

### T-04. Keyboard-фабрики

**Файлы:**
- `mysite/maxbot/keyboards.py`
- `tests/maxbot/test_keyboards.py`

**Публичные функции:**
```python
def main_menu_keyboard() -> InlineKeyboard: ...
def services_keyboard(services: list[Service]) -> InlineKeyboard: ...
def faq_keyboard(articles: list[HelpArticle]) -> InlineKeyboard: ...
def back_to_menu_keyboard() -> InlineKeyboard: ...
def confirm_booking_keyboard(service_id: int) -> InlineKeyboard: ...  # Подтвердить/Отменить
```

**RED:**
- `test_main_menu_has_four_buttons`
- `test_services_keyboard_includes_back_button`
- `test_services_keyboard_callback_contains_service_id`
- `test_faq_keyboard_renders_article_questions`
- `test_confirm_booking_has_yes_no_buttons_with_service_id_in_callback`

**GREEN:** построение `InlineKeyboard` через API SDK.

**REFACTOR:** вынести общую «Назад в меню» кнопку.

**Acceptance:** 5 тестов pass; keyboards корректно сериализуются в JSON (проверяется через `.to_dict()` или эквивалент SDK).

**Оценка:** 3h

---

### T-05. ~~FSM-стейт-менеджер~~ → объявление `StatesGroup`

**Изменено после research:** SDK уже содержит `MemoryContext` + `StatesGroup` — свой
state-менеджер не пишем. Задача сводится к объявлению группы состояний.

**Файлы:**
- `mysite/maxbot/states.py`
- `tests/maxbot/test_states.py`

**Содержимое `states.py`:**
```python
from maxapi.context.state_machine import State, StatesGroup

class BookingStates(StatesGroup):
    awaiting_name = State()
    awaiting_phone = State()
    awaiting_confirm = State()
```

**RED:**
- `test_booking_states_defines_three_states`
- `test_booking_states_names_are_qualified` (формат `"BookingStates:awaiting_name"`)

**Acceptance:** 2 теста pass.

**Оценка:** 0.5h (вместо 2h)

---

### T-06. Персонализация: `personalization.py`

**Файлы:**
- `mysite/maxbot/personalization.py`
- `tests/maxbot/test_personalization.py`

**Публичные функции:**
```python
@sync_to_async
def get_or_create_bot_user(max_user_id: int, display_name: str = "") -> tuple[BotUser, bool]: ...
# (instance, created)

def greet_text(bot_user: BotUser) -> str:
    """Возвращает приветствие с именем если есть, иначе дефолтное."""

@sync_to_async
def update_context(bot_user_id: int, **updates) -> None:
    """Атомарный update JSON-поля context."""
```

**RED:**
- `test_get_or_create_new_user` — returns (user, created=True)
- `test_get_or_create_existing_user_updates_last_seen`
- `test_greet_text_without_name_returns_default`
- `test_greet_text_with_name_personalizes` — `"Здравствуйте, Иван!"`
- `test_update_context_merges_dict` — существующий context={"a":1}, update b=2 → {"a":1,"b":2}

**GREEN:** ORM-операции через `asgiref.sync.sync_to_async`.

**Acceptance:** 5 тестов pass.

**Оценка:** 3h

---

### T-07. Handler: `/start` + главное меню

**Файлы:**
- `mysite/maxbot/handlers/start.py`
- `tests/maxbot/test_handlers_start.py`

**Поведение:**
- Триггер: `bot_started` event ИЛИ `message_created` с text `/start`
- Вызывает `get_or_create_bot_user`
- Отправляет `greet_text(bot_user)` + `main_menu_keyboard()`
- Сбрасывает FSM state

**RED (mocking Bot и Dispatcher):**
- `test_start_creates_new_bot_user_on_first_call`
- `test_start_greets_returning_user_by_name`
- `test_start_sends_main_menu_keyboard`
- `test_start_clears_fsm_state`

**GREEN:** handler с моками `event.message.answer()`.

**Acceptance:** 4 теста pass.

**Оценка:** 3h

---

### T-08. Handler: «Услуги» (каталог)

**Файлы:**
- `mysite/maxbot/handlers/services.py`
- `tests/maxbot/test_handlers_services.py`

**Поведение:**
- Callback из главного меню (`cb:menu:services`) → список услуг из `Service.objects.active().with_options()`, по 1 кнопке на услугу с callback `cb:svc:{id}`
- Клик на услугу → сохранить `service_id` в FSM state → перейти в `awaiting_name` → отправить `"Как к вам обращаться?"`
- `update_context(services_viewed=[slug])`

**RED:**
- `test_services_list_reads_from_db` — админ создал `Service(name='Тест')` → бот показывает в списке
- `test_services_list_includes_price_from` — кнопка показывает «от 1500 ₽»
- `test_service_click_sets_fsm_awaiting_name_with_service_id`
- `test_service_click_appends_to_viewed_context`

**GREEN:** handler с ORM-запросом.

**Acceptance:** 4 теста pass.

**Оценка:** 3h

---

### T-09. Handler: FSM заявки (`booking.py`)

**Файлы:**
- `mysite/maxbot/handlers/booking.py`
- `tests/maxbot/test_handlers_booking_fsm.py`

**Поведение (3 состояния):**
1. `awaiting_name`: text-message handler (только для этого state) → валидируем длину ≥2 символа → сохраняем в FSM ctx → переход в `awaiting_phone` → «Телефон для связи?»
2. `awaiting_phone`: text-message → нормализуем через `normalize_ru_phone` → сохраняем → `awaiting_confirm` → «Подтвердите заявку: имя, телефон, услуга» + keyboard Подтвердить/Отменить
3. `awaiting_confirm`: callback `cb:confirm:yes` → создаём `BookingRequest(source='bot_max', bot_user=...)` → Telegram/email менеджеру → подтверждение клиенту + главное меню → clear FSM; `cb:confirm:no` → просто clear FSM → «Отменено» + главное меню

**RED:**
- `test_awaiting_name_stores_name_in_fsm`
- `test_awaiting_name_rejects_too_short`
- `test_awaiting_phone_normalizes_to_plus7`
- `test_awaiting_phone_rejects_invalid_phone`
- `test_confirm_yes_creates_booking_request_with_source_bot_max`
- `test_confirm_yes_links_booking_to_bot_user`
- `test_confirm_yes_sends_telegram_and_email` (проверяем что `notifications.send_notification_telegram` вызван)
- `test_confirm_no_clears_state_without_creating_booking`
- `test_confirm_increments_bookings_count_in_bot_user_context`

**GREEN:** FSM-handlers с моками.

**Acceptance:** 9 тестов pass.

**Оценка:** 5h

---

### T-10. Handler: «Контакты»

**Файлы:**
- `mysite/maxbot/handlers/contacts.py`
- `tests/maxbot/test_handlers_contacts.py`

**Поведение:**
- Callback `cb:menu:contacts` → читает `SiteSettings` → форматирует сообщение (адрес, телефон, режим) + `back_to_menu_keyboard()`
- Кнопка «Позвонить» — link-кнопка `tel:88412393433`

**RED:**
- `test_contacts_reads_from_site_settings`
- `test_contacts_phone_is_tel_link`
- `test_contacts_falls_back_gracefully_if_no_site_settings`

**GREEN:** 3 теста.

**Оценка:** 2h

---

### T-11. Handler: FAQ

**Файлы:**
- `mysite/maxbot/handlers/faq.py`
- `tests/maxbot/test_handlers_faq.py`

**Поведение:**
- Callback `cb:menu:faq` → `HelpArticle.objects.filter(is_active=True).order_by('order')` → клавиатура
- Клик `cb:faq:{id}` → `HelpArticle.objects.get(id=..., is_active=True)` → `.answer` + кнопки «Назад к вопросам» и «Записаться»
- `update_context(faqs_viewed=[id])`

**RED:**
- `test_faq_list_shows_only_active`
- `test_faq_list_respects_order`
- `test_faq_answer_text_returned`
- `test_faq_answer_appends_to_viewed_context`
- `test_faq_answer_404_gracefully` — id несуществующий → fallback + главное меню

**GREEN:** 5 тестов.

**Оценка:** 3h

---

### T-12. Handler: fallback + глобальный error middleware

**Файлы:**
- `mysite/maxbot/handlers/fallback.py`
- `tests/maxbot/test_handlers_fallback.py`

**Поведение:**
- Любой text-message без активного FSM state → «Не совсем понял. Выберите из меню» + `main_menu_keyboard`
- Глобальный middleware ловит exception → логирует через `logging.getLogger('maxbot')` + отправляет алерт через `agents.telegram.send_agent_error_alert` (повторно используем!)

**RED:**
- `test_fallback_responds_with_main_menu_when_no_state`
- `test_fallback_does_not_interfere_with_active_fsm`
- `test_error_middleware_sends_alert_on_exception`

**GREEN:** 3 теста.

**Оценка:** 2h

---

### T-13. Entrypoint + реальная подписка webhook/polling

**Файлы:**
- `mysite/maxbot/main.py` — финальный entrypoint
- `.env.example` — добавить `MAX_WEBHOOK_HOST=127.0.0.1`, `MAX_WEBHOOK_PORT=8003`, `MAX_WEBHOOK_PATH=/api/maxbot/webhook/`

**Поведение:**
- Читает config
- Регистрирует все router'ы из `handlers/`
- `DEV_MODE=1` → long-polling (`dp.start_polling`)
- Иначе webhook (`dp.handle_webhook`)

**RED (интеграционные):**
- `test_main_registers_all_handlers` — после `main()`, dispatcher имеет ≥N handler'ов
- `test_main_long_polling_mode_when_dev_flag_set`

**GREEN:** 2 теста.

**Acceptance:** `MAX_BOT_TOKEN=<valid> DEV_MODE=1 python -m maxbot.main` — бот поднимается, отвечает на `/start` в тестовом MAX-аккаунте.

**Оценка:** 3h

---

### T-14. Инфра: systemd unit + nginx location

**Файлы (НЕ в репо, документируются в plan):**
- `/etc/systemd/system/formula-tela-maxbot.service` (конфиг ниже)
- `/etc/nginx/sites-enabled/formula_tela` (+location block)
- `.env` на проде — `MAX_BOT_TOKEN=<real>`

**systemd unit:**
```ini
[Unit]
Description=MAX Bot daemon for formulatela58.ru
After=network.target redis-server.service postgresql.service
Requires=redis-server.service

[Service]
Type=simple
User=taximeter
Group=taximeter
WorkingDirectory=/home/taximeter/mysite/formula_tela/mysite
EnvironmentFile=/home/taximeter/mysite/formula_tela/.env
Environment=DJANGO_SETTINGS_MODULE=mysite.settings
ExecStart=/home/taximeter/mysite/formula_tela/.venv312/bin/python -m maxbot.main
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**nginx location (внутри существующего 443 server-block):**
```nginx
location /api/maxbot/webhook/ {
    proxy_pass http://127.0.0.1:8003;
    include proxy_params;
    proxy_read_timeout 30s;
    client_max_body_size 1m;
}
```

**Шаги деплоя (с sudo через paramiko или руками):**
1. `git pull` на проде
2. `pip install -r requirements.txt` в `.venv312`
3. Добавить `MAX_BOT_TOKEN=<real>` в `.env`
4. `python manage.py migrate`
5. `python manage.py collectstatic --noinput` (если были изменения в static, тут нет)
6. `sudo cp formula-tela-maxbot.service /etc/systemd/system/` + `daemon-reload` + `enable` + `start`
7. Обновить nginx location → `sudo nginx -t && sudo systemctl reload nginx`
8. Подписать webhook: `curl -X POST https://botapi.max.ru/subscriptions -H "Authorization: $TOKEN" -H "Content-Type: application/json" -d '{"url":"https://formulatela58.ru/api/maxbot/webhook/"}'`
9. `sudo systemctl status formula-tela-maxbot` — должен быть running
10. `sudo journalctl -u formula-tela-maxbot -f` — смотрим логи пока тестер в MAX нажимает /start

**Acceptance:**
- `systemctl is-active formula-tela-maxbot` → active
- `curl -X POST https://formulatela58.ru/api/maxbot/webhook/` → 200 или структурированная ошибка от maxapi
- Реальный клик `/start` в MAX → бот отвечает

**Оценка:** 2h

---

### T-15. Документация и финальный коммит

**Файлы:**
- `CLAUDE.md` — раздел «MAX-бот» + обновить список приложений
- `README.md` — как запустить бот локально (если README есть; если нет — создаём)
- `docs/plans/maxbot-phase1.md` — пометить `STATUS: DONE`

**Acceptance:** PR `dev → main` с чек-листом приёмки + все T-01..T-15 коммиты зелёные в CI.

**Оценка:** 1h

---

## 6. Сводка по ресурсам

| Этап | Задачи | Часы |
|---|---|---:|
| Research | T-01 | 2 (✅ done) |
| Модели | T-02 | 2 |
| Bootstrap | T-03 | 2 |
| Core utils | T-04 (keyboards), T-05 (states), T-06 (personalization) | 6.5 |
| Handlers | T-07, T-08, T-09, T-10, T-11, T-12 | 18 |
| Entry + infra | T-13, T-14 | 5 |
| Docs | T-15 | 1 |
| **Итого** | **15 задач** | **36.5h** (-1.5 после research) |

*Примечание: 36.5h — это чистое время. Реалистично 3-4 рабочих дня с учётом debug, проверок, смен контекста.*

---

## 7. Риски

| # | Риск | Вероятность | Смягчение |
|---|---|---|---|
| R1 | `maxapi` SDK не поддерживает нужный тип кнопки / event | средняя | Fallback на прямые HTTP-запросы к `botapi.max.ru` через `httpx` |
| R2 | Webhook signature verification не документирована | высокая | Дополнительная задача T-01.5: разобраться при research |
| R3 | На проде конфликт портов (:8003 занят) | низкая | Перед T-14 `ss -tlnp \| grep :8003` |
| R4 | MAX API rate-limit (30 rps) не хватит при всплеске | очень низкая | Вряд ли, 50-100 пользователей Фазы 1 точно не создадут >30 rps; по факту — exponential backoff на 429 |
| R5 | `sync_to_async` где-то криво — race в FSM state | средняя | Тесты с `freezegun` + ручной long-polling smoke |
| R6 | fail2ban на проде блокирует меня при деплое | средняя | Группировать SSH-команды, использовать существующий paramiko-подход |

---

## 8. Ответы владельца (2026-04-24)

1. **Python 3.12** — подтверждено `.venv312` на проде. Совместимость `maxapi` проверяется в T-01.
2. **Название бота** — «Формула тела» / `id583403546770_bot`, user_id=254116108. Оставляем.
3. **Telegram-алерты** — те же получатели что у wizard (`SiteSettings.notification_emails` + `TELEGRAM_CHAT_ID`). Повторное использование `_notify_booking_request()` из website/views.py.
4. **FSM TTL** — 10 минут.
5. **Валидация имени** — 2–100 символов, буквы + пробел + тире, цифры запрещены.
6. **Отмена заявки** (`cb:confirm:no`) — сразу главное меню.

---

## 9. План отката (rollback)

Если что-то пошло не так после деплоя:

1. **Остановить бота:**
   ```bash
   sudo systemctl stop formula-tela-maxbot
   sudo systemctl disable formula-tela-maxbot
   ```
2. **Отписать webhook:**
   ```bash
   curl -X DELETE https://botapi.max.ru/subscriptions?url=... -H "Authorization: $TOKEN"
   ```
3. **Откатить миграцию** (если проблема в БД):
   ```bash
   python manage.py migrate services_app 00XX_previous
   ```
4. **Nginx:**
   ```bash
   sudo cp /etc/nginx/sites-enabled/formula_tela.bak.maxbot /etc/nginx/sites-enabled/formula_tela
   sudo nginx -t && sudo systemctl reload nginx
   ```
5. **Откатить код:** `git revert <merge-commit>` на `main`, re-deploy

Бот MAX не критичен для основного сайта — отключение maxbot-сервиса **не влияет** на `formula_tela.service` (разные процессы, разные порты).

---

## STATUS

- **APPROVED** 2026-04-24 — план зафиксирован, T-01 стартовал
- **CODE COMPLETE** 2026-04-25 — T-01..T-13 + T-06.5 review fixes + T-14a infra artifacts реализованы. 776 passed (после T-08.5 двухуровневое меню), 0 регрессий
- **DEPLOYED 2026-04-25** — PR #85 merged, autodeploy + ручной T-14b: systemd unit активен, nginx location добавлен, webhook subscribed. Smoke на проде пройден end-to-end (категории → услуга → FSM-заявка → BookingRequest source=bot_max + Telegram уведомление)

## Известные доработки post-deploy

- **T-09.5 (UX)** — после первой заявки сохранять `client_name`/`client_phone` в `BotUser` и при повторной записи пропускать FSM (бот «помнит» клиента). Сейчас бот спрашивает имя каждый раз.
- **NLP free-text → FAQ routing** — backlog (см. секцию выше): варианты 1-5 от keyword-match до RAG MCP-сервера.
- **Фаза 2** — нативная запись через YClients API, SMS-напоминания.
