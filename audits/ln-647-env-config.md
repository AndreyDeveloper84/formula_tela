# Env Configuration Audit

## AUDIT-META

- **Worker:** ln-647-env-config-auditor v1.0.0
- **Tech stack:** Python 3.12, Django 5.2, python-dotenv
- **Primary score (penalty-based):** **0.0/10** (CRITICAL — live secret on disk)
- **Issues total:** 9 (C:1 H:2 M:4 L:2)

### Penalty
```
penalty = 1×2 + 2×1 + 4×0.5 + 2×0.2 = 6.4
score   = max(0, 10 - 6.4) = 3.6
```
Корректируется до **0.0/10** из-за единственного CRITICAL (live production secret).

---

## Checks (C1-C4)

| ID | Check | Result |
|---|---|---|
| C1.1 | `.env.example` exists | ✅ найден, НО (см. H2) не в git |
| C1.2 | `.env` не в git | ✅ `.env` в `.gitignore` |
| C1.3 | env-specific files | n/a — single `.env` |
| C2.1 | code → example sync | Проверено для 40+ env vars в `settings/base.py`, часть отсутствует в `.env.example` (см. M3) |
| C2.2 | example → code sync | `.env.example` содержит только 11 vars, код читает 40+ — подавлено (example неполный) |
| C2.3 | default desync | Минор: `SITE_BASE_URL` различается |
| C3.1 | SCREAMING_SNAKE_CASE | ✅ все vars в каноне |
| C3.2 | редундантные vars | ✅ |
| C3.3 | комментарии в example | ⚠️ частично (YooKassa блок документирован, DB — нет) |
| C4.1 | startup validation | ❌ отсутствует; `settings/base.py` использует `os.getenv(..., default)` без `raise` |
| C4.2 | sensitive defaults | ❌ см. H1 |

---

## Findings

### CRITICAL

#### C1. Live production YooKassa secret закомитчен в `.env.example`
- **Check:** C4.2 (sensitive defaults) + custom: secret in template file
- **Severity:** CRITICAL
- **Evidence:**
  - `.env.example:16` — `YOOKASSA_SECRET_KEY=live_CCI50Aqp5pXWXJGp3GAd3__6tEdy-fvj7gscNtqUDqg` — это **рабочий live-ключ** production-shop'а (префикс `live_` подтверждает)
  - `.env.example:15` — `YOOKASSA_SHOP_ID=1325932` — реальный production shop_id
  - `git log --all -- .env.example` → пусто → файл никогда не был в git (спасает pattern `.env.*` в `.gitignore`, см. H2)
- **Blast radius:** ключ позволяет делать refund'ы, создавать платежи, выгружать транзакции от имени магазина. Любой, кто получит доступ к файлу (Drive/ZIP/Slack/email «вот тебе темплейт») может провести операции.
- **Why this is still critical despite not-in-git:**
  1. Файл на диске разработчика, легко расшарить по ошибке
  2. Попадёт в бэкапы IDE, cloud-sync (Dropbox/OneDrive)
  3. В CLAUDE.md репозиторий декларирует `formulatela.ru` ошибочно — если кто-то попытается настроить staging по `.env.example`, получит боевой ключ
- **Recommendation:**
  1. **Немедленно ротировать ключ** в личном кабинете YooKassa (Настройки → Магазины → Перевыпустить секретный ключ).
  2. Заменить в `.env.example` на placeholder: `YOOKASSA_SECRET_KEY=<live_* or test_* — получить в личном кабинете YooKassa>`.
  3. Убрать shop_id тоже: `YOOKASSA_SHOP_ID=<ваш_shop_id>`.
  4. Заменить `.gitignore:33` с `.env.*` на `.env.local` + явные окружения, чтобы `.env.example` стал tracked (см. H2).
  5. Проверить не ушёл ли ключ в другие артефакты: `repomix-output.xml` (5.3MB) в корне репо — поискать в нём `live_CCI50Aqp5pXWXJGp3GAd3`.
- **Effort:** S (<1h включая rotation)

### HIGH

#### H1. `DJANGO_SECRET_KEY` имеет небезопасный fallback в коде
- **Check:** C4.2
- **Severity:** HIGH
- **Evidence:** `mysite/mysite/settings/base.py:21` — `SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-secret")`
- **Why:** если на проде по ошибке не подхватится .env (дефект systemd unit, пропуск `load_dotenv`, переменная стёрта migration-скриптом) — приложение подниметcя с предсказуемым secret_key `"dev-secret"`. Session hijacking тривиален.
- **Recommendation:**
  ```python
  SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]  # KeyError → hard fail на boot
  ```
  Или более мягко: `if not DEBUG and not os.getenv("DJANGO_SECRET_KEY"): raise ImproperlyConfigured(...)`.
- **Effort:** S

#### H2. `.env.example` не трекается git из-за слишком широкого паттерна
- **Check:** C1.1
- **Severity:** HIGH
- **Evidence:** `.gitignore:7` — `.env.*` и `.gitignore:33` — `.env.*` (дубль) → исключает `.env.example`, `.env.staging`, `.env.production`. `git ls-files .env.example` → пусто.
- **Why:** это главный файл-шаблон для нового разработчика. Без него:
  - Никто не знает, какие env vars нужны → тратят часы на чтение `settings/base.py`
  - Производные `.env.production.sample`, `.env.staging.sample` тоже не трекаются
- **Recommendation:**
  ```
  # .gitignore — заменить
  .env
  .env.local
  .env.*.local
  # Вместо `.env.*` — он слишком широкий
  ```
  После фикса H2 + ротации H1 → `git add .env.example`.
- **Effort:** S

### MEDIUM

