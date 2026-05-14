from pathlib import Path
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # .../mysite

load_dotenv(BASE_DIR.parent / '.env')

# === ENV helpers ===
def _csv(name, default=""):
    raw = os.getenv(name, default)
    return [p.strip() for p in raw.split(",") if p.strip()]

def _bool(name, default=False):
    return os.getenv(name, str(default)).lower() in {"1","true","yes","on"}

def _scheme(origin: str) -> str:
    return origin if origin.startswith(("http://","https://")) else f"https://{origin}"

# === core ===
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret")  # в проде обязателен в .env
DEBUG = _bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = _csv("DJANGO_ALLOWED_HOSTS", "*" if DEBUG else "")
if not ALLOWED_HOSTS or ALLOWED_HOSTS == ["*"]:
    ALLOWED_HOSTS = ["*"] if DEBUG else ["127.0.0.1", "localhost"]

CSRF_TRUSTED_ORIGINS = [_scheme(o) for o in _csv("DJANGO_CSRF_TRUSTED_ORIGINS", "")]

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

ADMIN_NOTIFICATION_EMAIL = os.environ.get('ADMIN_NOTIFICATION_EMAIL', '')

# MAX-бот (для admin-action push-back BotInquiry → bot.send_message в MAX)
MAX_BOT_TOKEN = os.environ.get('MAX_BOT_TOKEN', '')

# Shared secret used by the ai-bot-platform sync layer to authenticate against
# /api/v1/catalog/* (Sprint 8 / DRF-725). Empty default → catalog endpoints
# return 401 for every request (deny-by-default). Production must set this in
# .env — settings/production.py fails fast on boot if it's missing.
AI_BOT_PLATFORM_TOKEN = os.environ.get('AI_BOT_PLATFORM_TOKEN', '')


# Outbound delta-push webhook (Sprint 8 / DRF-726). When the URL is empty the
# Celery task is a no-op — M3 lands ahead of the consumer side, so we keep it
# dormant by default and turn it on later by setting both env vars together.
# Deliberately NOT in production.py::_REQUIRED_ENV_VARS — we never want a
# missing optional webhook to take prod down on boot.
AI_BOT_PLATFORM_WEBHOOK_URL = os.environ.get('AI_BOT_PLATFORM_WEBHOOK_URL', '')
AI_BOT_PLATFORM_WEBHOOK_SECRET = os.environ.get('AI_BOT_PLATFORM_WEBHOOK_SECRET', '')

INSTALLED_APPS = [
    "django.contrib.admin","django.contrib.auth","django.contrib.contenttypes",
    "django.contrib.sessions","django.contrib.messages","django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.sitemaps",
    # Sprint 8 / DRF-724 (M1): DRF for /api/v1/catalog/* read-only endpoints
    # consumed by the ai-bot-platform. Listed already in requirements.txt
    # (djangorestframework==3.16.1) — adding here so its admin / browsable
    # API are discoverable. Default permission classes intentionally not
    # overridden globally; per-view auth is wired in M2 (DRF-725).
    "rest_framework",
    # твои приложения:
    "booking","services_app.apps.ServicesAppConfig","website",
    "agents",
    "payments",
    "maxbot",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    # CSP — включаем, если используешь django-csp:
    "csp.middleware.CSPMiddleware",
    # Sprint 8 / DRF-725 (M2): X-Service-Token gate for /api/v1/catalog/*
    # endpoints consumed by the ai-bot-platform sync layer. Runs after
    # CommonMiddleware (path normalised) and before Ratelimit so unauth
    # traffic doesn't consume rate-limit budget. Scoped strictly to the
    # catalog prefix — all other routes pass through unchanged.
    "services_app.api.v1.catalog.middleware.ServiceTokenAuthMiddleware",
    # Превращает django_ratelimit Ratelimited в 429 JSON для booking API
    "website.middleware.RatelimitMiddleware",
    # Ловит FileNotFoundError от отсутствующих медиа-файлов в admin (свежий
    # dev без синка media/ с прода), показывает messages вместо 500.
    "website.middleware.AdminMissingMediaMiddleware",
]

