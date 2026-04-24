# Pattern Analysis: Job Processing (Celery)

## AUDIT-META

- **Worker:** ln-641-pattern-analyzer v2.0.0
- **Pattern:** Job Processing
- **Tech stack:** Celery 5.x + Redis broker (DB 0), Django 5.2
- **Locations:** `mysite/celery.py`, `mysite/mysite/settings/base.py:180-233`, `agents/tasks.py`, `payments/tasks.py`
- **Diagnostic sub-scores:** Compliance=80 / Completeness=42 / Quality=70 / Implementation=75
- **Primary score (penalty-based):** **6.1/10**
- **Issues total:** 7 (C:0 H:2 M:3 L:2)

### Penalty breakdown
```
penalty = 0×2 + 2×1.0 + 3×0.5 + 2×0.2 = 3.9
score   = max(0, 10 - 3.9) = 6.1
```

---

## Checks

| Check | Result | Source |
|---|---|---|
| compliance_check | PASS (80) | Стандартные `@shared_task`, JSON-сериализация, отдельная queue `formula_tela`, `CELERY_TASK_ROUTES`, `CELERY_TIMEZONE=Europe/Moscow` |
| completeness_check | FAIL (42) | DLQ, graceful shutdown, concurrency control отсутствуют; backoff и timeout — только в 2 из 10 задач |
| quality_check | PASS (70) | Логирование везде, ошибка-маршрутизация в `fulfill_paid_order` корректная; `collect_retention_metrics` — «god-task» 180 строк |
| implementation_check | PASS (75) | 7 beat-schedules, production usage подтверждён, отсутствует external monitoring (Sentry/Prometheus для Celery) |

---

## Findings

### HIGH

#### H1. Нет Dead Letter Queue (DLQ)
- **Category:** completeness
- **Evidence:**
  - `mysite/mysite/settings/base.py:184-201` — только `formula_tela` queue, нет `x-dead-letter-exchange` config, нет отдельной DLQ queue в `CELERY_TASK_QUEUES`
  - `payments/tasks.py:81-92` — после `MaxRetriesExceededError` задача "теряется" (только лог + Telegram + admin_note на Order)
- **Why it matters:** если `fulfill_paid_order` упал после 5 ретраев, нет способа переиграть задачу без ручного разбора. Нет видимости в очереди мёртвых задач.
- **Suggestion:** добавить `Queue("formula_tela_dlq")` + в задачах критичного пути (`fulfill_paid_order`, `fulfill_paid_certificate`) на `MaxRetriesExceededError` публиковать в DLQ через `send_task("payments.tasks.dlq_handler", ...)`. Либо использовать celery-redbeat + ext для visibility.
- **Effort:** M (1-4h)

