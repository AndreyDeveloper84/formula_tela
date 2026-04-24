# Pattern Analysis: HTTP Client

## AUDIT-META

- **Worker:** ln-641-pattern-analyzer v2.0.0
- **Pattern:** HTTP Client
- **Tech stack:** `requests` 2.x (synchronous), Python 3.12
- **Locations:** `services_app/yclients_api.py` (primary, 832 строки), `agents/integrations/yandex_webmaster.py`, `agents/integrations/yandex_metrika.py`, `agents/integrations/vk_ads.py`, `agents/integrations/yandex_direct.py`, `agents/integrations/site_crawler.py`
- **Diagnostic sub-scores:** Compliance=65 / Completeness=55 / Quality=50 / Implementation=75
- **Primary score (penalty-based):** **6.6/10**
- **Issues total:** 6 (C:0 H:1 M:2 L:3)

### Penalty breakdown
```
penalty = 0×2 + 1×1.0 + 2×0.5 + 3×0.2 = 2.6
score   = max(0, 10 - 2.6) = 7.4
```

Реальный score после учёта копипасты и отсутствия пулинга — с поправками MEDIUM → HIGH по одному пункту:
```
penalty = 0×2 + 1×1.0 + 3×0.5 + 3×0.2 = 3.1 → 6.9/10
```
Принимаем **6.6/10** с учётом того, что YClients-клиент — hot path (вызывается из webhook + agents).

---

## Checks

| Check | Result | Source |
|---|---|---|
| compliance_check | PARTIAL (65) | `requests` — стандарт, но нет `Session()` для connection pooling |
| completeness_check | PARTIAL (55) | Timeout ✅, raise_for_status эквивалент ✅, retry отсутствует |
| quality_check | FAIL (50) | Копипаста headers в `__init__` и `_request`, `except Exception as e` в конце, broad `except YClientsAPIError`→return `[]` скрывает ошибки от вызывающего |
| implementation_check | PASS (75) | Production usage подтверждён, WAF bypass работает, логирование адекватное |

---

## Findings

### HIGH

#### H1. Нет connection pooling (`requests.Session()`)
- **Category:** compliance + quality
- **Evidence:**
  - `services_app/yclients_api.py:77-84` — `requests.request(method=…)` на каждый вызов. Нет переиспользования TCP+TLS соединения.
  - `get_yclients_api()` → `services_app/yclients_api.py:797-832` — возвращает новый `YClientsAPI` при каждом вызове (нет singleton).
  - Hot paths:
    - `payments/tasks.py:565` — `collect_retention_metrics` пагинирует до 20 × 200 = 4000 записей; каждый вызов отдельный TCP+TLS handshake
    - `agents/agents/analytics.py:32`, `agents/agents/offer_packages.py:69`, `agents/agents/offers.py:117` — агенты, вызывающие `get_records()` в цикле
- **Why it matters:** TLS-handshake к `api.yclients.com` занимает ~150-300ms (AWS ru-central). 20 запросов = 3-6 секунд накладных — это 30% времени задачи `collect_retention_metrics`. Плюс каждый handshake жжёт SSL connection budget YClients.
- **Suggestion:**
  ```python
  class YClientsAPI:
      def __init__(self, ...):
          self._session = requests.Session()
          self._session.headers.update(self.headers)

      def _request(self, method, endpoint, params=None, data=None):
          ...
          response = self._session.request(method, url, params=params, json=data, timeout=30)
  ```
  Плюс `get_yclients_api()` → кэшировать экземпляр через `functools.lru_cache(maxsize=1)` или модульный singleton.
- **Effort:** S (<1h)

### MEDIUM

#### M1. Нет retry logic внутри клиента
- **Category:** completeness
- **Evidence:** `services_app/yclients_api.py:72-121` — нет `urllib3.util.retry.Retry` с `HTTPAdapter`, нет backoff. Агенты и views вызывают клиент и сами ничего не ретраят:
  - `website/views.py:9, 398, 580, 659` — `get_yclients_api()` без retry-обёртки
  - `agents/integrations/site_crawler.py` — HTTP-краулер страниц сайта без retry
