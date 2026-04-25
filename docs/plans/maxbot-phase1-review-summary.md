# Code Review Summary: maxbot Фаза 1 (T-01..T-06)

**Date:** 2026-04-24
**Scope:** commits `98e88a9..d794dbe` (5 коммитов maxbot)
**Reviewers:**
1. **Layer 1** — `code-reviewer` (project-aware subagent с design-patterns + security-review-django checklist'ами) → `maxbot-phase1-review-code-reviewer.md`
2. **Layer 2a** — `ln-623-code-principles-auditor` (DRY/SOLID/YAGNI/error-handling/DI) → `maxbot-phase1-review-ln623.md` — Score **9.4/10**
3. **Layer 2b** — `ln-624-code-quality-auditor` (cyclomatic complexity/nesting/N+1) → `maxbot-phase1-review-ln624.md`

---

## Verdict: **CHANGES REQUESTED** (2 BLOCKING до staging)

Качество **выше среднего** для pre-handler стадии — TDD-дисциплина видна, патtern'ы соблюдены. Но 2 серьёзных gap'а должны быть закрыты до того как handler'ы (T-07..T-12) будут опираться на текущий фундамент.

---

## Cross-reviewer matches (= сильные сигналы)

| Finding | Layer 1 | ln-623 | ln-624 | Verdict |
|---|---|---|---|---|
| **Race condition `update_context`** | #4 Major | — | H1 HIGH | ⚠ **REAL** — фиксить до Фазы 2 |
| **`webhook_secret` unused** | #1 BLOCKING | LOW (informational) | — | 🔴 Reviewer Layer 1 поднял из LOW в BLOCKING (security) |

ln-623 (DRY/SOLID) ничего критичного не нашёл — pre-handler этап чистый по принципам. Реальные проблемы вылезли в Layer 1 (специфика проекта/security/Django) и ln-624 (метрики качества).

---

## Финальный приоритизированный план фиксов

### 🔴 CRITICAL — перед merge на staging (3 шт.)

| # | Источник | Issue | Effort |
|---|---|---|---|
| **C1** | Layer 1 #1 | `webhook_secret` читается из env, не передаётся в `dp.handle_webhook()` — публичный webhook без защиты. Проверить сигнатуру `handle_webhook` в SDK 1.0.0 и либо передать `secret_token`, либо удалить поле | M (~30 min) |
| **C2** | Layer 1 #5 | Миграция 0057 сгенерирована Django 6.0.3 (локально pip install Django ставит 6.0.3, requirements.txt пинит `<6.0`). Пересоздать в чистом venv с 5.2.x | S (~15 min) |
| **C3** | Layer 1 #2 | `tests/maxbot/test_personalization.py:6` — `pytestmark = pytest.mark.django_db` без `transaction=True`. Async-тесты с обычным `django_db` ненадёжны в CI | S (~5 min) |

### 🟡 HIGH — в этой же ветке до T-07 (handlers)

| # | Источник | Issue | Effort |
|---|---|---|---|
| **H1** | ln-624 H1 + Layer 1 #4 | `update_context`/`append_to_context` — race condition (read-modify-write без lock). `transaction.atomic + select_for_update` | S (~15 min) |
| **H2** | Layer 1 #3 | `HelpArticleQuerySet.active()` в `services_app/managers.py` — следовать проектному паттерну ДО T-11 чтобы handler сразу писал `HelpArticle.objects.active()` | S (~10 min) |
| **H3** | ln-624 M3 | `get_or_create_bot_user` лишний `save()` в else-branch → 2 query на `/start` returning user. `filter(pk=...).update(...)` | S (~10 min) |

### 🟢 MEDIUM — opportunistic (можно одним коммитом)

| # | Источник | Issue | Effort |
|---|---|---|---|
| **M1** | ln-624 M1 | Централизовать `cb:` namespace в `keyboards.py` через `_payload(*parts)` helper или `StrEnum` — до T-08 чтобы handler сразу использовал | S |
| **M2** | ln-624 M2 | `Iterable` → `Sequence[Service]` в `keyboards.services_keyboard`/`faq_keyboard` + комментарий про `select_related` | S |
| **M3** | Layer 1 #6 | `personalization.py` — top-level импорты вместо in-function (после C2 миграция стабильна, можно делать) | S |
| **M4** | ln-624 M4 | `BotUserAdmin.fields` → derive from `readonly_fields + editable_fields` | S |
| **M5** | ln-624 L5 | `BookingRequest.__str__` — добавить `[{source}]` если не wizard | S |

### 🔵 LOW — в backlog или не делаем

- **Layer 1 #9**: `MAX_BOT_TOKEN: ""` в CI env (профилактика)
- **Layer 1 #10**: `BotUser.client_phone` 20→30 (унификация с `BookingRequest`)
- **Layer 1 #7**: truncate `art.question[:64]` в faq_keyboard (надо проверить лимит SDK)
- **Layer 1 #11/12**: type annotations + django_bootstrap condition refinement
- **ln-624 L1-L4**: magic numbers, port validation, get_me try/except, bootstrap order
- **ln-623 LOW #3**: `docs/architecture.md` — уже в P3 backlog проекта

---

## Что сделать прямо сейчас

**Минимальный fix-PR (C1+C2+C3+H1+H2+H3 = 6 находок ~85 минут):**

1. C1 — `webhook_secret` в `dp.handle_webhook()` или удалить
2. C2 — пересоздать миграцию 0057 на Django 5.2.x
3. C3 — `transaction=True` в test_personalization
4. H1 — `transaction.atomic + select_for_update` в personalization
5. H2 — `HelpArticleQuerySet.active()` в managers.py
6. H3 — `filter().update()` вместо `save()` в get_or_create_bot_user

После этого commit `fix(maxbot): T-06.5 review fixes (C1-C3 critical, H1-H3 high)` и продолжаем T-07.

**Medium блок (M1-M5)** — отдельный коммит `refactor(maxbot): T-06.5 review medium findings`. Сделать перед началом T-07 (там handler'ы сразу подхватят `cb:` helper, типизацию, и т.д.) либо в parallel branch.

**LOW** — оставить в backlog раздел плана, делать opportunistically когда руки дойдут.

---

## Score & Quality

- ln-623 (principles): **9.4/10**
- ln-624 (quality metrics): high (нет god classes, CC max 3, nesting max 3)
- code-reviewer: CHANGES REQUESTED — но всё фиксится за ~85 минут

**Прогноз после fix-PR:** ln-623 ~9.6/10, code-reviewer → APPROVED. Готовность к T-07 — high.

---

## Что было сделано особенно хорошо (для memory)

- TDD дисциплина — RED-снимок до GREEN на каждой задаче
- `texts.py` отдельно — DRY для строк
- `keyboards.py` payload constants в одном месте
- `frozen=True` MaxBotConfig
- `ImproperlyConfigured` в `config.py` — паттерн из production.py применён
- `SET_NULL` FK + behavior test для `bot_user` deletion
- `sync_to_async` обёртки правильно изолируют ORM от async
