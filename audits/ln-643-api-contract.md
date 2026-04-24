# API Contract Audit

## AUDIT-META

- **Worker:** ln-643-api-contract-auditor v2.0.0
- **Service boundaries:** `payments/services.py`, `payments/booking_service.py`, `services_app/yclients_api.py`, `website/views.py` (API endpoints)
- **Diagnostic sub-scores:** Compliance=70 / Completeness=55 / Quality=60 / Implementation=65
- **Primary score (penalty-based):** **7.6/10**
- **Issues total:** 4 (C:0 H:1 M:2 L:1)

### Penalty
```
penalty = 0×2 + 1×1 + 2×0.5 + 1×0.2 = 2.2
score   = max(0, 10 - 2.2) = 7.8 → 7.6
```

---

## Checks (5 правил)

| # | Rule | Result | Notes |
|---|---|---|---|
| 1 | Layer Leakage | PASS | Services не принимают `HttpRequest`/headers — только Django models + primitives |
| 2 | Missing DTO | PARTIAL | `YClientsAPI.create_booking(staff_id, services, datetime, client: Dict, comment, notify_by_sms, notify_by_email)` — 7 params, нет DTO. См. M1 |
| 3 | Entity Leakage | FAIL | `website/views.py::api_wizard_booking` и подобные возвращают Django ORM model fields в JSON напрямую; отсутствуют DRF Response serializers для booking endpoints. См. H1 |
| 4 | Error Contracts | PARTIAL | `YClientsAPI.get_staff() → []` on error vs `YClientsAPI.create_booking() → raises`. Inconsistent. См. M2 |
| 5 | Redundant Overloads | PARTIAL | `YClientsAPI.get_available_times` + `get_available_times_alternative` — почти дубль. См. L1 |
| 6 | Architectural Honesty | PASS | Read-named функции (`get_*`, `find_*`) не содержат write side-effects |

---

## Findings

### HIGH

#### H1. API-endpoints возвращают сериализованные словари вручную (entity leakage soft)
- **Category:** Rule 3 (Entity Leakage)
- **Severity:** HIGH (downgrade до MEDIUM если API «internal») — здесь API publicly accessible под `/api/booking/*`, `/api/wizard/*`, `/api/bundle/*`, поэтому HIGH.
- **Evidence:**
  - `website/serializers.py` — есть только для `ServiceOrderCreateSerializer` (input validation) и `normalize_ru_phone` — для output serializers **пусто**.
  - `website/views.py:32` — `from services_app.models import (...)` и далее ручная сборка JSON: `JsonResponse({"services": [{"id": s.id, "name": s.name, ...} for s in services]})`.
  - Каждый endpoint заново форматирует model fields в dict — 1971 строк в одном файле, часть этого — ручные serializers.
- **Why it matters:**
  1. **Schema drift:** если в `Service` добавится поле — JSON endpoint его не вернёт (скрытый API break)
  2. **Security:** легко случайно вернуть sensitive field (admin_note, yclients_*_token) через `list(queryset.values())`
  3. **Contract tests:** нет единого источника правды для API response shape → DRF spectacular не может сгенерить OpenAPI
- **Recommendation:**
  - Для booking endpoints ввести DRF-serializers: `ServiceListSerializer`, `StaffSerializer`, `BookingResponseSerializer`.
  - `JsonResponse(serializer.data)` вместо ручного dict-constructоra.
  - Проект уже использует DRF (`djangorestframework` + `drf-spectacular` в CLAUDE.md) — инфраструктура есть, не используется.
- **Effort:** L (coverage через все endpoints) или M (только top-10 критичных)

### MEDIUM

#### M1. `YClientsAPI.create_booking` — 7 params, нужен request DTO
- **Category:** Rule 2 (Missing DTO)
- **Severity:** MEDIUM
- **Evidence:** `services_app/yclients_api.py:699-708`:
  ```python
  def create_booking(
      self,
      staff_id: int,
      services: List[int],
      datetime: str,
      client: Dict,
      comment: Optional[str] = None,
      notify_by_sms: int = 0,
      notify_by_email: int = 0
  ) -> Dict:
  ```
  - `client: Dict` — unstructured, внутри функции `client.get("phone")`, `client.get("name")`, `client.get("email")` — no typing.