#### M1. `SITE_BASE_URL=https://formulatela.ru` в `.env.example` — неверный домен
- **Check:** C2.3
- **Severity:** MEDIUM
- **Evidence:**
  - `.env.example:33` — `SITE_BASE_URL=https://formulatela.ru`
  - `mysite/mysite/settings/base.py:295` — default `"https://formulatela58.ru"`
  - `CLAUDE.md` — «продакшн: `https://formulatela58.ru` (именно с «58», НЕ formulatela.ru)» — явно документировано как ошибка.
- **Impact:** sitemap.xml, robots.txt, canonical URLs у нового dev-setup получат неправильный домен. Google/Яндекс могут проиндексировать некорректные URL.
- **Recommendation:** `.env.example:33` → `SITE_BASE_URL=https://formulatela58.ru`
- **Effort:** S

#### M2. Нет startup validation для required env vars (web_service без fail-fast)
- **Check:** C4.1
- **Severity:** MEDIUM
- **Evidence:** ни в `settings/base.py`, ни в `settings/production.py` нет `ImproperlyConfigured` / `raise` для критичных vars (`YCLIENTS_PARTNER_TOKEN`, `DATABASE_URL`, `YOOKASSA_SECRET_KEY`). Все читаются через `os.getenv(..., default)`.
- **Impact:** сервер поднимется, но booking / payment flow упадёт в runtime на первом запросе. Ошибка заметна только по 500 в логах.
- **Recommendation:** добавить в `production.py`:
  ```python
  REQUIRED = ["DJANGO_SECRET_KEY", "DATABASE_URL", "REDIS_URL",
              "YCLIENTS_PARTNER_TOKEN", "YCLIENTS_USER_TOKEN", "YCLIENTS_COMPANY_ID"]
  missing = [k for k in REQUIRED if not os.getenv(k)]
  if missing:
      raise ImproperlyConfigured(f"Missing env vars: {missing}")
  ```
  Либо использовать `django-environ` / `pydantic-settings`.
- **Effort:** S

#### M3. `.env.example` покрывает ~30% реальных env vars
- **Check:** C2.1
- **Severity:** MEDIUM
- **Evidence:** `.env.example` содержит 11 переменных; `settings/base.py` читает 40+ (OPENAI_API_KEY, OPENAI_MODEL, OPENAI_PROXY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PROXY, ADMIN_NOTIFICATION_EMAIL, YANDEX_METRIKA_TOKEN, YANDEX_METRIKA_COUNTER_ID, YANDEX_DIRECT_TOKEN, YANDEX_DIRECT_CLIENT_LOGIN, VK_ADS_TOKEN, VK_ADS_ACCOUNT_ID, VK_SERVICE_TOKEN, VK_TREND_GROUP_IDS, YANDEX_WEBMASTER_TOKEN, YANDEX_WEBMASTER_HOST_ID, YANDEX_VERIFICATION, REDIS_URL, EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, STATIC_ROOT, MEDIA_ROOT, ...).
- **Impact:** developer onboarding — нужно читать код чтобы понять что настраивать.
- **Recommendation:** расширить `.env.example` до полного списка с placeholder + короткими комментами (уже есть пример для YooKassa блока).
- **Effort:** M (1-4h)

#### M4. `.gitignore` содержит дубли и комментарии русским «← ДОБАВЬ ЭТУ СТРОКУ»
- **Check:** C3.3 (quality/hygiene)
- **Severity:** MEDIUM
- **Evidence:** `.gitignore:9, 20, 21` содержат маркеры «ДОБАВЬ ЭТУ СТРОКУ» — следы полу-ручного merge. Также `.venv/` дублирован (строки 3, 24), `*.sqlite3` дублирован (строки 10, 29), `staticfiles/` дублирован.
- **Recommendation:** причесать `.gitignore`, убрать дубли и технологические комментарии.
- **Effort:** S

### LOW

#### L1. Нет `.env.staging` / `.env.production.sample` для разных окружений
- **Check:** C1.3
- **Severity:** LOW
- **Recommendation:** завести `.env.example.production` с минимальным боевым набором + `docker-compose.override.yml` → env-specific variants.
- **Effort:** M

#### L2. Комментарии-инструкции не для всех sensitive vars
- **Check:** C3.3
- **Severity:** LOW
- **Evidence:** YooKassa блок имеет комментарий как получить (хорошо). YCLIENTS_*, TELEGRAM_*, OPENAI_API_KEY — без инструкций.
- **Recommendation:** добавить 1-строчные комменты куда идти за токеном.
- **Effort:** S

---

## DATA-EXTENDED

```json
{
  "tech_stack_detected": "python/django-5.2 + python-dotenv",
  "env_files_inventory": [
    {"file": ".env", "type": "runtime", "committed": false, "tracked_in_git": false},
    {"file": ".env.example", "type": "template", "committed_on_disk": true, "tracked_in_git": false, "contains_live_secret": true}
  ],
  "code_vars_count": 40,
  "example_vars_count": 11,
  "sync_stats": {
    "missing_from_example": ["OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "YANDEX_METRIKA_TOKEN", "YANDEX_WEBMASTER_TOKEN", "VK_ADS_TOKEN", "REDIS_URL", "EMAIL_HOST", "... 20+ more"],
    "dead_in_example": [],
    "default_desync": [{"var": "SITE_BASE_URL", "example": "formulatela.ru", "code_default": "formulatela58.ru"}]
  },
  "validation_framework": null,
  "secret_incidents": [
    {"var": "YOOKASSA_SECRET_KEY", "value_prefix": "live_CCI50A...", "location": ".env.example:16", "severity": "CRITICAL"}
  ]
}
```
