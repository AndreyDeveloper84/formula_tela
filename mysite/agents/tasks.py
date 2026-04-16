import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="agents.tasks.run_daily_agents", bind=True, max_retries=2)
def run_daily_agents(self):
    """
    Запускается Celery Beat ежедневно в 9:00.
    Supervisor решает запуск analytics/offers.
    AnalyticsBudgetAgent запускается всегда (воронка + Метрика + Директ).
    После завершения — обновляет DailyMetric с timing данными.
    """
    import datetime
    import time as _time

    logger.info("run_daily_agents: старт")
    start = _time.monotonic()
    try:
        from agents.agents.supervisor import SupervisorAgent
        SupervisorAgent().run()

        from agents.agents.analytics_budget import AnalyticsBudgetAgent
        AnalyticsBudgetAgent().run()

        logger.info("run_daily_agents: завершён")
    except Exception as exc:
        logger.exception("run_daily_agents: ошибка — %s", exc)
        raise self.retry(exc=exc, countdown=300)
    finally:
        # Обновляем DailyMetric с данными о запусках агентов
        try:
            from agents.models import AgentTask, DailyMetric
            today = datetime.date.today()
            today_tasks = AgentTask.objects.filter(created_at__date=today)
            agent_runs = {}
            total_duration = 0
            error_count = 0
            for t in today_tasks:
                dur = t.duration_seconds or 0
                agent_runs[t.agent_type] = {
                    "duration_s": dur,
                    "status": t.status,
                }
                total_duration += dur
                if t.status == AgentTask.ERROR:
                    error_count += 1
            DailyMetric.objects.filter(date=today).update(
                agent_runs=agent_runs,
                total_duration=total_duration,
                error_count=error_count,
            )
        except Exception as exc:
            logger.debug("run_daily_agents: не удалось обновить DailyMetric timing — %s", exc)


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


@shared_task(name="agents.tasks.collect_trends", bind=True, max_retries=1)
def collect_trends(self):
    """Еженедельный сбор трендов: Яндекс подсказки + VK группы → GPT-анализ."""
    logger.info("collect_trends: старт")
    try:
        from agents.agents.trend_scout import TrendScoutAgent
        TrendScoutAgent().run()
        logger.info("collect_trends: завершён")
    except Exception as exc:
        logger.exception("collect_trends: ошибка — %s", exc)
        raise self.retry(exc=exc, countdown=300)


