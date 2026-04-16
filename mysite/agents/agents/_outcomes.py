"""
Хелпер для создания AgentRecommendationOutcome из рекомендаций агента.
"""
import logging

logger = logging.getLogger(__name__)


def create_outcomes(report, agent_type: str, items: list, title_key: str = "title"):
    """
    Создаёт AgentRecommendationOutcome записи из списка рекомендаций.

    Args:
        report: AgentReport instance
        agent_type: тип агента (AgentTask.OFFERS, etc.)
        items: список dict-рекомендаций
        title_key: ключ в dict для заголовка (по умолчанию "title")
    """
    from agents.models import AgentRecommendationOutcome

    created = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get(title_key, ""))[:300]
        if not title:
            title = str(item.get("description", str(item)))[:300]
        try:
            AgentRecommendationOutcome.objects.create(
                report=report,
                agent_type=agent_type,
                title=title,
                body=item,
            )
            created += 1
        except Exception as exc:
            logger.warning("create_outcomes: ошибка — %s", exc)

    if created:
        logger.info("create_outcomes: создано %d рекомендаций (%s)", created, agent_type)
    return created
