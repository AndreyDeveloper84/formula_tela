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
mysite/                  ← корень git
├── mysite/              ← корень Django проекта (здесь manage.py)
│   ├── mysite/          ← пакет настроек проекта
│   │   └── settings/    ← base.py, dev.py, local.py, staging.py, production.py
│   ├── services_app/    ← основное приложение: каталог услуг, блоки, медиа, FAQ, отзывы
│   ├── website/         ← frontend: views, шаблоны, context processors
│   ├── booking/         ← заявки на запись, синхронизация с YClients
│   ├── agents/          ← AI-агенты: аналитика и маркетинговая автоматизация
│   ├── tests/           ← тесты pytest
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
- `Service` — slug, seo_h1, price_from, duration_min, related_services (M2M self-ref), emoji, short_description, is_active, is_popular
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
Маркетинговая и аналитическая автоматизация через OpenAI + Celery. Основные модели:
- `AgentTask` — выполнение AI-задач; типы: analytics, offers, offer_packages, smm_growth, seo_landing, analytics_budget; статусы: pending, running, done, error
- `AgentReport` — OneToOne сводка по AgentTask (recommendations JSON)
- `ContentPlan` — SMM контент-календарь; платформы: VK, Instagram, Telegram; типы постов: post, story, reel
- `SeoKeywordCluster` — маппинг ключевых слов на service_slug с keywords JSON
- `SeoRankSnapshot` — еженедельные метрики Яндекс.Вебмастера (clicks, impressions, ctr, avg_position)
- `DailyMetric` — дневные агрегаты (total_requests, processed, top_services JSON, masters_load JSON)

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
- `/healthz/` — health check → `{"status": "ok"}`

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
Скопируй `.env.example` → `.env`. Ключевые переменные:
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

Настройки выбираются автоматически: `__init__.py` читает переменную `DJANGO_ENV` (production → staging → local по умолчанию).

---

## Templatetags

### `services_app/templatetags/service_extras.py`
- `option_label(opt)` — форматирует ServiceOption как "60 мин × 10 процедур — 14 000 ₽ (1 400 ₽/проц.)"
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
    ↓
DailyMetric / SeoRankSnapshot (сохраняем в БД)
    ↓
AgentTask создаётся (status=pending)
    ↓
Celery worker забирает задачу → запускает агента
    ↓
Агент читает данные из БД → формирует prompt → GPT-4
    ↓
AgentReport сохраняется (status=done, recommendations JSON)
    ↓
Telegram уведомление администратору
```

### Типы AgentTask и их файлы
| task_type | файл | расписание |
|---|---|---|
| analytics | agents/tasks.py | ежедневно 9:00 |
| analytics_budget | agents/tasks.py | понедельник 8:00 |
| seo_landing | agents/seo_agent.py | понедельник 8:00 |
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
| VK Ads → в AnalyticsBudgetAgent | Один промпт видит все каналы → лучше сравнение CPL/ROMI |
| LandingPage.status = 'draft' по умолчанию | Человек проверяет перед публикацией |
| @csrf_exempt на booking API | Внешние вызовы от YClients-виджета |
| Prefetch в views | Предотвращение N+1 запросов |
| WAF bypass headers для YClients | Без них возвращается 403 |
| Slug-based URL везде | SEO-приоритет; ID-based → 301 редирект |

---

## Запрещённые действия (без явного разрешения)
- ❌ Не изменяй существующие миграции — только создавай новые
- ❌ Не удаляй поля моделей — только помечай как deprecated
- ❌ Не трогай `services_app/migrations/` без явной просьбы
- ❌ Не добавляй инлайн-скрипты в шаблоны (CSP заблокирует)
- ❌ Не публикуй `LandingPage` автоматически (только draft)
- ❌ Не коммить `.env` и медиафайлы в git
- ❌ Не используй ID-based URL — только slug-based
- ❌ Не создавай новые ветки без явной просьбы

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
- ✅ Analytics Agent (agents/tasks.py — run_daily_agents)
- ✅ SEO модели (SeoKeywordCluster, SeoRankSnapshot)
- ✅ YClients интеграция с WAF bypass
- ✅ Celery beat расписание (9:00 daily, 8:00 Monday)

### В процессе
- 🔄 SEOLandingAgent — файл agents/seo_agent.py, нужен `_build_weekly_summary()`
- 🔄 VK Ads — добавляется в AnalyticsBudgetAgent как 3-й канал

### Следующие задачи
- ⏳ OfferAgent — генерация акций по загрузке мастеров
- ⏳ Supervisor — оркестратор агентов
- ⏳ Telegram уведомления для SEO алертов
- ⏳ Technical SEO Watchdog (проверка 404/500 страниц)

---

## Шаблон начала сессии
<!-- Копируй это в начале каждой новой сессии Claude Code -->

```
Прочитай CLAUDE.md. Работай в ветке dev, не создавай новые ветки.
Задача на сегодня: 

