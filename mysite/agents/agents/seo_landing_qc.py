"""SEOLandingQCAgent — проверка качества LandingPage перед публикацией.

Паттерн Pipeline: последовательно запускает QC-проверки (Strategy classes
из qc_checks.py), собирает результаты, решает ready-to-publish / reject.

Правило CLAUDE.md: агенты НИКОГДА не публикуют контент автоматически.
Прошедшие QC → status=review + SeoTask(TYPE_CREATE_LANDING, HIGH) «готов к публикации»,
человек публикует вручную через admin.
Не прошедшие → status=review + SeoTask(TYPE_FIX_TECHNICAL, HIGH), Telegram-алерт.
"""
import logging
from dataclasses import asdict

from django.utils import timezone

from agents.agents._lifecycle import ensure_task_finalized
from agents.agents._outcomes import create_outcomes
from agents.agents.qc_checks import (
    BaseQCCheck,
    ContentDuplicateCheck,
    InternalLinksCheck,
    PublishedAtReadyCheck,
    RequiredBlocksCheck,
    UniqueH1Check,
    UniqueSlugCheck,
)
from agents.models import AgentReport, AgentTask, LandingPage, SeoTask
from agents.telegram import send_telegram

logger = logging.getLogger(__name__)


class SEOLandingQCAgent:
    """Оркестратор QC-проверок для LandingPage.

    Usage:
        agent = SEOLandingQCAgent()
        agent.run(task)  # task = AgentTask(agent_type="landing_qc")
    """

    DEFAULT_CHECKS: list[BaseQCCheck] = [
        UniqueH1Check(),
        UniqueSlugCheck(),
        PublishedAtReadyCheck(),
        RequiredBlocksCheck(),
        InternalLinksCheck(),
        ContentDuplicateCheck(),
    ]

    def __init__(self, checks: list[BaseQCCheck] | None = None):
        self.checks = checks if checks is not None else self.DEFAULT_CHECKS

    def run_qc(self, landing: LandingPage) -> list:
        """Запустить все checks для одного лендинга."""
        return [check.run(landing) for check in self.checks]

    @staticmethod
    def _ensure_task(task_type: str, target_url: str, title: str, description: str) -> SeoTask:
        # filter().first() вместо get_or_create(status__in=...) — последний падает
        # с MultipleObjectsReturned если в БД уже 2+ открытые задачи с тем же URL.
        existing = SeoTask.objects.filter(
            task_type=task_type,
            target_url=target_url,
            status__in=[SeoTask.STATUS_OPEN, SeoTask.STATUS_IN_PROGRESS],
        ).first()
        if existing:
            return existing
        return SeoTask.objects.create(
            task_type=task_type,
            target_url=target_url,
            title=title,
            description=description,
            priority=SeoTask.PRIORITY_HIGH,
        )

    def is_publishable(self, results: list) -> bool:
        """True если все critical checks прошли."""
        return not any(
            r.severity == "critical" and not r.passed
            for r in results
        )

    def run(self, task: AgentTask):
        """Main entry point. Проверяет все draft/review LandingPage."""
        task.status = AgentTask.RUNNING
        task.save(update_fields=["status"])

        try:
            landings = list(
                LandingPage.objects.filter(
                    status__in=[LandingPage.STATUS_DRAFT, "review"]
                ).order_by("slug")
            )

            if not landings:
                logger.info("SEOLandingQCAgent: нет draft/review лендингов для проверки")
                task.status = AgentTask.DONE
                task.finished_at = timezone.now()
                task.save(update_fields=["status", "finished_at"])
                return

            ready_count = 0
            review_count = 0
            report_items = []

            for landing in landings:
                results = self.run_qc(landing)
                publishable = self.is_publishable(results)
                failed_checks = [r for r in results if not r.passed]
                passed_checks = [r for r in results if r.passed]

                if publishable:
                    if landing.status != LandingPage.STATUS_REVIEW:
                        landing.status = LandingPage.STATUS_REVIEW
                        landing.save(update_fields=["status"])
                    ready_count += 1

                    self._ensure_task(
                        task_type=SeoTask.TYPE_CREATE_LANDING,
                        target_url=f"/{landing.slug}/",
                        title=f"Готов к публикации: /{landing.slug}/",
                        description=(
                            f"QC пройден ({len(passed_checks)}/{len(results)} проверок). "
                            f"Страница: /admin/agents/landingpage/{landing.pk}/change/\n"
                            "Проверьте контент вручную и нажмите «Опубликовать»."
                        ),
                    )

                    logger.info(
                        "SEOLandingQCAgent: /%s/ → review ready-to-publish (%d/%d checks ok)",
                        landing.slug, len(passed_checks), len(results),
                    )
                else:
                    if landing.status != LandingPage.STATUS_REVIEW:
                        landing.status = LandingPage.STATUS_REVIEW
                        landing.save(update_fields=["status"])
                    review_count += 1

                    self._ensure_task(
                        task_type=SeoTask.TYPE_FIX_TECHNICAL,
                        target_url=f"/{landing.slug}/",
                        title=f"QC failed: /{landing.slug}/",
                        description="\n".join(
                            f"- [{r.severity}] {r.check_name}: {r.message}"
                            for r in failed_checks
                        ),
                    )

                    logger.warning(
                        "SEOLandingQCAgent: /%s/ → review (%d failed: %s)",
                        landing.slug,
                        len(failed_checks),
                        ", ".join(r.check_name for r in failed_checks),
                    )

                report_items.append({
                    "slug": landing.slug,
                    "publishable": publishable,
                    "checks": [asdict(r) for r in results],
                })

            # AgentReport
            summary = (
                f"QC проверено: {len(landings)} лендингов. "
                f"Готовы к публикации: {ready_count}. На доработку: {review_count}."
            )
            recommendations = []
            for item in report_items:
                if not item["publishable"]:
                    failed = [c for c in item["checks"] if not c["passed"]]
                    recommendations.append({
                        "title": f"/{item['slug']}/ — не прошёл QC",
                        "details": failed,
                    })

            report = AgentReport.objects.create(
                task=task,
                summary=summary,
                recommendations=recommendations,
            )
            create_outcomes(report, "landing_qc", recommendations)

            # Telegram
            tg_lines = [f"🔍 SEO QC: {len(landings)} лендингов проверено\n"]
            if ready_count:
                tg_lines.append(
                    f"✅ Готовы к публикации: {ready_count} (требуется ручная модерация в admin)"
                )
            if review_count:
                tg_lines.append(f"⚠️ На доработку: {review_count}")
                for item in report_items:
                    if not item["publishable"]:
                        failed = [c for c in item["checks"] if not c["passed"]]
                        issues = ", ".join(c["check_name"] for c in failed)
                        tg_lines.append(f"  • /{item['slug']}/: {issues}")
            send_telegram("\n".join(tg_lines))

            task.status = AgentTask.DONE
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "finished_at"])

        except Exception:
            ensure_task_finalized(task)
            raise
