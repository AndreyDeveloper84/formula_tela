"""Food scanner handler for the MAX bot (DRF-246).

Triggers:
1. User sends a photo (any image attachment in a MessageCreated event).
2. User clicks a 152-FZ consent button (accept / decline).

Flow on photo:
1. Resolve BotUser (autocreate if first contact).
2. If BotUser.food_scanner_consent_at is NULL → render consent prompt, do nothing.
3. Download image bytes from MAX CDN URL (the URL is short-lived, so we fetch
   immediately rather than handing it to Ayla).
4. POST to Ayla `/api/v1/nutrition/internal/scan/` via NutritionClient.
5. Render `ai_ui.render_food_scan` card with diary buttons.

Errors are surfaced as plain-text fallbacks — the bot never silently fails.
"""
from __future__ import annotations

import logging

import httpx
from asgiref.sync import sync_to_async
from django.utils import timezone
from maxapi import F, Router
from maxapi.context.context import MemoryContext
from maxapi.enums.attachment import AttachmentType
from maxapi.types import MessageCallback, MessageCreated

from maxbot import ai_ui
from maxbot.menu_state import send_with_main_menu
from maxbot.personalization import get_or_create_bot_user
from maxbot.services.ayla_user_proxy import external_user_id_for
from maxbot.services.nutrition_client import (
    FoodNotRecognizedError,
    NutritionAPIError,
    NutritionUnavailableError,
    get_nutrition_client,
)


logger = logging.getLogger("maxbot.food_scanner")
router = Router()

PHOTO_DOWNLOAD_TIMEOUT_S = 8.0
MAX_PHOTO_BYTES = 10 * 1024 * 1024  # Ayla serializer caps at 10 MiB.


# ─── Photo upload trigger ──────────────────────────────────────────────────


@router.message_created()
async def on_photo_message(event: MessageCreated, context: MemoryContext) -> None:
    """Fires only when message has at least one IMAGE attachment.

    We can't easily filter in `@router.message_created()` decorator without
    a custom F-expression, so we early-return here. Other handlers (free-text
    AI, FSM) keep working — order in main.py decides which sees the event
    first; food_scanner must be registered before ai_assistant for photos.
    """
    if event.message.sender is None:
        return  # системные

    body = event.message.body
    if body is None:
        return

    photo_url = _first_photo_url(body)
    if photo_url is None:
        return

    chat_id = event.message.recipient.chat_id
    sender = event.message.sender
    bot_user, _ = await get_or_create_bot_user(sender.user_id, sender.full_name)

    # Consent gate
    if bot_user.food_scanner_consent_at is None:
        text, atts = ai_ui.render_food_consent_request()
        await event.bot.send_message(chat_id=chat_id, text=text, attachments=atts)
        return

    # Download photo bytes from MAX CDN
    try:
        image_bytes = await _download_photo(photo_url)
    except _PhotoTooLargeError:
        await send_with_main_menu(
            bot=event.bot, chat_id=chat_id,
            text="Фото слишком большое. Пришлите фото поменьше (до 10 МБ).",
            bot_user=bot_user,
        )
        return
    except Exception as exc:  # noqa: BLE001
        logger.warning("food_scanner.download_failed url=%s err=%s",
                       photo_url[:60], type(exc).__name__)
        await send_with_main_menu(
            bot=event.bot, chat_id=chat_id,
            text="Не получилось загрузить фото. Попробуйте ещё раз.",
            bot_user=bot_user,
        )
        return

    external_id = external_user_id_for(bot_user)
    client = get_nutrition_client()

    try:
        scan = await client.scan_photo(
            external_user_id=external_id,
            image_bytes=image_bytes,
        )
    except FoodNotRecognizedError:
        await send_with_main_menu(
            bot=event.bot, chat_id=chat_id,
            text="Не получилось распознать блюдо на фото. Попробуйте сделать фото получше.",
            bot_user=bot_user,
        )
        return
    except NutritionUnavailableError as exc:
        logger.warning("food_scanner.unavailable user=%s reason=%s",
                       bot_user.max_user_id, exc)
        await send_with_main_menu(
            bot=event.bot, chat_id=chat_id,
            text="Сканер еды временно недоступен. Попробуйте через минуту.",
            bot_user=bot_user,
        )
        return
    except NutritionAPIError as exc:
        logger.exception("food_scanner.api_error user=%s err=%s",
                         bot_user.max_user_id, exc)
        await send_with_main_menu(
            bot=event.bot, chat_id=chat_id,
            text="Что-то пошло не так со сканером. Попробуйте позже.",
            bot_user=bot_user,
        )
        return

    text, attachments = ai_ui.render_food_scan(scan.raw)
    if attachments:
        await event.bot.send_message(
            chat_id=chat_id, text=text, attachments=attachments,
        )
    else:
        await send_with_main_menu(
            bot=event.bot, chat_id=chat_id, text=text, bot_user=bot_user,
        )


# ─── Consent callbacks ─────────────────────────────────────────────────────


@router.message_callback(F.callback.payload == "cb:nutrition:consent:agree")
async def on_consent_agree(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None or callback.callback.user is None:
        return
    user_id = callback.callback.user.user_id
    full_name = callback.callback.user.full_name
    bot_user, _ = await get_or_create_bot_user(user_id, full_name)

    await sync_to_async(_set_consent)(bot_user)
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Спасибо! Теперь шлите фото еды — я распознаю блюдо и посчитаю КБЖУ.",
    )


@router.message_callback(F.callback.payload == "cb:nutrition:consent:decline")
async def on_consent_decline(callback: MessageCallback, context: MemoryContext) -> None:
    chat_id = callback.message.recipient.chat_id if callback.message else None
    if chat_id is None:
        return
    await callback.bot.send_message(
        chat_id=chat_id,
        text="Понятно. Сканер еды доступен, когда передумаете — просто пришлите фото снова.",
    )


# ─── Helpers ───────────────────────────────────────────────────────────────


class _PhotoTooLargeError(Exception):
    pass


def _first_photo_url(body) -> str | None:
    """Return the URL of the first IMAGE attachment, or None."""
    attachments = getattr(body, "attachments", None) or []
    for att in attachments:
        if getattr(att, "type", None) != AttachmentType.IMAGE:
            continue
        payload = getattr(att, "payload", None)
        url = getattr(payload, "url", None) if payload else None
        if url:
            return url
    return None


async def _download_photo(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=PHOTO_DOWNLOAD_TIMEOUT_S) as http:
        async with http.stream("GET", url) as resp:
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > MAX_PHOTO_BYTES:
                    raise _PhotoTooLargeError(f"photo > {MAX_PHOTO_BYTES} bytes")
                chunks.append(chunk)
            return b"".join(chunks)


def _set_consent(bot_user) -> None:
    bot_user.food_scanner_consent_at = timezone.now()
    bot_user.save(update_fields=["food_scanner_consent_at"])
