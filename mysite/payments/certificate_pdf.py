"""Генерация PDF-сертификата через WeasyPrint.

Две страницы:
  1. Лицевая: СЕРТИФИКАТ, состав комплекса / номинал, Кому/От кого, срок.
  2. Оборотная: телефон, адрес, список направлений, юридический текст.
"""
import logging

from django.conf import settings
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def generate_certificate_pdf(cert, order) -> bytes:
    """Рендерит HTML-шаблон сертификата и возвращает PDF-байты.

    Raises:
        Exception: если WeasyPrint недоступен или рендер упал.
    """
    import weasyprint  # lazy import — не ломает сервер если не установлен

    base_url = getattr(settings, "SITE_BASE_URL", "https://formulatela58.ru")

    theme_key = cert.theme or (
        cert.bundle.certificate_theme if cert.bundle else "pink"
    )

    html_string = render_to_string(
        "certificates/certificate_pdf.html",
        {
            "cert": cert,
            "order": order,
            "bundle": cert.bundle,
            "theme_key": theme_key,
        },
    )
    return weasyprint.HTML(string=html_string, base_url=base_url).write_pdf()
