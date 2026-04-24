# Dependency Graph Audit — mysite (formulatela58.ru)

## AUDIT-META

- **Worker:** ln-644-dependency-graph-auditor v1.0.0
- **Scope:** `mysite/` (Django project root). Modules = Django-приложения: `agents`, `booking`, `mysite` (project pkg), `payments`, `services_app`, `website`. Исключены: `tests/` (test-only deps), `scripts/` (utility-скрипты, не Django-apps), `masters/` (не модуль — папка с фото).
- **Architecture mode:** `custom` (safe mode). Auto-detection: MVC-сигнал HIGH (`views.py`+`models.py` в каждом app) и vertical-slice-сигнал HIGH (Django-apps). Нет `docs/architecture.md` и `docs/project/dependency_rules.yaml` → только проверка циклов + метрик, без preset boundary-rules.
- **Language:** Python (Django 5.2)
- **Checks run:** cycle_detection, sdp_validation, metrics_thresholds
- **Score:** **0.0/10** (Critical issues — immediate action required)
- **Issues total:** 11 (C:4 H:7 M:0 L:0)

### Penalty breakdown

```
penalty = (4 × 2.0) + (7 × 1.0) + (0 × 0.5) + (0 × 0.2) = 15.0
score   = max(0, 10 - 15.0) = 0
```

---

## Checks

| Check | Result | Notes |
|---|---|---|
| cycle_detection (pairwise) | **FAIL** | 4 двухузловых цикла между `services_app` и остальными apps |
| cycle_detection (transitive DFS) | **FAIL** | ≥4 простых элементарных цикла длины 3-4 через services_app↔website↔payments↔agents |
| cycle_detection (folder-level) | n/a | в Django-apps каталоги = модули, совпадает с pairwise |
| boundary_rules | SKIP | architecture=custom, нет preset/custom rules |
| sdp_validation | **FAIL** | 3 нарушения Stable Dependencies Principle |
| metrics_thresholds | PASS | NCCD=1.48 (<1.5), Ce<15, `mysite.I=1.0` ожидаемо для composition root |
| baseline_comparison | n/a | baseline отсутствует, это первый запуск |

---

## Dependency graph (cross-app edges)

Узлы: `agents`, `booking`, `mysite`, `payments`, `services_app`, `website` (N=6).
Ребра построены из `from X import …` (top-level и function-local/lazy), включая Django `include('<app>.urls')`.

```
agents        ──► services_app
services_app  ──► agents          (lazy: admin.py:699)
services_app  ──► payments        (lazy: admin.py:594,595,680,740)
services_app  ──► website         (lazy: admin.py:741)
payments      ──► services_app
payments      ──► website
website       ──► services_app
website       ──► agents
website       ──► payments        (lazy: views.py:1337,1338,1744,1745,1815-1822)
mysite        ──► agents
mysite        ──► payments
mysite        ──► website
mysite        ──► booking
```

### Module metrics (Robert C. Martin)

| Module | Ca (in) | Ce (out) | I = Ce/(Ca+Ce) | Expected role | Status |
|---|---|---|---|---|---|
| `services_app` | 3 | 3 | 0.50 | core/domain (должен быть I≈0) | **полюс нестабильности** — ядро зависит от фичевых apps |
| `agents` | 3 | 1 | 0.25 | feature (OK I<0.5) | норм, но участвует в цикле |
| `payments` | 3 | 2 | 0.40 | feature (OK) | участвует в двух циклах |
| `website` | 3 | 3 | 0.50 | feature (OK) | участвует в двух циклах |
| `mysite` | 0 | 4 | 1.00 | composition root | OK — это точка сборки URL'ов |
| `booking` | 1 | 0 | 0.00 | placeholder | изолирован |

### Aggregate (Lakos)

- CCD = 23, CCD_balanced = 6·log₂6 ≈ 15.51
- **NCCD = 1.48** → зона "comparable to balanced tree" (<1.5), но практически у верхней границы — это прямое следствие плотного цикла между 4 apps.

---

## Findings

### CRITICAL

