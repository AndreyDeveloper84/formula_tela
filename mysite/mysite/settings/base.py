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

INSTALLED_APPS = [
    "django.contrib.admin","django.contrib.auth","django.contrib.contenttypes",
    "django.contrib.sessions","django.contrib.messages","django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.sitemaps",
    # твои приложения:
    "booking","services_app.apps.ServicesAppConfig","website",
    "agents",
    "payments",
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
    # Превращает django_ratelimit Ratelimited в 429 JSON для booking API
    "website.middleware.RatelimitMiddleware",
]

# CSP — django-csp v4 dict-based API.
# EXCLUDE_URL_PREFIXES: CSP не применяется к этим префиксам. Django admin
# активно использует inline scripts (sidebar toggle, collapse, datepicker) —
# под жёстким CSP они ломаются. Публичный сайт остаётся под защитой.
CONTENT_SECURITY_POLICY = {
    "EXCLUDE_URL_PREFIXES": ["/admin/"],
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'", "https://w951024.yclients.com"],
        "style-src": ["'self'", "'unsafe-inline'", "https:"],
        "img-src": ["'self'", "data:", "https:"],
        "font-src": ["'self'", "data:", "https:"],
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
