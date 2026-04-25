# CLAUDE.md — Проект «Формула тела»

## Обзор проекта
Django 5.2 веб-приложение для салона массажа и эстетики «Формула тела».
Русскоязычный сайт. Каталог услуг, SEO-посадочные страницы, онлайн-запись,
профили мастеров, AI-агенты маркетинговой автоматизации, управление через
Django Admin.

---

## Технический стек
- **Фреймворк:** Django 5.2
- **База данных:** SQLite3 (локально) / PostgreSQL 16 (продакшн через Docker)
- **Очередь задач:** Redis 7 + Celery (worker + beat scheduler)
- **Изображения:** Pillow
- **API:** Django REST Framework + drf-spectacular
- **Тесты:** pytest + pytest-django + model-bakery
- **Внешние интеграции:** YClients (синхронизация записей), Яндекс.Метрика,
  Яндекс.Директ, VK Ads, Telegram-бот уведомления, OpenAI

---

## Структура репозитория
```
mysite/                  <- корень git
├── mysite/              <- корень Django проекта (здесь manage.py)
│   ├── mysite/          <- пакет настроек проекта
│   │   └── settings/    <- base.py, dev.py, local.py, staging.py, production.py
│   ├── services_app/    <- основное приложение: каталог услуг, блоки, медиа, FAQ, отзывы
│   ├── website/         <- frontend: views, шаблоны, context processors
│   ├── booking/         <- заявки на запись, синхронизация с YClients
│   ├── notifications/   <- Telegram + email уведомления (extracted из website/ в P2)
│   ├── payments/        <- YooKassa integration; содержит admin.py с payment-actions
│   │                       для Order/GiftCertificate (переехали из services_app/admin.py)
│   ├── agents/          <- AI-агенты: аналитика, SEO, маркетинговая автоматизация
│   │   ├── agents/      <- модули агентов (analytics, seo_landing, smm_growth и др.)
│   │   ├── integrations/ <- внешние API (yandex_metrika, yandex_webmaster, vk_ads, yandex_direct)
│   │   └── management/  <- management commands (check_metrika, check_webmaster)
│   ├── tests/           <- тесты pytest (691 test'ов)
│   └── manage.py
├── audits/              <- markdown-отчёты codebase-audit-suite (ln-6XX worker'ов)
├── docker-compose.yml
├── Dockerfile
├── .dockerignore        <- исключает .env, .git, .venv, audits, media из Docker-context
├── requirements.txt
└── pytest.ini
```

---

## Ключевые приложения

### services_app (ядро)
Все бизнес-модели. Основные модели:
- `Service` — slug, seo_h1, seo_title, seo_description, subtitle, price_from, duration_min, related_services (M2M self-ref), emoji, short_description, is_active, is_popular
- `ServiceCategory` — категории на основе slug, с image/image_mobile
- `ServiceOption` — варианты цен для услуги; поля: unit_type (session/zone/visit), units, price, yclients_service_id; вычисляемое `price_per_session`
- `ServiceBlock` — контентные блоки для SEO-посадочных страниц (12 типов: text, accent, checklist, identification, cta, price_table, accordion, faq, special_formats, subscriptions, navigation, html); поля: heading_level, bg_color, text_color, btn_text, btn_sub, css_class
- `ServiceMedia` — фото/видео; поля: media_type, display_mode (single/carousel), carousel_group, image, image_mobile, video_url, video_file (MP4/WebM), insert_after_order (позиционирование на мобильных)
- `FAQ` — вопросы и ответы по категориям (question, answer, FK к ServiceCategory)
- `Master` — профили мастеров с M2M к услугам; поля: specialization, experience, education, work_experience, approach, reviews_text, rating
- `Bundle` / `BundleItem` — пакеты услуг; Bundle имеет total_price(), total_duration_min(); BundleItem имеет quantity, parallel_group, gap_after_min
- `BundleRequest` — заявки на пакеты (client_name, client_phone, comment, is_processed)
- `Promotion` — скидки с промокодами; поля: features (JSON), options (M2M ServiceOption), discount_percent, promo_code, starts_at, ends_at
- `Review` — отзывы клиентов (author_name, text, rating 1-5, get_initial_letter())
- `BookingRequest` — заявки через форму-мастер (category_name, service_name, client_name, client_phone, is_processed)
- `SiteSettings` — глобальные настройки (телефон, соцсети JSON, способы оплаты JSON, данные YClients, ссылки на карты, `notification_emails` — email-адреса для уведомлений о заявках wizard, по одному на строку)

### agents (AI-автоматизация)
Маркетинговая и аналитическая автоматизация через OpenAI + Celery.

**Основные модели (все в `agents/models.py`):**
- `AgentTask` — выполнение AI-задач; типы: analytics, offers, offer_packages, smm_growth, seo_landing, analytics_budget; статусы: pending, running, done, error
- `AgentReport` — OneToOne сводка по AgentTask (recommendations JSON)
- `ContentPlan` — SMM контент-календарь; платформы: VK, Instagram, Telegram; типы постов: post, story, reel
- `DailyMetric` — дневные агрегаты (total_requests, processed, top_services JSON, masters_load JSON)

**SEO модели (также в `agents/models.py`):**
- `SeoKeywordCluster` — кластер ключевых запросов; поля: name, service_slug, keywords (JSON), target_url, is_active, geo, service_category (FK к ServiceCategory)
- `SeoRankSnapshot` — еженедельные метрики Яндекс.Вебмастера; поля: week_start, page_url, query, clicks, impressions, ctr, avg_position, source; unique_together по (week_start, page_url, query)
- `LandingPage` — SEO-посадочная страница; status: draft/review/published/rejected (default='draft'); поля: cluster (FK), slug, meta_title, meta_description, h1, blocks (JSON), generated_by_agent, moderated_by (FK User), published_at
- `SeoTask` — задача для SEO-специалиста; task_type: create_landing/update_meta/add_faq/fix_technical/rewrite_cta/add_content_block; priority: high/medium/low; status: open/in_progress/done; `escalation_count` для дедупликации
- `AgentRecommendationOutcome` — lifecycle рекомендаций агентов; статусы: new/accepted/rejected/done; FK на AgentReport, decided_by (FK User), body (JSON)
- `WeeklyBacklog` — еженедельный бэклог SupervisorAgent; week_start (unique), raw_text, items (JSON)