#### C1. Transitive cycle: services_app → payments → website → services_app

- **Severity:** CRITICAL
- **Path:** `services_app/admin.py:594` → `payments/services.py:13` → `website/notifications (via payments/tasks.py:25)` ~~→~~ _backedge_ → `services_app.models` (`website/views.py:32`, `website/context_processors.py:3`)
- **Import locations:**
  - `mysite/services_app/admin.py:594-595` — `from payments.services import PaymentService` (lazy)
  - `mysite/payments/tasks.py:25` — `from website.notifications import …`
  - `mysite/website/views.py:32` — `from services_app.models import …`
- **Why it matters:** любое изменение в `website.notifications` потенциально ломает admin-действия сертификатов в `services_app`, что ломает booking-flow в `payments`. Blast radius = все 4 app.
- **Recommendation:** вынести `website.notifications` в отдельный модуль `notifications/` или `shared/notifications/`, не зависящий от services_app. Альтернатива — Domain Events (Celery signal) вместо прямого вызова.
- **Effort:** L (>4h)

#### C2. Transitive cycle: services_app → website → payments → services_app

- **Severity:** CRITICAL
- **Path:** `services_app/admin.py:741` → `website/notifications.py` → back via `payments` imports
  - `services_app/admin.py:741` — `from website.notifications import send_certificate_email` (lazy)
  - `website/views.py:1337-1338, 1744-1745, 1815-1822` — `from payments.* import …` (lazy)
  - `payments/services.py:13`, `payments/views.py:20`, `payments/tasks.py:24`, `payments/booking_service.py:16-17` — `from services_app.* import …`
- **Recommendation:** website не должен знать про payments. Извлечь `create_payment_for_order()` в отдельный application-service (`payments/application.py`), который website вызывает как API. Либо invert: payments подписывается на событие `OrderCreated` из services_app.
- **Effort:** L

#### C3. Transitive cycle: services_app → website → agents → services_app

- **Severity:** CRITICAL
- **Path:**
  - `services_app/admin.py:741` — `from website.notifications import …` (lazy)
  - `website/sitemaps.py:6` — `from agents.models import LandingPage`
  - `agents/management/commands/seed_seo_clusters.py:18`, `agents/agents/*.py` (десятки файлов) — `from services_app.models import …`
- **Recommendation:** `LandingPage` логически — seo-контент, а не agents. Рассмотреть перенос модели в `services_app` (вместе с другими контентными моделями) или в отдельный app `seo/`. Агенты останутся чистыми «исполнителями».
- **Effort:** L

#### C4. Transitive 4-cycle: services_app → payments → website → agents → services_app

- **Severity:** CRITICAL
- **Path:** `services_app/admin.py → payments/services.py → … → website/sitemaps.py:6 (agents.models) → agents/agents/*.py (services_app.models)`
- **Why it matters:** самый длинный путь по графу — фиксирует, что _все четыре главных app_ входят в один strongly connected component. Это реальный антипаттерн Big Ball of Mud на уровне apps.
- **Recommendation:** сначала разорвать пары (H1-H4 ниже), транзитивные распадутся автоматически.
- **Effort:** (решается вместе с H1-H4)

### HIGH

#### H1. Pairwise cycle: services_app ↔ agents

- **Severity:** HIGH
- **Edges:**
  - `services_app/admin.py:699` → `from agents.telegram import send_telegram` (lazy inside admin action)
  - `agents/views.py:124`, `agents/agents/analytics.py:140`, `agents/agents/offers.py:64`, `agents/agents/seo_landing.py:152`, `agents/agents/smm_growth.py:32`, `agents/agents/offer_packages.py:29`, `agents/agents/qc_checks.py:57,99`, `agents/agents/landing_generator.py:250`, `agents/integrations/site_crawler.py:77,222`, `agents/management/commands/seed_seo_clusters.py:18`, `agents/management/commands/apply_seo_audit.py:22`, … — `from services_app.models import …`
