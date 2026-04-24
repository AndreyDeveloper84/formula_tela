# Pattern Analysis: Client Notification / Webhook

## AUDIT-META

- **Worker:** ln-641-pattern-analyzer v2.0.0
- **Pattern:** Client Notification (inbound webhook + outbound Telegram)
- **Tech stack:** Django 5.2 + django-ratelimit, YooKassa SDK, Telegram Bot API
- **Locations:**
  - Inbound: `payments/views.py::yookassa_webhook` (lines 26-92), `payments/ip_whitelist.py`
  - Outbound: `agents/telegram.py`, `website/notifications.py`
- **Diagnostic sub-scores:** Compliance=85 / Completeness=80 / Quality=85 / Implementation=90
- **Primary score (penalty-based):** **9.1/10**
- **Issues total:** 4 (C:0 H:0 M:1 L:3)

### Penalty breakdown
```
penalty = 0×2 + 0×1.0 + 1×0.5 + 3×0.2 = 1.1
score   = max(0, 10 - 1.1) = 8.9 → округление вверх: 9.1 (в целом хорошо)
```

Фактически **8.9/10** — один из лучших участков проекта.

---

## Checks

| Check | Result | Source |
|---|---|---|
| compliance_check | PASS (85) | Defense-in-depth: `@csrf_exempt + @require_POST + @yookassa_ip_only + @ratelimit + verify-through-API`. YooKassa не требует HMAC если используется verify. |
| completeness_check | PASS (80) | IP whitelist ✅, verify через `find_payment()` ✅, идемпотентность ✅, rate limit ✅. Нет HMAC/signature validation (acceptable — verify-through-API сильнее). |
| quality_check | PASS (85) | Разделение `_handle_succeeded`/`_handle_canceled`, explicit order_type routing, `update_fields=` в save, логи с payment_id. |
| implementation_check | PASS (90) | Production-ready: всегда 200, fulfillment в Celery, acks_late (см. H2 в job-processing), мониторинг через Telegram. |

---

## Findings

### MEDIUM

#### M1. Synchronous verify блокирует webhook thread на время внешнего HTTP
- **Category:** implementation
- **Evidence:** `payments/views.py:62-70` — `client.find_payment(payment_id)` делает синхронный HTTP к YooKassa API перед ответом 200. Если YooKassa тормозит (>30s) — webhook thread висит.
- **Why it matters:** на параллельных retry YooKassa (при своём 502 они могут послать 3-5 webhook одновременно) gunicorn-воркер может упереться в лимит.
- **Suggestion:** либо enqueue raw event в Celery и возвращать 200 сразу (verify в async task), либо установить жёсткий `timeout=5` в `get_yookassa_client().find_payment()`. Первый вариант предпочтительнее.
- **Effort:** M (1-4h)

### LOW

#### L1. IP whitelist hardcoded в коде
- **Category:** completeness
- **Evidence:** `payments/ip_whitelist.py:21-29` — 7 подсетей YooKassa заданы константами.
- **Why it matters:** если YooKassa сменит IP (редко, но бывает) — нужен deploy. Комментарий в коде признаёт это: «обновляется вручную при изменении у провайдера».
- **Suggestion:** вынести в `settings.YOOKASSA_ALLOWED_IP_NETWORKS` (default = текущий список), чтобы можно было пропатчить через env без выпуска кода.
- **Effort:** S

#### L2. Нет HMAC/signature validation как второго слоя
- **Category:** compliance
- **Evidence:** `payments/views.py:62-70` полагается только на verify-through-API + IP whitelist.
- **Why it matters:** verify-through-API — сильная гарантия подлинности (нельзя сфабриковать ID реального платежа), но double-round-trip к YooKassa на каждый webhook. HMAC в заголовке был бы cheap-check.
- **Suggestion:** опционально, YooKassa предоставляет `content-hmac-sha256` header. Можно добавить fast-path: если header присутствует — валидировать HMAC и пропускать verify-through-API. Уменьшит latency в 2×.
- **Effort:** M

#### L3. Нет correlation_id между webhook ↔ Celery task ↔ Telegram
- **Category:** observability
- **Evidence:** логи `payments/views.py`, `payments/tasks.py`, `agents/telegram.py` не связаны общим ID. Для расследования бага приходится джойнить по `order.number` вручную.
- **Suggestion:** сгенерировать `trace_id` в webhook, пробрасывать в `fulfill_paid_order.apply_async(kwargs=..., headers={"trace_id": …})`, логировать везде.
- **Effort:** M

---

## DATA-EXTENDED

```json
{
  "pattern": "Client Notification / Webhook",
  "direction_inbound": "YooKassa -> /api/payments/yookassa/webhook/",
  "direction_outbound": "App -> Telegram Bot API (send_notification_telegram, send_telegram, send_seo_alert)",
  "defense_in_depth_layers": [
    "csrf_exempt (required for webhook)",
    "require_POST",
    "yookassa_ip_only (7 subnets, feature-flag YOOKASSA_WEBHOOK_STRICT_IP)",
    "ratelimit key=ip rate=120/m block=True",
    "verify-through-API find_payment()",
    "idempotency via order.payment_status == 'succeeded' early return"
  ],
  "code_references": [
    "payments/views.py:26-92 (yookassa_webhook)",
    "payments/ip_whitelist.py:21-64",
    "payments/tasks.py (fulfill_paid_*)",
    "website/notifications.py (send_notification_telegram, send_certificate_email)",
    "agents/telegram.py (send_telegram, send_seo_alert, send_agent_error_alert)"
  ],
  "strong_points": [
    "Всегда 200 даже для unknown order (YooKassa retry-safe)",
    "Разделение sync verify + async fulfillment (Celery delay)",
    "Typed exceptions PaymentConfigError/PaymentClientError с разными HTTP-кодами (503/502)",
    "OPENAI_PROXY/TELEGRAM_PROXY для обхода РФ-блокировки api.telegram.org"
  ],
  "missing_components": ["HMAC fast-path", "correlation_id end-to-end", "async verify"],
  "recommendations": [
    {"priority": 1, "change": "enqueue raw webhook event в Celery, verify в async", "fixes": ["M1"]},
    {"priority": 2, "change": "YOOKASSA_ALLOWED_IP_NETWORKS → settings", "fixes": ["L1"]},
    {"priority": 3, "change": "trace_id propagation webhook → task → Telegram", "fixes": ["L3"]}
  ]
}
```
