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

        from agents.agents.seo_growth import SEOGrowthAgent
        SEOGrowthAgent().run()

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


@shared_task(
    name="agents.tasks.collect_rank_snapshots",
    bind=True,
    max_retries=1,
    soft_time_limit=90,
    time_limit=120,
)
def collect_rank_snapshots(self):
    """
    Ежедневный сбор данных Яндекс.Вебмастера и агрегация по кластерам.

    Алгоритм:
    1. get_query_stats(today-7, today) — Вебмастер имеет задержку 2-3 дня,
       окно 7 дней гарантирует наличие данных.
    2. Для каждого активного SeoKeywordCluster:
       - Сопоставляет cluster.keywords с query stats (case-insensitive exact match).
       - Агрегирует: sum(clicks), sum(impressions), weighted avg(ctr), weighted avg(position).
    3. SeoClusterSnapshot.objects.update_or_create(cluster, date=today, defaults=...).
    4. Цепочка: запускает analyze_rank_changes.delay().

    soft_time_limit=90с — убивает задачу если прокси/API зависает,
    чтобы не блокировать worker slot для run_daily_agents в 09:00.

    При ошибке API — логирует warning, возвращает без retry.
    """
    import datetime
    from agents.integrations.yandex_webmaster import (
        YandexWebmasterClient, YandexWebmasterError,
    )
    from agents.models import SeoKeywordCluster, SeoClusterSnapshot

    logger.info("collect_rank_snapshots: старт")
    today = datetime.date.today()
    date_from = (today - datetime.timedelta(days=7)).isoformat()
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
                    from django.db.models import F
                    existing.priority = SeoTask.PRIORITY_HIGH
                    existing.escalation_count = F('escalation_count') + 1
                    existing.description += (
                        f"\n\n[{today}] Повторное падение кликов: "
                        f"{snap_prev.total_clicks} → {snap_now.total_clicks} "
                        f"({click_change:+.0%})"
                    )
                    existing.payload = alert
                    existing.save(update_fields=[
                        "priority", "escalation_count", "description", "payload",
                    ])
                    existing.refresh_from_db(fields=["escalation_count"])
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
                    from django.db.models import F
                    if pos_change >= POSITION_DROP_THRESHOLD + 2:
                        existing.priority = SeoTask.PRIORITY_HIGH
                    existing.escalation_count = F('escalation_count') + 1
                    existing.description += (
                        f"\n\n[{today}] Повторная просадка позиции: "
                        f"{snap_prev.avg_position:.1f} → {snap_now.avg_position:.1f} "
                        f"(+{pos_change:.1f} мест)"
                    )
                    existing.payload = alert
                    existing.save(update_fields=[
                        "priority", "escalation_count", "description", "payload",
                    ])
                    existing.refresh_from_db(fields=["escalation_count"])
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
    errors = []
    total = min(len(candidates_sorted), 3)

    for cluster in candidates_sorted[:3]:  # максимум 3 за запуск
        try:
            landing = generator.generate_landing(cluster)
            generated += 1
            logger.info(
                "generate_missing_landings: создан лендинг '%s' для кластера '%s'",
                landing.slug, cluster.name,
            )
        except LandingGeneratorError as exc:
            errors.append((cluster.name, str(exc)))
            logger.warning(
                "generate_missing_landings: кластер '%s' — %s",
                cluster.name, exc,
            )
        except Exception as exc:
            errors.append((cluster.name, str(exc)))
            logger.exception(
                "generate_missing_landings: кластер '%s' — %s",
                cluster.name, exc,
            )

    logger.info(
        "generate_missing_landings: завершён — %d из %d кандидатов",
        generated, total,
    )

    if errors:
        from agents.telegram import send_telegram
        details = "\n".join(f"• {name}: {err[:100]}" for name, err in errors)
        send_telegram(
            f"⚠️ generate_missing_landings: {len(errors)} из {total} ошибок\n\n"
            f"{details}"
        )


