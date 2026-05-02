#!/usr/bin/env bash
# Pre-commit hook: напоминает обновить docs/bot_smoke_tests.md при правке
# AI Concierge. Soft — печатает warning, не блокирует commit.
#
# Установка:
#   chmod +x .githooks/pre-commit-smoke-tests-reminder.sh
#   git config core.hooksPath .githooks
#   ln -s pre-commit-smoke-tests-reminder.sh .githooks/pre-commit
#
# Или просто dotted alias:
#   git config core.hooksPath .githooks
#   mv .githooks/pre-commit-smoke-tests-reminder.sh .githooks/pre-commit

STAGED=$(git diff --cached --name-only)

BOT_FILES=$(echo "$STAGED" | grep -E '^(mysite/maxbot/(ai_prompts|ai_tool_handlers|ai_concierge)\.py|mysite/maxbot/handlers/ai_assistant\.py)$' || true)
DOC=$(echo "$STAGED" | grep -E '^docs/bot_smoke_tests\.md$' || true)

if [ -n "$BOT_FILES" ] && [ -z "$DOC" ]; then
  echo ""
  echo "⚠  WARNING: меняется AI Concierge, но docs/bot_smoke_tests.md не в коммите."
  echo ""
  echo "Изменённые bot-файлы:"
  echo "$BOT_FILES" | sed 's/^/    /'
  echo ""
  echo "Если эта правка меняет UX — добавь сценарий в docs/bot_smoke_tests.md"
  echo "и перекоммить (или git add docs/bot_smoke_tests.md && git commit --amend)."
  echo ""
  echo "Если рефакторинг без UX-изменений — игнорируй это сообщение."
  echo ""
fi

exit 0  # never block — только напоминание
