"""TIER-A анкета — FSM handlers (Phase 3.1 Part 1).

Точка входа: `on_start_anketa` в nutrition_entry.py (после клика
PAYLOAD_NUTRITION_START_ANKETA). Дальше — chain handlers по state'ам:

    awaiting_consent → awaiting_gender → awaiting_age → awaiting_height →
    awaiting_weight → awaiting_goal → (awaiting_pace | awaiting_gain_clarify) →
    [awaiting_bmi_ladder] → complete

Каждый шаг шлёт PATCH в Ayla `POST /profile/` с complete=false; последний —
с complete=true. Idempotency-Key = uuid5(external_user_id, step_name).

См. `docs/plans/maxbot-phase3-nutrition-design.md` v2 §4 + Ayla spec §1.
"""
from __future__ import annotations

import logging

from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback, MessageCreated

from maxbot import keyboards
from maxbot.states import NutritionAnketaStates


logger = logging.getLogger("maxbot.handlers.nutrition_anketa")
router = Router()


CONSENT_TEXT = (
    "📝 Перед тем как начнём — короткий дисклеймер.\n\n"
    "Я попрошу 5 параметров (пол, возраст, рост, вес, цель), чтобы "
    "посчитать твою норму ккал и БЖУ. Эти данные хранятся в зашифрованном "
    "виде, используются только внутри сервиса (152-ФЗ).\n\n"
    "Любой шаг можно пропустить — тогда применю средние значения."
)

GENDER_TEXT = (
    "● ○ ○ ○ ○\n\n"
    "Какой у тебя пол?\n\n"
    "Это нужно для расчёта BMR (базового обмена) — у Ж и М разные "
    "коэффициенты. Можно пропустить — тогда возьму средние значения."
)


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_CONSENT_OK)
async def on_consent_ok(callback: MessageCallback, context: MemoryContext) -> None:
    """Согласие → переход на awaiting_gender."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    await context.set_state(NutritionAnketaStates.awaiting_gender)
    await callback.bot.send_message(
        chat_id=chat_id,
        text=GENDER_TEXT,
        attachments=[keyboards.anketa_gender_keyboard()],
    )


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_ANKETA_CONSENT_DECLINE,
)
async def on_consent_decline(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """Отказ от анкеты → state очищен. Юзер может вернуться позже из меню."""
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    await context.clear()
    await callback.bot.send_message(
        chat_id=chat_id,
        text=(
            "Поняла, без проблем. Когда соберёшься настроить — заходи в "
            "🍎 Дневник питания через главное меню.\n\n"
            "Сейчас можешь просто прислать фото блюда — посчитаю калории "
            "по средним значениям."
        ),
    )
