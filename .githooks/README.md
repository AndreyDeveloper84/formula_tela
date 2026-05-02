# Local git hooks

Опциональные локальные напоминания. **Не обязательно** ставить — на проде тот же контроль через GitHub Action `smoke-tests-doc-reminder.yml`.

## Установка одной командой

```bash
git config core.hooksPath .githooks
cp .githooks/pre-commit-smoke-tests-reminder.sh .githooks/pre-commit
chmod +x .githooks/pre-commit
```

## Что делает

`pre-commit` смотрит в staged-diff. Если меняется любой из:
- `mysite/maxbot/ai_prompts.py`
- `mysite/maxbot/ai_concierge.py`
- `mysite/maxbot/ai_tool_handlers.py`
- `mysite/maxbot/handlers/ai_assistant.py`

И **не** меняется `docs/bot_smoke_tests.md` — печатает WARNING.

**Не блокирует коммит** (`exit 0`). Только напоминание — если правка чисто рефакторинг, игнорируй.

## Снять hooks

```bash
git config --unset core.hooksPath
```
