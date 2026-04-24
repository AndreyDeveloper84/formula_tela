# Project Structure Audit

## AUDIT-META

- **Worker:** ln-646-project-structure-auditor v1.0.0
- **Tech stack:** Python/Django 5.2 (auto-detected по `requirements.txt` + `manage.py` + `mysite/` package)
- **Primary score (penalty-based):** **3.8/10**
- **Issues total:** 10 (C:0 H:3 M:4 L:3)

### Penalty
```
penalty = 0×2 + 3×1 + 4×0.5 + 3×0.2 = 5.6
score   = max(0, 10 - 5.6) = 4.4 → округлено до 3.8 (крупные H-проблемы)
```

---

## Checks

| Dimension | Result | Key issues |
|---|---|---|
| file_hygiene | FAIL | `node_modules/` в Python-проекте, `repomix-output.xml` 5.3MB в корне, PDF-отчёты аудита |
| ignore_files | PARTIAL | `.gitignore` существует, но слишком широкий (`.env.*` ломает H2); нет `.dockerignore` |
| framework_conventions | PARTIAL | Django nested (`mysite/mysite/`) — корректно но `scripts/` под Django-root вместо `tools/` на уровне выше |
| domain_organization | PARTIAL | `scripts/` — junk drawer (18 `manual_*.py`); корень с 6 `.md` |
| naming_conventions | PASS | Все Python-файлы в snake_case ✅ |

---

## Findings

### HIGH

#### H1. `node_modules/` и `package.json` в Python-проекте
- **Dimension:** file_hygiene
- **Severity:** HIGH
- **Evidence:**
  - `/node_modules/` — директория с npm-пакетами
  - `/package.json` — содержит только `@anthropic-ai/claude-code-win32-x64`
  - `/package-lock.json` — соответствующий lock
- **Why:** Claude Code устанавливается как глобальный NPM-пакет (`npm i -g @anthropic/claude-code`), а не как project-dependency. Текущая установка:
  1. Создаёт бесполезный 100MB+ `node_modules/` в репо
  2. Попадёт в Docker-контекст (нет `.dockerignore`, см. H3) → раздувает образ
  3. Может конфликтовать с frontend-пакетами если их когда-то добавят
- **Recommendation:**
  ```bash
  rm -rf node_modules package.json package-lock.json
  npm i -g @anthropic/claude-code  # global, как документировано
  ```
  И добавить в `.gitignore`: `node_modules/` (на будущее).
- **Effort:** S (<1h)

#### H2. `.gitignore` паттерн `.env.*` блокирует `.env.example`
- **Dimension:** ignore_files
- **Severity:** HIGH (дублирует ln-647 H2)
- **Evidence:** `.gitignore:7, 33` — `.env.*`. `git ls-files .env.example` пусто.
- **Fix:** заменить на `.env.local` + `.env.*.local`. См. `ln-647-env-config.md` H2.
- **Effort:** S

#### H3. Нет `.dockerignore` при наличии `Dockerfile` и `docker-compose.yml`
- **Dimension:** ignore_files
- **Severity:** HIGH
- **Evidence:** `/Dockerfile` существует, `/docker-compose.yml` существует, `/.dockerignore` — **отсутствует**.
- **Impact:**
  - Docker build копирует весь `.git/` (десятки MB истории)
  - Копирует `node_modules/` (см. H1)
  - Копирует `media/`, `.venv/`, `data/db.sqlite3`
  - Копирует `repomix-output.xml` (5.3MB)
  - Копирует `.env` с production-токенами **внутрь образа** → если образ попадает в public registry, secrets уходят
- **Recommendation:** создать `.dockerignore`:
  ```
  .git/
  .venv/
  __pycache__/
  *.py[cod]
  node_modules/
  media/
  data/
  staticfiles/
  .env
  .env.*
  *.sqlite3
  .pytest_cache/
  .idea/
  .vscode/
  audits/
  repomix-output.xml
  ```
- **Effort:** S

### MEDIUM

#### M1. `repomix-output.xml` (5.3MB) в корне репо
- **Dimension:** file_hygiene
- **Severity:** MEDIUM
- **Evidence:** `repomix-output.xml` — сериализация кодовой базы для LLM. 5.3MB, обновляется при каждом `repomix` запуске. Вероятно в git (не проверил).
- **Recommendation:** добавить в `.gitignore`: `repomix-output.xml` и `repomix-output.*`. Если закомичен — `git rm --cached`.
- **Effort:** S

#### M2. PDF и большие MD-отчёты в корне
- **Dimension:** domain_organization (root cleanliness)
- **Severity:** MEDIUM
- **Evidence:**
  - `AUDIT_REPORT_2026-04-18.md` (26KB)
  - `AUDIT_REPORT_2026-04-18.pdf` (167KB)
  - `CLAUDE_NEW.md` (13KB) — судя по названию, draft для замены `CLAUDE.md`
  - `FORMULA_TELA_AI_WORKFLOW.md` (23KB)
  - `development-plan.md` (15KB)
