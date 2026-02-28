"""
Views для посадочных страниц (LandingPage).
"""
import logging

from django.shortcuts import get_object_or_404, render

from agents.models import LandingPage

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
        LandingPage,
        slug=slug,
        status=LandingPage.STATUS_PUBLISHED,
    )
    logger.info(
        "landing_page_view: slug='%s', landing_id=%s", slug, landing.pk
    )

    # Безопасные значения по умолчанию если блоки не заполнены
    blocks = landing.blocks or {}

    context = {
        "landing": landing,
        "blocks":  blocks,
        "faq":     blocks.get("faq", []),
    }
    return render(request, "agents/landing_page.html", context)
