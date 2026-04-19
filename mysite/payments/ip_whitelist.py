"""IP-whitelist для YooKassa webhook.

YooKassa шлёт webhook-запросы только с известных IP-подсетей (указаны в
её документации). Дополнительная защита сверх verify-through-API.

Выключается через settings.YOOKASSA_WEBHOOK_STRICT_IP = False — полезно
для локальных тестов (ngrok, staging) и CI.
"""
import ipaddress
import logging
from functools import wraps

from django.conf import settings
from django.http import HttpResponseForbidden

logger = logging.getLogger(__name__)

# Актуальные на 2026 IP-блоки YooKassa (см. официальную доку).
# Список задан тупо как константы — обновляется вручную при изменении
# у провайдера (максимум раз в несколько лет).
YOOKASSA_ALLOWED_NETWORKS = [
    ipaddress.ip_network("185.71.76.0/27"),
    ipaddress.ip_network("185.71.77.0/27"),
    ipaddress.ip_network("77.75.153.0/25"),
    ipaddress.ip_network("77.75.154.128/25"),
    ipaddress.ip_network("77.75.156.11/32"),
    ipaddress.ip_network("77.75.156.35/32"),
    ipaddress.ip_network("2a02:5180::/32"),
]


def _get_client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def yookassa_ip_only(view_func):
    """Отказывает с 403, если IP клиента не в YOOKASSA_ALLOWED_NETWORKS.

    Проверка отключается флагом settings.YOOKASSA_WEBHOOK_STRICT_IP=False.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not getattr(settings, "YOOKASSA_WEBHOOK_STRICT_IP", True):
            return view_func(request, *args, **kwargs)

        raw_ip = _get_client_ip(request)
        try:
            client_ip = ipaddress.ip_address(raw_ip)
        except ValueError:
            logger.warning("yookassa webhook: invalid client ip=%r", raw_ip)
            return HttpResponseForbidden("invalid ip")

        if not any(client_ip in net for net in YOOKASSA_ALLOWED_NETWORKS):
            logger.warning("yookassa webhook: ip %s not in whitelist", client_ip)
            return HttpResponseForbidden("ip not whitelisted")

        return view_func(request, *args, **kwargs)

    return wrapper