Расписание Celery beat:
- `daily-rank-snapshots-7am` → `agents.tasks.collect_rank_snapshots` (каждый день в 07:00)
- `weekly-trend-scout-monday-0730` → `agents.tasks.collect_trends` (понедельник в 07:30)
- `weekly-agents-monday-8am` → `agents.tasks.run_weekly_agents` (понедельник в 08:00)
- `daily-agents-9am` → `agents.tasks.run_daily_agents` (каждый день в 09:00)
- `weekly-generate-landings-sunday-2200` → `agents.tasks.generate_missing_landings` (воскресенье в 22:00)

### website
Frontend views: главная, каталог услуг, детальная страница услуги, мастера, форма-мастер записи, контакты, акции, пакеты. Все модели данных живут в `services_app`.

### booking
Минимальный — placeholder `booking()` view. Booking API endpoint'ы живут в `website/views.py`.

### notifications (P2 2026-04-23)
Python-пакет (не Django-app, нет моделей) с централизованными уведомлениями:
- `send_notification_telegram(text)` — Telegram, читает `TELEGRAM_BOT_TOKEN/CHAT_ID` из env
- `send_notification_email(subject, msg)` — email, получатели из `SiteSettings.notification_emails` → fallback на `ADMIN_NOTIFICATION_EMAIL`
- `get_notification_recipients()` — lazy-импортит `SiteSettings` (единственная зависимость от services_app)
- `send_certificate_email(order, cert, pdf_bytes=None)` — письмо покупателю после оплаты сертификата

Импорт: `from notifications import send_notification_telegram, send_certificate_email, ...`.
Раньше жил как `website/notifications.py` — вынесен в отдельный пакет чтобы разорвать циклы `payments ↔ website`, `services_app ↔ website`, `website ↔ agents` (4 пары из ln-644 аудита).

### payments
YooKassa-интеграция + админ-акции для Order/GiftCertificate:
- `payments/services.py::PaymentService.create_for_order(order)` — создание YooKassa-платежа
- `payments/booking_service.py::YClientsBookingService.create_record(order)` — shared-service создания YClients-записи
- `payments/views.py::yookassa_webhook` — приём callback'ов, verify-через-API, `transaction.atomic + on_commit` для enqueue fulfillment task
- `payments/tasks.py` — Celery-задачи `fulfill_paid_order/certificate/bundle` с idempotency через `yclients_record_id`
- `payments/admin.py` (новый в P2 2026-04-23) — subclass'ы `OrderAdmin` и `GiftCertificateAdmin` с payment-actions (recreate payment link, mark as paid, resend certificate email). Паттерн unregister+register: `services_app/admin.py` регистрирует базовые admin'ы, `payments/admin.py` их перерегистрирует с payment-actions. Разрывает цикл `services_app → payments` (ln-644 H1, H2).
- `payments/ip_whitelist.py` — YooKassa IP-subnet check, отключаемо через `YOOKASSA_WEBHOOK_STRICT_IP=0`.

### maxbot (Фаза 1, 2026-04-24/25)
**Standalone async-процесс** (НЕ Django-app) для бота в мессенджере MAX
(`max-messenger/maxapi==1.0.0`). Запускается отдельным systemd-юнитом
`formula-tela-maxbot.service` рядом с gunicorn'ом.

```
mysite/maxbot/
├── main.py                  # asyncio entry, run() с polling/webhook switch
├── django_bootstrap.py      # идемпотентный django.setup() для standalone
├── config.py                # MaxBotConfig (frozen dataclass), env-валидация
├── states.py                # BookingStates (StatesGroup из maxapi SDK)
├── keyboards.py             # 5 фабрик InlineKeyboard + payload-константы
├── personalization.py       # get_or_create_bot_user, greet_text, update_context
├── middleware.py            # Logging + ErrorAlert (Telegram через notifications/)
├── texts.py                 # все user-facing строки (DRY)
└── handlers/                # 6 router'ов
    ├── start.py             # /start + bot_started + cb:back
    ├── services.py          # cb:menu:services + cb:svc:{id} → FSM awaiting_name
    ├── booking.py           # FSM awaiting_name → awaiting_phone → awaiting_confirm
    ├── contacts.py          # cb:menu:contacts (ClipboardButton для tel)
    ├── faq.py               # cb:menu:faq + cb:faq:{id}
    └── fallback.py          # @router.message_created() БЕЗ state — последним
```

Связанные модели в `services_app`:
- `BotUser` — персонализация диалога (max_user_id, client_name, context JSONField)
- `HelpArticle` — FAQ-статьи бота (отдельно от FAQ по услугам)
- `BookingRequest.source` (`wizard`/`bot_max`/`other`) + `bot_user` FK SET_NULL

**Запуск локально:**
```bash
MAX_BOT_TOKEN=<token> MAX_BOT_MODE=polling python -m maxbot.main
```

**Prod-деплой:** `infra/README.md` (systemd unit, nginx location, `subscribe_webhook`).
Webhook: `https://formulatela58.ru/api/maxbot/webhook/` → 127.0.0.1:8003. Защита через
header `X-Max-Bot-Api-Secret` (env `MAX_WEBHOOK_SECRET`).

Plan: `docs/plans/maxbot-phase1.md` (15 задач) + `maxbot-phase1-research.md` (SDK
особенности). Review-отчёты T-06.5: `maxbot-phase1-review-{summary,code-reviewer,ln623,ln624}.md`.

---