# CSP — django-csp v4 dict-based API.
# EXCLUDE_URL_PREFIXES: CSP не применяется к этим префиксам. Django admin
# активно использует inline scripts (sidebar toggle, collapse, datepicker) —
# под жёстким CSP они ломаются. Публичный сайт остаётся под защитой.
CONTENT_SECURITY_POLICY = {
    "EXCLUDE_URL_PREFIXES": ["/admin/"],
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'", "https://w951024.yclients.com", "https://yastatic.net", "https://cdn.jsdelivr.net", "https://mc.yandex.ru", "https://mc.yandex.com"],
        "style-src": ["'self'", "'unsafe-inline'", "https:"],
        "img-src": ["'self'", "data:", "https:"],
        "font-src": ["'self'", "data:", "https:"],
        "frame-src": ["'self'", "https://yandex.ru"],
        "connect-src": ["'self'", "https://mc.yandex.ru", "https://mc.yandex.com", "wss://mc.yandex.com"],
    },
}

ROOT_URLCONF = "mysite.urls"
WSGI_APPLICATION = "mysite.wsgi.application"
ASGI_APPLICATION = "mysite.asgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "website.context_processors.settings",
    ]},
}]

# --- БД через ENV: SQLite по умолчанию, легко переключить на Postgres ---
DB_ENGINE = os.getenv("DB_ENGINE", "django.db.backends.sqlite3")
if "sqlite" in DB_ENGINE:
    DB_NAME = os.getenv("DB_NAME", str(BASE_DIR / "data" / "db.sqlite3"))
    DATABASES = {"default": {"ENGINE": DB_ENGINE, "NAME": DB_NAME}}
else:
    DATABASES = {"default": {
        "ENGINE": DB_ENGINE,
        "NAME": os.getenv("DB_NAME", "mysite_db"),
        "USER": os.getenv("DB_USER", "mysite_user"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "5432"),
        # Держим коннект 60 сек, чтобы не открывать TCP+TLS на каждый запрос.
        # Health check (Django 4.1+) делает SELECT 1 и защищает от stale-коннекта.
        "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
    }}

LANGUAGE_CODE = os.getenv("DJANGO_LANGUAGE_CODE", "ru")
TIME_ZONE     = os.getenv("DJANGO_TIME_ZONE", "Europe/Moscow")
USE_I18N = True
USE_TZ   = True

STATIC_URL  = "/static/"
STATIC_ROOT = os.getenv("STATIC_ROOT", str(BASE_DIR / "staticfiles"))
STATICFILES_DIRS = [
    BASE_DIR / "static",  # Глобальная папка static в корне проекта
]
MEDIA_URL   = "/media/"
MEDIA_ROOT  = os.getenv("MEDIA_ROOT", str(BASE_DIR / "media"))

# === MAX-бот ===
# Welcome-картинка для новых пользователей (отправляется первым контактом
# в bot_started только для is_new=True). Если файла нет — приветствие
# отправляется без картинки. Сменить на свою — переопределить env-переменной
# или положить файл по другому пути.
MAXBOT_WELCOME_IMAGE_PATH = os.getenv(
    "MAXBOT_WELCOME_IMAGE_PATH",
    str(BASE_DIR / "static" / "images" / "massaj-big.jpg"),
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "[{levelname}] {asctime} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO" if not DEBUG else "DEBUG"},
    "loggers": {
        "services_app.yclients_api": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        }
    }
}

# === YClients API Configuration ===
YCLIENTS_PARTNER_TOKEN = os.getenv("YCLIENTS_PARTNER_TOKEN", "")
YCLIENTS_USER_TOKEN = os.getenv("YCLIENTS_USER_TOKEN", "")
YCLIENTS_COMPANY_ID = os.getenv("YCLIENTS_COMPANY_ID", "")

# === YooKassa API Configuration ===
# Онлайн-оплата услуг. Кнопка «Оплатить онлайн» показывается клиентам
# только когда SiteSettings.online_payment_enabled = True И креденшелы ниже
# заполнены — это feature flag, переключается через /admin/ без деплоя.
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")
# Куда YooKassa редиректит клиента после оплаты. Поддерживает плейсхолдер
# {order_number}, подставляется в PaymentService.create_for_order.
YOOKASSA_RETURN_URL = os.getenv(
    "YOOKASSA_RETURN_URL",
    "https://formulatela58.ru/payments/success/?order={order_number}",
)
# Webhook IP whitelist. Если True (default) — webhook отвечает 403 на запросы
# не от официальных IP YooKassa. Выключать только в локальной разработке и
# тестах (ngrok, CI).
YOOKASSA_WEBHOOK_STRICT_IP = os.getenv("YOOKASSA_WEBHOOK_STRICT_IP", "1") not in ("0", "false", "False")
# Код НДС для чека 54-ФЗ: 1=без НДС (ИП на УСН), 2=0%, 3=10%, 4=20%.
YOOKASSA_VAT_CODE = int(os.getenv("YOOKASSA_VAT_CODE", "1"))

