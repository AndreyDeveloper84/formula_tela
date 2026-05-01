"""AI-помощник handler — свободный текст → AI Concierge (Phase 2.3 §T10).

Триггеры:
1. Кнопка «💬 Задать вопрос» в главном меню → state `awaiting_question`
2. Любой text-message без активного booking-state (вытесняет старый fallback)

Pipeline (T10):
1. send_action TYPING_ON (typing-индикатор пока LLM думает)
2. context.clear() — диалог one-shot со state-стороны (FSM не нужен,
   AI Concierge сам управляет history через Conversation+Message)
3. intent-router → если phatic (привет/спасибо/как дела) → canned response,
   AI Concierge не зовётся (fast path, $0 OpenAI)
4. get_or_create_bot_user → нужен для AI Concierge + menu_state
5. ai_concierge.send_message(bot_user, message_text) → ChatResponseDTO
6. if dto.action_type → render_action() → (text, action_attachments)
7. else → text=dto.content, action_attachments=[]
8. is_giveup(content) AND action_type=None → BotInquiry + Telegram + canned text
9. send_with_main_menu(text, extra_attachments=action_attachments)

Backward-compat: chat_rag и response_cache остаются в llm.py / response_cache.py
для warmup (10 hot questions, отдельный preload-пайплайн).
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.enums.sender_action import SenderAction
from maxapi.types import MessageCallback, MessageCreated

from maxbot import ai_concierge, ai_ui, keyboards, texts
from maxbot.ai_action_service import close_active_conversation
from maxbot.intents import detect_intent
from maxbot.llm import LLM_GIVEUP_MESSAGE, is_giveup
from maxbot.menu_state import send_with_main_menu
from maxbot.personalization import get_or_create_bot_user
from maxbot.states import AskStates
from notifications import send_notification_telegram
from services_app.models import BotInquiry, Conversation


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


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_MENU_MY_BOOKINGS)
async def on_my_bookings_button(callback: MessageCallback, context: MemoryContext) -> None:
    """Клик «📋 Мои записи» → AI Concierge с pseudo-text «покажи мои записи»."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await context.clear()
    user = callback.callback.user
    bot_user, _ = await get_or_create_bot_user(user.user_id, user.full_name, chat_id=chat_id)
    await run_ai_turn(
        bot=callback.bot, chat_id=chat_id, bot_user=bot_user,
        user_text="Покажи мои записи (предстоящие и прошедшие)",
        original_user_text="cb:menu:my_bookings",
    )


# ─── Free-text → AI Concierge ──────────────────────────────────────────────


@router.message_created()
async def on_free_text(event: MessageCreated, context: MemoryContext) -> None:
    if event.message.sender is None:
        return  # системные

    chat_id = event.message.recipient.chat_id
    user_text = (event.message.body.text or "").strip() if event.message.body else ""
    if not user_text:
        return

    # 1. MARK_SEEN + TYPING_ON (best-effort, порядок важен — typing должен
    # быть последним active sender_action чтобы UI показал «печатает»)
    try:
        await event.bot.send_action(chat_id=chat_id, action=SenderAction.MARK_SEEN)
    except Exception as exc:  # noqa: BLE001
        logger.debug("send_action MARK_SEEN failed: %s", exc)
    try:
        await event.bot.send_action(chat_id=chat_id, action=SenderAction.TYPING_ON)
    except Exception as exc:  # noqa: BLE001
        logger.warning("send_action TYPING_ON failed: %s", exc)

    # 2. Чистим state — AI Concierge управляет multi-turn через Conversation
    await context.clear()

    sender = event.message.sender
    bot_user, _ = await get_or_create_bot_user(sender.user_id, sender.full_name, chat_id=chat_id)

    # 3. Intent-router (regex, ~1ms): phatic phrases → canned, без OpenAI
    intent_response = detect_intent(user_text)
    if intent_response is not None:
        logger.info("ai_assistant: INTENT MATCH user_id=%s text=%r",
                    sender.user_id, user_text[:60])
        await send_with_main_menu(
            bot=event.bot, chat_id=chat_id,
            text=intent_response, bot_user=bot_user,
        )
        return

    # 4-7. Прогон через AI Concierge + рендер + отправка
    await run_ai_turn(
        bot=event.bot, chat_id=chat_id,
        bot_user=bot_user, user_text=user_text,
        original_user_text=user_text,
    )


# ─── Public helper — переиспользуется в ai_callbacks.py ────────────────────


