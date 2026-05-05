"""TIER-B health screening (Phase 3.2A) — lazy on-demand FSM handlers.

Запускается из 2 точек:
  - free-text trigger в ai_assistant (`detect_health_signal` hit)
  - explicit opt-in (callback из settings menu или free-text «настрой советы»)

После complete: Ayla `POST /profile/` пересчитывает нормы с override
(pregnancy/breastfeeding/eating_disorder ladder) → бот рендерит «Учла важное».

См. Design Doc v2 §4.5 + §4.6.
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from asgiref.sync import sync_to_async
from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback

from maxbot import keyboards
from maxbot.personalization import get_or_create_bot_user
from maxbot.states import NutritionAnketaStates


logger = logging.getLogger("maxbot.handlers.health_screening")
router = Router()


CONSENT_TEXT = (
    "🤖 Хочу подсказать аккуратно — но сначала "
    "пара уточнений (15 секунд), чтобы совет был безопасным."
)

PREGNANCY_TEXT = "Сейчас беременна?"
BREASTFEEDING_TEXT = "Кормишь грудью?"
DIABETES_TEXT = "Есть диабет или преддиабет?"
CHRONIC_TEXT = (
    "Хронические состояния — выбери всё, что относится. "
    "Когда закончишь, нажми «✓ Готово»."
)
ALLERGIES_TEXT = "Аллергии или непереносимость продуктов?"
ALLERGIES_FREE_TEXT_PROMPT = "Какие? Напиши через запятую."
MEDS_TEXT = "Принимаешь регулярные лекарства? (какие — не спрашиваю)"
MENOPAUSE_TEXT = "Есть проявления менопаузы или предклимакс?"


# ─── Helpers ───────────────────────────────────────────────────────────────


def _persist_health_flag(bot_user, key: str, value) -> None:
    """Sync ORM helper. Updates BotUser.health_flags JSON, saves only that field.

    Module-level (not nested) for monkeypatch in tests.
    """
    flags = dict(bot_user.health_flags or {})
    flags[key] = value
    bot_user.health_flags = flags
    bot_user.save(update_fields=["health_flags"])


def _utc_now_iso() -> str:
    return datetime.now(ZoneInfo("UTC")).isoformat()


# ─── Public entry ──────────────────────────────────────────────────────────


async def start_health_screening(
    *, bot, chat_id: int, context: MemoryContext,
) -> None:
    """Public entry — invoked from ai_assistant pre-hook OR explicit-opt-in handler."""
    await context.set_state(NutritionAnketaStates.awaiting_health_consent)
    await bot.send_message(
        chat_id=chat_id,
        text=CONSENT_TEXT,
        attachments=[keyboards.tier_b_consent_keyboard()],
    )


# ─── Screen 0 — consent ────────────────────────────────────────────────────


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_TIER_B_CONSENT_OK)
async def on_health_consent_ok(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None or callback.callback.user is None:
        return
    user_id = callback.callback.user.user_id
    full_name = callback.callback.user.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)
    await sync_to_async(_persist_health_flag)(
        bot_user, "health_consent_acked_at", _utc_now_iso(),
    )
    await context.set_state(NutritionAnketaStates.awaiting_pregnancy)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=PREGNANCY_TEXT,
        attachments=[keyboards.tier_b_yes_no_keyboard()],
    )


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_TIER_B_CONSENT_DECLINE)
async def on_health_consent_decline(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None or callback.callback.user is None:
        return
    user_id = callback.callback.user.user_id
    full_name = callback.callback.user.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)
    await sync_to_async(_persist_health_flag)(
        bot_user, "health_consent_declined_at", _utc_now_iso(),
    )
    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "Хорошо, поняла. Буду отвечать без персональных рекомендаций — "
            "общая инфа всегда доступна. Если передумаешь, напиши «настрой советы»."
        ),
    )
