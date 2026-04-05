"""
Настройки для production окружения (formulatela58.ru)
Использование: DJANGO_SETTINGS_MODULE=mysite.settings.production
"""
from .base import *
from .base import _csv, _bool, _scheme  # private helpers not exported by import *

# ⚠️ DEBUG всегда выключен в production
DEBUG = False

# Разрешённые хосты ТОЛЬКО из .env (безопасность!)
ALLOWED_HOSTS = _csv("DJANGO_ALLOWED_HOSTS", "formulatela58.ru,www.formulatela58.ru")

# ✅ SSL обязателен + все защиты
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# HSTS - жёсткие настройки (год!)
SECURE_HSTS_SECONDS = 31536000  # 1 год
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Защита от clickjacking
X_FRAME_OPTIONS = "DENY"

# Защита от MIME-sniffing
SECURE_CONTENT_TYPE_NOSNIFF = True

# Защита от XSS
SECURE_BROWSER_XSS_FILTER = True

# Доверяем заголовку от nginx/traefik
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Проверка на старте
assert not DEBUG, "❌ DEBUG must be False in production!"
assert ALLOWED_HOSTS, "❌ ALLOWED_HOSTS must be set in production!"

import logging as _logging
_logging.getLogger(__name__).info("Загружены настройки PRODUCTION")