# === Django cache (rate limit + booking idempotency) ===
# Redis DB 1 — изолирован от Celery broker (DB 0), чтобы ключи кэша не
# пересекались с очередью задач. Локально достаточно дефолтного
# REDIS_URL, в проде — брать из .env.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.getenv(
            "DJANGO_CACHE_URL",
            "redis://127.0.0.1:6379/1",
        ),
    }
}

# === Celery ===
from celery.schedules import crontab  # noqa: E402
from kombu import Queue  # noqa: E402

CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
# Расписание Celery считаем в локальном часовом поясе салона, чтобы "12:00"
# означало именно 12:00 по Москве, а не 09:00 UTC.
CELERY_TIMEZONE = os.getenv("CELERY_TIMEZONE", "Europe/Moscow")
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
# Подтверждать задачу ПОСЛЕ выполнения, а не до. Без этого SIGKILL/OOM/
# рестарт воркера посреди задачи = тихая потеря (default early-ack). В связке
# с REJECT_ON_WORKER_LOST задача вернётся в очередь и перезапустится.
# Требует идемпотентности задач — у нас AgentTask.status=RUNNING защищает от
# двойного выполнения через _lifecycle.ensure_task_finalized.
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
# Видеть задачи в STARTED в Flower/монитористе (по умолчанию состояние не пишется).
CELERY_TASK_TRACK_STARTED = True
# prefetch=1 — воркер берёт одну задачу за раз (fair dispatch). Без этого
# worker с несколькими потоками может забрать 4 задачи, одну выполнять 10
# минут, а остальные 3 ждать — короткие fulfill_paid_order «голодают» за
# длинными collect_retention_metrics. Критично при acks_late.
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
# Redis visibility_timeout — сколько брокер держит задачу «невидимой» после
# выдачи worker'у. Если worker не ack'нул за это время, задача вернётся в
# очередь. Должен быть >= CELERY_TASK_TIME_LIMIT (1860s), иначе долгая
# задача будет передоставлена и выполнится дважды.
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}
# Жёсткий потолок 30 мин — задача не может висеть бесконечно, иначе воркер
# залипает и beat не дождётся следующего слота. Задачи агентов укладываются
# в <5 мин, 30 мин — safety net.
CELERY_TASK_SOFT_TIME_LIMIT = 1800
CELERY_TASK_TIME_LIMIT = 1860  # hard kill через 60 сек после soft limit
# Выделяем задачи formula_tela в отдельную queue, чтобы business-markets
# worker (тот же Redis, DB 0) не воровал наши задачи. Без этого оба worker'а
# слушают дефолтную queue "celery" → race condition → задачи теряются.
# CELERY_DEFAULT_QUEUE — старое имя Celery 3.x, игнорируется в Celery 5+.
# Правильное имя: CELERY_TASK_DEFAULT_QUEUE (namespace CELERY_ + task_default_queue).
CELERY_TASK_DEFAULT_QUEUE = "formula_tela"
CELERY_TASK_QUEUES = (Queue("formula_tela"),)
CELERY_TASK_ROUTES = {
    "agents.tasks.*": {"queue": "formula_tela"},
    "payments.tasks.*": {"queue": "formula_tela"},
}
CELERY_BEAT_SCHEDULE = {
    "daily-agents-12pm-msk": {
        "task": "agents.tasks.run_daily_agents",
        "schedule": crontab(hour=12, minute=0),
    },
    "weekly-agents-monday-11am-msk": {
        "task": "agents.tasks.run_weekly_agents",
        "schedule": crontab(hour=11, minute=0, day_of_week="monday"),
    },
    "daily-rank-snapshots-10am-msk": {
        "task": "agents.tasks.collect_rank_snapshots",
        "schedule": crontab(hour=10, minute=0),
    },
    "weekly-trend-scout-monday-1030-msk": {
        "task": "agents.tasks.collect_trends",
        "schedule": crontab(hour=10, minute=30, day_of_week="monday"),
    },
    # Исторически задача шла в воскресенье 22:00 UTC, что соответствует
    # понедельнику 01:00 по Москве. Фиксируем локальное время явно.
    "weekly-generate-landings-monday-0100-msk": {
        "task": "agents.tasks.generate_missing_landings",
        "schedule": crontab(hour=1, minute=0, day_of_week="monday"),
    },
    "daily-retention-metrics-11am-msk": {
        "task": "agents.tasks.collect_retention_metrics",
        "schedule": crontab(hour=11, minute=0),
    },
    "daily-landing-qc-9am-msk": {
        "task": "agents.tasks.run_landing_qc",
        "schedule": crontab(hour=9, minute=0),
    },
    # Phase 1 conversation lifecycle: закрыть AI-диалоги без активности 7+ дней
    # как outcome=abandoned. Cheap UPDATE-query, не нагружает БД.
    "daily-close-stale-conversations-3am-msk": {
        "task": "services_app.tasks.close_stale_conversations",
        "schedule": crontab(hour=3, minute=0),
    },
    # Phase 2 Learning Roadmap: LLM meta-analysis последних 20 неудавшихся диалогов
    # → patterns + prompt_additions → Telegram-отчёт администратору + auto-PR.
    "weekly-analyze-failed-conversations-monday-6am-msk": {
        "task": "services_app.tasks.analyze_failed_conversations",
        "schedule": crontab(hour=6, minute=0, day_of_week="monday"),
    },
    # Phase 2.4 «Auto-tune #1»: курирует success-диалоги в few-shot примеры,
    # которые render_system_prompt подмешивает в prompt → бот учится стилю
    # без модели fine-tuning'а.
    "weekly-collect-success-examples-sunday-22-msk": {
        "task": "services_app.tasks.collect_success_examples",
        "schedule": crontab(hour=22, minute=0, day_of_week="sunday"),
    },
    # N2 reminder system — каждые 15 минут отправлять PENDING reminder'ы.
    "maxbot-send-due-reminders-every-15min": {
        "task": "maxbot.tasks.send_due_reminders",
        "schedule": crontab(minute="*/15"),
    },
    # N2 escalation — каждый час проверять SENT_NO_REPLY с visit_at <= now+12h.
    "maxbot-escalate-stale-reminders-hourly": {
        "task": "maxbot.tasks.escalate_stale_reminders",
        "schedule": crontab(minute=15),
    },
    # T07 post-visit follow-up — daily 19:00 «как прошёл визит?»
    "maxbot-post-visit-followups-1900-msk": {
        "task": "maxbot.tasks.send_post_visit_followups",
        "schedule": crontab(hour=19, minute=0),
    },
    # T07 repeat offer — weekly Monday 12:00 «время повторить?»
    "maxbot-repeat-offers-monday-1200-msk": {
        "task": "maxbot.tasks.send_repeat_offers",
        "schedule": crontab(hour=12, minute=0, day_of_week="monday"),
    },
    # Phase 3.1 Part 2D.2 T05: hourly trigger, per-user time filter inside task
    "maxbot-daily-reports-hourly": {
        "task": "maxbot.tasks.send_daily_reports",
        "schedule": crontab(minute=0),  # каждый час в :00, per-user filter inside
    },
    # Phase 3.1 Part 2D.2 T08: adaptive water reminders 4h × UTC, per-user filters
    "maxbot-water-reminders-4h": {
        "task": "maxbot.tasks.send_water_reminders",
        "schedule": crontab(minute=0, hour="0,4,8,12,16,20"),  # UTC × 6/day
    },
}

