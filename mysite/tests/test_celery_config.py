from django.conf import settings


def test_celery_timezone_uses_moscow():
    assert settings.CELERY_TIMEZONE == "Europe/Moscow"


def test_celery_reliability_settings():
    """acks_late + reject_on_worker_lost + prefetch=1 — защита от потери задач при deploy/SIGKILL."""
    assert settings.CELERY_TASK_ACKS_LATE is True
    assert settings.CELERY_TASK_REJECT_ON_WORKER_LOST is True
    assert settings.CELERY_WORKER_PREFETCH_MULTIPLIER == 1


def test_celery_visibility_timeout_exceeds_task_time_limit():
    """visibility_timeout должен быть >= TIME_LIMIT, иначе долгая задача
    будет передоставлена и выполнится дважды."""
    transport_opts = settings.CELERY_BROKER_TRANSPORT_OPTIONS
    assert transport_opts["visibility_timeout"] >= settings.CELERY_TASK_TIME_LIMIT


def test_celery_agent_queue_is_explicit():
    assert settings.CELERY_TASK_DEFAULT_QUEUE == "formula_tela"
    assert [queue.name for queue in settings.CELERY_TASK_QUEUES] == ["formula_tela"]
    assert settings.CELERY_TASK_ROUTES["agents.tasks.*"]["queue"] == "formula_tela"
    assert settings.CELERY_TASK_ROUTES["payments.tasks.*"]["queue"] == "formula_tela"


def test_daily_agents_run_at_noon_moscow():
    schedule = settings.CELERY_BEAT_SCHEDULE["daily-agents-12pm-msk"]["schedule"]
    assert schedule._orig_hour == 12
    assert schedule._orig_minute == 0


def test_other_celery_schedule_times_preserved_in_moscow():
    weekly_agents = settings.CELERY_BEAT_SCHEDULE["weekly-agents-monday-11am-msk"]["schedule"]
    rank_snapshots = settings.CELERY_BEAT_SCHEDULE["daily-rank-snapshots-10am-msk"]["schedule"]
    trend_scout = settings.CELERY_BEAT_SCHEDULE["weekly-trend-scout-monday-1030-msk"]["schedule"]
    landings = settings.CELERY_BEAT_SCHEDULE["weekly-generate-landings-monday-0100-msk"]["schedule"]
    retention = settings.CELERY_BEAT_SCHEDULE["daily-retention-metrics-11am-msk"]["schedule"]
    landing_qc = settings.CELERY_BEAT_SCHEDULE["daily-landing-qc-9am-msk"]["schedule"]

    assert weekly_agents._orig_hour == 11
    assert weekly_agents._orig_minute == 0
    assert rank_snapshots._orig_hour == 10
    assert rank_snapshots._orig_minute == 0
    assert trend_scout._orig_hour == 10
    assert trend_scout._orig_minute == 30
    assert landings._orig_hour == 1
    assert landings._orig_minute == 0
    assert retention._orig_hour == 11
    assert retention._orig_minute == 0
    assert landing_qc._orig_hour == 9
    assert landing_qc._orig_minute == 0
