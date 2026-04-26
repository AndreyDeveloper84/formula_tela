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
from maxapi.enums.sender_action import SenderAction
from maxapi.types import MessageCallback, MessageCreated

from maxbot import keyboards, texts
from maxbot.llm import LLM_GIVEUP_MESSAGE, chat_rag
from maxbot.mcp_client import MaxbotMCPClient
from maxbot.personalization import get_or_create_bot_user
from maxbot.response_cache import get_cached_answer, set_cached_answer
from maxbot.states import AskStates
from notifications import send_notification_telegram
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

    # Нативный typing-индикатор пока LLM думает (~5-10s через прокси).
    # Best-effort: сетевой сбой не должен блокировать ответ клиенту.
    try:
        await event.bot.send_action(chat_id=chat_id, action=SenderAction.TYPING_ON)
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_action TYPING_ON failed: %s", exc)

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
    """RAG-as-context (1 LLM call после search_faq, без tool-use loop).

    Быстрее chat_with_tools на ~30%. Если top FAQ-similarity < threshold —
    возвращаем GIVEUP без вызова LLM (экономия ещё ~2s).

    Перед запуском пайплайна — проверка response cache (24ч TTL): повторные
    «как записаться?» отдаются мгновенно без OpenAI/MCP. Кэшируем только
    успешные ответы (LLM_GIVEUP_MESSAGE — нет, чтобы retry имел шанс).
    """
    import time
    started = time.perf_counter()

    cached = await get_cached_answer(user_text)
    if cached is not None:
        elapsed = time.perf_counter() - started
        logger.info("ai_assistant: CACHE HIT %.3fs user_id=%s text=%r",
                    elapsed, sender.user_id, user_text[:60])
        return cached

    try:
        mcp_client = MaxbotMCPClient.instance()
        answer = await chat_rag(
            user_text=user_text,
            system_prompt=texts.AI_SYSTEM_PROMPT,
            mcp_client=mcp_client,
        )
        elapsed = time.perf_counter() - started
        logger.info("ai_assistant: %.2fs user_id=%s text=%r answer_len=%d",
                    elapsed, sender.user_id, user_text[:60], len(answer))
        if answer != LLM_GIVEUP_MESSAGE:
            await set_cached_answer(user_text, answer)
        return answer
    except Exception:  # noqa: BLE001
        elapsed = time.perf_counter() - started
        logger.exception("ai_assistant: chat_rag crashed after %.2fs user_id=%s text=%r",
                         elapsed, sender.user_id, user_text[:80])
        return LLM_GIVEUP_MESSAGE


async def _create_bot_inquiry(*, user_id: int, full_name: str, chat_id: int, question: str) -> None:
    """Создаём BotInquiry для менеджера + Telegram-алерт."""
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)
    inquiry = await sync_to_async(BotInquiry.objects.create)(
        bot_user=bot_user,
        chat_id=chat_id,
        question=question,
    )
    # Алерт менеджеру в Telegram (через прокси, см. notifications/)
    await sync_to_async(send_notification_telegram)(
        f"🤖 Вопрос для менеджера от MAX-бота\n\n"
        f"👤 {bot_user.client_name or bot_user.display_name or f'#{user_id}'}\n"
        f"❓ {question}\n\n"
        f"Ответить: /admin/services_app/botinquiry/{inquiry.id}/change/"
    )