# === Email (SMTP) ===
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "1") in ("1", "true", "True")
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "0") in ("1", "true", "True")
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    EMAIL_HOST_USER or "noreply@formulatela58.ru",
)
EMAIL_TIMEOUT = 10

# === OpenAI ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")  # API-прокси для OpenAI
OPENAI_PROXY = os.getenv("OPENAI_PROXY", "")  # HTTP-прокси (http://user:pass@host:port)

# === Ayla nutrition API (DRF-246) ===
# MAX bot calls Ayla `/api/v1/nutrition/internal/*` over HTTP with
# X-Service-Token + X-External-User-ID headers. Both must be set in
# dev/staging/prod env; empty values disable food scanner.
AYLA_BASE_URL = os.getenv("AYLA_BASE_URL", "")
NUTRITION_SERVICE_TOKEN = os.getenv("NUTRITION_SERVICE_TOKEN", "")

# Feature flag: показывать ли кнопку «🍎 Дневник питания» в main_menu_keyboard.
# Default OFF — Phase 3.1 Part 1 готов code-wise, но Ayla backend ещё не
# задеплоил DRF-300..303 internal endpoints. Когда Ayla готов — поставить
# NUTRITION_ENABLED=1 в .env + рестартануть бота. См.
# `docs/plans/maxbot-phase3-ayla-spec.md` §6 acceptance criteria.
NUTRITION_ENABLED = _bool("NUTRITION_ENABLED", default=False)

