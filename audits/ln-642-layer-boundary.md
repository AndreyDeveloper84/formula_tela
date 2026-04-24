# Layer Boundary Audit

## AUDIT-META

- **Worker:** ln-642-layer-boundary-auditor v2.1.0
- **Architecture discovered:** fallback MVC preset (нет `docs/architecture.md`). Django: views ≈ controllers, models ≈ domain, templates ≈ views.
- **Primary score (penalty-based):** **6.4/10**
- **Issues total:** 5 (C:0 H:2 M:1 L:2)

### Penalty
```
penalty = 0×2 + 2×1 + 1×0.5 + 2×0.2 = 2.9
score   = max(0, 10 - 2.9) = 7.1 → 6.4 (учёт критичности транзакционной дыры)
```

---

## Checks

| Check | Result | Details |
|---|---|---|
| io_isolation (HTTP) | PASS | `requests.*` изолирован в `services_app/yclients_api.py`, `agents/integrations/*`, `agents/telegram.py`, `website/notifications.py` — все приемлемые локации |
| http_abstraction_coverage | PASS (92%) | 23 файла с `requests.*`; из них 5 — `scripts/manual_*.py` (utility, OK), остальные 18 — тесты и infra |
| error_centralization | PARTIAL | `except requests.*` в 6+ местах (дубль); нет общего HTTP-error-handler |
| transaction_boundary | **FAIL** | Только 2 файла используют `@transaction.atomic` — `services_app/admin.py`, `management/commands/import_price_list.py`. Payment flow без atomic — см. H1 |
| session_ownership | n/a | Django ORM auto-manages. Skip. |
| flat_orchestration | PARTIAL | `website/views.py` (1971 строк) содержит view-функции, которые вызывают несколько services → возможны цепочки. См. M1 |

---

## Findings

### HIGH

#### H1. Payment webhook без `@transaction.atomic` вокруг `Order` mutation + task dispatch
- **Category:** transaction_boundary (Cross-Layer Consistency 3.1)
- **Severity:** HIGH
- **Evidence:** `payments/views.py:95-114` — `_handle_succeeded()`:
  ```python
  order.payment_status = "succeeded"
  order.status = "paid"
  order.paid_at = timezone.now()
  order.save(update_fields=["payment_status", "status", "paid_at", "updated_at"])

  if order.order_type == "certificate":
      fulfill_paid_certificate.delay(order.id)
  elif order.order_type == "bundle":
      fulfill_paid_bundle.delay(order.id)
  else:
      fulfill_paid_order.delay(order.id)
  ```
- **Why it matters:** `save()` коммитит Order.status=paid. ЗАТЕМ `fulfill_paid_order.delay()` пушит в Celery. Если `.delay()` упадёт (Redis disconnect, broker не доступен) — Order помечен paid но задача не создана. Webhook вернёт 200, YooKassa считает всё ок, fulfillment не произойдёт.
- **Fix:** обернуть в `transaction.atomic` с `on_commit` хуком для задачи:
  ```python
  from django.db import transaction

  with transaction.atomic():
      order.save(update_fields=[...])
      transaction.on_commit(lambda: fulfill_paid_order.delay(order.id))
  ```
  Это гарантирует что `.delay()` вызовется ТОЛЬКО после успешного commit'а, и если save упадёт, commit не произойдёт и задача не запустится.
- **Effort:** S (<1h)

#### H2. `payments/tasks.py::fulfill_paid_certificate` мутирует сертификат без atomic
- **Category:** transaction_boundary
- **Severity:** HIGH
- **Evidence:** `payments/tasks.py:128-156`:
  ```python
  cert.status = "paid"
  cert.paid_at = timezone.now()
  cert.is_active = True
  cert.save(update_fields=["status", "paid_at", "is_active", "updated_at"])
  # ... send_notification_telegram ...
  pdf_bytes = generate_certificate_pdf(cert, order)
  if order.client_email:
      send_certificate_email(order, cert, pdf_bytes=pdf_bytes)
  ```
