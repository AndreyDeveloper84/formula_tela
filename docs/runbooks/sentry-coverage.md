# Sentry Coverage Runbook (B-19 / DRF-298)

**Status:** Bot-side audit complete (2026-05-07).
**Owner:** Tech lead.
**Last verified:** 2026-05-07.

---

## 1. Quick reference

**Активация Sentry:** opt-in через env var `SENTRY_DSN`. Без DSN — `sentry_sdk.init()` не вызывается, проект работает обычно.

**Что захватывается автоматически:**
- Все `logger.exception(...)` calls → Sentry **event** (level ERROR + traceback)
- Все `logger.error(...)` calls → Sentry event (level ERROR)
- Все `logger.info`/`warning`/`debug` calls → Sentry **breadcrumb** (контекст для следующего event)
- Django unhandled exceptions → Sentry event (через `DjangoIntegration`)
- Celery task failures → Sentry event (через `CeleryIntegration`)

**Что НЕ захватывается:**
- `logger.warning(...)` сам по себе → только breadcrumb, не event
- Typed exceptions, которые caller проглатывает (`except SpecificError: log + return`) — это by design (transient failures)
- PII fields — `send_default_pii=False` гарантирует no client_phone / display_name leak

---

## 2. Sentry SDK initialization

Файл: `mysite/mysite/settings/production.py` (lines ~64-89, после fail-fast checks).

```python
_sentry_dsn = os.getenv("SENTRY_DSN", "").strip()
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=_sentry_dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        release=os.getenv("SENTRY_RELEASE") or None,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        send_default_pii=False,  # 152-ФЗ
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
            LoggingIntegration(
                level=logging.INFO,         # breadcrumbs from INFO+
                event_level=logging.ERROR,  # events from ERROR+
            ),
        ],
    )
```

### Required env vars (для production)

| Var | Required? | Default | Notes |
|---|---|---|---|
| `SENTRY_DSN` | Optional | empty (skip init) | Sentry project DSN |
| `SENTRY_ENVIRONMENT` | Optional | `production` | tag для UI filter |
| `SENTRY_RELEASE` | Optional | `None` | Git SHA или version tag — для release tracking |
| `SENTRY_TRACES_SAMPLE_RATE` | Optional | `0.0` | Performance monitoring sample rate (0.0..1.0). 0 = только error capture |

### Setup checklist (когда подключаем реальный Sentry account)

1. Создать Sentry project (тип Django)
2. Получить DSN из Settings → Client Keys
3. SSH на прод: `sudo nano /home/taximeter/mysite/formula_tela/.env` → добавить `SENTRY_DSN=https://...@o000000.ingest.sentry.io/000000`
4. (Опц.) `SENTRY_RELEASE=$(git rev-parse HEAD)` — set during deploy via `.github/workflows/deploy.yml`
5. `sudo systemctl restart formula-tela-maxbot && sudo systemctl restart gunicorn-formula-tela`
6. Тест: trigger logger.exception (см. §6 Manual smoke ниже)

---

## 3. Coverage map (verified 2026-05-07)

### 3.1 nutrition_client.* (Ayla HTTP wrapper)

Все методы используют паттерн **log warning + raise typed exception** на нижнем уровне:

| Method | Network/timeout | 5xx | 4xx (typed) | Catch-all |
|---|---|---|---|---|
| `scan_food` | `logger.warning + raise NutritionUnavailableError` | `logger.warning + raise` | type-specific raise | n/a |
| `log_meal` | same | same | same | n/a |
| `daily_summary` | same | same | same | n/a |
| `get_water_today` | same | same | same | n/a |
| `add_water` | same | same | same | n/a |
| `get_profile` | same | same | same | n/a |
| `upsert_profile` | same | same | same | n/a |
| `delete_water_entry` | same | same | same | n/a |

**Status:** ✅ OK. Caller-уровень catches typed exception → log warning (transient) или logger.exception (catch-all). Sentry получает event только если caller имеет catch-all блок.

**Rationale `logger.warning` here:** `nutrition_client` методы перебрасывают через `raise X from exc`. Caller обязан catch — на caller-уровне будет полный context (operation + bot_user + traceback). Если бы тут было `logger.exception`, получили бы дублирующиеся events за одну ошибку.

### 3.2 Celery tasks (`maxbot/tasks.py`)

| Task | Catch-all | Status |
|---|---|---|
| `send_due_reminders` | `logger.warning` (typed) only — no catch-all | ✅ Celery `CeleryIntegration` ловит uncaught |
| `escalate_stale_reminders` | same | ✅ Celery default |
| `send_post_visit_followups` | typed only | ✅ Celery default |
| `send_repeat_offers` | typed only | ✅ Celery default |
| `send_daily_reports` | `logger.exception` ✅ (B-19 fix) | **fixed 2026-05-07** |
| `send_water_reminders` | `logger.exception` ✅ (B-19 fix) | **fixed 2026-05-07** |
| `purge_deleted_water_entries` | typed only | ✅ Celery default |

**B-19 fixes:**
- `mysite/maxbot/tasks.py:399` (send_daily_reports send loop): `logger.warning` → `logger.exception` (catch-all `except Exception`)
- `mysite/maxbot/tasks.py:557` (send_water_reminders send loop): same
- Reason: outer catch swallows error без re-raise, traceback нужен для Sentry triage

### 3.3 Cross-domain handler (`maxbot/handlers/cross_domain.py`)

