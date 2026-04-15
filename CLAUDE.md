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
│   ├── agents/          <- AI-агенты: аналитика, SEO, маркетинговая автоматизация
│   │   ├── agents/      <- модули агентов (analytics, seo_landing, smm_growth и др.)
│   │   ├── integrations/ <- внешние API (yandex_metrika, yandex_webmaster, vk_ads, yandex_direct)
│   │   └── management/  <- management commands (check_metrika, check_webmaster)
│   ├── tests/           <- тесты pytest
│   └── manage.py
├── docker-compose.yml
├── Dockerfile
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
- `SeoTask` — задача для SEO-специалиста; task_type: create_landing/update_meta/add_faq/fix_technical/rewrite_cta/add_content_block; priority: high/medium/low; status: open/in_progress/done

Расписание Celery beat:
- `daily-rank-snapshots-7am` → `agents.tasks.collect_rank_snapshots` (каждый день в 07:00)
- `daily-agents-9am` → `agents.tasks.run_daily_agents` (каждый день в 09:00)
- `weekly-agents-monday-8am` → `agents.tasks.run_weekly_agents` (понедельник в 08:00)

### website
Frontend views: главная, каталог услуг, детальная страница услуги, мастера, форма-мастер записи, контакты, акции, пакеты. Все модели данных живут в `services_app`.

### booking
Минимальный — placeholder `booking()` view. Booking API endpoint'ы живут в `website/views.py`.

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
- `/<slug>/` — SEO-посадочная страница (только published, catch-all последним в urlpatterns)
- `/healthz/` — health check -> `{"status": "ok"}`

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

### Следующие задачи
- Доработка логики OfferAgent по загрузке мастеров
- Расширение SupervisorAgent для более гранулярного управления

---

## Шаблон начала сессии
```
Прочитай CLAUDE.md. Работай в ветке dev, не создавай новые ветки.
Задача на сегодня: [описание задачи]
```

---

*Последнее обновление: 2026-04-08*

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