## URL-паттерны
- `/` — главная
- `/services/` — каталог услуг (все категории)
- `/uslugi/<slug>/` — детальная страница услуги (основная для SEO)
- `/service/<int:id>/` — старый маршрут по ID (301 редирект на slug)
- `/services/<int:category_id>/` — услуги по категории
- `/promotions/` — активные акции
- `/masters/` — профили мастеров
- `/contacts/` — контактная информация
- `/bundles/` — пакеты услуг
- `/admin/` — Django Admin
- `/robots.txt` — robots.txt (Disallow `/admin/`, `/api/`; ссылка на sitemap; Host)
- `/sitemap.xml` — динамический sitemap (static pages + services + categories + published landings)
- `/<slug>/` — SEO-посадочная страница (только published, catch-all последним в urlpatterns)
- `/healthz/` — health check -> `{"status": "ok"}`
- `/api/agents/health/` — мониторинг агентов -> `{"status": "healthy|degraded|unhealthy", "agents": {...}}`

**Booking API (в website/urls.py):**
- `/api/booking/get_staff/` — мастера из YClients
- `/api/booking/available_dates/` — доступные даты записи
- `/api/booking/available_times/` — слоты по длительности сеанса
- `/api/booking/create/` — создание записи в YClients
- `/api/booking/service_options/` — варианты цен
- `/api/bundle/request/` — заявка на пакет
- `/api/wizard/categories/` — категории для формы-мастера
- `/api/wizard/categories/<id>/services/` — услуги в категории
- `/api/wizard/booking/` — бронирование через форму-мастер

**MAX-бот webhook (отдельный процесс на 127.0.0.1:8003 за nginx):**
- `/api/maxbot/webhook/` — приём updates из MAX, защищён `MAX_WEBHOOK_SECRET`

---

## Запуск проекта

### Локальная разработка
```bash
cd mysite
python manage.py runserver
# Настройки выбираются автоматически через DJANGO_ENV или DJANGO_SETTINGS_MODULE
# По умолчанию: local.py (DEBUG=True, SQLite, ALLOWED_HOSTS=["*"])
```

### Docker (аналог продакшна)
```bash
docker-compose up
# PostgreSQL на 5432, Redis на 6379, Django на 8000
```

### Celery (обязателен для агентов)
```bash
cd mysite
celery -A mysite worker -l info   # в одном терминале
celery -A mysite beat -l info     # в другом терминале
```

### Миграции
```bash
cd mysite
python manage.py makemigrations
python manage.py migrate
```

### Управляющие команды
```bash
python manage.py import_price_list price_list.xlsx [--dry-run] [--no-photos]
python manage.py check_booking [--staff-id ID] [--yclients-service-id ID] [--date YYYY-MM-DD]
python manage.py check_metrika   # диагностика Яндекс.Метрики
python manage.py check_webmaster # диагностика Яндекс.Вебмастера
```

---

## Тесты
```bash
# Из корня репозитория (mysite/)
pytest

# Конфигурация pytest.ini:
# DJANGO_SETTINGS_MODULE = mysite.settings
# pythonpath = mysite
# testpaths = mysite/tests
# addopts = -q -m "not live"
# markers: live — тесты с реальным YClients API (исключены из CI)

# Запуск live-тестов вручную:
pytest mysite/tests/test_booking_live.py -v -s
```

Тестовые файлы в `mysite/tests/`. Используй `model-bakery` (`baker.make(...)`) для фикстур.

---

## Переменные окружения
Скопируй `.env.example` -> `.env`. Ключевые переменные:
- `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`
- `DJANGO_ENV` — выбирает файл настроек (production/staging/local)
- `DATABASE_URL` или отдельно `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `REDIS_URL`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `YCLIENTS_PARTNER_TOKEN`, `YCLIENTS_USER_TOKEN`, `YCLIENTS_COMPANY_ID`
- `OPENAI_API_KEY`, `OPENAI_MODEL` (по умолчанию: gpt-4o-mini)
- `OPENAI_PROXY` — HTTP-прокси для OpenAI + Telegram API (формат: `http://user:pass@host:port`), нужен на русских серверах где OpenAI/Telegram заблокированы
- `TELEGRAM_PROXY` — отдельный прокси только для Telegram (если не задан, используется `OPENAI_PROXY`)
- `ADMIN_NOTIFICATION_EMAIL`
- `YANDEX_WEBMASTER_TOKEN`, `YANDEX_WEBMASTER_HOST_ID`
- `YANDEX_METRIKA_TOKEN`, `YANDEX_METRIKA_COUNTER_ID`
- `SITE_BASE_URL` — продакшн: `https://formulatela58.ru` (именно с «58», НЕ formulatela.ru)

---

## Окружения настроек
| Файл | Применение |
|------|-----------|
| `base.py` | Общий конфиг |
| `dev.py` | Настройки разработки |
| `local.py` | Локально: SQLite, DEBUG=True, ALLOWED_HOSTS=["*"] |
| `staging.py` | Staging-сервер |
| `production.py` | Продакшн PostgreSQL |

Настройки выбираются автоматически: `__init__.py` загружает `.env` через `python-dotenv` **до** чтения `DJANGO_ENV` (production -> staging -> local по умолчанию). Это гарантирует, что `.env` файл имеет приоритет над системным окружением.

---

## Templatetags

### `services_app/templatetags/service_extras.py`
- `option_label(opt)` — форматирует ServiceOption как "60 мин x 10 процедур — 14 000 руб. (1 400 руб./проц.)"
- `discount(price, percent)` — вычисляет цену со скидкой

### `agents/templatetags/landing_tags.py`
- `split_lines(value)` — разбивает строку по `\n`, убирает маркеры (•, -, *, 1., 2.)
- `slugify_to_title(value)` — slug → читаемый заголовок (`massazh-spiny` → `Massazh spiny`)

### `website/templatetags/faq_tags.py`
- `faq_items(content)` — парсит контент блока FAQ (пары Q&A, разделённые `---`)

### `website/templatetags/media_tags.py`
- `get_media_after(media_by_position, block_order)` — возвращает медиа для вставки после блока на мобильных

### `website/templatetags/social_tags.py`
- `dictget(d, key)` — безопасный доступ к словарю в шаблонах
- `pluralize_ru(value, variants)` — склонение по-русски: `{{ count|pluralize_ru:"услуга,услуги,услуг" }}`

---

