"""
Настройки для production окружения (formulatela58.ru)
Использование: DJANGO_SETTINGS_MODULE=mysite.settings.production
"""
from django.core.exceptions import ImproperlyConfigured

from .base import *
from .base import _csv, _bool, _scheme  # private helpers not exported by import *

# ⚠️ DEBUG всегда выключен в production
DEBUG = False

# ⚠️ fail-fast на boot если критичные env vars отсутствуют.
# ImproperlyConfigured вместо assert — assert выключается флагом python -O.
_REQUIRED_ENV_VARS = (
    "DJANGO_SECRET_KEY",
    "YCLIENTS_PARTNER_TOKEN",
    "YCLIENTS_USER_TOKEN",
    "YCLIENTS_COMPANY_ID",
)
_missing = [v for v in _REQUIRED_ENV_VARS if not os.getenv(v)]
if _missing:
    raise ImproperlyConfigured(
        f"Production: отсутствуют обязательные env vars: {', '.join(_missing)}"
    )
if os.getenv("DJANGO_SECRET_KEY") == "dev-secret":
    raise ImproperlyConfigured(
        "Production: DJANGO_SECRET_KEY='dev-secret' — это дефолт из base.py, "
        "на проде должен быть реальный секрет (см. .env.example)"
    )

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

# Доверяем заголовкам от nginx: схема и хост берутся из X-Forwarded-*
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

# Финальная проверка (DEBUG/ALLOWED_HOSTS) — SECRET_KEY уже проверен выше.
if DEBUG:
    raise ImproperlyConfigured("Production: DEBUG must be False")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("Production: ALLOWED_HOSTS must be set")

import logging as _logging
_logging.getLogger(__name__).info("Загружены настройки PRODUCTION")