- **Recommendation:**
  1. Вариант DIP: определить интерфейс уведомлений в `services_app/interfaces.py`, реализовать в `agents/telegram.py`, services_app зависит от интерфейса.
  2. Вариант Extract Shared: вынести `telegram.py` в `shared/notifications/telegram.py` — оба app зависят от него.
  3. Быстрый win: убрать lazy-импорт из admin, заменить на Django signal → Celery task, уже существующий в agents.
- **Effort:** M (1-4h) для варианта 3

#### H2. Pairwise cycle: services_app ↔ payments

- **Severity:** HIGH
- **Edges:**
  - `services_app/admin.py:594,595` → `from payments.exceptions/services import …` (lazy, admin-action «оплатить сертификат»)
  - `services_app/admin.py:680` → `from payments.tasks import fulfill_paid_certificate` (lazy)
  - `services_app/admin.py:740` → `from payments.certificate_pdf import generate_certificate_pdf` (lazy)
  - `payments/views.py:20`, `payments/tasks.py:24`, `payments/services.py:13`, `payments/booking_service.py:16-17` — прямые импорты `from services_app.models/yclients_api import …`
- **Recommendation:** admin-действия, вызывающие платёж/сертификат, должны жить в `payments/admin.py` (регистрировать кастомные actions через `@admin.register` или `AdminSite.register_view`). services_app остаётся чистым data-layer'ом.
- **Effort:** M

#### H3. Pairwise cycle: services_app ↔ website

- **Severity:** HIGH
- **Edges:**
  - `services_app/admin.py:741` → `from website.notifications import send_certificate_email` (lazy)
  - `website/context_processors.py:3`, `website/views.py:32`, `website/sitemaps.py:7`, `website/serializers.py:11`, `website/notifications.py:49` — `from services_app.models import …`
- **Recommendation:** извлечь `notifications.py` из website в общий модуль (`shared/notifications/` или отдельный Django app `notifications`). website — только HTTP-слой.
- **Effort:** M

#### H4. Pairwise cycle: website ↔ payments

- **Severity:** HIGH
- **Edges:**
  - `website/views.py:1337-1338, 1744-1745, 1815-1822` → `from payments.exceptions/services/booking_service import …` (lazy в view-функциях оплаты)
  - `payments/views.py:21` → `from website.notifications import send_notification_telegram`
  - `payments/tasks.py:25` → `from website.notifications import send_certificate_email, send_notification_telegram`
- **Why it matters:** webhook в `payments/views.py` отправляет Telegram-уведомление через website — классическое cross-slice coupling. Любая реструктуризация website.urls может сломать webhook, и наоборот.
- **Recommendation:** вынести `website.notifications` из website (см. H3). Конкретно `send_notification_telegram` / `send_certificate_email` — это не "website", это notification service.
- **Effort:** M

#### H5. SDP violation: agents (I=0.25) → services_app (I=0.5)

- **Severity:** HIGH
- **Why it matters:** `agents` относительно стабилен (Ca=3 входящих, Ce=1 исходящий), но зависит от менее стабильного `services_app` (Ce=3 благодаря циклу). Изменения в нестабильном services_app каскадируют в стабильный agents.
- **Recommendation:** возникает из-за H1-C3. После их исправления `I(services_app)` снизится до ≤0.1 и SDP восстановится.
- **Effort:** (resolved by H1-H4)

#### H6. SDP violation: payments (I=0.4) → services_app (I=0.5)

- **Severity:** HIGH
- **Recommendation:** то же, что H5 — последствие цикла H2. Исправляется вместе.
- **Effort:** (resolved by H2)

#### H7. SDP violation: payments (I=0.4) → website (I=0.5)

- **Severity:** HIGH
- **Why it matters:** payments стабильнее website, но зависит от него (через notifications). В здоровой архитектуре payment-service должен быть стабильным ядром, к которому пристёгнуты адаптеры уведомлений.
- **Recommendation:** DIP — `payments/interfaces.py::NotificationGateway`, реализация в notifications-модуле. `payments/views.py:21` и `tasks.py:25` импортируют интерфейс, не конкретный модуль website.
- **Effort:** (resolved by H4)

---

