# Formula Tela AI Workflow

**Проектный документ: как Claude работает с formulatela58.ru**

Версия 2.0 — обновлено под новую реальность: AI-агенты внутри Django, Celery, PostgreSQL, 34 теста, три окружения, BeautyGo.

---

## 1. Проблема, которую решаем

Ты соло-разработчик с production-сайтом салона массажа. Проект:
- Вырос с простого сайта до системы с 7 AI-агентами внутри (SEO, SMM, analytics, offers, ...)
- Использует OpenAI (через прокси), YClients, Яндекс API, VK Ads
- Работает в production на реальных клиентах через YClients бронирования
- Имеет 34 теста, Celery worker+beat, PostgreSQL, Docker

**Без дисциплинированного процесса это превращается в хаос:**
- Фичи начинаются без чёткого понимания что нужно
- Код пишется "как получится", потом переделывается
- Тесты добавляются постфактум (или вообще не добавляются)
- Deploy ломает прод из-за пропущенного checklist шага
- Секреты утекают в логи/коммиты
- Manual debug scripts плодятся как кролики (у тебя уже 15 штук `manual_*.py`)

**Эта система решает это через workflow-дисциплину + skills-first архитектуру.**

---

## 2. Философия

### 2.1. Skills-first, не agent-zoo

В экосистеме Claude Code есть два подхода:
- **Agent zoo** — плодить субагентов на каждую задачу (было популярно в начале)
- **Skills-first** — одна главная сессия Claude с large контекстом, skills автоподгружаются по нужде, субагенты только где нужна изоляция контекста

Superpowers (152k⭐) и Everything Claude Code (140k⭐) — оба пришли к skills-first. Мы тоже.

**Преимущества:**
- Claude знает весь контекст, не нужно передавать между агентами
- Skills — markdown-файлы с YAML frontmatter, легко редактировать
- Меньше overhead от subagent spawning
- Subagent используется только для специфических isolated задач (code review, security audit, deploy execution)

### 2.2. Design-first, не code-first

Главное изменение в workflow — **brainstorm и план ДО кода**. Звучит банально, но 90% AI-ассистентов (и разработчиков) прыгают в код.

Цикл:
```
brainstorm → write plan → execute plan → review → deploy
   ↑________________|           |
    (пересогласование если deviation)
```

Каждый этап — отдельный skill с явным hard rule "не делай X до Y".

### 2.3. Dual-use everywhere

Бизнес-логика должна работать **везде**: view, Celery task, management command, shell. Это значит функции не зависят от `request`.

Зачем: у тебя уже 7 AI-агентов, которые дёргают одну и ту же функциональность из разных точек. Если `create_booking()` требует `request` — тебя ждёт рефакторинг.

### 2.4. DRY & SOLID — не опционально

Соло-разработчику особенно важна предсказуемость. Дублирование кода = дублирование багов = ночные фиксы в проде.

---

## 3. Компоненты системы

```
.claude/
├── skills/                          — Knowledge modules (auto-loaded by keyword)
│   ├── feature-brainstorm/          — Phase 1: understand before building
│   ├── writing-plans/               — Phase 2: decompose into tasks
│   ├── executing-plans/             — Phase 3: disciplined TDD execution
│   ├── django-feature-tdd/          — TDD cycle specifics for Django
│   ├── design-patterns/             — SOLID, DRY, dual-use reference
│   ├── yclients-api/                — YClients integration patterns
│   ├── safe-deploy/                 — Production deploy preflight
│   ├── systematic-debug/            — 4-phase debugging methodology
│   ├── security-review-django/      — OWASP + project-specific security
│   └── secret-hygiene/              — API keys, tokens, incident response
│
├── agents/                          — Isolated-context subagents
│   ├── code-reviewer.md             — PR review with 3-pass methodology
│   ├── security-auditor.md          — Deep security audit with PoC
│   └── deploy-operator.md           — Executes safe-deploy runbook
│
├── commands/                        — Slash commands (user invokes)
│   ├── plan.md                      — /plan <feature> — brainstorm + plan
│   ├── tdd.md                       — /tdd <plan-file> — execute
│   ├── review.md                    — /review — invoke code-reviewer
│   ├── pre-deploy.md                — /pre-deploy — invoke deploy-operator
│   └── debug-prod.md                — /debug-prod <symptom> — systematic debug
│
├── hooks/                           — Quality gates (auto-run at events)
│   ├── hooks.json                   — configuration
│   ├── block-dangerous-commands.sh  — PreToolUse Bash
│   ├── check-no-secrets.sh          — PreToolUse Edit/Write
│   ├── post-edit-quality.sh         — PostToolUse Edit/Write
│   └── discipline-reminder.sh       — UserPromptSubmit
│
└── settings.json                    — Claude Code config

CLAUDE.md                            — Project orientation (first-read)
FORMULA_TELA_AI_WORKFLOW.md          — This file
docs/
├── specs/                           — Design docs from brainstorm
├── plans/                           — Task breakdowns
├── incidents/                       — Post-mortems
├── findings/                        — Bugs/issues to fix later
├── deploy-log.md                    — Deploy history
└── changes/                         — Changelogs
```