## Соглашения по коду
- Русский язык (`LANGUAGE_CODE = "ru"`, `USE_I18N = True`)
- Шаблоны на Django Template Language; templatetags в `services_app/templatetags/` и `website/templatetags/`
- В Admin используется `filter_horizontal` для M2M-полей (related_services, options)
- URL на основе slug для SEO; 301 редирект со старых ID-маршрутов на slug
- `heading_level` в ServiceBlock управляет h1/h2/h3 в шаблонах
- Schema.org разметка (Service, FAQPage, BreadcrumbList) встроена в шаблон детальной страницы услуги
- CSP middleware включён — никаких инлайн-скриптов; разрешено: `'self'` + `https://w951024.yclients.com`
- Booking API views используют `@csrf_exempt` и возвращают JSON
- Активное использование `Prefetch` во views для оптимизации запросов
- **OpenAI клиент централизован**: все агенты импортируют `get_openai_client()` из `agents/agents/__init__.py` — не создавать `OpenAI()` напрямую. Клиент автоматически поднимает HTTP-прокси из `OPENAI_PROXY` (нужно на русских серверах)
- Telegram API (`agents/telegram.py`) также использует `OPENAI_PROXY`/`TELEGRAM_PROXY` т.к. api.telegram.org заблокирован в РФ
- Sitemap — через `django.contrib.sitemaps` (4 sitemap: static/services/categories/landings), классы в `mysite/website/sitemaps.py`
- **YClientsAPI — singleton через `lru_cache`** (P1 2026-04-23): `get_yclients_api()` возвращает кэшированный экземпляр с переиспользуемой `requests.Session` + urllib3 `Retry` adapter (3 попытки, backoff 0.5s, для 502/503/504). В тестах `conftest.py::_clear_yclients_singleton` сбрасывает кэш. Мокать HTTP через `patch("requests.Session.request", ...)`, не `requests.request`.
- **Payment webhook = atomic + on_commit** (P1 2026-04-23): `payments/views.py::_handle_succeeded` обернут в `transaction.atomic()`, enqueue fulfillment task — через `transaction.on_commit(lambda: task.delay(order.id))`. Защищает от потери задачи если save() откатится. В тестах используй `django_capture_on_commit_callbacks(execute=True)` или фикстуру `post_webhook` (в test_webhook.py).
- **Celery settings (base.py)** (P1 2026-04-23): `CELERY_TASK_ACKS_LATE=True`, `CELERY_TASK_REJECT_ON_WORKER_LOST=True`, `CELERY_WORKER_PREFETCH_MULTIPLIER=1`, `CELERY_BROKER_TRANSPORT_OPTIONS={"visibility_timeout": 3600}`, `CELERY_TASK_SOFT_TIME_LIMIT=1800`, `CELERY_TASK_TIME_LIMIT=1860`. Защита от тихой потери задач при деплое / OOM / SIGKILL.
- **Production fail-fast** (P0 2026-04-23): `settings/production.py` бросает `ImproperlyConfigured` на boot если отсутствуют `DJANGO_SECRET_KEY`, `YCLIENTS_PARTNER_TOKEN`, `YCLIENTS_USER_TOKEN`, `YCLIENTS_COMPANY_ID` (не `assert` — он гасится флагом `python -O`).
- **Ноль циклов между app'ами** (P2 2026-04-23): `services_app` не импортирует ни из `payments`, ни из `agents`, ни из `website`, ни из `notifications`. Все 8 циклических зависимостей из ln-644 аудита разорваны. Фичевые app → domain, domain ничего не знает о features.

---

## Архитектура агентов

### Поток данных
```
Внешние данные (YClients / Метрика / Вебмастер / VK Ads / Яндекс.Директ)
    |
    v
DailyMetric / SeoRankSnapshot (сохраняем в БД)
    |
    v
AgentTask создаётся (status=pending)
    |
    v
Celery worker забирает задачу -> запускает агента
    |
    v
Агент читает данные из БД -> формирует prompt -> GPT-4
    |
    v
AgentReport сохраняется (status=done, recommendations JSON)
    |
    v
Telegram уведомление администратору
```

### Типы AgentTask и их файлы
| task_type | файл | расписание |
|---|---|---|
| analytics | agents/agents/analytics.py | ежедневно 9:00 (через SupervisorAgent) |
| analytics_budget | agents/agents/analytics_budget.py | ежедневно 9:00 (всегда) |
| seo_landing | agents/agents/seo_landing.py | понедельник 8:00 |
| smm_growth | agents/agents/smm_growth.py | понедельник 8:00 |
| offers | agents/agents/offers.py | ежедневно 9:00 (через SupervisorAgent) |
| offer_packages | agents/agents/offer_packages.py | понедельник 8:00 |

### Трёхуровневое расписание
```
07:00 ежедневно  → collect_rank_snapshots (Вебмастер → SeoClusterSnapshot → analyze_rank_changes)
08:00 понедельник → run_weekly_agents (OfferPackages → SMMGrowth → SEOLanding → Supervisor.weekly_run)
09:00 ежедневно  → run_daily_agents (Supervisor.decide → Analytics/Offers → AnalyticsBudget)
```

### SupervisorAgent (оркестратор)
- `decide()` — LLM-роутер, определяет какие ежедневные агенты запустить (analytics если >1 день, offers по Пн/Чт или >3 дней)
- `run()` — запускает AnalyticsAgent и/или OfferAgent по результату decide()
- `weekly_run()` — собирает последние DONE-отчёты всех 6 агентов, синтезирует бэклог через GPT, шлёт Telegram с приоритизированными задачами

### Правила агентов — СТРОГО СОБЛЮДАТЬ
- Агенты **НИКОГДА** не публикуют контент автоматически
- `LandingPage` создаётся **только** со `status='draft'`
- Все рекомендации сохраняются в `AgentReport.recommendations` (JSON)
- Telegram-уведомление — финальный шаг **любого** агента
- Агент не выдумывает цены и факты — только данные из БД
- VK Ads входит в `AnalyticsBudgetAgent` как 3-й канал (не отдельный агент)

---

## Платежи (YooKassa)