Файл: ### Задача 1.1 — Модели БД
**Статус:** ⏳ Не начата  
**Файл:** `agents/seo/models.py`

Если папки `agents/seo/` не существует — создать с `__init__.py` внутри.

Создать 4 модели:

**SeoKeywordCluster**
- `name` = CharField(max_length=200)
- `geo` = CharField(max_length=100, default='Пенза')
- `keywords` = JSONField(default=list) — список строк: `["массаж пенза", "массаж цена пенза"]`
- `target_url` = CharField(max_length=500, blank=True) — `/uslugi/klassicheskiy-massazh/`
- `service_category` = ForeignKey('services_app.ServiceCategory', on_delete=SET_NULL, null=True, blank=True)
- `is_active` = BooleanField(default=True)
- `created_at` = DateTimeField(auto_now_add=True)
- Meta: `verbose_name = 'SEO кластер'`, `ordering = ['name']`
- `__str__`: `f"{self.name} ({self.geo})"`

**SeoRankSnapshot**
- `cluster` = ForeignKey(SeoKeywordCluster, on_delete=CASCADE, related_name='snapshots')
- `date` = DateField()
- `avg_position` = FloatField(null=True, blank=True)
- `top3_count` = IntegerField(default=0)
- `top10_count` = IntegerField(default=0)
- `clicks` = IntegerField(default=0)
- `impressions` = IntegerField(default=0)
- `ctr` = FloatField(default=0.0) — в процентах: 3.5 = 3.5%
- `source` = CharField(choices=[('webmaster','Яндекс.Вебмастер'),('tracker','Трекер позиций')], default='webmaster')
- Meta: `unique_together = ['cluster', 'date']`, `ordering = ['-date']`
- `__str__`: `f"{self.cluster.name} | {self.date} | pos: {self.avg_position}"`

**LandingPage**
- `cluster` = ForeignKey(SeoKeywordCluster, on_delete=SET_NULL, null=True, blank=True)
- `slug` = SlugField(max_length=200, unique=True)
- `status` = CharField(choices=[('draft','Черновик'),('review','На модерации'),('published','Опубликована'),('rejected','Отклонена')], **default='draft'**)
- `meta_title` = CharField(max_length=70)
- `meta_description` = CharField(max_length=160)
- `h1` = CharField(max_length=200)
- `blocks` = JSONField(default=dict) — структура: `{intro, how_it_works, who_is_it_for, contraindications, results, faq:[{question,answer}], cta_text, internal_links}`
- `generated_by_agent` = BooleanField(default=True)
- `moderated_by` = ForeignKey('auth.User', on_delete=SET_NULL, null=True, blank=True)
- `created_at` = DateTimeField(auto_now_add=True)
- `published_at` = DateTimeField(null=True, blank=True)
- Meta: `verbose_name = 'Посадочная страница'`, `ordering = ['-created_at']`
- `__str__`: `f"{self.h1} [{self.get_status_display()}]"`

**SeoTask**
- `task_type` = CharField(choices=[('create_landing','Создать страницу'),('update_meta','Обновить мета-теги'),('add_faq','Добавить FAQ'),('fix_technical','Технический баг'),('rewrite_cta','Переписать CTA'),('add_content_block','Добавить блок')])
- `priority` = CharField(choices=[('high','Высокий'),('medium','Средний'),('low','Низкий')], default='medium')
- `status` = CharField(choices=[('open','Открыта'),('in_progress','В работе'),('done','Готово')], default='open')
- `title` = CharField(max_length=300)
- `description` = TextField(blank=True)
- `target_url` = CharField(max_length=500, blank=True)
- `payload` = JSONField(default=dict)
- `created_at` = DateTimeField(auto_now_add=True)
- Meta: `ordering = ['-priority', '-created_at']`
- `__str__`: `f"[{self.get_priority_display()}] {self.title}"`

**Не трогать:**
- `services_app/models.py` и `services_app/migrations/`
- `agents/models.py` (там уже есть AgentTask, AgentReport и др.)

**После создания:**
```bash
cd mysite
python manage.py makemigrations agents
python manage.py migrate
python manage.py check  # ожидаем 0 ошибок
```
