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


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_CONSENT_OK)
async def on_consent_ok(callback: MessageCallback, context: MemoryContext) -> None:
    """Согласие → переход на awaiting_gender."""
    # Заполнено в Task 5.
    raise NotImplementedError("filled in Task 5")


@router.message_callback(
    F.callback.payload == keyboards.PAYLOAD_ANKETA_CONSENT_DECLINE,
)
async def on_consent_decline(
    callback: MessageCallback, context: MemoryContext,
) -> None:
    """Отказ → state cleared, exit на главное меню."""
    # Заполнено в Task 5.
    raise NotImplementedError("filled in Task 5")
