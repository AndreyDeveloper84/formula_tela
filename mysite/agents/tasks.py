import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="agents.tasks.run_daily_agents", bind=True, max_retries=2)
def run_daily_agents(self):
    """
    Запускается Celery Beat ежедневно в 9:00.
    Supervisor решает запуск analytics/offers.
    AnalyticsBudgetAgent запускается всегда (воронка + Метрика + Директ).
    """
    logger.info("run_daily_agents: старт")
    try:
        from agents.agents.supervisor import SupervisorAgent
        SupervisorAgent().run()

        from agents.agents.analytics_budget import AnalyticsBudgetAgent
        AnalyticsBudgetAgent().run()

        logger.info("run_daily_agents: завершён")
    except Exception as exc:
        logger.exception("run_daily_agents: ошибка — %s", exc)
        raise self.retry(exc=exc, countdown=300)


@shared_task(name="agents.tasks.run_weekly_agents", bind=True, max_retries=2)
def run_weekly_agents(self):
    """
    Запускается Celery Beat каждый понедельник в 08:00.
    Порядок: OfferPackages → SMM → SEO → Supervisor.weekly_run (синтез бэклога).
    """
    logger.info("run_weekly_agents: старт")
    try:
        from agents.agents.offer_packages import OfferPackagesAgent
        OfferPackagesAgent().run()

        from agents.agents.smm_growth import SMMGrowthAgent
        SMMGrowthAgent().run()

        from agents.agents.seo_landing import SEOLandingAgent
        SEOLandingAgent().run()

        from agents.agents.supervisor import SupervisorAgent
        SupervisorAgent().weekly_run()

        logger.info("run_weekly_agents: завершён")
    except Exception as exc:
        logger.exception("run_weekly_agents: ошибка — %s", exc)
        raise self.retry(exc=exc, countdown=300)