#### H2. Нет graceful shutdown / acks_late
- **Category:** completeness + implementation
- **Evidence:**
  - `mysite/mysite/settings/base.py:189-201` — не установлены `CELERY_TASK_ACKS_LATE`, `CELERY_WORKER_PREFETCH_MULTIPLIER`, `CELERY_WORKER_CANCEL_LONG_RUNNING_TASKS_ON_CONNECTION_LOSS`
  - Результат: при перезапуске воркера (SIGTERM при deploy) или Redis disconnect активная задача потеряется (message уже ack'нут брокером до выполнения)
- **Why it matters:** на этом проекте deploy идёт через GitHub Actions с перезапуском systemd-воркера. `fulfill_paid_order` может быть убита в середине создания записи в YClients — и запись либо создастся, либо нет, но Celery об этом не узнает.
- **Suggestion:** добавить в settings:
  ```python
  CELERY_TASK_ACKS_LATE = True
  CELERY_TASK_REJECT_ON_WORKER_LOST = True
  CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # для fair dispatch + критичных задач
  CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 3600}
  ```
- **Effort:** S (<1h)

### MEDIUM

#### M1. Экспоненциальный backoff только в payments.tasks.fulfill_paid_order
- **Category:** completeness
- **Evidence:**
  - ✅ `payments/tasks.py:30-38` — `retry_backoff=True, retry_backoff_max=600, retry_jitter=True, max_retries=5`
  - ❌ `agents/tasks.py:31` — `self.retry(exc=exc, countdown=300)` — линейный 5-минутный countdown
  - ❌ `agents/tasks.py:85, 98` — тот же паттерн
- **Suggestion:** унифицировать через декоратор или `autoretry_for=(Exception,), retry_backoff=True` на `run_daily_agents`/`run_weekly_agents`/`collect_trends`/`collect_rank_snapshots`. Jitter важен чтобы не ретраить одновременно от нескольких воркеров.
- **Effort:** S

#### M2. Concurrency control не задан
- **Category:** completeness
- **Evidence:** `mysite/mysite/settings/base.py:180-201` — нет `CELERY_WORKER_CONCURRENCY`, нет rate_limit на задачах, нет semaphore для внешних API
- **Why it matters:** `collect_retention_metrics` пагинирует YClients (до 20 страниц), `collect_rank_snapshots` качает Webmaster — если они попадут в один worker slot, можно упереться в rate limit YClients (429). Плюс агентские задачи качают OpenAI — лимиты по токенам.
- **Suggestion:** `rate_limit="10/m"` на задачах, бьющих внешние API, или изолировать их в отдельную queue с concurrency=1.
- **Effort:** S

#### M3. time_limit / soft_time_limit только на одной задаче
- **Category:** completeness
- **Evidence:**
  - ✅ `agents/tasks.py:101-107` — `collect_rank_snapshots` имеет `soft_time_limit=90, time_limit=120` с комментарием почему
  - ❌ `agents/tasks.py:739-763` — `run_landing_qc` без таймаута (может зависнуть на проверке URLов)
  - ❌ `agents/tasks.py:541-` — `collect_retention_metrics` с 180-дневной пагинацией YClients, без таймаута
  - ❌ `payments/tasks.py` — `fulfill_paid_*` без time_limit (YClients зависнет → задача тоже)
- **Suggestion:** задать дефолтный `CELERY_TASK_SOFT_TIME_LIMIT = 300`, `CELERY_TASK_TIME_LIMIT = 360` в settings + override на длительных задачах.
- **Effort:** S

### LOW

#### L1. Нет приоритезации задач
- **Category:** completeness
- **Evidence:** нет `priority` параметра ни в одной задаче. `fulfill_paid_order` (клиент ждёт) обрабатывается в той же очереди что и `generate_missing_landings` (weekly housekeeping).
- **Suggestion:** Redis priority queues через `CELERY_BROKER_TRANSPORT_OPTIONS = {"priority_steps": [0, 3, 6, 9]}` + `priority=0` (highest) на `fulfill_paid_*`, `priority=6` на агентские задачи.
- **Effort:** S

#### L2. Нет прогресс-трекинга / observability
- **Category:** implementation
- **Evidence:** нет `self.update_state(...)` нигде, нет Flower/Prometheus exporter, нет Sentry для Celery worker
- **Suggestion:** добавить `celery-prometheus-exporter` или хотя бы `CELERY_SEND_TASK_SENT_EVENT = True` + периодический dump метрик в `DailyMetric`.
- **Effort:** M

---

## DATA-EXTENDED

```json
{
  "pattern": "Job Processing",
  "tech_stack": "Celery 5.x + Redis + Django 5.2",
  "task_count": 10,
  "beat_schedule_count": 7,
  "code_references": [
    "mysite/celery.py:1-9",
    "mysite/mysite/settings/base.py:180-233",
    "agents/tasks.py (5 tasks)",
    "payments/tasks.py (3 tasks: fulfill_paid_order/certificate/bundle)"
  ],
  "missing_components": ["DLQ", "task_acks_late", "worker_concurrency", "default time_limit", "priority_steps"],
  "partial_components": ["exponential_backoff (1/10)", "time_limit (1/10)"],
  "strong_points": ["idempotency via DB flag", "queue isolation (formula_tela)", "JSON serializer", "timezone explicit"],
  "recommendations": [
    {"priority": 1, "change": "CELERY_TASK_ACKS_LATE=True + REJECT_ON_WORKER_LOST + prefetch=1", "fixes": ["H2"]},
    {"priority": 2, "change": "Add DLQ queue + dlq_handler task", "fixes": ["H1"]},
    {"priority": 3, "change": "autoretry_for + retry_backoff на agents/tasks.py задачах", "fixes": ["M1"]},
    {"priority": 4, "change": "Global soft_time_limit/time_limit в settings", "fixes": ["M3"]}
  ]
}
```