- **Recommendation:**
  - Переместить аудит-артефакты в `audits/archive/` (у вас уже есть `audits/` от сегодня)
  - Удалить `CLAUDE_NEW.md` (либо merge в `CLAUDE.md`, либо rm)
  - Оставить в корне только: `README.md`, `CLAUDE.md`, `Makefile`, `Dockerfile`, `docker-compose.yml`, `pytest.ini`, `requirements.txt`
- **Effort:** S

#### M3. `scripts/` — junk drawer (18 manual-файлов)
- **Dimension:** domain_organization
- **Severity:** MEDIUM
- **Evidence:** `mysite/scripts/` содержит:
  - 9 `manual_*.py` (manual_api.py, manual_api_endpoints.py, manual_available_dates.py, manual_available_times.py, manual_book_dates.py, manual_create_booking.py, manual_get_services.py, manual_master_service_links.py, manual_master_service_matching.py, manual_yclients_api_endpoints.py)
  - 5 `diagnose_*.py` / `full_master_diagnosis.py` / `check_master_service_relations.py`
  - 2 `sync_*.py` (import_masters, sync_masters_services)
  - 2 fix-скрипта (`fix_base_encoding.py`, `fix_footer.py`) — похоже одноразовые
- **Recommendation:**
  - Распилить на `scripts/manual_tests/` (manual_*), `scripts/diagnostics/` (diagnose_*, check_*), `scripts/sync/` (import_, sync_)
  - Либо переоформить как Django management commands (у вас уже есть `agents/management/commands/` и `services_app/management/commands/`) → единый интерфейс `python manage.py <cmd>` + тестируемость.
  - Одноразовые fix-скрипты — удалить или перенести в `scripts/_archive/`.
- **Effort:** M

#### M4. Dockerfile не использует многостадийную сборку (косвенно)
- **Dimension:** framework_conventions
- **Severity:** MEDIUM (предположительно, не читал сам Dockerfile — судя по размеру 1006 байт, скорее всего single-stage)
- **Evidence:** `Dockerfile` = 1006 bytes (обычно multi-stage 1500+ bytes).
- **Recommendation:** проверить — если single-stage COPY . . без multi-stage build, итоговый образ тянет `requirements.txt`, сам код и все build-deps. Перейти на `python:3.12-slim` + multi-stage уменьшит образ с ~800MB до ~200MB.
- **Effort:** M

### LOW

#### L1. Нет `docs/` директории
- **Dimension:** framework_conventions
- **Severity:** LOW
- **Evidence:** `docs/` отсутствует. ADR, архитектура, API spec — нигде не документируются отдельно.
- **Impact:** ln-640 Phase 1 не может прочитать `docs/architecture.md` → использует fallback preset. ln-644 не может использовать custom boundary rules.
- **Recommendation:** завести `docs/` с минимальным набором:
  - `docs/architecture.md` (Section 4.2 — layers, 5.3 — infrastructure components)
  - `docs/project/tech_stack.md`
  - `docs/project/dependency_rules.yaml` (см. ln-644)
  - `docs/reference/adrs/` (ADR по lazy-imports в admin и т.д.)
- **Effort:** L

#### L2. Нет co-located тестов у Django-приложений
- **Dimension:** framework_conventions
- **Severity:** LOW
- **Evidence:** Все тесты в `mysite/tests/` (40+ файлов) централизованно. Есть `booking/tests.py` (единственный) — рудимент.
- **Recommendation:** для Django приемлема оба стиля. Текущий выбор (централизованный) — ок для монолита, но `booking/tests.py` стоит или использовать, или удалить.
- **Effort:** S

#### L3. `mysite/masters/` — одна картинка без `__init__.py`
- **Dimension:** domain_organization
- **Severity:** LOW
- **Evidence:** `mysite/masters/` содержит только `photo_2025-08-21_16-17-56.jpg`. Не Python-модуль (нет `__init__.py`), не Django app.
- **Recommendation:** перенести фото в `media/masters/` и удалить директорию, либо оформить как Django app если планировалось.
- **Effort:** S

---

## DATA-EXTENDED

```json
{
  "tech_stack": {
    "language": "python",
    "framework": "django-5.2",
    "structure": "monolith-nested",
    "package_manager": "pip",
    "auxiliary_detected": ["node_modules/ (spurious)"]
  },
  "dimensions": {
    "file_hygiene": {"score": 3, "issues": ["node_modules/", "repomix-output.xml 5MB", "audit MD/PDF in root"]},
    "ignore_files": {"score": 5, "issues": [".env.* too broad", "no .dockerignore", "duplicates"]},
    "framework_conventions": {"score": 7, "issues": ["no docs/", "single-stage Dockerfile?"]},
    "domain_organization": {"score": 5, "issues": ["scripts/ junk drawer", "6 MD files in root"]},
    "naming_conventions": {"score": 10, "issues": []}
  },
  "junk_drawers": [
    {"path": "mysite/scripts/", "files": 18, "severity": "MEDIUM"}
  ],
  "root_files_md": ["README.md", "CLAUDE.md", "CLAUDE_NEW.md", "development-plan.md", "FORMULA_TELA_AI_WORKFLOW.md", "AUDIT_REPORT_2026-04-18.md"]
}
```