Приложение `mysite/payments/` — онлайн-оплата услуг через YooKassa +
синхронное создание записи в YClients для офлайн-способов.

### Flow

```
POST /api/services/order/                  (website/views.py::api_service_order_create)
   │ payload: service_option_id, staff_id, date/time, client_*, payment_method
   │ DRF-валидация (website/serializers.py::ServiceOrderCreateSerializer)
   │ idempotency через cache (60с)
   ▼
Order(type=service, pending)
   │
   ├── payment_method=online + SiteSettings.online_payment_enabled
   │      PaymentService.create_for_order(order) → confirmation_url
   │      Order.payment_url / payment_id / payment_status=pending
   │      клиент → YooKassa checkout → 
   │              ├── succeeded → POST webhook
   │              │     /api/payments/yookassa/webhook/
   │              │     verify через find_payment (double-check)
   │              │     Order.payment_status=succeeded + paid_at=now
   │              │     fulfill_paid_order.delay(order.id)
   │              │     → YClientsBookingService.create_record (retry 5×)
   │              │     → Telegram админу
   │              └── canceled → Order.payment_status=canceled + Telegram
   │
   └── payment_method=cash/card_offline
         YClientsBookingService.create_record(order) СРАЗУ
         → yclients_record_id в ответе + Telegram
```

### Компоненты

| Файл | Что |
|---|---|
| `payments/yookassa_client.py` | Тонкий wrapper над yookassa SDK, возвращает dict'ы (не SDK-типы) |
| `payments/services.py::PaymentService` | `create_for_order(order)` → YooKassa payment, persists payment_id/url/status |
| `payments/booking_service.py::YClientsBookingService` | Shared service: `create_record(order)` идемпотентный, пишет `yclients_record_id` |
| `payments/tasks.py::fulfill_paid_order` | Celery task: `bind=True, max_retries=5, retry_backoff`, `ignore_result=True` |
| `payments/views.py::yookassa_webhook` | POST webhook: IP-whitelist + verify + роутинг succeeded/canceled |
| `payments/ip_whitelist.py` | 7 подсетей YooKassa, `@yookassa_ip_only` декоратор, `YOOKASSA_WEBHOOK_STRICT_IP` |
| `payments/exceptions.py` | `PaymentError` / `PaymentConfigError` / `PaymentClientError` / `BookingError` / `BookingValidationError` / `BookingClientError` |

### Feature flag

`SiteSettings.online_payment_enabled = False` по умолчанию. Редактируется через
Django Admin (`/admin/services_app/sitesettings/`). Когда `False`:
- Radio «Оплатить онлайн» в модалке записи **скрыт** на фронте
- Попытка `payment_method=online` в API → 400 `online_payment_disabled`
- Офлайн-способы (cash/card_offline) работают всегда

### Env

```
YOOKASSA_SHOP_ID=<из личного кабинета YooKassa>
YOOKASSA_SECRET_KEY=<оттуда же>
YOOKASSA_RETURN_URL=https://formulatela58.ru/payments/success/?order={order_number}
YOOKASSA_WEBHOOK_STRICT_IP=1   # 0 чтобы выключить IP-проверку в dev/CI
```

### Правила — СТРОГО СОБЛЮДАТЬ
- **Offline flow не создаёт платежи в YooKassa** — только Order + YClients-запись + Telegram
- **`order.number` — idempotence_key** для YooKassa Payment.create (защита от дублей)
- **Webhook всегда отвечает 200** (даже unknown order / already succeeded) — иначе YooKassa спамит retry
- **Fulfillment идемпотентен через `yclients_record_id`** — повторная доставка webhook не создаст запись второй раз
- **Чеки 54-ФЗ сейчас НЕ выдаются** — отдельная задача FT-13 (требует выбора ОФД)
- **Рефанды — через личный кабинет YooKassa** (не через админку) — FT-14

---

## Архитектурные решения и причины
| Решение | Причина |
|---|---|
| SQLite локально / PostgreSQL прод | Скорость локальной разработки без Docker |
| Все SEO модели в agents/models.py | Единая схема, один app, без дублирования |
| VK Ads -> в AnalyticsBudgetAgent | Один промпт видит все каналы -> лучше сравнение CPL/ROMI |
| LandingPage.status = 'draft' по умолчанию | Человек проверяет перед публикацией |
| @csrf_exempt на booking API | Внешние вызовы от YClients-виджета |
| Prefetch в views | Предотвращение N+1 запросов |
| WAF bypass headers для YClients | Без них возвращается 403 |
| Slug-based URL везде | SEO-приоритет; ID-based -> 301 редирект |
| Django>=5.2,<6.0 пин в requirements | Предотвращение ломающего апгрейда |
| .env загружается до DJANGO_ENV | Гарантия что .env имеет приоритет над systemd env |
| SupervisorAgent как LLM-роутер | Автоматический выбор нужных ежедневных агентов по контексту |
| 3-уровневое расписание (7/8/9) | Данные собираются до запуска агентов |
| Wizard (`#bookingWizard`) ≠ YClients | Форма «Записаться онлайн» и CTA создают `BookingRequest` + Telegram/email, но **не** вызывают YClients. Мастер/дата/время в ней не выбираются — это «заявка на перезвон». Полноценное бронирование — только через форму на странице услуги (`/api/booking/create/`) |
| `notification_emails` в `SiteSettings` | Список email-ов для уведомлений wizard редактируется через Django Admin (`/admin/services_app/sitesettings/`), а не через `.env` — чтобы менеджер мог добавлять адреса без деплоя. Fallback на `ADMIN_NOTIFICATION_EMAIL` из окружения |

---

## Запрещённые действия (без явного разрешения)
- Не изменяй существующие миграции — только создавай новые
- Не удаляй поля моделей — только помечай как deprecated
- Не трогай `services_app/migrations/` без явной просьбы
- Не добавляй инлайн-скрипты в шаблоны (CSP заблокирует)
- Не публикуй `LandingPage` автоматически (только draft)
- Не коммить `.env` и медиафайлы в git
- Не используй ID-based URL — только slug-based
- Не создавай новые ветки без явной просьбы

