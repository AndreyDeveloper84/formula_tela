"""Централизованные уведомления о заявках — Telegram + email.

Вызывается из всех endpoint'ов, где создаётся заявка/заказ:
api_wizard_booking, api_bundle_request, api_certificate_request и будущие.

- Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID из окружения
- Email:    список получателей из SiteSettings.notification_emails
            (редактируется в админке), fallback на ADMIN_NOTIFICATION_EMAIL
"""
import logging

import requests as http_requests
from django.conf import settings as django_settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_notification_telegram(text: str) -> bool:
    """Отправляет текст в Telegram чат администратора.

    Ничего не делает, если TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID не заданы
    или если POST упал (ошибка логируется, исключение не пробрасывается).
    Возвращает True при успешной отправке.
    """
    token = getattr(django_settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(django_settings, "TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False

    try:
        http_requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
        return True
    except Exception as e:
        logger.warning(f"Telegram notification failed: {e}")
        return False


def get_notification_recipients() -> list[str]:
    """Список email-адресов для уведомлений о заявках.

    Приоритет — SiteSettings.notification_emails (редактируется в админке),
    fallback на ADMIN_NOTIFICATION_EMAIL из окружения.
    """
    from services_app.models import SiteSettings

    site = SiteSettings.objects.first()
    if site:
        recipients = site.get_notification_emails()
        if recipients:
            return recipients

    fallback = getattr(django_settings, "ADMIN_NOTIFICATION_EMAIL", "")
    return [fallback] if fallback else []


def send_notification_email(subject: str, message: str) -> bool:
    """Отправляет email администраторам.

    Получатели берутся из SiteSettings.notification_emails (через
    get_notification_recipients). Если список пуст — ничего не делает.
    Не пробрасывает исключения.
    """
    recipients = get_notification_recipients()
    if not recipients:
        return False

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=None,
            recipient_list=recipients,
            fail_silently=True,
        )
        return True
    except Exception as e:
        logger.error(f"Email notification failed: {e}")
        return False
