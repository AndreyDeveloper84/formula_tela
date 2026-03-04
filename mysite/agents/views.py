"""
Views для посадочных страниц (LandingPage).
"""
import logging

from django.shortcuts import get_object_or_404, render

from agents.models import LandingPage
from website.templatetags.faq_tags import faq_items

logger = logging.getLogger(__name__)


def landing_page_view(request, slug: str):
    """
    Отдаёт опубликованную посадочную страницу по slug.

    Возвращает 404 если:
    - страница не найдена
    - страница существует но статус не 'published' (черновик, модерация)

    Логирует каждый просмотр для мониторинга.
    """
    landing = get_object_or_404(
        LandingPage.objects.select_related("service"),
        slug=slug,
        status=LandingPage.STATUS_PUBLISHED,
    )
    logger.info(
        "landing_page_view: slug='%s', landing_id=%s", slug, landing.pk
    )

    # Безопасные значения по умолчанию если блоки не заполнены
    blocks = list(landing.landing_blocks.filter(is_active=True).order_by("order"))
    intro_block = next((b for b in blocks if b.block_type == "text"), None)

    faq = []
    for block in blocks:
        if block.block_type == "faq":
            faq.extend(faq_items(block.content))

    media_items = []
    if landing.service_id:
        media_items = list(landing.service.media.filter(is_active=True).order_by("order"))

    context = {
        "landing": landing,
        "blocks": blocks,
        "faq": faq,
        "intro_block": intro_block,
        "media_items": media_items,
    }
    return render(request, "agents/landing_page.html", context)