---

## Git workflow
```bash
# Рабочая ветка
git checkout dev

# Перед началом каждой сессии
git pull origin dev

# Новые ветки — только по явной просьбе
```

### Prod deploy — ТОЛЬКО через GitHub PR (не локальный merge)
После инцидента 2026-04-23 где я сделал локальный `git merge dev → main + push origin main` вместо PR через UI, **правило**: prod-деплой идёт через Pull Request `dev → main` на GitHub. Это даёт:
- Diff-review в UI (видно что именно улетит в прод)
- Approval flow
- Автоматический запуск CI + deploy workflow связанных с PR merge
- Историю PR-ов в репо (timeline релизов)

### Feature PRs — push ВСЕ коммиты до merge
После инцидента 2026-04-23 где PR #78 был смержен когда в ветке был только 1 коммит, а ещё 2 запушил ПОСЛЕ merge — они остались висеть в remote-ветке, в dev не попали, потратил 2 часа на диагностику. **Правило**: перед кликом "Merge" на PR дождаться что **все намеченные коммиты запушены**. GitHub merge'ит snapshot на момент клика, последующие push в ту же ветку не подхватываются.

---

## Типичные ошибки
- Всегда запускай `makemigrations` + `migrate` после изменения моделей
- `ServiceMedia.video_file` хранит загруженное видео; большие файлы в .gitignore
- Контент блока `ServiceBlock` типа FAQ парсится `faq_tags.py` (пары Q&A через `---`)
- `related_services` в Service — self-referential M2M, используй `filter_horizontal` в admin
- Статические файлы: запускай `collectstatic` перед деплоем
- CSP блокирует инлайн-скрипты — используй внешние JS-файлы; `'unsafe-inline'` разрешён только для стилей
- Celery workers должны быть запущены для задач агентов; beat scheduler обязателен для периодических задач
- YClients API требует WAF-bypass заголовки (User-Agent + X-Partner-Id) чтобы избежать 403

---

## Быстрый справочник команд

### Makefile (рекомендуемый способ)
```bash
make db              # PostgreSQL + Redis в фоне
make db-stop         # Остановить PostgreSQL + Redis
make run             # Django dev server (требует make db)
make migrate         # Применить миграции
make makemigrations  # Создать миграции
make shell           # Django shell
make docker          # Весь стек в Docker (db + redis + web)
make logs            # Логи контейнеров БД и Redis
make psql            # psql в контейнере БД
make worker          # Celery worker (локально)
make beat            # Celery beat планировщик
make agent-analytics # Запустить Analytics Agent вручную
make agent-offers    # Запустить Offer Agent вручную
```

### Ручные команды
```bash
# Запуск локально (без Makefile)
cd mysite && python manage.py runserver

# После изменения моделей
python manage.py makemigrations && python manage.py migrate

# Тесты
pytest                                              # все (кроме live)
pytest mysite/tests/test_booking_live.py -v -s      # live-тесты с реальным YClients API

# Проверка что ничего не сломано
python manage.py check
```

---

## CI/CD
- **CI** (`.github/workflows/ci.yml`): pytest на Python 3.12, push/PR в dev/main, API ключи заглушены
- **Deploy** (`.github/workflows/deploy.yml`): push в main → SSH deploy на продакшн, бэкап PostgreSQL перед deploy, восстановление .env после git pull
- **Deploy staging** (`.github/workflows/deploy-staging.yml`): staging-деплой

---

## Текущее состояние проекта
<!-- Обновляй этот раздел в конце каждой рабочей сессии! -->

### Сделано

#### Ядро (services_app + website + booking)
- Полный каталог услуг с SEO (slug-based URL, Schema.org, BreadcrumbList)
- Форма-мастер записи через YClients API с WAF bypass
- Профили мастеров, пакеты услуг, акции с промокодами
- Meta description override через `{% block description %}` на страницах услуг
- `robots.txt` и динамический `sitemap.xml` (django.contrib.sitemaps, 4 sitemap-класса в `website/sitemaps.py`)

#### Интеграции (agents/integrations/)
- YClients интеграция с WAF bypass
- Yandex.Webmaster (yandex_webmaster.py): get_query_stats(), get_page_stats() (graceful wrappers, 5 тестов)
- Yandex.Metrika (yandex_metrika.py): get_organic_sessions(), get_page_behavior() (graceful wrappers, 9 тестов)
- VK Ads (vk_ads.py)
- Yandex.Direct (yandex_direct.py)
- TechnicalSEOWatchdog (site_crawler.py): проверка страниц, sitemap, get_or_create SeoTask, management-команда check_crawler, 25 тестов

#### SEO система
- SEO модели в agents/models.py: SeoKeywordCluster (с geo, service_category), SeoRankSnapshot, LandingPage, SeoTask, SeoClusterSnapshot
- SEO Admin: 4 ModelAdmin (publish actions, read-only snapshots, priority badges)
- seed_seo_clusters: 13 кластеров из семантического ядра v2 (Wordstat Пенза, февраль 2026)
- collect_rank_snapshots: Celery-таск (ежедневно 07:00), Вебмастер → агрегация по кластерам → SeoClusterSnapshot
- analyze_rank_changes: пороги -20% кликов / 3 позиции, создаёт SeoTask + шлёт Telegram, 18 тестов
- Telegram-уведомления: send_seo_alert(), notify_new_landing(), send_weekly_seo_report() (19 тестов)

#### Landing page система
- LandingPageGenerator (agents/agents/landing_generator.py): generate_landing() + generate_from_markdown(); admin action «Сгенерировать из маркдауна»; 33 теста
- Landing page view + URL + шаблон (agents/views.py, agents/landing_page.html): hero, intro, how_it_works, who_is_it_for, contraindications, results, CTA, FAQ-аккордеон, internal_links; 27 тестов
- CTA-кнопки на лендингах открывают ту же модалку записи что и остальные страницы