@shared_task(name="agents.tasks.collect_rank_snapshots", bind=True, max_retries=1)
def collect_rank_snapshots(self):
    """
    Ежедневный сбор данных Яндекс.Вебмастера и агрегация по кластерам.

    Алгоритм:
    1. get_query_stats(today-3, today) — Вебмастер имеет задержку 2-3 дня.
    2. Для каждого активного SeoKeywordCluster:
       - Сопоставляет cluster.keywords с query stats (case-insensitive exact match).
       - Агрегирует: sum(clicks), sum(impressions), weighted avg(ctr), weighted avg(position).
    3. SeoClusterSnapshot.objects.update_or_create(cluster, date=today, defaults=...).
    4. Цепочка: запускает analyze_rank_changes.delay().

    При ошибке API — логирует warning, возвращает без retry.
    """
    import datetime
    from agents.integrations.yandex_webmaster import (
        YandexWebmasterClient, YandexWebmasterError,
    )
    from agents.models import SeoKeywordCluster, SeoClusterSnapshot

    logger.info("collect_rank_snapshots: старт")
    today = datetime.date.today()
    date_from = (today - datetime.timedelta(days=3)).isoformat()
    date_to = today.isoformat()

    # Шаг 1: загружаем данные из Вебмастера
    try:
        wm = YandexWebmasterClient.from_settings()
    except YandexWebmasterError as exc:
        logger.warning(
            "collect_rank_snapshots: Вебмастер не настроен — %s", exc
        )
        return

    query_stats = wm.get_query_stats(date_from, date_to, limit=500)
    if not query_stats:
        logger.warning("collect_rank_snapshots: Вебмастер вернул пустые данные")
        return

    # Шаг 2: индекс по нормализованным запросам
    stats_by_query = {}
    for qs in query_stats:
        key = qs["query"].lower().strip()
        if key:
            stats_by_query[key] = qs

    # Шаг 3: итерация по активным кластерам
    clusters = SeoKeywordCluster.objects.filter(is_active=True)
    snapshots_created = 0

    for cluster in clusters:
        matched = []
        for kw in (cluster.keywords or []):
            normalized = kw.lower().strip()
            if normalized in stats_by_query:
                matched.append(stats_by_query[normalized])

        matched_count = len(matched)
        if matched_count == 0:
            # Zero-snapshot — кластер без данных
            SeoClusterSnapshot.objects.update_or_create(
                cluster=cluster,
                date=today,
                defaults={
                    "total_clicks": 0,
                    "total_impressions": 0,
                    "avg_ctr": 0.0,
                    "avg_position": 0.0,
                    "matched_queries": 0,
                },
            )
            continue

        total_clicks = sum(m["clicks"] for m in matched)
        total_impressions = sum(m["impressions"] for m in matched)

        # Взвешенное среднее по показам (более точно для SEO)
        if total_impressions > 0:
            w_avg_ctr = sum(
                m["ctr"] * m["impressions"] for m in matched
            ) / total_impressions
            w_avg_position = sum(
                m["avg_position"] * m["impressions"] for m in matched
            ) / total_impressions
        else:
            # Fallback — простое среднее
            w_avg_ctr = sum(m["ctr"] for m in matched) / matched_count
            w_avg_position = sum(
                m["avg_position"] for m in matched
            ) / matched_count

        SeoClusterSnapshot.objects.update_or_create(
            cluster=cluster,
            date=today,
            defaults={
                "total_clicks": total_clicks,
                "total_impressions": total_impressions,
                "avg_ctr": round(w_avg_ctr, 4),
                "avg_position": round(w_avg_position, 2),
                "matched_queries": matched_count,
            },
        )
        snapshots_created += 1

    logger.info(
        "collect_rank_snapshots: завершён — %d кластеров, %d с данными",
        clusters.count(), snapshots_created,
    )

    # Шаг 4: цепочка — анализ просадок
    analyze_rank_changes.delay()