@shared_task(name="agents.tasks.collect_retention_metrics", bind=True, max_retries=1)
def collect_retention_metrics(self):
    """
    Ежедневный расчёт метрик удержания клиентов.

    Данные: 180 дней YClients записей, группировка по клиентам.
    Расписание: 08:00 ежедневно (между SEO-снапшотами 07:00 и агентами 09:00).
    """
    import datetime
    import time as _time
    from collections import defaultdict

    from agents.agents._revenue import extract_record_revenue
    from agents.models import RetentionSnapshot
    from agents.telegram import send_retention_report, send_retention_summary

    logger.info("collect_retention_metrics: старт")
    start = _time.monotonic()
    today = datetime.date.today()
    period_days = 180
    period_start = today - datetime.timedelta(days=period_days)

    # ── 1. Fetch YClients records (paginated) ────────────────────────
    try:
        from services_app.yclients_api import get_yclients_api
        api = get_yclients_api()
    except Exception as exc:
        logger.error("collect_retention_metrics: YClients недоступен: %s", exc)
        from agents.telegram import send_telegram
        send_telegram(f"⚠️ collect_retention_metrics: YClients недоступен\n{exc}")
        return

    all_records = []
    page = 1
    max_pages = 20
    while page <= max_pages:
        try:
            batch = api.get_records(
                start_date=str(period_start),
                end_date=str(today),
                count=200,
                page=page,
            )
        except Exception as exc:
            logger.warning("collect_retention_metrics: page %d error: %s", page, exc)
            break
        if not batch:
            break
        all_records.extend(batch)
        if len(batch) < 200:
            break
        page += 1
        _time.sleep(0.5)

    logger.info("collect_retention_metrics: получено %d записей за %d дней", len(all_records), period_days)

    if not all_records:
        logger.warning("collect_retention_metrics: нет записей — пропускаем")
        return

    # ── 2. Group by client ───────────────────────────────────────────
    clients = defaultdict(lambda: {
        "visits": [],
        "revenue": 0.0,
        "services": [],
    })
    for rec in all_records:
        client = rec.get("client") or {}
        client_key = client.get("id") or client.get("phone")
        if not client_key:
            continue
        visit_date = str(rec.get("date", ""))[:10]
        if not visit_date or len(visit_date) < 10:
            continue
        clients[client_key]["visits"].append(visit_date)
        clients[client_key]["revenue"] += extract_record_revenue(rec)
        for svc in rec.get("services") or []:
            name = svc.get("title") or svc.get("name") or "?"
            clients[client_key]["services"].append(name)

    # ── 3. Per-client aggregation ────────────────────────────────────
    total_clients = len(clients)
    if total_clients == 0:
        logger.warning("collect_retention_metrics: 0 уникальных клиентов")
        return

    new_count = 0
    returning_count = 0
    ret_30 = 0
    ret_60 = 0
    ret_90 = 0
    churn_count = 0
    total_visits = 0
    total_revenue = 0.0
    churned_services = defaultdict(int)
    cohort_buckets = defaultdict(lambda: defaultdict(set))

    for key, data in clients.items():
        dates = sorted(set(data["visits"]))
        first = datetime.date.fromisoformat(dates[0])
        last = datetime.date.fromisoformat(dates[-1])
        visit_count = len(dates)
        total_visits += visit_count
        total_revenue += data["revenue"]

        if visit_count == 1:
            new_count += 1
        else:
            returning_count += 1

        # Retention: second visit within N days of first
        if visit_count >= 2:
            second = datetime.date.fromisoformat(dates[1])
            gap = (second - first).days
            if gap <= 30:
                ret_30 += 1
            if gap <= 60:
                ret_60 += 1
            if gap <= 90:
                ret_90 += 1

        # Churn: last visit > 90 days ago
        if (today - last).days > 90:
            churn_count += 1
            for svc_name in set(data["services"]):
                churned_services[svc_name] += 1

        # Cohort matrix: month of first visit
        cohort_month = first.strftime("%Y-%m")
        for d_str in dates:
            visit_d = datetime.date.fromisoformat(d_str)
            month_offset = (visit_d.year - first.year) * 12 + (visit_d.month - first.month)
            cohort_buckets[cohort_month][f"m{month_offset}"].add(key)

    # ── 4. Compute aggregates ────────────────────────────────────────
    months_in_period = max(period_days / 30.0, 1)
    avg_frequency = (total_visits / total_clients) / months_in_period
    avg_check = total_revenue / total_visits if total_visits else 0.0
    avg_ltv = total_revenue / total_clients if total_clients else 0.0
    churn_rate = (churn_count / total_clients * 100) if total_clients else 0.0
    retention_30d = (ret_30 / total_clients * 100) if total_clients else 0.0
    retention_60d = (ret_60 / total_clients * 100) if total_clients else 0.0
    retention_90d = (ret_90 / total_clients * 100) if total_clients else 0.0

    top_churned = sorted(churned_services.items(), key=lambda x: -x[1])[:10]
    top_churned_list = [{"service": s, "count": c} for s, c in top_churned]

    # Cohort matrix: convert sets to counts, normalize to %
    cohort_data = {}
    for month, offsets in sorted(cohort_buckets.items()):
        m0_count = len(offsets.get("m0", set())) or 1
        cohort_data[month] = {
            k: round(len(v) / m0_count * 100)
            for k, v in sorted(offsets.items())
        }

    # ── 5. Save to DB ────────────────────────────────────────────────
    snapshot, _ = RetentionSnapshot.objects.update_or_create(
        date=today,
        defaults={
            "period_days": period_days,
            "total_clients": total_clients,
            "new_clients": new_count,
            "returning_clients": returning_count,
            "retention_30d": round(retention_30d, 1),
            "retention_60d": round(retention_60d, 1),
            "retention_90d": round(retention_90d, 1),
            "avg_frequency": round(avg_frequency, 2),
            "avg_check": round(avg_check),
            "avg_ltv_180d": round(avg_ltv),
            "churn_count": churn_count,
            "churn_rate": round(churn_rate, 1),
            "top_churned_services": top_churned_list,
            "cohort_data": cohort_data,
        },
    )

    elapsed = _time.monotonic() - start
    logger.info(
        "collect_retention_metrics: завершён за %.1fс — "
        "%d клиентов, R30=%.1f%%, churn=%.1f%%",
        elapsed, total_clients, retention_30d, churn_rate,
    )

    # ── 6. Telegram ──────────────────────────────────────────────────
    previous = (
        RetentionSnapshot.objects
        .filter(date__lt=today)
        .order_by("-date")
        .first()
    )
    is_monday = today.weekday() == 0
    if is_monday:
        send_retention_report(snapshot, previous)
    else:
        send_retention_summary(snapshot, previous)


@shared_task(name="agents.tasks.run_landing_qc", bind=True, max_retries=1)
def run_landing_qc(self):
    """QC-проверка draft/review LandingPage: уникальность H1/slug, блоки, ссылки, дубли.

    Прошедшие все critical checks → status=review + SeoTask(TYPE_CREATE_LANDING, HIGH)
    «готов к публикации». Человек публикует вручную через admin (правило CLAUDE.md).
    Не прошедшие → status=review + SeoTask(TYPE_FIX_TECHNICAL, HIGH), Telegram-алерт.

    Расписание: ежедневно 06:00 UTC (09:00 MSK) — перед run_daily_agents.
    """
    from agents.agents.seo_landing_qc import SEOLandingQCAgent
    from agents.models import AgentTask
    from agents.telegram import send_agent_error_alert

    logger.info("run_landing_qc: старт")
    task = AgentTask.objects.create(agent_type="landing_qc", status=AgentTask.PENDING)
    try:
        agent = SEOLandingQCAgent()
        agent.run(task)
        logger.info("run_landing_qc: завершён")
    except Exception as exc:
        logger.exception("run_landing_qc: ошибка — %s", exc)
        send_agent_error_alert("Landing QC", task.pk, str(exc))
        raise