async def run_ai_turn(
    *,
    bot,
    chat_id: int,
    bot_user,
    user_text: str,
    original_user_text: str | None = None,
) -> None:
    """Один turn AI Concierge: AI Concierge → render → send_with_main_menu.

    Используется и в on_free_text (свободный ввод), и в callback'ах
    cb:ai:pick_master/pick_slot/answer — там pseudo-user-text формируется
    из выбора клиента и передаётся в AI как продолжение диалога.

    original_user_text — что записать в BotInquiry если AI упал. Для
    callback'ов это краткое описание выбора, для free-text — то же что
    user_text.
    """
    inquiry_question = original_user_text or user_text

    try:
        dto = await ai_concierge.send_message(
            bot_user=bot_user, message_text=user_text,
        )
    except Exception:  # noqa: BLE001
        logger.exception("ai_assistant: AI Concierge crashed text=%r",
                         user_text[:80])
        await close_active_conversation(bot_user, outcome=Conversation.Outcome.ERROR.value)
        await _create_bot_inquiry(
            user_id=bot_user.max_user_id,
            full_name=bot_user.display_name or "",
            chat_id=chat_id, question=inquiry_question,
        )
        await send_with_main_menu(
            bot=bot, chat_id=chat_id,
            text=texts.AI_FORWARDED_TO_MANAGER, bot_user=bot_user,
        )
        return

    if dto.action_type:
        rendered_text, action_attachments = ai_ui.render_action(
            conversation_id=str(dto.conversation_id),
            action_type=dto.action_type,
            action_data=dto.action_data or {},
        )
        # Преамбула от LLM перед tool_call (например «Конечно, давайте
        # подберём!») — клеим к карточке, иначе бот звучит как робот.
        preamble = (dto.content or "").strip()
        if preamble:
            text = f"{preamble}\n\n{rendered_text}"
        else:
            text = rendered_text
    elif _is_promise_without_action(dto.content):
        # Safety net: LLM написал «сейчас подберу», но не вызвал tool →
        # клиент получит обещание + пустоту. Принудительно даём ему меню.
        logger.warning(
            "ai_assistant: promise-without-action detected, fallback to main menu. "
            "content=%r", (dto.content or "")[:120],
        )
        text = (dto.content or "").strip() + (
            "\n\n(Уточните, что именно подобрать — выберите из меню или "
            "опишите подробнее.)"
        )
        action_attachments = []
    else:
        text = dto.content
        action_attachments = []

    # Сохраняем итоговый текст в Message.rendered_text — для admin-аудита
    # (особенно важно для tool-call: content="" а карточки видны только в текст'е).
    if dto.assistant_message_id is not None:
        try:
            await ai_concierge.update_message_rendered_text(
                dto.assistant_message_id, text,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("update_message_rendered_text failed: %s", exc)

    if dto.action_type is None and is_giveup(text):
        await close_active_conversation(bot_user, outcome=Conversation.Outcome.REDIRECTED.value)
        await _create_bot_inquiry(
            user_id=bot_user.max_user_id,
            full_name=bot_user.display_name or "",
            chat_id=chat_id, question=inquiry_question,
        )
        await send_with_main_menu(
            bot=bot, chat_id=chat_id,
            text=texts.AI_FORWARDED_TO_MANAGER, bot_user=bot_user,
        )
        return

    # MAX API ограничение: только ОДИН inline_keyboard на сообщение.
    # Если у action есть свои кнопки (карточка с CallbackButton'ами) — отправляем
    # БЕЗ main_menu (оно «плавает» на предыдущем сообщении). Если action без
    # кнопок (show_my_bookings empty, ask_clarification без options) — приклеиваем
    # main_menu для удобства навигации.
    has_card_keyboard = any(
        getattr(att, "type", None) == "inline_keyboard"
        for att in action_attachments
    )
    if has_card_keyboard:
        await bot.send_message(
            chat_id=chat_id, text=text, attachments=action_attachments,
        )
    else:
        await send_with_main_menu(
            bot=bot, chat_id=chat_id, text=text, bot_user=bot_user,
        )


# ─── Helpers ────────────────────────────────────────────────────────────────


_PROMISE_PATTERNS = (
    "сейчас подберу", "подобрала", "подобрал", "подбираю",
    "вот варианты", "вот кто подойдёт", "вот кто подходит",
    "рассмотрим", "рассмотрите", "посмотрим", "посмотрите",
    "сейчас гляну", "гляну свободное", "гляну доступн",
    "давайте уточним", "давай уточним", "давайте подберём",
    "записываю — проверьте",
)


def _is_promise_without_action(content: str | None) -> bool:
    """LLM написал тёплую преамбулу-обещание, но НЕ вызвал tool_call.

    Detect-by-substring (lower-case): такая ситуация = silent failure для
    клиента (получит «сейчас подберу...» и тишину). Возвращаем True если
    content содержит маркер обещания → handler покажет fallback с меню.
    """
    if not content:
        return False
    text = content.lower().strip()
    return any(marker in text for marker in _PROMISE_PATTERNS)


async def _create_bot_inquiry(*, user_id: int, full_name: str, chat_id: int,
                              question: str) -> None:
    """Создаём BotInquiry для менеджера + Telegram-алерт."""
    bot_user, _ = await get_or_create_bot_user(user_id, full_name, chat_id=chat_id)
    inquiry = await sync_to_async(BotInquiry.objects.create)(
        bot_user=bot_user,
        chat_id=chat_id,
        question=question,
    )
    await sync_to_async(send_notification_telegram)(
        f"🤖 Вопрос для менеджера от MAX-бота\n\n"
        f"👤 {bot_user.client_name or bot_user.display_name or f'#{user_id}'}\n"
        f"❓ {question}\n\n"
        f"Ответить: /admin/services_app/botinquiry/{inquiry.id}/change/"
    )
