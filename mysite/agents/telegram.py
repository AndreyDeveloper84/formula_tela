import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def send_telegram(text: str) -> bool:
    """Отправить сообщение в Telegram-чат. Возвращает True при успехе."""
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("send_telegram: TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не настроены")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if not r.ok:
            logger.error("send_telegram HTTP %s: %s", r.status_code, r.text[:200])
        return r.ok
    except requests.RequestException as exc:
        logger.error("send_telegram error: %s", exc)
        return False
