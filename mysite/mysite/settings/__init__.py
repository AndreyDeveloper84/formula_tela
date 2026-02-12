"""
Автоматический выбор настроек на основе переменной окружения.

Приоритет:
1. DJANGO_SETTINGS_MODULE (если задана явно)
2. Иначе смотрит на DJANGO_ENV
3. Fallback на local (для безопасности)
"""
import os as _os

# Пробуем определить окружение
env = _os.getenv("DJANGO_ENV", "local").lower()

# Выбираем правильный файл настроек
if env == "production" or env == "prod":
    from .production import *  # noqa
    print("📦 Окружение: PRODUCTION")
elif env == "staging" or env == "stg":
    from .staging import *  # noqa
    print("📦 Окружение: STAGING")
else:
    from .local import *  # noqa
    print("📦 Окружение: LOCAL (localhost)")
