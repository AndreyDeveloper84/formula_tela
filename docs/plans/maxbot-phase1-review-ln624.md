# ln-624 Code Quality Audit: maxbot Фаза 1 (T-01..T-06)

**Worker:** ln-624-code-quality-auditor (manual fallback — Skill tool denied at runtime)
**Scope:** commits `98e88a9..d794dbe` (5 коммитов maxbot)
**Date:** 2026-04-24

---

## Executive summary

Quality of new maxbot package is **HIGH**. Files short, functions small, nesting shallow, no god classes, no obvious N+1.

**Counts:** 0 CRITICAL · 1 HIGH · 4 MEDIUM · 5 LOW

| File | LOC | Functions | Max func len | Max nesting | Max CC | God? |
|---|---|---|---|---|---|---|
| `maxbot/__init__.py` | 4 | 0 | — | — | — | no |
| `maxbot/config.py` | 56 | 1 | 21 | 2 | 3 | no |
| `maxbot/django_bootstrap.py` | 22 | 1 | 9 | 2 | 2 | no |
| `maxbot/main.py` | 75 | 4 | 23 | 2 | 3 | no |
| `maxbot/texts.py` | 43 | 0 | — | — | — | no |
| `maxbot/keyboards.py` | 87 | 5 | 11 | 2 | 1 | no |
| `maxbot/states.py` | 12 | 0 | — | — | — | no |
| `maxbot/personalization.py` | 70 | 4 | 24 | 3 | 3 | no |

Все под порогами (CC<10, nesting<4, func<50, file<300).

---

## Findings

### HIGH

**H1 — `personalization.update_context` claims atomicity it does not provide**
`mysite/maxbot/personalization.py:50-57` (и `:60-69` `append_to_context`)

Docstring: *"Atomically merges kwargs в context dict"*. Реализация — классический read-modify-write без транзакции/lock'а:
```python
user = BotUser.objects.get(pk=bot_user_id)
user.context.update(updates)
user.save(update_fields=["context", "last_seen"])
```
Два concurrent webhook handler'а (например fast double-tap на inline-кнопку) гонятся — last writer wins, второе обновление теряется. JSONField сохраняет полный re-serialized dict, partial-update от PostgreSQL не работает.

**Fix:** обернуть в `transaction.atomic()` + `select_for_update()`. Минимум — поменять docstring на "**not** atomic, last-writer-wins; OK because handlers are single-user-scoped and MAX delivers per-user webhooks serially" если предположение верно.

### MEDIUM

**M1 — Hardcoded `"cb:"` префикс в 9 string-литералах**
`mysite/maxbot/keyboards.py:18-27`

Каждая константа дублирует namespace `"cb:"` (`PAYLOAD_MENU_BOOK = "cb:menu:book"`). Когда T-08 добавит роутинг (`callback.payload.startswith("cb:svc:")`), префикс повторится в handlers + tests. Версионирование протокола (`"cb2:"`) требует grep/replace везде.

**Fix:** extract single source.
```python
_NS = "cb"
def _payload(*parts: str) -> str: return ":".join((_NS, *parts))
PAYLOAD_MENU_BOOK = _payload("menu", "book")
PAYLOAD_SVC_PREFIX = _payload("svc", "")  # "cb:svc:"
```
Или `from enum import StrEnum`. ~10 минут.

**M2 — `keyboards.services_keyboard`/`faq_keyboard` будут N+1 в T-08**
`mysite/maxbot/keyboards.py:44-69`

Сейчас обращаются только к `.id` + `.name`/`.question` — безопасно. Но `Iterable` type-hint скрывает intent: caller может передать `Service.objects.all()` lazy queryset и в T-08 добавить `.category.name` в текст кнопки → instant N+1.

**Fix:** ужесточить hint до `Sequence[Service]` (форсировать материализацию) + комментарий *"caller responsible for `select_related(...)` if accessing FK fields in button text"*.

**M3 — `get_or_create_bot_user` лишний save в else-branch**
`mysite/maxbot/personalization.py:24-36`

`get_or_create` уже бьёт DB; если `display_name` совпадает — extra `save(update_fields=["last_seen"])` ради `auto_now`. **2 DB-roundtrip per message** для returning user. На hot path /start это доминирует.

**Fix:** один `BotUser.objects.filter(pk=user.pk).update(last_seen=timezone.now(), display_name=...)` после fetch — 1 query для common case. Или skip last_seen и cron'ом раз в N минут.

**M4 — `BotUserAdmin.fields` дублирует `readonly_fields`**
`mysite/services_app/admin.py:548-549`

```python
readonly_fields = ("max_user_id", "display_name", "first_seen", "last_seen", "context")
fields = ("max_user_id", "display_name", "client_name", "client_phone", "first_seen", "last_seen", "context")
```
Добавление поля требует апдейта обоих tuple — дрейф.

**Fix:** `fields = readonly_fields + editable_fields` или удалить `fields` (Django auto-generate). Если ordering важен — комментарий.

### LOW

**L1 — Magic number "2" в `texts.BOOKING_NAME_TOO_SHORT`**
`mysite/maxbot/texts.py:24`. Constant в user-facing string, реальная проверка `len(name) >= 2` будет в T-09. **Fix:** `MIN_NAME_LEN = 2` в handlers, `format()` в текст.

**L2 — `MaxBotConfig` не валидирует `webhook_port` диапазон**
`mysite/maxbot/config.py:54`. `int(os.environ.get(...))` → "abc" или "-1" падает только при `dp.handle_webhook`. **Fix:** `1 <= port <= 65535` в `get_config()`.

**L3 — `main.run()` не сглаживает auth-error от `bot.get_me()`**
`mysite/maxbot/main.py:45-46`. Token invalid → stack trace без подсказки. **Fix:** try/except с hint про `MAX_BOT_TOKEN`.

**L4 — `setup_django` early-return brittle**
`mysite/maxbot/django_bootstrap.py:17-18`. `from django.conf import settings` уже трогает settings до `setdefault`. **Fix:** перенести `os.environ.setdefault(...)` на module-top, до django-импортов.

**L5 — `BookingRequest.__str__` не показывает source**
`mysite/services_app/models.py:1100-1101`. С multi-source (wizard/bot_max) в admin/Telegram digests не отличить. **Fix:** `[{source}]` в `__str__` если `source != "wizard"`.

---

## Что НЕ проблема (verified)

- **Нет god classes** — biggest file is `keyboards.py` at 87 LOC
- **Нет deep nesting** — max 3 (в `get_or_create_bot_user`)
- **Нет long methods** — longest 24 lines (`get_or_create_bot_user`)
- **Нет O(n²)** — все loops single-level над bounded sets (≤10 services, ≤20 FAQ)
- **Нет N+1 сейчас** — keyboards только local fields (M2 — preventive)
- **Constants извлечены** — `VALID_MODES`, `BOOKING_SOURCE_CHOICES`, `PAYLOAD_*`, `BotUser.SOURCE_NAME`
- **Cyclomatic complexity** — max CC=3, target <10

---

## Recommended action order

1. **H1** — fix docstring (минимум) или `transaction.atomic`. ~15min
2. **M3** — single-update для returning user. ~10min, hot path
3. **M1** — centralize `cb:` namespace до T-08. ~10min
4. **M2** — tighten types в keyboards до того как handlers начнут передавать live querysets. ~5min
5. M4, L1-L5 — opportunistic cleanup, не блокеры

---

**Note:** Skill tool `codebase-audit-suite:ln-624-code-quality-auditor` denied at runtime. Auditor выполнил manual audit по тому же checklist (CC, nesting, length, god-class, N+1, magic numbers).
