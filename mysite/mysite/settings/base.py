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
    # твои приложения:
    "booking","services_app.apps.ServicesAppConfig","website",
    "agents",
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
]

# CSP — расширенный (безопасный) вариант
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC  = ("'self'", "https://w951024.yclients.com")
CSP_STYLE_SRC   = ("'self'", "'unsafe-inline'", "https:")
CSP_IMG_SRC     = ("'self'", "data:", "https:")
CSP_FONT_SRC    = ("'self'", "data:", "https:")

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
    }}

LANGUAGE_CODE = os.getenv("DJANGO_LANGUAGE_CODE", "ru")
TIME_ZONE     = os.getenv("DJANGO_TIME_ZONE", "UTC")
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

# === Celery ===
from celery.schedules import crontab  # noqa: E402

CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_BEAT_SCHEDULE = {
    "daily-agents-9am": {
        "task": "agents.tasks.run_daily_agents",
        "schedule": crontab(hour=9, minute=0),
    },
    "weekly-agents-monday-8am": {
        "task": "agents.tasks.run_weekly_agents",
        "schedule": crontab(hour=8, minute=0, day_of_week="monday"),
    },
}

# === OpenAI ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# === Яндекс.Метрика ===
YANDEX_METRIKA_TOKEN      = os.getenv("YANDEX_METRIKA_TOKEN", "")
YANDEX_METRIKA_COUNTER_ID = os.getenv("YANDEX_METRIKA_COUNTER_ID", "")

# === Яндекс.Директ ===
YANDEX_DIRECT_TOKEN        = os.getenv("YANDEX_DIRECT_TOKEN", "")
YANDEX_DIRECT_CLIENT_LOGIN = os.getenv("YANDEX_DIRECT_CLIENT_LOGIN", "")

# === VK Реклама ===
VK_ADS_TOKEN      = os.getenv("VK_ADS_TOKEN", "")
VK_ADS_ACCOUNT_ID = os.getenv("VK_ADS_ACCOUNT_ID", "")

# === Яндекс.Вебмастер ===
# Токен: https://oauth.yandex.ru/ (scope: webmaster:info)
# HOST_ID: encoded URL вида https:yourdomain.ru:443
#   Узнать: python manage.py check_webmaster --list-hosts
YANDEX_WEBMASTER_TOKEN   = os.getenv("YANDEX_WEBMASTER_TOKEN", "")
YANDEX_WEBMASTER_USER_ID = os.getenv("YANDEX_WEBMASTER_USER_ID", "")  # авто-получается если пусто
YANDEX_WEBMASTER_HOST_ID = os.getenv("YANDEX_WEBMASTER_HOST_ID", "")