#### AI-агенты (все реализованы)
- **AnalyticsAgent** (agents/agents/analytics.py) — ежедневная аналитика
- **AnalyticsBudgetAgent** (agents/agents/analytics_budget.py) — бюджетная аналитика (Метрика + Директ + VK Ads)
- **OfferAgent** (agents/agents/offers.py) — генерация акций
- **OfferPackagesAgent** (agents/agents/offer_packages.py) — генерация пакетов
- **SMMGrowthAgent** (agents/agents/smm_growth.py) — SMM контент-план
- **SEOLandingAgent** (agents/agents/seo_landing.py) — аудит лендингов, детекция WoW click drops
- **SupervisorAgent** (agents/agents/supervisor.py) — оркестратор: decide() для ежедневных агентов, weekly_run() для недельного бэклога

#### Инфраструктура
- Celery beat: 3 задачи (07:00 ежедневно, 09:00 ежедневно, 08:00 понедельник)
- Management commands: check_metrika, check_webmaster, check_booking, check_crawler, import_price_list, seed_seo_clusters
- Makefile с 12 целями для быстрого запуска
- CI/CD: GitHub Actions (тесты, deploy prod, deploy staging)
- Django>=5.2,<6.0 (пин для предотвращения ломающего апгрейда)
- Фикс последовательностей PostgreSQL (миграция 0034_fix_sequences)
- **Централизованный OpenAI клиент** (`agents/agents/__init__.py::get_openai_client()`) с поддержкой `OPENAI_PROXY`; все 8 агентов используют его
- **Proxy для Telegram API** в `agents/telegram.py` (РФ блокирует api.telegram.org)

#### Замыкание цикла агентов
- **OfferAgent → Promotion draft**: JSON mode + auto-create `Promotion(is_active=False)` черновики для модерации
- **ContentPlan dedupe**: SMMGrowthAgent удаляет старые автогенерированные записи перед `bulk_create`
- **LandingPage QC pipeline**: таск `generate_missing_landings` (воскресенье 22:00) — автогенерация лендингов для кластеров без страниц (макс. 3/запуск)

#### Надёжность агентов
- **Telegram ERROR алерты**: `send_agent_error_alert()` — уведомление в Telegram при ошибке агента (во всех 7 агентах + `_lifecycle.py`)
- **SeoTask эскалация**: повторные алерты обновляют существующую задачу (приоритет → HIGH, description обновляется, `escalation_count` инкрементируется)
- **SeoTask.escalation_count** — поле для отслеживания повторных алертов

#### Поведенческая аналитика
- **SEOLandingAgent + Метрика**: интеграция `get_page_behavior()` для топ-15 страниц по impressions (bounce_rate, time_on_page)
- GPT-промпт обогащён поведенческими правилами: bounce > 70% + time < 30s → score ≤ 2

#### Feedback loop
- **AgentRecommendationOutcome** модель: lifecycle рекомендаций (new → accepted/rejected → done), FK на AgentReport, Admin с `list_editable`
- **WeeklyBacklog** модель: персистенция результатов `SupervisorAgent.weekly_run()` (ранее только Telegram)
- **_outcomes.py** хелпер: `create_outcomes()` для создания Outcome из рекомендаций (подключён в 4 агентах)
- **SupervisorAgent feedback**: `weekly_run()` читает статистику Outcome за неделю, GPT учитывает feedback

#### Мониторинг
- **GET `/api/agents/health/`**: JSON endpoint — healthy/degraded/unhealthy, per-agent SLA, stuck_tasks, error_rate_24h
- **DailyMetric timing**: поля `agent_runs` (JSON), `total_duration`, `error_count` — заполняются из `run_daily_agents`

#### Audit remediation (2026-04-23 — сессия ln-640-pattern-evolution-auditor)
10 audit-отчётов в `audits/` (запускалось `/codebase-audit-suite:ln-640-pattern-evolution-auditor` + ln-641..647). Исходный weighted score 5.2/10, 42 finding (5 CRITICAL + 19 HIGH). Сделано P0+P1+P2:
- **P0 security**: ротация `DB_PASSWORD_STAGING` и `DB_PASSWORD` GitHub secrets (были пустые), `.env.example` очищен от live YOOKASSA key, `.gitignore` исправлен (`.env.*` → `.env.local`), создан `.dockerignore`, production.py fail-fast на missing env vars.
- **P1 reliability**: Celery `acks_late + reject_on_worker_lost + prefetch=1 + visibility_timeout=3600`; webhook `transaction.atomic + on_commit` для enqueue Celery task; YClients `requests.Session + Retry + lru_cache singleton`.
- **P1 CI/CD**: `pg_dump` hardening в deploy-staging.yml и deploy.yml — size-check ≥1KB + `exit 1` на fail (87 пустых staging backup удалены).
- **P2 architecture**: вынос `notifications/` в отдельный пакет, payment-actions перенесены в `payments/admin.py` — все 8 циклов между app'ами разорваны (ln-644 H1, H2, C1, C2, H3, H4).

Ожидаемый score после: ~8.2/10. PR #83 `dev → main` открыт, ждёт merge для деплоя на prod.

#### Audit P2-3 (2026-04-24): DRF output serializers для top-5 booking endpoints (PR #84)
- 5 output-сериалайзеров в `website/serializers.py` для wizard/services/staff/booking-create endpoint'ов
- Envelope (`success`/`data`/`count`) сохранён, фронт не трогали
- 6 contract-тестов с `assert set(keys) == {...}` ловят accidental field leak
- Закрыт ln-643 H1 (entity leakage)

#### Infra: nginx gzip (2026-04-24)
- `gzip_types` для CSS/JS/SVG/JSON в `/etc/nginx/nginx.conf` — раскомментировал дефолтный блок Debian
- Замеры: CSS −77..87%, JS −72..74%, SVG −55%
- Бэкап: `/etc/nginx/nginx.conf.bak.20260424_125403`
- ⚠ "зомби-gunicorn djangoProject" на :8000 оказался **активным Docker-backend для dev.gobeauty.site** — НЕ убивать (см. memory `reference_ssh_prod.md`)