@shared_task(name="agents.tasks.analyze_rank_changes", bind=True, max_retries=2)
def analyze_rank_changes(self):
    """
    Анализирует тренды позиций по SEO-кластерам.

    Сравнивает снапшоты сегодня vs 7 дней назад.

    Алерт создаётся при:
    - Падение кликов: (current - previous) / previous <= -20%  -> type="click_drop"
    - Ухудшение позиции: current - previous >= 3 места         -> type="position_drop"

    При наличии алертов:
    1. Создаёт SeoTask (get_or_create, без дублей) в БД для панели администратора
    2. Отправляет Telegram-алерт через send_seo_alert()

    Запускается автоматически из collect_rank_snapshots.delay().
    """
    import datetime
    from agents.models import SeoClusterSnapshot, SeoTask
    from agents.telegram import send_seo_alert

    # Пороги
    CLICK_DROP_THRESHOLD = -0.20     # -20%
    POSITION_DROP_THRESHOLD = 3.0    # 3 позиции вниз (рост числа = ухудшение)

    logger.info("analyze_rank_changes: старт")
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)

    # Загружаем снапшоты сегодня и неделю назад
    today_snaps = {
        s.cluster_id: s
        for s in SeoClusterSnapshot.objects.filter(date=today).select_related("cluster")
    }
    week_ago_snaps = {
        s.cluster_id: s
        for s in SeoClusterSnapshot.objects.filter(date=week_ago)
    }

    if not today_snaps:
        logger.info(
            "analyze_rank_changes: нет снапшотов за %s — пропускаем", today
        )
        return

    alerts = []           # список алертов для Telegram
    tasks_created = 0

    for cluster_id, snap_now in today_snaps.items():
        snap_prev = week_ago_snaps.get(cluster_id)
        if not snap_prev:
            continue  # нет данных прошлой недели — не с чем сравнивать

        cluster = snap_now.cluster

        # ── Просадка кликов ───────────────────────────────────────────
        if snap_prev.total_clicks > 0:
            click_change = (
                (snap_now.total_clicks - snap_prev.total_clicks)
                / snap_prev.total_clicks
            )
            if click_change <= CLICK_DROP_THRESHOLD:
                alert = {
                    "cluster": cluster.name,
                    "type": "click_drop",
                    "change": round(click_change * 100, 1),   # в процентах, отрицательный
                    "current": float(snap_now.total_clicks),
                    "previous": float(snap_prev.total_clicks),
                    "url": cluster.target_url,
                }
                alerts.append(alert)

                # SeoTask для панели администратора (с эскалацией)
                existing = SeoTask.objects.filter(
                    task_type=SeoTask.TYPE_UPDATE_META,
                    target_url=cluster.target_url,
                    status__in=[SeoTask.STATUS_OPEN, SeoTask.STATUS_IN_PROGRESS],
                ).first()
                if existing:
                    existing.priority = SeoTask.PRIORITY_HIGH
                    existing.escalation_count += 1
                    existing.description += (
                        f"\n\n[{today}] Повторное падение кликов: "
                        f"{snap_prev.total_clicks} → {snap_now.total_clicks} "
                        f"({click_change:+.0%})"
                    )
                    existing.payload = alert
                    existing.save(update_fields=[
                        "priority", "escalation_count", "description", "payload",
                    ])
                    logger.warning(
                        "analyze_rank_changes: кластер '%s' — эскалация #%d, "
                        "падение кликов %+.0f%%",
                        cluster.name, existing.escalation_count,
                        click_change * 100,
                    )
                else:
                    SeoTask.objects.create(
                        task_type=SeoTask.TYPE_UPDATE_META,
                        target_url=cluster.target_url,
                        title=(
                            f"Падение кликов: {cluster.name} "
                            f"({click_change:+.0%} за неделю)"
                        ),
                        description=(
                            f"Кластер '{cluster.name}': клики упали с "
                            f"{snap_prev.total_clicks} до {snap_now.total_clicks} "
                            f"({click_change:+.0%}). "
                            f"Проверь позиции и мета-теги: {cluster.target_url}"
                        ),
                        priority=SeoTask.PRIORITY_HIGH,
                        payload=alert,
                    )
                    tasks_created += 1
                    logger.warning(
                        "analyze_rank_changes: кластер '%s' — падение кликов %+.0f%%",
                        cluster.name, click_change * 100,
                    )

        # ── Просадка позиции ──────────────────────────────────────────
        if snap_prev.avg_position > 0 and snap_now.avg_position > 0:
            pos_change = snap_now.avg_position - snap_prev.avg_position
            if pos_change >= POSITION_DROP_THRESHOLD:
                alert = {
                    "cluster": cluster.name,
                    "type": "position_drop",
                    "change": round(pos_change, 1),   # положительный = ухудшение
                    "current": round(snap_now.avg_position, 1),
                    "previous": round(snap_prev.avg_position, 1),
                    "url": cluster.target_url,
                }
                alerts.append(alert)

                existing = SeoTask.objects.filter(
                    task_type=SeoTask.TYPE_UPDATE_META,
                    target_url=cluster.target_url,
                    status__in=[SeoTask.STATUS_OPEN, SeoTask.STATUS_IN_PROGRESS],
                ).first()
                if existing:
                    if pos_change >= POSITION_DROP_THRESHOLD + 2:
                        existing.priority = SeoTask.PRIORITY_HIGH
                    existing.escalation_count += 1
                    existing.description += (
                        f"\n\n[{today}] Повторная просадка позиции: "
                        f"{snap_prev.avg_position:.1f} → {snap_now.avg_position:.1f} "
                        f"(+{pos_change:.1f} мест)"
                    )
                    existing.payload = alert
                    existing.save(update_fields=[
                        "priority", "escalation_count", "description", "payload",
                    ])
                    logger.warning(
                        "analyze_rank_changes: кластер '%s' — эскалация #%d, "
                        "просадка позиции +%.1f мест",
                        cluster.name, existing.escalation_count, pos_change,
                    )
                else:
                    SeoTask.objects.create(
                        task_type=SeoTask.TYPE_UPDATE_META,
                        target_url=cluster.target_url,
                        title=(
                            f"Просадка позиций: {cluster.name} "
                            f"(+{pos_change:.1f} мест)"
                        ),
                        description=(
                            f"Кластер '{cluster.name}': позиция ухудшилась "
                            f"с {snap_prev.avg_position:.1f} до "
                            f"{snap_now.avg_position:.1f} (+{pos_change:.1f}). "
                            f"Страница: {cluster.target_url}"
                        ),
                        priority=SeoTask.PRIORITY_MEDIUM,
                        payload=alert,
                    )
                    tasks_created += 1
                    logger.warning(
                        "analyze_rank_changes: кластер '%s' — просадка позиции +%.1f мест",
                        cluster.name, pos_change,
                    )

    # ── Telegram-алерт ────────────────────────────────────────────────
    if alerts:
        send_seo_alert(alerts)
        logger.info(
            "analyze_rank_changes: отправлен алерт — %d событий", len(alerts)
        )
    else:
        logger.info(
            "analyze_rank_changes: просадок не обнаружено, алерт не отправляется"
        )

    logger.info(
        "analyze_rank_changes: завершён — %d кластеров, %d алертов, %d новых задач",
        len(today_snaps), len(alerts), tasks_created,
    )