| Path | Logging |
|---|---|
| `_maybe_send_cross_domain_card` typed errors | `logger.warning` ✅ — transient Ayla unavailability |
| `on_log_meal` cross-domain hook outer | `logger.warning(..., exc_info=True)` ✅ — `exc_info=True` is alternative form, attaches traceback identically to `logger.exception` |

**Status:** ✅ OK as-is. Best-effort hook never breaks log_meal flow; traceback захватывается через `exc_info=True`.

### 3.4 AI Concierge (`maxbot/ai_concierge.py`)

| Path | Line | Logging |
|---|---|---|
| `send_message` deficit_hint catch | 252 | `logger.exception` ✅ |
| `send_message` retry tool_choice catch | 379 | `logger.warning` (transient retry) ✅ |
| `send_message` outer | n/a | uncaught → bubbles to handler `on_free_text` |
| `on_free_text` outer | `ai_assistant.py:212` | `logger.exception` ✅ |

**Status:** ✅ OK. `on_free_text` имеет outer `logger.exception` для catch-all.

### 3.5 YClients webhook (`maxbot/yclients_webhook.py`)

| Path | Line | Logging |
|---|---|---|
| outer handler catch | 358 | `logger.exception` ✅ |

**Status:** ✅ OK. Webhook ВСЕГДА returns 200 (per spec — иначе YClients ретраит forever), но errors логируются с traceback.

### 3.6 Food scanner (`maxbot/handlers/food_scanner.py`)

| Path | Line | Logging |
|---|---|---|
| `on_photo` food scan typed | 178 | `logger.warning` ✅ — transient |
| `on_photo` food scan unexpected | 183 | `logger.exception` ✅ |
| `on_log_meal` log_meal unexpected | 274 | `logger.exception` ✅ |
| `_maybe_send_evening_inline` typed (summary) | 331 | `logger.warning` ✅ — transient |
| `_maybe_send_evening_inline` outer catch-all | 364 | `logger.exception` ✅ (B-19 fix) **fixed 2026-05-07** |
| `on_diary_command` summary unexpected | 464 | `logger.exception` ✅ |

**B-19 fix:**
- `mysite/maxbot/handlers/food_scanner.py:362-367` (evening inline outer): `logger.warning` → `logger.exception`

---

## 4. Coverage testing

### 4.1 Automated tests

`mysite/tests/maxbot/test_sentry_coverage.py` (5 tests) — verify catch-all blocks вызывают `logger.exception` с непустым `exc_info` (required for Sentry LoggingIntegration capture):

- `test_send_daily_reports_catch_all_uses_logger_exception`
- `test_send_water_reminders_catch_all_uses_logger_exception`
- `test_evening_inline_catch_all_uses_logger_exception`
- `test_production_settings_skip_sentry_init_when_dsn_absent` (graceful no-op)
- `test_logger_exception_attaches_exc_info` (smoke API contract)

### 4.2 Manual smoke (когда Sentry подключён)

Когда SENTRY_DSN установлен на staging/проде, запустить smoke:

```python
# Django shell на проде/staging
from maxbot.services.nutrition_client import NutritionUnavailableError, get_nutrition_client
import asyncio

async def smoke():
    client = get_nutrition_client()
    # Mock или просто вызвать с invalid endpoint → real exception
    try:
        # Force exception path
        raise NutritionUnavailableError("smoke test from prod")
    except Exception:
        import logging
        logging.getLogger("smoke.sentry").exception(
            "Sentry smoke from %s — expect Sentry event in next 30s",
            "prod",
        )

asyncio.run(smoke())
```

Проверить в Sentry UI (Issues tab) — event должен появиться в течение 30 секунд с `level=error` + traceback.

---

## 5. Known gaps / non-blockers

### 5.1 nutrition_client log+raise pattern

`nutrition_client.*` методы используют `logger.warning(...)` перед `raise X from exc`. Это by design — caller catches typed exception. Sentry получит event только если caller имеет catch-all. **Не баг, не fix.**

### 5.2 Celery default integration coverage

Mid-task uncaught exceptions ловятся Celery `CeleryIntegration` автоматически. Тестировать через `celery_app.send_task(...)` с broken implementation — но это integration test, не unit.

### 5.3 Performance monitoring отключен

`SENTRY_TRACES_SAMPLE_RATE=0.0` по умолчанию — capture только errors, не traces. Включить когда понадобится latency analysis (~5% sample rate good start).

---

## 6. Priorities for next iteration

| Priority | Action | Owner |
|---|---|---|
| Optional | Set up real Sentry project + populate `SENTRY_DSN` env var | tech lead + ops |
| Optional | Auto-set `SENTRY_RELEASE` в `.github/workflows/deploy.yml` (`git rev-parse HEAD`) | ops |
| Backlog | Sample rate `SENTRY_TRACES_SAMPLE_RATE=0.05` для AI Concierge latency profiling | tech lead |
| Backlog | Ayla side coverage doc (mirror этого) | Ayla backend dev |

---

## 7. Audit changelog

- **2026-05-07** — B-19 / DRF-298 initial audit. Found `sentry-sdk` not installed → added opt-in setup. Fixed 3 `logger.warning` → `logger.exception` in catch-all blocks. Coverage doc создан.

---

*Maintained as living doc. Update при добавлении новых critical paths
(`logger.warning(..., exc_info=True)` или `logger.exception` в catch-all
обязательно покрывать).*