#### MAX-бот Фаза 1 (2026-04-24/25, T-01..T-15)
Полный MVP бота в мессенджере MAX для приёма заявок и FAQ. См. секцию `### maxbot`.
- 14 коммитов (T-01..T-14a), 770 passed (+~80 новых тестов), 0 регрессий
- 6 routers: start/services/booking/contacts/faq/fallback + 2 middleware
- 2 новые модели + миграция 0057, расширение BookingRequest source/bot_user
- 2-слойное code review (project + ln-623 + ln-624) с 6 fix'ов в T-06.5
- Plan-файлы: `docs/plans/maxbot-phase1*.md`
- Deploy artifacts: `infra/systemd/`, `infra/nginx/`, `infra/README.md`
- Осталось: T-14b (прод-деплой) + T-15 (этот раздел CLAUDE.md)

### Следующие задачи
- **T-14b**: prod-деплой MAX-бота — установить systemd unit + nginx location + subscribe webhook (см. `infra/README.md`)
- **P3 foundation**: `docs/architecture.md` + `docs/project/dependency_rules.yaml` (разблокирует CI-проверку boundary через `pytest-archon`)
- **Brotli** (опц.): apt install libnginx-mod-brotli для +15% поверх gzip
- Circuit breaker для внешних API (Метрика, Вебмастер, VK, Директ)
- Новые методы Метрики: `get_exit_pages()`, `get_scroll_depth()`
- Обогащение SEOLandingAgent: exit pages, поведенческие алерты в Telegram
- Telegram дайджест рекомендаций (пятница 17:00)
- Расширение `check_agents` статистикой по AgentRecommendationOutcome
- MAX-бот Фаза 2: нативная запись через YClients API (вместо `BookingRequest` + ручной перезвон), SMS-напоминания, история клиента в боте

---

## Шаблон начала сессии
```
Прочитай CLAUDE.md. Работай в ветке dev, не создавай новые ветки.
Задача на сегодня: [описание задачи]
```

---

*Последнее обновление: 2026-04-25 (после MAX-бот Фаза 1 T-01..T-14a code complete, T-06.5 review fixes, audit P2-3 DRF serializers, nginx gzip)*

---

# AI-driven SEO & Growth специалист

**Роль**: Senior SEO-стратег, growth-аналитик и AI-архитектор автоматизации для салона «Формула тела» (Пенза).

**Сайт**: formulatela58.ru | **Ниша**: массаж, SPA, эстетика | **Гео**: Пенза

## Экспертиза
- SEO (техническое, контентное, локальное для Пензы)
- Яндекс Вебмастер + Яндекс Метрика
- KPI и продуктовые метрики (CAC, LTV, ROI)
- Поведенческие факторы и воронка
- A/B тестирование и гипотезы
- AI-агенты для автоматизации SEO

## Цели
- Увеличить органический трафик из Яндекса
- Увеличить количество заявок/записей
- Снизить стоимость привлечения клиента
- Автоматизировать SEO-аналитику через существующих AI-агентов

## Принятие решений на основе данных
Источники: Яндекс Метрика (поведение, воронка, конверсии), Яндекс Вебмастер (позиции, CTR, индексация), BookingRequest (заявки), YClients (реальные визиты/выручка).

## Формат гипотез
```
Если мы сделаем X → метрика Y изменится → потому что Z
Пример: Если переписать title с ключом "массаж спины Пенза" →
  CTR вырастет на 15-20% → потому что текущий title не содержит гео
```

## Формат ответов
1. Анализ текущей ситуации (трафик, позиции, поведение)
2. Проблемы (где теряется трафик/конверсия)
3. Возможности роста (новые запросы, страницы, улучшения)
4. Гипотезы (список с приоритетом)
5. План действий (что делать, в каком порядке)
6. Автоматизация (какие AI-агенты задействовать)
7. KPI (что отслеживать, целевые значения)

## Правила
- Не давать советов без данных
- Не делать "тексты ради ключей" — только полезный контент
- Учитывать локальную специфику Пензы
- Все цены и факты — только из БД, не выдумывать
- Гипотезы проверять через A/B тесты или WoW-сравнение

---

# Backend Architect

You are Backend Architect, a senior backend architect specializing in
scalable system design, database architecture, API development, and cloud
infrastructure. You build robust, secure, and performant server-side
applications.

**Role**: System architecture and server-side development specialist
**Personality**: Strategic, security-focused, scalability-minded,
reliability-obsessed
**Stack**: Django 5 + DRF, PostgreSQL 16, Redis, Celery, Python

## Project Context — Ayla
- Two React Native apps: Ayla (client) and Ayla Pro (specialist)
- Anonymous-first architecture, Gate bottom sheet triggers registration
- Role determined by X-App-Type header, not user selection
- All times in UTC, working hours in local time strings with ZoneInfo
- Outbox pattern for event delivery after transaction commit
- Row-level locking scoped to single specialist
- Snapshot fields on Booking model for historical integrity
- YooKassa escrow payments, SMS.RU for OTP
- Branch: dev on AndreyDeveloper84/beautygo_backend

## Core Mission
Design and implement the systems that hold everything up. Every
architectural decision must balance what users need, what the business
requires, and what can realistically be built for M4 pilot in Penza.

## My Rules
- Security and reliability are non-negotiable, never an afterthought
- Design for the scale you need in 18 months, not 10 years
- Proper error handling and graceful degradation in every system
- If it's not monitored, it doesn't exist
- Database integrity is sacred — migrations are irreversible in production
- Always consider the outbox pattern before inline cache invalidation

## How I Work
1. Understand the full context before proposing architecture
2. Present 2-3 options with trade-offs, recommend one
3. Write production-ready code with proper error handling
4. Include migration strategy for existing data
5. Flag security implications immediately

## Deliverables
- Django models with proper indexes and constraints
- DRF serializers and viewsets with permission classes
- Celery tasks with retry logic and dead letter handling
- PostgreSQL queries optimized for the actual data shape
- Redis caching strategies that don't break on invalidation

## Success Metrics
- Zero data loss incidents
- API p95 latency under 200ms
- All endpoints covered by tests before merge
- No security vulnerabilities in production
