"""
Настройки для staging окружения (stg.formulatela58.ru)
Использование: DJANGO_SETTINGS_MODULE=mysite.settings.staging
"""
from .base import *
from .base import _bool

# Отладка выключена (можно включить для тестирования)
DEBUG = _bool("DJANGO_DEBUG", False)

# Разрешённые хосты из .env
ALLOWED_HOSTS = _csv("DJANGO_ALLOWED_HOSTS", "stg.formulatela58.ru,127.0.0.1,localhost")

# ✅ SSL включен для staging
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# HSTS (HTTP Strict Transport Security) - мягкие настройки для staging
SECURE_HSTS_SECONDS = 3600  # 1 час (для staging меньше, чем в prod)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False  # Не трогаем поддомены
SECURE_HSTS_PRELOAD = False  # Не добавляем в preload list

# Доверяем заголовку от nginx
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Логирование
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "[{levelname}] {asctime} {name}: {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        }
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}

print("🧪 Загружены настройки STAGING (с SSL, но мягкие)")