# DRF-287 (B-8): per-user gate для Phase 3 — пока NUTRITION_ENABLED=False,
# только перечисленные max_user_id видят «🍎 Дневник питания» в main_menu.
# Comma-separated list of MAX user IDs (BigInt). Empty default → нулевая
# internal-cohort. Пример: PHASE3_INTERNAL_ACCOUNTS=12345,67890,11111
PHASE3_INTERNAL_ACCOUNTS = [
    int(x) for x in os.getenv("PHASE3_INTERNAL_ACCOUNTS", "").split(",") if x
]

# DRF-292 (B-13): 50/50 A/B middleware. Когда PHASE3_AB_ENABLED=True (а
# NUTRITION_ENABLED=False), public users разделены детерминированно по
# `bot_user.id % 100 < 50` — segment A видит кнопку, segment B нет.
# Internal accounts всегда в segment A независимо от этого флага.
# Default OFF — A/B activates только когда B-10 internal smoke прошёл.
PHASE3_AB_ENABLED = _bool("PHASE3_AB_ENABLED", default=False)

# DRF-269/DRF-274 (B-4): cross-domain insights bot integration.
# Default OFF. Production rollout blocked by DRF-271 (B-3) cumulative + DRF-275.
CROSS_DOMAIN_ENABLED = _bool("CROSS_DOMAIN_ENABLED", default=False)

# DRF-288 (B9): per-user gate for Track E (cross-domain insights).
# When CROSS_DOMAIN_ENABLED is False, only listed max_user_ids получают cards.
# Comma-separated list of MAX user IDs (BigInt). Empty by default → no internal users.
CROSS_DOMAIN_INTERNAL_ACCOUNTS = [
    int(x) for x in os.getenv("CROSS_DOMAIN_INTERNAL_ACCOUNTS", "").split(",") if x
]

# === Яндекс.Метрика ===
YANDEX_METRIKA_TOKEN      = os.getenv("YANDEX_METRIKA_TOKEN", "")
YANDEX_METRIKA_COUNTER_ID = os.getenv("YANDEX_METRIKA_COUNTER_ID", "")

# === Яндекс.Директ ===
YANDEX_DIRECT_TOKEN        = os.getenv("YANDEX_DIRECT_TOKEN", "")
YANDEX_DIRECT_CLIENT_LOGIN = os.getenv("YANDEX_DIRECT_CLIENT_LOGIN", "")

# === VK Реклама ===
VK_ADS_TOKEN      = os.getenv("VK_ADS_TOKEN", "")
VK_ADS_ACCOUNT_ID = os.getenv("VK_ADS_ACCOUNT_ID", "")

# === VK Social (парсинг групп для трендов) ===
VK_SERVICE_TOKEN = os.getenv("VK_SERVICE_TOKEN", "")
VK_TREND_GROUP_IDS = [gid.strip() for gid in os.getenv("VK_TREND_GROUP_IDS", "").split(",") if gid.strip()]

# === Парсер трендов ===
TREND_SEED_QUERIES = [q.strip() for q in os.getenv("TREND_SEED_QUERIES",
    "массаж пенза,спа пенза,массаж лица,антицеллюлитный массаж,"
    "лимфодренажный массаж,массаж спины,подарочный сертификат массаж,"
    "массажист пенза,lpg массаж,спа процедуры"
).split(",") if q.strip()]

# === Яндекс.Вебмастер ===
# Токен: https://oauth.yandex.ru/ (scope: webmaster:info)
# HOST_ID: encoded URL вида https:yourdomain.ru:443
#   Узнать: python manage.py check_webmaster --list-hosts
YANDEX_WEBMASTER_TOKEN   = os.getenv("YANDEX_WEBMASTER_TOKEN", "")
YANDEX_WEBMASTER_USER_ID = os.getenv("YANDEX_WEBMASTER_USER_ID", "")  # авто-получается если пусто
YANDEX_WEBMASTER_HOST_ID = os.getenv("YANDEX_WEBMASTER_HOST_ID", "")

# Код верификации для метатега подтверждения прав в Яндекс.Вебмастере.
# Получается в UI Вебмастера → «Подтверждение прав» → «Мета-тег».
# Если пусто — метатег в base.html не рендерится.
YANDEX_VERIFICATION = os.getenv("YANDEX_VERIFICATION", "")

# Базовый URL сайта (без trailing slash)
# Используется TechnicalSEOWatchdog для проверки страниц
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://formulatela58.ru")