---

## 4. Workflow: типичный день разработчика

### Сценарий 1: Новая фича

```
User: /plan добавить блок "Похожие услуги" на страницу услуги

[Claude reads feature-brainstorm skill]

Claude: Понял как: на странице услуги показать карточки услуг из related_services M2M,
        ограничить топ-3, сортировать по популярности. Правильно?

User: Да, но только популярные (is_popular=True)

Claude: Вижу три варианта реализации:
        A) Новый ServiceBlock type — гибко, но требует миграцию
        B) Template tag {% related_services %} — быстро, позиция захардкожена
        C) Signal + denormalized — overkill для текущей нагрузки
        Рекомендую B.

User: Согласен с B.

[Claude writes spec to docs/specs/2026-04-18-related-services.md]
[Claude reads writing-plans skill]
[Claude creates docs/plans/2026-04-18-related-services.md — 5 tasks]

Claude: План готов. 5 задач, ~2 часа. Проверь и скажи "приступай".

User: /tdd latest

[Claude reads executing-plans + django-feature-tdd]
[Claude runs pytest -q to confirm baseline green]
[For each task: RED test → GREEN impl → regression → commit]

Claude: ✅ Task 1 done (abc123f)
Claude: ✅ Task 2 done (def456a)
...
Claude: ✅ All 5 tasks complete. Ветка готова к review.

User: /review

[Claude invokes code-reviewer subagent]
[Subagent: 3-pass review + output с severity levels]

Subagent: 🟡 MAJOR finding: в test_views.py нет теста edge case "related_services пустой"
          🔵 MINOR: template partial можно переиспользовать вместо копии
          ✅ Otherwise approved

User: Исправь MAJOR, MINOR можем оставить на потом

[Claude adds missing test, commits]

User: /pre-deploy

[Claude invokes deploy-operator]
[12-step checklist...]
[All pass]
[User confirms]
[Deploy executes]
[Post-deploy verification...]

Deploy-operator: ✅ Production healthy. Log в docs/deploy-log.md
```

### Сценарий 2: Production incident

```
User: /debug-prod бронирование не работает, 500 на /api/booking/create/

[Claude reads systematic-debug]

Claude: Phase 1: Reproduce.
        - С какого момента началось?
        - У всех или у части?
        - Последний deploy был когда?

User: Полчаса назад, у всех. Deploy был вчера утром.

Claude: Phase 2: Observability.

[Claude runs]:
  $ ssh ... "sudo journalctl -u formula_tela --since '1 hour ago' | grep -iE 'error'"

Output: YClientsAPIError: 401 — Bearer token invalid

Phase 3: Hypothesis testing.

Hypothesis: YClients token истёк.

Test:
  $ curl -H "Authorization: Bearer $YCLIENTS_PARTNER_TOKEN" \
         "https://api.yclients.com/api/v1/company/884045/services"

Result: {"success": false, "meta": {"message": "token expired"}}

✅ Hypothesis confirmed.

Phase 4: Fix.
Immediate: rotate token in YClients dashboard, update .env, restart.
Prevention: добавить monitoring — check token validity раз в неделю.
Post-mortem: docs/incidents/2026-04-18-yclients-token-expired.md
```

### Сценарий 3: Пользователь прыгает к коду

```
User: напиши код для валидации телефона

[discipline-reminder hook fires]
💡 Workflow reminder: Claude сконфигурирован работать через brainstorm → plan → execute.
   Для быстрого: /plan <описание>.

[Claude respects the reminder but also uses judgement]

Claude: Понял — нужен phone validator. Один уточняющий вопрос:

        У тебя в проекте уже есть normalize_phone функция (grep показал
        services_app/utils.py::normalize_phone и test_phone_normalize.py).
        Ты хочешь:
        A) Просто использовать существующую?
        B) Добавить Django-form validator который её использует?
        C) Расширить existing (добавить новое правило)?
```