- **Why:** callsites в `website/views.py` и `payments/booking_service.py` собирают этот dict сами — легко опечатать ключ, нет IDE-autocompletion, нет валидации.
- **Recommendation:**
  ```python
  from dataclasses import dataclass

  @dataclass(frozen=True)
  class BookingClient:
      phone: str
      name: str
      email: str = ""

  @dataclass(frozen=True)
  class BookingRequest:
      staff_id: int
      services: list[int]
      datetime: str
      client: BookingClient
      comment: str = ""
      notify_by_sms: bool = False
      notify_by_email: bool = False

  def create_booking(self, request: BookingRequest) -> dict: ...
  ```
- **Effort:** S (2-3h вместе с callsites)

#### M2. Inconsistent error contracts: read-методы возвращают `[]`, write — raise
- **Category:** Rule 4 (Error Contracts)
- **Severity:** MEDIUM
- **Evidence:**
  - `YClientsAPI.get_staff() → []` at `yclients_api.py:292-296` on any error
  - `YClientsAPI.get_services() → []` at `yclients_api.py:441-443`
  - `YClientsAPI.get_book_dates() → []` at `yclients_api.py:509-513`
  - `YClientsAPI.get_records() → []` at `yclients_api.py:791-794`
  - vs `YClientsAPI.create_booking() → raises YClientsAPIError` at `yclients_api.py:757-759`
- **Why:** caller не знает, `[]` это «никто не зарегистрирован» или «API упал». В booking flow `website/views.py::api_get_staff` при ошибке YClients покажет «нет мастеров» вместо 500.
- **Recommendation:** унифицировать — все методы raise on failure. Caller сам решает «показать пусто или ошибку». Либо Result-тип: `Ok[list[Staff]] | Err[YClientsAPIError]` через `result` package или simple namedtuple.
- **Effort:** M (нужно обновить все callsites)

### LOW

#### L1. `get_available_times` + `get_available_times_alternative` — дубль для workaround
- **Category:** Rule 5 (Redundant Overloads)
- **Severity:** LOW
- **Evidence:** `services_app/yclients_api.py:525-647` (основной) и `:654-696` (alternative). Различие: `alternative` вручную собирает URL с `?service_ids[]=N` в случае если `requests` не поддерживает массивы в params.
- **Why:** `requests` 2.x поддерживает списки в params (`params={'service_ids': [1,2,3]}` → `?service_ids=1&service_ids=2&service_ids=3`). YClients API может ждать bracket notation `service_ids[]` — это особенность PHP-style API.
- **Recommendation:** убедиться через CI-тест какой вариант работает, удалить второй. Или объединить через флаг: `def get_available_times(..., use_bracket_notation=False)`.
- **Effort:** S

---

## DATA-EXTENDED

```json
{
  "service_boundaries": {
    "api_layer": ["website/views.py (monolithic)", "agents/views.py", "payments/views.py", "mysite/urls.py"],
    "service_layer": ["payments/services.py::PaymentService", "payments/booking_service.py::YClientsBookingService", "services_app/yclients_api.py::YClientsAPI"],
    "domain_layer": ["services_app/models.py", "agents/models.py"]
  },
  "issues_by_rule": {
    "layer_leakage": 0,
    "missing_dto": 1,
    "entity_leakage": 1,
    "error_contracts": 1,
    "redundant_overloads": 1,
    "architectural_honesty": 0
  },
  "drf_usage": {
    "request_serializers": ["ServiceOrderCreateSerializer"],
    "response_serializers": [],
    "spectacular_enabled": true,
    "gap": "output serializers отсутствуют, хотя DRF+spectacular установлены"
  },
  "recommendations_priority": [
    {"priority": 1, "change": "DRF output serializers for booking/wizard endpoints", "fixes": ["H1"]},
    {"priority": 2, "change": "BookingRequest dataclass + BookingClient", "fixes": ["M1"]},
    {"priority": 3, "change": "Унифицировать error handling (raise везде)", "fixes": ["M2"]}
  ]
}
```
