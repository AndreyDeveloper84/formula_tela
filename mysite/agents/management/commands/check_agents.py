"""
Диагностика работы AI-агентов на проде.

Использование:
    python manage.py check_agents               # сводка за 7 дней
    python manage.py check_agents --days 14     # другой период
    python manage.py check_agents --verbose     # + тексты ошибок и превью отчётов
"""

import datetime

from django.core.management.base import BaseCommand
from django.db.models import Count, Max, Q
from django.utils import timezone


DAILY_TYPES = {"analytics", "offers", "analytics_budget"}
WEEKLY_TYPES = {"offer_packages", "smm_growth", "seo_landing", "trend_scout"}

STALE_DAILY_HOURS = 36
STALE_WEEKLY_DAYS = 10
STUCK_HOURS = 1


class Command(BaseCommand):
    help = "Показывает состояние AI-агентов: запуски, ошибки, свежесть данных"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)
        parser.add_argument("--verbose", action="store_true", default=False)

    def handle(self, *args, **options):
        from agents.models import (
            AgentReport,
            AgentTask,
            DailyMetric,
            SeoClusterSnapshot,
            SeoRankSnapshot,
        )

        S, E, W = self.style.SUCCESS, self.style.ERROR, self.style.WARNING
        H = self.style.MIGRATE_HEADING
        sep = "=" * 72
        days = options["days"]
        now = timezone.now()
        since = now - datetime.timedelta(days=days)
        alerts: list[str] = []

        # ── 1. Сводка по типам агентов ────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H(f"=== 1. Сводка по агентам (последние {days} дн.) ==="))
        self.stdout.write(sep)

        all_types = [code for code, _ in AgentTask.AGENT_CHOICES]
        header = f"  {'Агент':<20} {'Всего':>6} {'Done':>6} {'Error':>6} {'Последний done':>22}"
        self.stdout.write(header)
        self.stdout.write("  " + "-" * 70)

        by_type_last_done: dict[str, datetime.datetime | None] = {}

        for agent_type in all_types:
            qs = AgentTask.objects.filter(agent_type=agent_type, created_at__gte=since)
            total = qs.count()
            done = qs.filter(status=AgentTask.DONE).count()
            errors = qs.filter(status=AgentTask.ERROR).count()
            last_done = (
                AgentTask.objects.filter(agent_type=agent_type, status=AgentTask.DONE)
                .aggregate(m=Max("finished_at"))["m"]
            )
            by_type_last_done[agent_type] = last_done
            last_str = last_done.strftime("%d.%m %H:%M") if last_done else "—"
            row = f"  {agent_type:<20} {total:>6} {done:>6} {errors:>6} {last_str:>22}"
            if errors:
                self.stdout.write(E(row))
            elif total == 0:
                self.stdout.write(W(row))
            else:
                self.stdout.write(row)

        # ── 2. Проверка свежести (по ожидаемому расписанию) ───────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== 2. Свежесть запусков (vs ожидаемое расписание) ==="))
        self.stdout.write(sep)

        for agent_type in all_types:
            last = by_type_last_done.get(agent_type)
            if agent_type in DAILY_TYPES:
                limit = datetime.timedelta(hours=STALE_DAILY_HOURS)
                label = f"ежедневный (SLA {STALE_DAILY_HOURS}ч)"
            elif agent_type in WEEKLY_TYPES:
                limit = datetime.timedelta(days=STALE_WEEKLY_DAYS)
                label = f"еженедельный (SLA {STALE_WEEKLY_DAYS}д)"
            else:
                limit = None
                label = "без расписания"

            if last is None:
                msg = f"  {agent_type:<20} {label:<32} НИ ОДНОГО УСПЕШНОГО ЗАПУСКА"
                self.stdout.write(E(msg))
                if limit is not None:
                    alerts.append(f"{agent_type}: ни одного done за всё время")
                continue

            age = now - last
            age_h = int(age.total_seconds() // 3600)
            age_str = f"{age_h // 24}д {age_h % 24}ч назад" if age_h >= 24 else f"{age_h}ч назад"

            if limit is not None and age > limit:
                self.stdout.write(E(f"  {agent_type:<20} {label:<32} ПРОСРОЧЕН: {age_str}"))
                alerts.append(f"{agent_type}: последний done {age_str}, SLA нарушен")
            else:
                self.stdout.write(S(f"  {agent_type:<20} {label:<32} OK, {age_str}"))

        # ── 3. Застрявшие pending/running ─────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H(f"=== 3. Застрявшие задачи (>{STUCK_HOURS}ч в pending/running) ==="))
        self.stdout.write(sep)

        stuck_cutoff = now - datetime.timedelta(hours=STUCK_HOURS)
        stuck = AgentTask.objects.filter(
            status__in=[AgentTask.PENDING, AgentTask.RUNNING],
            created_at__lt=stuck_cutoff,
        ).order_by("-created_at")

        if not stuck.exists():
            self.stdout.write(S("  [OK] Застрявших задач нет"))
        else:
            for t in stuck[:20]:
                age_min = int((now - t.created_at).total_seconds() // 60)
                self.stdout.write(
                    E(f"  [{t.status}] {t.agent_type:<18} id={t.id} "
                      f"создан {t.created_at:%d.%m %H:%M} ({age_min} мин назад)")
                )
                alerts.append(f"{t.agent_type} id={t.id} застрял в {t.status} {age_min} мин")

        # ── 4. Последние ошибки ───────────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H(f"=== 4. Последние ошибки (за {days} дн.) ==="))
        self.stdout.write(sep)

        recent_errors = AgentTask.objects.filter(
            status=AgentTask.ERROR, created_at__gte=since
        ).order_by("-created_at")[:10]

        if not recent_errors:
            self.stdout.write(S("  [OK] Ошибок нет"))
        else:
            for t in recent_errors:
                self.stdout.write(
                    E(f"  {t.created_at:%d.%m %H:%M}  {t.agent_type:<18} id={t.id}")
                )
                msg = (t.error_message or "").strip()
                if msg:
                    preview = msg if options["verbose"] else msg.splitlines()[0][:200]
                    for line in preview.splitlines() if options["verbose"] else [preview]:
                        self.stdout.write(f"      {line}")
                alerts.append(f"{t.agent_type} id={t.id}: {(msg.splitlines()[0] if msg else 'без сообщения')[:100]}")

        # ── 5. Последний отчёт по каждому типу ────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== 5. Последние отчёты агентов ==="))
        self.stdout.write(sep)

        for agent_type in all_types:
            report = (
                AgentReport.objects
                .filter(task__agent_type=agent_type)
                .select_related("task")
                .order_by("-created_at")
                .first()
            )
            if not report:
                self.stdout.write(W(f"  {agent_type:<20} — нет отчётов"))
                continue

            recs = report.recommendations or []
            recs_count = len(recs) if isinstance(recs, list) else (
                len(recs.keys()) if isinstance(recs, dict) else 0
            )
            summary_line = (report.summary or "").strip().splitlines()[0] if report.summary else ""
            self.stdout.write(
                S(f"  {agent_type:<20} {report.created_at:%d.%m %H:%M}  "
                  f"рекомендаций: {recs_count}")
            )
            if summary_line:
                self.stdout.write(f"      {summary_line[:120]}")
            if options["verbose"] and isinstance(recs, list) and recs:
                for i, r in enumerate(recs[:3], 1):
                    r_str = r if isinstance(r, str) else str(r)
                    self.stdout.write(f"      {i}. {r_str[:180]}")

        # ── 6. Свежесть данных под агенты ─────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== 6. Свежесть входных данных ==="))
        self.stdout.write(sep)

        last_daily = DailyMetric.objects.order_by("-date").first()
        if last_daily:
            age_days = (now.date() - last_daily.date).days
            row = f"  DailyMetric         последняя {last_daily.date}  ({age_days}д назад)"
            if age_days > 1:
                self.stdout.write(E(row))
                alerts.append(f"DailyMetric отстаёт на {age_days}д")
            else:
                self.stdout.write(S(row))
        else:
            self.stdout.write(E("  DailyMetric         нет данных"))
            alerts.append("DailyMetric пустой")

        last_rank = SeoRankSnapshot.objects.aggregate(m=Max("created_at"))["m"]
        if last_rank:
            age_h = int((now - last_rank).total_seconds() // 3600)
            row = f"  SeoRankSnapshot     последний {last_rank:%d.%m %H:%M}  ({age_h}ч назад)"
            if age_h > 48:
                self.stdout.write(E(row))
                alerts.append(
                    f"SeoRankSnapshot отстаёт на {age_h}ч — collect_rank_snapshots "
                    f"не отработал или Вебмастер недоступен"
                )
            else:
                self.stdout.write(S(row))
        else:
            self.stdout.write(E("  SeoRankSnapshot     нет данных"))
            alerts.append(
                "SeoRankSnapshot ни разу не заполнялся — проверь YANDEX_WEBMASTER_TOKEN "
                "и запусти collect_rank_snapshots вручную"
            )

        last_cluster = SeoClusterSnapshot.objects.order_by("-date").first()
        if last_cluster:
            age_days = (now.date() - last_cluster.date).days
            row = f"  SeoClusterSnapshot  последний {last_cluster.date}  ({age_days}д назад)"
            if age_days > 2:
                self.stdout.write(W(row))
            else:
                self.stdout.write(S(row))
        else:
            self.stdout.write(W("  SeoClusterSnapshot  нет данных"))

        # ── 7. Итог ───────────────────────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== Итог ==="))
        self.stdout.write(sep)

        if not alerts:
            self.stdout.write(S("[OK] Агенты работают штатно"))
        else:
            self.stdout.write(E(f"[FAIL] Найдено проблем: {len(alerts)}"))
            for a in alerts:
                self.stdout.write(E(f"  • {a}"))
        self.stdout.write("")