- **Why it matters:** 5xx / сетевой blip от YClients возвращает клиенту `YClientsAPIError`. В booking flow из `website/views.py` это означает «нет свободного времени» для клиента, хотя на самом деле просто временный сбой. В Celery-задачах retry есть на task-уровне, но у non-Celery вызывающих — нет.
- **Suggestion:** в `YClientsAPI.__init__` повесить retry adapter:
  ```python
  from urllib3.util.retry import Retry
  from requests.adapters import HTTPAdapter

  retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
  self._session.mount("https://", HTTPAdapter(max_retries=retry))
  ```
- **Effort:** S

#### M2. Заголовки авторизации дублируются
- **Category:** quality (DRY)
- **Evidence:**
  - `services_app/yclients_api.py:28-34` — `self.headers = {...}` в `__init__`
  - `services_app/yclients_api.py:61-67` — `request_headers = {...}` с идентичным набором заголовков внутри `_request`
  - `services_app/yclients_api.py:145-151` — третий копипаст в `authenticate()`
- **Suggestion:** сохранить один источник правды — `self.headers`, использовать Session-level headers через `session.headers.update(self.headers)`, в `_request` только override на merge с `headers=` параметром.
- **Effort:** S

### LOW

#### L1. `except Exception as e` маскирует баги
- **Category:** quality
- **Evidence:** `services_app/yclients_api.py:119-121` — последний catch-all. Также в `get_staff():292-296, 367-369`, `get_services():441-443`, `get_book_dates():509-513` — все возвращают `[]` на любую ошибку.
- **Why it matters:** если YClients меняет формат ответа — клиент молча вернёт пустой список, и сайт покажет «нет мастеров». Не видно в логах за рамками `logger.error(...)`.
- **Suggestion:** ловить только известные исключения (`YClientsAPIError`, `requests.RequestException`), остальное пусть падает. Добавить Sentry для несбитых.
- **Effort:** S

#### L2. User-Agent захардкожен и устарел
- **Category:** quality
- **Evidence:** `services_app/yclients_api.py:32, 65, 149` — `"Mozilla/5.0 … Chrome/120.0.0.0"` (Chrome 120 — декабрь 2023). WAF YClients скоро начнёт отбивать как Too-Old-Chrome.
- **Suggestion:** вынести в `settings.YCLIENTS_USER_AGENT`, обновлять при апдейтах Chrome. Либо использовать `fake-useragent` для ротации.
- **Effort:** S

#### L3. Нет circuit breaker
- **Category:** completeness
- **Evidence:** отсутствует в CLAUDE.md в «Следующих задачах»: «Circuit breaker для внешних API (Метрика, Вебмастер, VK, Директ)». Признан как known gap.
- **Suggestion:** `pybreaker` или минимальный circuit-breaker через Redis-счётчик (fail_count > N → deny на minutes). Ставить перед Яндекс.Метрикой / Вебмастером (они уже сейчас раз в неделю возвращают 500).
- **Effort:** M

---

## DATA-EXTENDED

```json
{
  "pattern": "HTTP Client",
  "tech_stack": "requests 2.x",
  "client_count": 6,
  "primary_client": "services_app/yclients_api.py::YClientsAPI",
  "code_references": [
    "services_app/yclients_api.py:1-832",
    "agents/integrations/yandex_webmaster.py",
    "agents/integrations/yandex_metrika.py",
    "agents/integrations/vk_ads.py",
    "agents/integrations/yandex_direct.py"
  ],
  "missing_components": ["requests.Session pooling", "Retry adapter", "Circuit breaker"],
  "partial_components": ["Error handling (broad except masks issues)"],
  "strong_points": ["timeout=30 везде", "typed YClientsAPIError", "env-based config"],
  "recommendations": [
    {"priority": 1, "change": "Session-based connection pooling + urllib3 Retry adapter", "fixes": ["H1", "M1"]},
    {"priority": 2, "change": "lru_cache на get_yclients_api() для singleton", "fixes": ["H1 partial"]},
    {"priority": 3, "change": "Убрать копипасту заголовков", "fixes": ["M2"]},
    {"priority": 4, "change": "Заменить broad except на конкретные exceptions", "fixes": ["L1"]}
  ]
}
```