Claude не стал полным protocol запускать для мелкой задачи, но и не поспешил писать код — проверил existing.

---

## 5. Key Design Decisions

### 5.1. Разделённые skills для фаз workflow

Почему `feature-brainstorm`, `writing-plans`, `executing-plans` — три разных skill'а, а не один?

Каждая фаза имеет свой hard rule:
- Brainstorm: "не писать код"
- Plan: "не начинать execute без утверждённого плана"
- Execute: "не отклоняться от плана без эскалации"

Разделение позволяет каждый rule сделать жёстким без перемешивания. Описание активирует правильный skill в правильный момент.

### 5.2. Почему hooks, а не соглашения

Human напоминания забываются. Hook блокирует автоматически:
- `block-dangerous-commands.sh` — защита от случайного `rm -rf`, force push, DROP TABLE
- `check-no-secrets.sh` — блокирует запись файла с похожим на секрет контентом
- `post-edit-quality.sh` — reminder про миграции если редактирован models.py
- `discipline-reminder.sh` — soft reminder когда user пытается прыгнуть к коду

### 5.3. Subagents только для изолированных задач

Три subagent'а:
- **code-reviewer** — изолированный контекст для объективного ревью (не "свой же код оцениваю")
- **security-auditor** — специализированный pentester mindset
- **deploy-operator** — строгое исполнение runbook без "давайте заодно..."

Остальное — skills в main Claude session.

### 5.4. Skills-first vs hardcoded в CLAUDE.md

Почему правила в skills, а не одним большим CLAUDE.md?

- Контекст-экономия: skill загружается только когда нужен
- Обновление: поменять skill — один файл, не огромный CLAUDE.md
- Условная активация: description skill'а определяет когда он применим

CLAUDE.md — только orientation + pointer на skills.

---

## 6. What's NOT in this system

Честно: чего нет и почему.

### 6.1. Нет "AI-агента-который-сам-всё-сделает"

Не обещаю "поставил задачу, утром получил готовый feature". Это плохо работает для production-кода с реальными клиентами. Claude требует human-in-the-loop на ключевых этапах:
- Approval дизайна после brainstorm
- Approval плана перед execution
- Approval перед deploy

Попытки full-auto — источник тех самых production-инцидентов.

### 6.2. Нет агентов для каждой роли ("Product Manager agent", "Designer agent")

У тебя уже есть `growth-marketer-senior` (custom persona) и `pm-skills` plugin (pm-marketing-growth, pm-go-to-market). Этого достаточно для твоей стадии. Плодить ещё "CEO agent", "CFO agent" — overhead без value.

### 6.3. Нет automatic deployment

Automatic merge dev → main + auto-deploy — **нет**. `/pre-deploy` требует explicit user confirmation на финальном шаге. Причина: см. 20GB disk-full incident, SSL renewal outage. Automation без проверки → инциденты.

### 6.4. Нет skill'ов для BeautyGo

BeautyGo — отдельный проект, отдельный стек (мобильное приложение). Когда начнёшь активно его разрабатывать — создадим отдельный `.claude/` там, с собственными skills под мобильный стек.

---

## 7. Integration with existing `.claude/` setup

У тебя уже есть в репо:
- `.claude/settings.json` с `pm-marketing-growth` и `pm-go-to-market` plugins
- `.claude/worktrees/exciting-sutherland/.claude/agents/growth-marketer-senior`

**Как новая система это уважает:**
- Плагины остаются активны — Claude сможет звать pm-skills для маркетинговых задач
- `growth-marketer-senior` остаётся в worktree — его можно звать отдельно для growth-стратегии
- Новые skills НЕ дублируют маркетинговую функциональность — они про инженерию (код, тесты, деплой, security)

Если Andrey запросит "придумай акцию для клиентов" — Claude предложит использовать `growth-marketer-senior` или pm-skills.
Если Andrey запросит "добавь field в Service model" — Claude запустит feature-brainstorm.

Разделение зон ответственности.

---

## 8. Installation & Adoption

### 8.1. Как применить в репо

```bash
# 1. Распакуй пакет в корне проекта
cd /path/to/formulatela58.ru

# 2. Положи .claude/ content (merge с существующим)
cp -r /path/to/unpacked/.claude/skills .claude/
cp -r /path/to/unpacked/.claude/agents .claude/
cp -r /path/to/unpacked/.claude/commands .claude/
cp -r /path/to/unpacked/.claude/hooks .claude/

# 3. Проверь hooks.json объединён с существующим settings.json
# (если нужно — добавь hook paths вручную)

# 4. chmod +x на hook scripts (если не сохранились)
chmod +x .claude/hooks/*.sh

# 5. Обнови CLAUDE.md — слей предоставленный с существующим
# НЕ перезаписывай вслепую — в существующем может быть важный контекст

# 6. Создай docs/ директории
mkdir -p docs/{specs,plans,incidents,findings,changes}
touch docs/deploy-log.md

# 7. Commit
git add .claude/ CLAUDE.md FORMULA_TELA_AI_WORKFLOW.md docs/
git commit -m "chore: add AI workflow system with skills, agents, hooks, commands"
```

