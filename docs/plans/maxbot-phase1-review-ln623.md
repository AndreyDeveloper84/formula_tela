# ln-623 Code Principles Audit: maxbot Фаза 1 (T-01..T-06)

**Worker:** ln-623-code-principles-auditor v5.0.0
**Scope:** commits `98e88a9..d794dbe` (5 коммитов maxbot)
**Files:** `mysite/maxbot/*.py`, `mysite/services_app/models.py` (BotUser/HelpArticle/BookingRequest changes), `mysite/services_app/admin.py` (3 admin classes), `mysite/tests/maxbot/*.py`, `mysite/tests/test_bot_models.py`
**Date:** 2026-04-24

---

## Score: **9.4 / 10**

### Penalty
```
0 × CRITICAL × 2.0 = 0
0 × HIGH     × 1.0 = 0
0 × MEDIUM   × 0.5 = 0   (все Layer-1 medium → downgrade to LOW по контексту)
3 × LOW      × 0.2 = 0.6
penalty = 0.6 → score = 10 - 0.6 = 9.4
```

---

## Findings

| # | Severity | Rule | Location | Note |
|---|---|---|---|---|
| 1 | LOW | DRY 1.4 Similar Patterns | `maxbot/personalization.py:50-69` | `update_context` и `append_to_context` имеют похожую структуру (5 строк boilerplate `@sync_to_async` + `BotUser.objects.get` + `save(update_fields=...)`), но **разные операции** (merge vs append-без-дублей). Layer 2: 2 экземпляра, расхождение в логике (modify vs setdefault+append) — abstraction = premature. **Не рефакторить.** Вернуться когда появится 3-й похожий метод. |
| 2 | LOW | YAGNI Unused config | `maxbot/config.py:31` (`webhook_secret`) | Поле определено, но не используется. Layer 2: подготовлено для T-13/T-14 (защита webhook secret-path) — **intentional preparation**. Запись информационная — следить, чтобы T-13/T-14 действительно использовали. |
| 3 | LOW | Best practices guide | (отсутствует `docs/architecture.md`) | Уже в backlog post-audit (`memory/project_audit_state.md` § P3). Не блокер. |

---

## Что сделано хорошо (Positive findings — для memory)

- ✅ **`texts.py`** — централизация **всех** user-facing строк бота. Соответствует DRY 1.3 (Repeated Error Messages → Centralized catalog). Менеджер сможет редактировать без правок логики.
- ✅ **`keyboards.py`** — payload-константы (`PAYLOAD_MENU_BOOK`, `PAYLOAD_BACK`, etc.) объявлены в одном месте, handlers будут импортить — нет string-typo рисков.
- ✅ **`states.py`** — использует встроенный `StatesGroup` SDK (не reinvent the wheel — KISS).
- ✅ **`config.py`** — fail-fast валидация (`ImproperlyConfigured` с понятным сообщением + ссылкой на план), `dataclass(frozen=True)` для immutability.
- ✅ **`django_bootstrap.py`** — идемпотентный `setup_django()` через `settings.configured` check.
- ✅ **Тесты** — отличные helper'ы (`_flatten`/`_payloads`/`_texts` в test_keyboards.py; `amake`/`_arefresh` в test_personalization.py) — DRY 1.6 на уровне тестовой инфраструктуры.
- ✅ **Commit messages** — каждый привязан к T-XX задаче плана и описывает Why-not-What.
- ✅ **TDD дисциплина** — RED тесты написаны первыми, у каждого failure-snapshot до GREEN.
- ✅ **`personalization.py::get_or_create_bot_user`** — корректно сохраняет `client_name` (то что клиент сам сказал) при обновлении `display_name` от MAX. Защита от потери UX-state.

---

## Что НЕ нашёл (но проверил по чек-листу)

| Rule | Result |
|---|---|
| DRY 1.1 Identical Code (>10 lines) | PASS — все файлы уникальны |
| DRY 1.2 Duplicated Validation | N/A — валидация в T-09 (booking FSM) ещё не написана |
| DRY 1.5 Duplicated SQL/ORM | PASS — нет raw SQL, ORM-запросы уникальны |
| DRY 1.6 Copy-Pasted Tests | PASS — DRY через helper'ы, не fixture'ы |
| DRY 1.7-1.10 (API responses, middleware, types, mappers) | N/A — handlers/middleware ещё не написаны |
| KISS Abstract class with 1 impl | PASS — ноль abstract classes |
| KISS Factory <3 types | PASS — ноль factories |
| KISS Deep inheritance | PASS — `BookingStates → StatesGroup` (1 уровень) |
| KISS Wrapper-only classes | PASS — `MaxBotConfig` это data class, не wrapper |
| YAGNI Dead feature flags | PASS — нет |
| YAGNI Abstract methods never overridden | N/A — нет abstract |
| YAGNI Premature generics | PASS — нет |
| Error handling в `config.py` | PASS — `ImproperlyConfigured` с контекстом |
| DI / Centralized init | PASS — `main.build_dispatcher()` это bootstrap, прямые импорты Django-idiomatic |

---

## Tracked, but planned (informational, не finding)

- **Centralized error middleware** для handler'ов — отсутствует, **запланировано в T-12** (`maxbot/middleware.py`). Все async ORM-операции в `personalization.py` сейчас не имеют explicit try/except — но `MemoryContext._lock` (asyncio.Lock в SDK) и `transaction.atomic` от Django + middleware T-12 покроют. После T-12 пройти ревью повторно.
- **DRF output serializers для bot endpoints** — N/A, у нас не REST API а webhook-handlers (специфика maxapi SDK).

---

## Рекомендации (порядок выполнения)

1. **Перед T-13** — реализовать `webhook_secret` в `main.py` (`@dp.webhook_post(f"/{cfg.webhook_secret}")` если не пуст). Сейчас поле в config есть, использования нет — это **YAGNI #2 закроется автоматически** когда T-13 будет готов.
2. **После T-12 (middleware)** — повторно прогнать ln-623 чтобы убедиться что error handling переехал в централизованный middleware.
3. **P3 (вне Фазы 1)** — `docs/architecture.md` (уже в backlog).

---

## Conclusion

Pre-handler stage maxbot-кода (T-01..T-06) **в очень хорошем состоянии**. Score 9.4/10.

Принципиальных нарушений DRY/KISS/YAGNI **нет**. Отсутствие централизованного error handling — это known gap, закрытый T-12 в плане.

**Следующая точка ревью:** после T-12 (`middleware.py`), затем после T-14 (`webhook_secret` в action).