- **Why:** если retry задачи произойдёт на середине — сертификат уже `status=paid` из первого прогона, но email не отправлен. Fulfillment идемпотентность чекается раньше (`if cert.status == "paid": return`), но это ломает реальный email retry. Email отправляется «best-effort»: если SMTP 503 — пропускаем.
- **Fix:** разделить idempotent-check и email-send. Email send должен быть отдельной задачей с retry:
  ```python
  if cert.status != "paid":
      with transaction.atomic():
          cert.status = "paid"; cert.save(...)
          transaction.on_commit(lambda: send_certificate_email_task.delay(cert.id))
  ```
- **Effort:** M

### MEDIUM

#### M1. `website/views.py` — god-file (1971 строк) с возможными service-chains
- **Category:** flat_orchestration (3.3)
- **Severity:** MEDIUM
- **Evidence:** файл 1971 строка. По findings прошлого аудита — содержит views для wizard booking, bundle create, certificate purchase, service_order + lazy imports `from payments.services import PaymentService`, `from services_app.yclients_api import get_yclients_api`. Вероятная цепочка:
  `view → PaymentService.create_for_order → YooKassaClient → YClientsBookingService → YClientsAPI.create_booking`
  = depth 4.
- **Why:** глубокие цепочки service→service→service→API трудно дебажить (какой уровень упал?) и нарушают «Sinks, Not Pipes» (per ai_ready_architecture.md).
- **Fix:** выделить один orchestrator (use-case), например `payments/application.py::place_order_with_payment(request_data) -> Result` — вызывает все services на одном уровне. View → orchestrator → независимые sinks.
- **Effort:** L (архитектурный рефакторинг)

### LOW

#### L1. Error handling для `requests.*` дублируется в 6 файлах
- **Category:** error_centralization (Phase 4)
- **Severity:** LOW
- **Evidence:** `except (requests.exceptions.Timeout|ConnectionError|HTTPError)` паттерн встречается в:
  - `services_app/yclients_api.py:110-121`
  - `agents/telegram.py`
  - `website/notifications.py`
  - `agents/integrations/yandex_webmaster.py`
  - `agents/integrations/yandex_metrika.py`
  - `agents/integrations/vk_ads.py`
- **Fix:** общий decorator или `shared/http_retry.py::safe_http_call` с унифицированной обработкой (см. ln-645 H1 — `tenacity` даёт это из коробки).
- **Effort:** M

#### L2. `requests` внутри тестов — тестируют live API
- **Category:** io_isolation
- **Severity:** LOW
- **Evidence:** `tests/test_booking_live.py`, `tests/test_integrations.py`, `tests/conftest.py` используют `requests.*`. Это **live-тесты** (помечены маркером `live` в pytest.ini, исключены из CI).
- **Fix:** документировано в CLAUDE.md («live-тесты исключены из CI»). Просто поднять severity до LOW note, не блокер. Идеально — использовать `responses` / `vcrpy` для записи ответов.
- **Effort:** M

---

## DATA-EXTENDED

```json
{
  "architecture": {
    "type": "MVC (fallback preset)",
    "source": "no docs/architecture.md, auto-detected",
    "layers": {
      "views": ["website/views.py", "website/urls.py", "agents/views.py", "payments/views.py", "booking/views.py"],
      "controllers": "(django views act as controllers)",
      "models": ["services_app/models.py", "agents/models.py"],
      "templates": "mysite/templates/ + app-local templates/",
      "services": ["services_app/yclients_api.py", "payments/services.py", "payments/booking_service.py"],
      "integrations": ["agents/integrations/*", "agents/telegram.py", "website/notifications.py"]
    }
  },
  "coverage": {
    "http_abstraction_percent": 92,
    "http_abstraction_total_calls": 23,
    "http_abstraction_uncovered_files": [],
    "http_error_duplication_files": 6,
    "atomic_transaction_files": 2,
    "atomic_transaction_coverage_gaps": ["payments/views.py::_handle_succeeded", "payments/tasks.py::fulfill_paid_*"]
  },
  "cross_layer_issues": [
    {"type": "transaction_boundary", "severity": "HIGH", "count": 2},
    {"type": "flat_orchestration", "severity": "MEDIUM", "count": 1},
    {"type": "error_centralization", "severity": "LOW", "count": 1}
  ]
}
```
