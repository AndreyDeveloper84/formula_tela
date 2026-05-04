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
import uuid

from asgiref.sync import sync_to_async
from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.types import MessageCallback, MessageCreated

from maxbot import keyboards
from maxbot.services.ayla_user_proxy import external_user_id_for
from maxbot.services.nutrition_client import (
    NutritionAPIError,
    NutritionUnavailableError,
    get_nutrition_client,
)
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


# ─── helpers ───────────────────────────────────────────────────────────────


def _client():
    """Indirection чтобы тесты могли monkeypatch'ить."""
    return get_nutrition_client()


async def _resolve_bot_user(callback_or_event):
    """Получить BotUser по sender max_user_id с lazy-create.

    Принимает либо MessageCallback (имеет .callback.user.user_id), либо
    MessageCreated (имеет .message.sender.user_id).
    """
    from maxbot.personalization import get_or_create_bot_user
    if hasattr(callback_or_event, "callback"):
        sender_id = callback_or_event.callback.user.user_id  # MessageCallback
    else:
        sender_id = callback_or_event.message.sender.user_id  # MessageCreated
    return await sync_to_async(get_or_create_bot_user)(sender_id)


def _idempotency_key(external_user_id: str, step: str) -> str:
    """UUID5 — стабилен между ретраями того же шага.

    NOTE (deferred): этот ключ ПОКА не передаётся в `upsert_profile` —
    у `NutritionClient.upsert_profile()` нет kwarg `idempotency_key`.
    Helper зарезервирован под расширение клиента (Phase 3.2): добавить
    `idempotency_key: str | None = None` в client method, который
    приклеит его как HTTP header `Idempotency-Key: <uuid>` (Ayla spec §1.2).
    """
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{external_user_id}:anketa:{step}"))


async def _upsert(
    callback_or_event,
    *,
    step: str,
    body: dict,
    advance_to,
    context: MemoryContext,
    next_text: str,
    next_keyboard,
    chat_id: int,
) -> None:
    """Общий шаг анкеты: POST в Ayla → если успех, advance state + render
    next screen. На транзиентной ошибке — show retry hint, state не меняем.
    """
    bot_user = await _resolve_bot_user(callback_or_event)
    extid = external_user_id_for(bot_user)

    try:
        await _client().upsert_profile(
            external_user_id=extid,
            data={**body, "complete": False},
        )
    except NutritionUnavailableError:
        await callback_or_event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Хм, не могу сохранить шаг — попробуй ещё раз через минуту "
                "или нажми «Назад» в меню. Извини 🙏"
            ),
        )
        return
    except NutritionAPIError as exc:
        logger.warning("anketa.upsert_failed step=%s err=%s", step, exc)
        await callback_or_event.bot.send_message(
            chat_id=chat_id,
            text="Не получилось — давай попробуем заново через меню.",
        )
        await context.clear()
        return

    await context.set_state(advance_to)
    await callback_or_event.bot.send_message(
        chat_id=chat_id,
        text=next_text,
        attachments=[next_keyboard()] if next_keyboard else None,
    )


# ─── gender ────────────────────────────────────────────────────────────────


AGE_TEXT = (
    "● ● ○ ○ ○\n\n"
    "Сколько тебе лет? Напиши число (например, 35) или пропусти."
)


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_GENDER_FEMALE)
async def on_gender_female(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await _upsert(
        callback,
        step="gender",
        body={"gender": "female"},
        advance_to=NutritionAnketaStates.awaiting_age,
        context=context,
        next_text=AGE_TEXT,
        next_keyboard=keyboards.anketa_skip_keyboard,
        chat_id=chat_id,
    )


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_GENDER_MALE)
async def on_gender_male(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await _upsert(
        callback,
        step="gender",
        body={"gender": "male"},
        advance_to=NutritionAnketaStates.awaiting_age,
        context=context,
        next_text=AGE_TEXT,
        next_keyboard=keyboards.anketa_skip_keyboard,
        chat_id=chat_id,
    )


# ─── age (text-input) ──────────────────────────────────────────────────────


HEIGHT_TEXT = (
    "● ● ● ○ ○\n\n"
    "Какой у тебя рост в сантиметрах? Напиши число (например, 165) "
    "или пропусти."
)


async def _treat_text_step_as_skip(
    msg, ctx, chat_id, *, field, advance_to, next_text, next_kb,
) -> None:
    """Helper: free-text парсер вернул REFUSED → шлём как skip."""
    await _upsert(
        msg,
        step=field,
        body={"_skipped_fields": [field]},
        advance_to=advance_to,
        context=ctx,
        next_text=next_text,
        next_keyboard=next_kb,
        chat_id=chat_id,
    )


@router.message_created(NutritionAnketaStates.awaiting_age)
async def on_age_text(event: MessageCreated, context: MemoryContext) -> None:
    """Юзер пишет возраст — пытаемся parse_age."""
    from maxbot.ai_parsers import parse_age, REFUSED

    text = (event.message.body.text or "").strip()
    chat_id = event.message.recipient.chat_id

    parsed = await parse_age(text)

    if parsed == REFUSED:
        await _treat_text_step_as_skip(
            event, context, chat_id,
            field="age",
            advance_to=NutritionAnketaStates.awaiting_height,
            next_text=HEIGHT_TEXT,
            next_kb=keyboards.anketa_skip_keyboard,
        )
        return

    if parsed is None:
        await event.bot.send_message(
            chat_id=chat_id,
            text=(
                "Не понял возраст — напиши число от 16 до 99 (например, 35) "
                "или нажми «⏭ Пропустить»."
            ),
            attachments=[keyboards.anketa_skip_keyboard()],
        )
        return

    await _upsert(
        event,
        step="age",
        body={"age": parsed},
        advance_to=NutritionAnketaStates.awaiting_height,
        context=context,
        next_text=HEIGHT_TEXT,
        next_keyboard=keyboards.anketa_skip_keyboard,
        chat_id=chat_id,
    )


# ─── universal Skip handler — диспетчер по текущему state ──────────────────


_SKIP_FIELD_BY_STATE = {
    str(NutritionAnketaStates.awaiting_gender): (
        "gender",
        NutritionAnketaStates.awaiting_age,
        AGE_TEXT,
        keyboards.anketa_skip_keyboard,
    ),
    str(NutritionAnketaStates.awaiting_age): (
        "age",
        NutritionAnketaStates.awaiting_height,
        HEIGHT_TEXT,
        keyboards.anketa_skip_keyboard,
    ),
    # остальные пары добавляются в Tasks 8-9
}


@router.message_callback(F.callback.payload == keyboards.PAYLOAD_ANKETA_SKIP)
async def on_skip(callback: MessageCallback, context: MemoryContext) -> None:
    """Универсальный Skip: маппит current state → field name + next state."""
    state = await context.get_state()
    if str(state) not in _SKIP_FIELD_BY_STATE:
        # Skip-кнопка не должна появляться вне состояний из мапа.
        # Если попали — это либо UI-баг, либо забыли добавить state в
        # _SKIP_FIELD_BY_STATE при добавлении нового шага.
        logger.warning(
            "anketa.skip_unknown_state state=%r — _SKIP_FIELD_BY_STATE not updated?",
            state,
        )
        return
    field, advance_to, next_text, next_kb = _SKIP_FIELD_BY_STATE[str(state)]

    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return

    await _upsert(
        callback,
        step=field,
        body={"_skipped_fields": [field]},
        advance_to=advance_to,
        context=context,
        next_text=next_text,
        next_keyboard=next_kb,
        chat_id=chat_id,
    )
