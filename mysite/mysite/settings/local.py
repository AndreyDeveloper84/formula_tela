"""
Настройки для локальной разработки (localhost)
Использование: DJANGO_SETTINGS_MODULE=mysite.settings.local
"""
from .base import *
from .base import _bool

# Режим отладки
DEBUG = True

# Разрешаем все хосты для локалки
ALLOWED_HOSTS = ["*"]

# ❌ SSL полностью выключен для localhost
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# Логи в консоль с подробностями
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{levelname}] {asctime} {name} {funcName}: {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": "DEBUG",
    },
}

