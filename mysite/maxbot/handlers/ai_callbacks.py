"""AI Concierge callback handlers — клики по cb:ai:* кнопкам.

Phase 2.3 §T08. Регистрируется ПЕРЕД ai_assistant_router в get_routers(),
чтобы матчить специфичные callback-payload'ы раньше general message_created.

Callback payloads (стабильный wire-format с ai_ui.py):
- cb:ai:pick_master:{conv}:{master_id} — клиент выбрал мастера → AI turn
- cb:ai:pick_slot:{conv}:{slot_iso}    — клиент выбрал слот → AI turn
- cb:ai:answer:{conv}:{option_idx}     — ответ на ask_clarification → AI turn
- cb:ai:confirm:{conv}                  — подтверждение → execute_confirm_booking
- cb:ai:cancel:{conv}                   — отмена → close conversation
- cb:ai:edit:{conv}                     — изменить → ask_clarification

pick/answer переводят выбор клиента в pseudo-user-message и зовут
ai_concierge через run_ai_turn (диалог продолжается с тем же conversation,
LLM учитывает в контексте что клиент выбрал).
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback

from maxbot import ai_action_service
from maxbot.handlers.ai_assistant import run_ai_turn
from maxbot.menu_state import send_with_main_menu
from maxbot.personalization import get_or_create_bot_user
from services_app.models import Conversation, Master, Message


logger = logging.getLogger("maxbot.ai_callbacks")
router = Router()


CB_PREFIX = "cb:ai:"


# ─── Helpers ───────────────────────────────────────────────────────────────


def _parse_payload(payload: str) -> tuple[str, list[str]]:
    """Разбирает cb:ai:{kind}:{conv}[:rest...] → (kind, [conv, *rest])."""
    parts = (payload or "").split(":")
    # parts: ["cb", "ai", kind, conv, ...]
    if len(parts) < 4 or parts[0] != "cb" or parts[1] != "ai":
        return "", []
    return parts[2], parts[3:]


@sync_to_async
def _load_active_conversation(conv_id: str) -> Conversation | None:
    return Conversation.objects.filter(id=conv_id, is_active=True).first()


@sync_to_async
def _master_label(master_id: int) -> str:
    m = Master.objects.filter(id=master_id).first()
    return m.name if m else f"#{master_id}"


@sync_to_async
def _last_clarification_options(conv_id: str) -> list[str]:
    """Загружаем options последнего ask_clarification message — для маппинга idx → text."""
    msg = (
        Message.objects
        .filter(conversation_id=conv_id, role=Message.Role.ASSISTANT,
                action_type="ask_clarification")
        .order_by("-created_at")
        .first()
    )
    if not msg or not msg.action_data:
        return []
    return list(msg.action_data.get("options") or [])


# ─── Pick master ───────────────────────────────────────────────────────────


@router.message_callback(F.callback.payload.startswith("cb:ai:pick_master:"))
async def on_pick_master(callback: MessageCallback, context: MemoryContext) -> None:
    payload = callback.callback.payload
    kind, rest = _parse_payload(payload)
    if kind != "pick_master" or len(rest) < 2:
        return
    conv_id, master_id_str = rest[0], rest[1]

    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    user = callback.callback.user
    bot_user, _ = await get_or_create_bot_user(user.user_id, user.full_name)
    master_name = await _master_label(int(master_id_str))

    # Pseudo-user-message — продолжение диалога в AI Concierge
    pseudo = f"Выбираю мастера {master_name} (id={master_id_str})"
    logger.info("ai_callbacks.pick_master conv=%s master=%s", conv_id, master_id_str)
    await run_ai_turn(
        bot=callback.bot, chat_id=chat_id,
        bot_user=bot_user, user_text=pseudo,
        original_user_text=f"выбор мастера {master_name}",
    )


# ─── Pick slot ─────────────────────────────────────────────────────────────


@router.message_callback(F.callback.payload.startswith("cb:ai:pick_slot:"))
async def on_pick_slot(callback: MessageCallback, context: MemoryContext) -> None:
    payload = callback.callback.payload
    kind, rest = _parse_payload(payload)
    if kind != "pick_slot" or len(rest) < 2:
        return
    conv_id = rest[0]
    slot_str = ":".join(rest[1:])  # время может содержать ":" (10:00)

    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    user = callback.callback.user
    bot_user, _ = await get_or_create_bot_user(user.user_id, user.full_name)

    pseudo = f"Хочу записаться на {slot_str}"
    logger.info("ai_callbacks.pick_slot conv=%s slot=%s", conv_id, slot_str)
    await run_ai_turn(
        bot=callback.bot, chat_id=chat_id,
        bot_user=bot_user, user_text=pseudo,
        original_user_text=f"выбор слота {slot_str}",
    )


# ─── Answer (ask_clarification option) ─────────────────────────────────────


@router.message_callback(F.callback.payload.startswith("cb:ai:answer:"))
async def on_answer(callback: MessageCallback, context: MemoryContext) -> None:
    payload = callback.callback.payload
    kind, rest = _parse_payload(payload)
    if kind != "answer" or len(rest) < 2:
        return
    conv_id, idx_str = rest[0], rest[1]

    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    user = callback.callback.user
    bot_user, _ = await get_or_create_bot_user(user.user_id, user.full_name)

    options = await _last_clarification_options(conv_id)
    try:
        chosen = options[int(idx_str)]
    except (ValueError, IndexError):
        chosen = "(непонятный выбор)"

    pseudo = chosen
    logger.info("ai_callbacks.answer conv=%s idx=%s text=%r",
                conv_id, idx_str, chosen[:60])
    await run_ai_turn(
        bot=callback.bot, chat_id=chat_id,
        bot_user=bot_user, user_text=pseudo,
        original_user_text=f"ответ на уточнение: {chosen}",
    )


# ─── Confirm booking ───────────────────────────────────────────────────────


@router.message_callback(F.callback.payload.startswith("cb:ai:confirm:"))
async def on_confirm(callback: MessageCallback, context: MemoryContext) -> None:
    payload = callback.callback.payload
    kind, rest = _parse_payload(payload)
    if kind != "confirm" or not rest:
        return
    conv_id = rest[0]

    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    user = callback.callback.user
    bot_user, _ = await get_or_create_bot_user(user.user_id, user.full_name)

    conversation = await _load_active_conversation(conv_id)
    if conversation is None:
        await send_with_main_menu(
            bot=callback.bot, chat_id=chat_id,
            text="Эта запись уже завершена. Если хотите, начнём заново — спросите про услуги.",
            bot_user=bot_user,
        )
        return

    logger.info("ai_callbacks.confirm conv=%s user=%s", conv_id, user.user_id)
    result = await ai_action_service.execute_confirm_booking(
        conversation=conversation, bot_user=bot_user,
    )
    await send_with_main_menu(
        bot=callback.bot, chat_id=chat_id,
        text=result.user_message, bot_user=bot_user,
    )


# ─── Cancel ────────────────────────────────────────────────────────────────


@router.message_callback(F.callback.payload.startswith("cb:ai:cancel:"))
async def on_cancel(callback: MessageCallback, context: MemoryContext) -> None:
    payload = callback.callback.payload
    kind, rest = _parse_payload(payload)
    if kind != "cancel" or not rest:
        return
    conv_id = rest[0]

    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    user = callback.callback.user
    bot_user, _ = await get_or_create_bot_user(user.user_id, user.full_name)

    conversation = await _load_active_conversation(conv_id)
    if conversation is None:
        # Уже закрыто — мягкий ответ
        await send_with_main_menu(
            bot=callback.bot, chat_id=chat_id,
            text="Запись уже отменена. Чем ещё помочь?",
            bot_user=bot_user,
        )
        return

    msg = await ai_action_service.cancel_conversation(conversation)
    await send_with_main_menu(
        bot=callback.bot, chat_id=chat_id, text=msg, bot_user=bot_user,
    )


# ─── Edit ──────────────────────────────────────────────────────────────────


@router.message_callback(F.callback.payload.startswith("cb:ai:edit:"))
async def on_edit(callback: MessageCallback, context: MemoryContext) -> None:
    """Изменить детали — отправляем pseudo-message «хочу изменить» в AI Concierge."""
    payload = callback.callback.payload
    kind, rest = _parse_payload(payload)
    if kind != "edit" or not rest:
        return
    conv_id = rest[0]

    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    user = callback.callback.user
    bot_user, _ = await get_or_create_bot_user(user.user_id, user.full_name)

    pseudo = "Хочу изменить детали записи"
    logger.info("ai_callbacks.edit conv=%s user=%s", conv_id, user.user_id)
    await run_ai_turn(
        bot=callback.bot, chat_id=chat_id,
        bot_user=bot_user, user_text=pseudo,
        original_user_text="изменение деталей записи",
    )
