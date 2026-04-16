"""
Views для посадочных страниц (LandingPage) и API мониторинга.
"""
import datetime
import logging

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from agents.models import AgentTask, LandingPage

logger = logging.getLogger(__name__)

# SLA для агентов
_DAILY_SLA_HOURS = 36
_WEEKLY_SLA_DAYS = 10
_STUCK_HOURS = 1

_DAILY_TYPES = {"analytics", "offers", "analytics_budget"}
_WEEKLY_TYPES = {"offer_packages", "smm_growth", "seo_landing", "trend_scout"}


@require_GET
def agents_health(request):
    """
    GET /api/agents/health/ — JSON endpoint мониторинга агентов.

    Возвращает:
    - status: healthy / degraded / unhealthy
    - agents: последний запуск каждого агента
    - stuck_tasks: количество зависших
    - error_rate_24h: доля ошибок за 24 часа
    """
    now = timezone.now()
    day_ago = now - datetime.timedelta(hours=24)

    agents_info = {}
    all_types = dict(AgentTask.AGENT_CHOICES)
    stale_count = 0

    for atype in all_types:
        last = (
            AgentTask.objects.filter(agent_type=atype)
            .order_by("-created_at")
            .first()
        )
        if last:
            is_daily = atype in _DAILY_TYPES
            sla_delta = (
                datetime.timedelta(hours=_DAILY_SLA_HOURS) if is_daily
                else datetime.timedelta(days=_WEEKLY_SLA_DAYS)
            )
            stale = (now - last.created_at) > sla_delta
            if stale:
                stale_count += 1
            agents_info[atype] = {
                "last_run": last.created_at.isoformat(),
                "status": last.status,
                "stale": stale,
            }
        else:
            agents_info[atype] = {
                "last_run": None,
                "status": "never",
                "stale": True,
            }
            stale_count += 1

    # Stuck tasks
    stuck_threshold = now - datetime.timedelta(hours=_STUCK_HOURS)
    stuck_tasks = AgentTask.objects.filter(
        status=AgentTask.RUNNING,
        created_at__lt=stuck_threshold,
    ).count()

    # Error rate 24h
    recent_total = AgentTask.objects.filter(created_at__gte=day_ago).count()
    recent_errors = AgentTask.objects.filter(
        created_at__gte=day_ago, status=AgentTask.ERROR
    ).count()
    error_rate = round(recent_errors / recent_total, 2) if recent_total else 0.0

    # Overall status
    if stuck_tasks > 0 or error_rate > 0.3:
        status = "unhealthy"
    elif stale_count > 0 or error_rate > 0.1:
        status = "degraded"
    else:
        status = "healthy"

    return JsonResponse({
        "status": status,
        "agents": agents_info,
        "stuck_tasks": stuck_tasks,
        "error_rate_24h": error_rate,
    })


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
