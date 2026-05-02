"""Локальная симуляция AI Concierge без подключения к MAX.

Прогоняет один user-message через ai_assistant.run_ai_turn с mock'ом MAX
bot — реальный LLM, реальная БД. Вывод в stdout: что бы клиент увидел.

Запуск:
    python manage.py simulate_chat "хочу массаж от боли в спине"
    python manage.py simulate_chat --user-id 99999 "запиши на лазер"
    python manage.py simulate_chat --reset --user-id 99999 "привет"

`--reset` закрывает активные Conversation для этого user_id перед запуском
(новый чистый диалог). Без `--reset` продолжает существующий.

Use cases:
- Smoke regression после правки prompt'а
- Прогон сценария из docs/bot_smoke_tests.md без открытия MAX
- Проверка edge-case'ов с `--user-id` фейкового клиента
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand, CommandError


DEFAULT_TEST_USER_ID = 99999
DEFAULT_TEST_CHAT_ID = 88888


class Command(BaseCommand):
    help = (
        "Прогоняет user-message через AI Concierge с mock'ом MAX bot. "
        "Реальный LLM, реальная БД. Вывод — что увидит клиент."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "text", type=str,
            help="Сообщение от клиента (в кавычках)",
        )
        parser.add_argument(
            "--user-id", type=int, default=DEFAULT_TEST_USER_ID,
            help=f"max_user_id BotUser (default {DEFAULT_TEST_USER_ID})",
        )
        parser.add_argument(
            "--chat-id", type=int, default=DEFAULT_TEST_CHAT_ID,
            help=f"chat_id (default {DEFAULT_TEST_CHAT_ID})",
        )
        parser.add_argument(
            "--name", type=str, default="Тест Тестов",
            help='Display name BotUser (default "Тест Тестов")',
        )
        parser.add_argument(
            "--reset", action="store_true",
            help="Закрыть активные conversation перед прогоном (новый чат)",
        )
        parser.add_argument(
            "--json", action="store_true",
            help="Вывод в JSON (для regression-сравнений)",
        )

    def handle(self, *args, **opts):
        text = opts["text"]
        user_id = opts["user_id"]
        chat_id = opts["chat_id"]
        name = opts["name"]
        reset = opts["reset"]
        as_json = opts["json"]

        if not os.environ.get("OPENAI_API_KEY"):
            raise CommandError(
                "OPENAI_API_KEY не задан в env — без него LLM не позовётся"
            )

        result = asyncio.run(_simulate(
            text=text, user_id=user_id, chat_id=chat_id,
            name=name, reset=reset,
        ))

        if as_json:
            self.stdout.write(json.dumps(result, ensure_ascii=False, default=str, indent=2))
            return

        self.stdout.write("")
        self.stdout.write(self.style.NOTICE(f"[USER] {text}"))
        self.stdout.write(self.style.NOTICE(f"[CONV] {result['conversation_id']}"))
        if result.get("action_type"):
            self.stdout.write(self.style.SUCCESS(f"[ACTION] {result['action_type']}"))
            ad = result.get("action_data") or {}
            for key in ("goals", "options", "services", "masters", "slots",
                        "explanation", "question", "filter", "date",
                        "master_name", "service_name", "datetime"):
                if key in ad and ad[key] not in (None, [], ""):
                    val = ad[key]
                    if isinstance(val, list):
                        s = json.dumps(val, ensure_ascii=False, default=str)
                        if len(s) > 200:
                            s = s[:200] + "..."
                        self.stdout.write(f"  {key}: {s}")
                    else:
                        self.stdout.write(f"  {key}: {val!r}")
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("[BOT REPLY]"))
        self.stdout.write(result["bot_text"] or "(нет ответа)")
        self.stdout.write("")
        if result.get("send_actions"):
            self.stdout.write(f"[send_action calls: {result['send_actions']}]")
        if result.get("created_inquiry"):
            self.stdout.write(self.style.WARNING(
                "⚠ создан BotInquiry (бот сдался — silent failure / giveup)"
            ))


async def _simulate(*, text: str, user_id: int, chat_id: int,
                    name: str, reset: bool) -> dict[str, Any]:
    """Async core. Возвращает dict с captured-данными для красивого вывода."""
    from maxbot.handlers.ai_assistant import run_ai_turn
    from maxbot.personalization import get_or_create_bot_user
    from services_app.models import BotInquiry, Conversation, Message

    if reset:
        @sync_to_async
        def _close_existing():
            Conversation.objects.filter(
                bot_user__max_user_id=user_id, is_active=True,
            ).update(is_active=False)
        await _close_existing()

    bot_user, _ = await get_or_create_bot_user(
        user_id, name, chat_id=chat_id,
    )

    # Mock MAX bot: захватываем все send_message / send_action вызовы.
    captured_messages: list[dict] = []
    captured_actions: list[str] = []

    async def fake_send_message(*, chat_id, text, attachments=None, **kwargs):
        captured_messages.append({
            "chat_id": chat_id, "text": text or "",
            "attachments_count": len(attachments) if attachments else 0,
        })

    async def fake_send_action(*, chat_id, action, **kwargs):
        captured_actions.append(str(action))

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=fake_send_message)
    bot.send_action = AsyncMock(side_effect=fake_send_action)

    # Запоминаем сколько BotInquiry было до
    @sync_to_async
    def _count_inquiries():
        return BotInquiry.objects.filter(bot_user=bot_user).count()
    inq_before = await _count_inquiries()

    # Прогон AI Concierge
    await run_ai_turn(
        bot=bot, chat_id=chat_id,
        bot_user=bot_user, user_text=text,
        original_user_text=text,
    )

    # Достаём последнее assistant-сообщение из БД
    @sync_to_async
    def _last_assistant():
        conv = Conversation.objects.filter(
            bot_user=bot_user, is_active=True,
        ).order_by("-last_message_at").first()
        if conv is None:
            return None, None
        msg = conv.messages.filter(role=Message.Role.ASSISTANT).order_by("-created_at").first()
        return conv, msg
    conv, msg = await _last_assistant()
    inq_after = await _count_inquiries()

    bot_text = ""
    if captured_messages:
        bot_text = "\n---\n".join(
            f"{m['text']}" + (f"\n[attachments: {m['attachments_count']}]"
                              if m['attachments_count'] else "")
            for m in captured_messages
        )

    return {
        "conversation_id": str(conv.id) if conv else None,
        "action_type": msg.action_type if msg else "",
        "action_data": msg.action_data if msg else None,
        "rendered_text": msg.rendered_text if msg else "",
        "content": msg.content if msg else "",
        "bot_text": bot_text,
        "send_actions": captured_actions,
        "messages_sent": len(captured_messages),
        "created_inquiry": inq_after > inq_before,
    }