### 8.2. Первые шаги после установки

```bash
# Проверь что slash commands работают
# В Claude Code: набери /, должны увидеть plan, tdd, review, pre-deploy, debug-prod

# Тест на простой фиче
# User: /plan добавить поле "short_description" в Review model

# Если всё работает — workflow запустится
```

### 8.3. Постепенное внедрение

Не обязательно сразу использовать ВСЁ. Минимальный набор для старта:
1. **feature-brainstorm + writing-plans + executing-plans** — workflow-ядро
2. **design-patterns** — справочник при вопросах

Остальное (security, secret-hygiene, deploy-operator) подключай по мере роста — когда начнёшь интенсивный deploy cycle.

---

## 9. Maintenance

### 9.1. Когда обновлять skills

- Изменился стек проекта (новая библиотека, новый паттерн) → обновить `design-patterns`
- Появился новый API (новый Yandex сервис, другой CRM) → новый skill или обновить existing
- YClients API изменился → обновить `yclients-api`
- Появился новый класс секретов → обновить `secret-hygiene`

### 9.2. Когда пересматривать архитектуру

- Количество skills >20 — возможно нужна категоризация
- Subagent'ы дублируют функциональность skills — упростить
- Hooks тормозят работу — оптимизировать или убрать
- Workflow "обходят" больше чем используют — упростить процесс

### 9.3. Как добавить новый skill

1. Создай `.claude/skills/<skill-name>/SKILL.md`
2. YAML frontmatter: `name` (snake-case) и `description` (starts with "Use when...")
3. Описание активирующих триггеров в первом разделе
4. Hard rules — что skill запрещает/требует
5. Examples хороших/плохих подходов
6. Handoff — какие другие skills часто нужны вместе

Template — см. существующие skills в этом пакете.

---

## 10. Success Metrics

Через 3 месяца использования проверь:

**Process metrics:**
- % фич начинающихся с brainstorm (цель: >80%)
- % фич с документированным spec (цель: >60% для фич >1 час)
- % реализаций следующих плану без deviation (цель: >70%)

**Quality metrics:**
- Количество post-deploy incident'ов (цель: <1/month)
- Количество rollback'ов (цель: 0)
- Test coverage (цель: >70% для services_app, website, booking)

**Developer velocity:**
- Время от идеи до production (цель: <1 неделя для small features)
- Количество "переделок" после code review (цель: <2/фича в среднем)

Если метрики не идут — пересматривать и упрощать workflow.

---

## 11. Credits & References

Архитектура вдохновлена:
- **Superpowers** (obra/superpowers, 152k⭐) — skills-first подход, SKILL.md формат
- **Awesome Claude Code** (hesreallyhim/awesome-claude-code, 30.9k⭐) — экосистема
- **Everything Claude Code** (affaan-m/everything-claude-code, 140k⭐) — Django-specific patterns
- **CC DevOps Skills** (akin-ozer/cc-devops-skills) — generator + validator pattern

Adapted для specific контекста formulatela58.ru — production Django + AI-агенты + solo developer.

---

## 12. Changelog

**v2.0** — 2026-04-18 (this version)
- Полная переработка под новый репомикс: AI-агенты внутри Django, PostgreSQL, Celery, Docker, 34 теста
- Добавлены skills: feature-brainstorm, writing-plans, executing-plans, design-patterns, security-review-django, secret-hygiene
- Добавлены subagents: code-reviewer, security-auditor, deploy-operator
- Добавлены slash commands: /plan, /tdd, /review, /pre-deploy, /debug-prod
- Добавлены hooks: block-dangerous-commands, check-no-secrets, post-edit-quality, discipline-reminder
- Env vars актуализированы (без `DJANGO_` префикса для YClients/OpenAI/Yandex)
- Safe-deploy расширен до 12 шагов с учётом Celery, PostgreSQL, OpenAI budget, agents health

**v1.0** — предыдущая версия (скромная)
- Базовые skills для старой структуры проекта (4 Django app'а, SQLite, 4 теста)