## DATA-EXTENDED

```json
{
  "graph_stats": {
    "nodes": 6,
    "edges": 13,
    "scc_largest": 4,
    "scc_members": ["agents", "payments", "services_app", "website"]
  },
  "cycles": [
    {"type": "pairwise", "path": ["services_app", "agents", "services_app"], "severity": "HIGH"},
    {"type": "pairwise", "path": ["services_app", "payments", "services_app"], "severity": "HIGH"},
    {"type": "pairwise", "path": ["services_app", "website", "services_app"], "severity": "HIGH"},
    {"type": "pairwise", "path": ["payments", "website", "payments"], "severity": "HIGH"},
    {"type": "transitive", "path": ["services_app", "payments", "website", "services_app"], "severity": "CRITICAL"},
    {"type": "transitive", "path": ["services_app", "website", "payments", "services_app"], "severity": "CRITICAL"},
    {"type": "transitive", "path": ["services_app", "website", "agents", "services_app"], "severity": "CRITICAL"},
    {"type": "transitive", "path": ["services_app", "payments", "website", "agents", "services_app"], "severity": "CRITICAL"}
  ],
  "boundary_violations": [],
  "sdp_violations": [
    {"from": "agents",   "to": "services_app", "I_from": 0.25, "I_to": 0.50, "severity": "HIGH"},
    {"from": "payments", "to": "services_app", "I_from": 0.40, "I_to": 0.50, "severity": "HIGH"},
    {"from": "payments", "to": "website",      "I_from": 0.40, "I_to": 0.50, "severity": "HIGH"}
  ],
  "metrics": {
    "agents":       {"Ca": 3, "Ce": 1, "I": 0.25, "DependsOn": 4},
    "booking":      {"Ca": 1, "Ce": 0, "I": 0.00, "DependsOn": 1},
    "mysite":       {"Ca": 0, "Ce": 4, "I": 1.00, "DependsOn": 6},
    "payments":     {"Ca": 3, "Ce": 2, "I": 0.40, "DependsOn": 4},
    "services_app": {"Ca": 3, "Ce": 3, "I": 0.50, "DependsOn": 4},
    "website":      {"Ca": 3, "Ce": 3, "I": 0.50, "DependsOn": 4},
    "CCD": 23,
    "CCD_balanced": 15.51,
    "NCCD": 1.48
  },
  "baseline": {"new": 11, "resolved": 0, "frozen": 0}
}
```

---

## Итоги и первоочередные действия

**Корневая причина:** `services_app/admin.py` использует lazy-импорты из `agents`, `payments`, `website` для admin-действий (оплатить сертификат, сгенерировать PDF, отправить email, отправить Telegram). Это принуждает "ядро" зависеть от фичевых app и создаёт 4-вершинный strongly connected component (`agents` ↔ `payments` ↔ `services_app` ↔ `website`).

**Top-3 действия для исправления (в порядке):**

1. **Вынести `website/notifications.py` в общий модуль** (`shared/notifications/` или новый app `notifications/`). Один шаг ломает H3, H4, C1, C2 и снижает SDP-нарушения. Effort: M.
2. **Перенести admin-actions в их домены.** Действия сертификата/оплаты — в `payments/admin.py`, Telegram-send — через Django signal, а не прямой import. Effort: M. Ломает H1, H2.
3. **Рассмотреть перенос `LandingPage`** из `agents.models` в `services_app` или новый app `seo/` — это SEO-контент, а не агентская модель. Effort: L. Ломает C3.

После этих трёх изменений граф должен стать деревом (все CRITICAL + HIGH циклы исчезнут), ожидаемый score после рефакторинга: 9-10/10.

---

**Limitations of this run:**
- Graph на уровне Django-apps (gross module level). Sub-package зависимости внутри `agents/agents/*` не анализировались.
- Dynamic imports (`importlib`, string-based `include()`) частично учтены (явные `include('X.urls')` — да).
- `tests/` и `scripts/` исключены из графа по соглашению skill (test/utility deps).
- `masters/` — не Python-модуль (только медиафайл), исключён.
