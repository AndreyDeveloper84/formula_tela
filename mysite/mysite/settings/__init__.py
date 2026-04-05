"""
Автоматический выбор настроек на основе переменной окружения.

Приоритет:
1. DJANGO_SETTINGS_MODULE (если задана явно)
2. Иначе смотрит на DJANGO_ENV (сначала в окружении, потом в .env)
3. Fallback на local (для безопасности)
"""
import os as _os
from pathlib import Path as _Path

# Загружаем .env ДО того как читаем DJANGO_ENV,
# чтобы DJANGO_ENV=production из .env файла работал без правки systemd.
try:
    from dotenv import load_dotenv as _load_dotenv
    _settings_dir = _Path(__file__).resolve().parent          # .../mysite/settings
    _env_file = _settings_dir.parent.parent.parent / '.env'   # .../formula_tela/.env
    _load_dotenv(_env_file, override=False)                    # override=False: process env приоритетнее
except Exception:
    pass  # python-dotenv не установлен или .env нет — не страшно

# Пробуем определить окружение
env = _os.getenv("DJANGO_ENV", "local").lower()

# Выбираем правильный файл настроек
if env == "production" or env == "prod":
    from .production import *  # noqa
elif env == "staging" or env == "stg":
    from .staging import *  # noqa
else:
    from .local import *  # noqa