@shared_task(name="agents.tasks.generate_missing_landings", bind=True, max_retries=1)
def generate_missing_landings(self):
    """
    Еженедельно (воскресенье 22:00) генерирует черновики лендингов
    для кластеров без draft/published страниц.
    Максимум 3 страницы за запуск (лимит API + модерация).
    """
    from agents.agents.landing_generator import LandingPageGenerator, LandingGeneratorError
    from agents.models import LandingPage, SeoClusterSnapshot, SeoKeywordCluster

    logger.info("generate_missing_landings: старт")

    # Кластеры, у которых уже есть лендинг (draft, review или published)
    clusters_with_landing = set(
        LandingPage.objects.filter(
            status__in=[
                LandingPage.STATUS_DRAFT,
                LandingPage.STATUS_REVIEW,
                LandingPage.STATUS_PUBLISHED,
            ],
            cluster__isnull=False,
        ).values_list("cluster_id", flat=True)
    )

    # Активные кластеры без лендинга
    candidates = SeoKeywordCluster.objects.filter(
        is_active=True,
    ).exclude(pk__in=clusters_with_landing)

    if not candidates.exists():
        logger.info("generate_missing_landings: все кластеры покрыты лендингами")
        return

    # Приоритизация: по impressions из последнего SeoClusterSnapshot
    import datetime
    recent_date = datetime.date.today() - datetime.timedelta(days=7)
    snapshot_impressions = dict(
        SeoClusterSnapshot.objects.filter(
            cluster__in=candidates,
            date__gte=recent_date,
        ).values_list("cluster_id", "total_impressions")
    )
    candidates_sorted = sorted(
        candidates,
        key=lambda c: snapshot_impressions.get(c.pk, 0),
        reverse=True,
    )

    generator = LandingPageGenerator()
    generated = 0

    for cluster in candidates_sorted[:3]:  # максимум 3 за запуск
        try:
            landing = generator.generate_landing(cluster)
            generated += 1
            logger.info(
                "generate_missing_landings: создан лендинг '%s' для кластера '%s'",
                landing.slug, cluster.name,
            )
        except LandingGeneratorError as exc:
            logger.warning(
                "generate_missing_landings: кластер '%s' — %s",
                cluster.name, exc,
            )
        except Exception as exc:
            logger.exception(
                "generate_missing_landings: кластер '%s' — %s",
                cluster.name, exc,
            )

    logger.info(
        "generate_missing_landings: завершён — %d из %d кандидатов",
        generated, len(candidates_sorted),
    )
