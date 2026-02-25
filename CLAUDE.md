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
- `SiteSettings` — глобальные настройки (телефон, соцсети JSON, способы оплаты JSON, данные YClients, ссылки на карты)

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
# addopts = -q
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
- `SITE_BASE_URL` (например: https://formulatela.ru)

---

## Окружения настроек
| Файл | Применение |
|------|-----------|
| `base.py` | Общий конфиг |
| `dev.py` | Настройки разработки |
| `local.py` | Локально: SQLite, DEBUG=True, ALLOWED_HOSTS=["*"] |
| `staging.py` | Staging-сервер |
| `production.py` | Продакшн PostgreSQL |

Настройки выбираются автоматически: `__init__.py` читает переменную `DJANGO_ENV` (production -> staging -> local по умолчанию).

---

## Templatetags

### `services_app/templatetags/service_extras.py`
- `option_label(opt)` — форматирует ServiceOption как "60 мин x 10 процедур — 14 000 руб. (1 400 руб./проц.)"
- `discount(price, percent)` — вычисляет цену со скидкой

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
| analytics | agents/tasks.py | ежедневно 9:00 |
| analytics_budget | agents/tasks.py | понедельник 8:00 |
| seo_landing | agents/agents/seo_landing.py | понедельник 8:00 |
| smm_growth | agents/tasks.py | понедельник 8:00 |
| offers | agents/tasks.py | ежедневно 9:00 |

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
```bash
# Запуск локально
cd mysite && python manage.py runserver

# Celery (оба нужны для агентов)
celery -A mysite worker -l info
celery -A mysite beat -l info

# После изменения моделей
python manage.py makemigrations && python manage.py migrate

# Тесты
pytest  # из корня репозитория

# Проверка что ничего не сломано
python manage.py check

# Запустить агента вручную (для теста)
python manage.py shell
>>> from agents.tasks import run_daily_agents
>>> run_daily_agents()
```

---

## Текущее состояние проекта
<!-- Обновляй этот раздел в конце каждой рабочей сессии! -->

### Сделано
- Analytics Agent (agents/tasks.py -- run_daily_agents)
- SEO модели в agents/models.py: SeoKeywordCluster (с geo, service_category), SeoRankSnapshot, LandingPage, SeoTask
- SEO Admin: 4 ModelAdmin в agents/admin.py (publish actions, read-only snapshots, priority badges)
- YClients интеграция с WAF bypass
- Celery beat расписание (9:00 daily, 8:00 Monday)
- Yandex.Webmaster интеграция (agents/integrations/yandex_webmaster.py)
- Yandex.Metrika интеграция (agents/integrations/yandex_metrika.py)
- VK Ads интеграция (agents/integrations/vk_ads.py)
- Yandex.Direct интеграция (agents/integrations/yandex_direct.py)
- Management commands: check_metrika, check_webmaster, check_booking, import_price_list

### В процессе
- SEOLandingAgent -- файл agents/agents/seo_landing.py, нужен `_build_weekly_summary()`

### Следующие задачи
- OfferAgent -- генерация акций по загрузке мастеров
- Supervisor -- оркестратор агентов
- Telegram уведомления для SEO алертов
- Technical SEO Watchdog (проверка 404/500 страниц)
- seed_seo_clusters management command (наполнение SeoKeywordCluster данными)

---

## Шаблон начала сессии
<!-- Копируй это в начале каждой новой сессии Claude Code -->

```
Прочитай CLAUDE.md. Работай в ветке dev, не создавай новые ветки.
Задача на сегодня: [описание задачи]
```
