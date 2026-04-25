"""AI-помощник handler — свободный текст → LLM с tools (T-06c).

Триггеры:
1. Кнопка «💬 Задать вопрос» в главном меню → state `awaiting_question`
2. Любой text-message без активного booking-state (вытесняет старый fallback)

Pipeline:
1. ensure_started() persistent MCP-клиент (T-06a)
2. chat_with_tools (T-06b) с system prompt из texts.AI_SYSTEM_PROMPT
3. Если LLM вернул LLM_GIVEUP_MESSAGE → создаём BotInquiry (T-02) +
   шлём AI_FORWARDED_TO_MANAGER + главное меню. Менеджер увидит в админке,
   ответит, нажмёт action «Отправить» (T-09 — реальный push-back в MAX).
4. Иначе — отправляем ответ модели + главное меню.

Зачем НЕ trim до booking-state-фильтра: ai_assistant ловит "всё остальное" —
если booking handlers не сработали (нет matching state), ai_assistant
обрабатывает. Это явно ставит ai_assistant_router ПЕРЕД fallback_router в
get_routers().
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback, MessageCreated

from maxbot import keyboards, texts
from maxbot.llm import LLM_GIVEUP_MESSAGE, chat_with_tools
from maxbot.mcp_client import MaxbotMCPClient
from maxbot.personalization import get_or_create_bot_user
from maxbot.states import AskStates
from services_app.models import BotInquiry


logger = logging.getLogger("maxbot.ai")
router = Router()


# ─── Кнопка «Задать вопрос» — переход в state awaiting_question ────────────


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_MENU_ASK)
async def on_ask_button(callback: MessageCallback, context: MemoryContext) -> None:
    """Клик «💬 Задать вопрос» в главном меню → ждём текст."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await context.set_state(AskStates.awaiting_question)
    await callback.bot.send_message(chat_id=chat_id, text=texts.AI_ASK_PROMPT)


# ─── Free-text → AI ────────────────────────────────────────────────────────
#
# БЕЗ state-фильтра — handler ловит всё что не подхватили booking-handlers
# (у них есть state-filter BookingStates.X). Если активен AskStates.awaiting_question
# — тоже сработает (нет state-filter blocker'а).


@router.message_created()
async def on_free_text(event: MessageCreated, context: MemoryContext) -> None:
    if event.message.sender is None:
        return  # системные

    chat_id = event.message.recipient.chat_id
    user_text = (event.message.body.text or "").strip() if event.message.body else ""
    if not user_text:
        return

    # Сразу даём фидбек — LLM может занять 5-10 сек через прокси
    await event.bot.send_message(chat_id=chat_id, text=texts.AI_THINKING)

    # Чистим state — диалог one-shot (state ставился на awaiting_question
    # кнопкой, а тут уже ответили)
    await context.clear()

    # Получаем ответ через LLM + MCP
    sender = event.message.sender
    answer = await _get_ai_answer(user_text, sender)

    if answer == LLM_GIVEUP_MESSAGE:
        # LLM не справился → BotInquiry + главное меню
        await _create_bot_inquiry(
            user_id=sender.user_id, full_name=sender.full_name,
            chat_id=chat_id, question=user_text,
        )
        await event.bot.send_message(
            chat_id=chat_id,
            text=texts.AI_FORWARDED_TO_MANAGER,
            attachments=[keyboards.main_menu_keyboard()],
        )
        return

    await event.bot.send_message(
        chat_id=chat_id,
        text=answer,
        attachments=[keyboards.main_menu_keyboard()],
    )


# ─── Helpers ────────────────────────────────────────────────────────────────


async def _get_ai_answer(user_text: str, sender) -> str:
    """Вызов chat_with_tools с защитой от exception → giveup."""
    try:
        mcp_client = MaxbotMCPClient.instance()
        return await chat_with_tools(
            messages=[
                {"role": "system", "content": texts.AI_SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            mcp_client=mcp_client,
        )
    except Exception:  # noqa: BLE001
        logger.exception("ai_assistant: chat_with_tools crashed for user_id=%s text=%r",
                         sender.user_id, user_text[:80])
        return LLM_GIVEUP_MESSAGE


async def _create_bot_inquiry(*, user_id: int, full_name: str, chat_id: int, question: str) -> None:
    """Создаём BotInquiry для менеджера (T-02 модель)."""
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)
    await sync_to_async(BotInquiry.objects.create)(
        bot_user=bot_user,
        chat_id=chat_id,
        question=question,
    )
