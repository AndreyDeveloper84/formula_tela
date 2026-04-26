"""maxbot.welcome — кэшированный upload приветственной картинки."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.test import override_settings

from maxapi.enums.attachment import AttachmentType
from maxapi.enums.upload_type import UploadType
from maxapi.types.attachments.attachment import Attachment
from maxapi.types.attachments.upload import AttachmentPayload, AttachmentUpload


@pytest.fixture
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def welcome_image_file(tmp_path):
    """Реальный файл-плейсхолдер. Содержимое не важно — bot.upload_media мокается."""
    f = tmp_path / "welcome.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0fake jpeg")
    return f


def _fake_upload(token: str = "TOKEN_ABC") -> AttachmentUpload:
    return AttachmentUpload(
        type=UploadType.IMAGE,
        payload=AttachmentPayload(token=token),
    )


# ─── cache hit ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_welcome_returns_attachment_on_cache_hit(_clear_cache, welcome_image_file):
    """Cache hit → возвращаем Attachment, bot.upload_media НЕ вызывается."""
    from maxbot.welcome import CACHE_KEY, get_welcome_attachment

    cached_dict = _fake_upload("CACHED").model_dump()
    await sync_to_async(cache.set)(CACHE_KEY, cached_dict, 60)

    bot = MagicMock()
    bot.upload_media = AsyncMock()

    with override_settings(MAXBOT_WELCOME_IMAGE_PATH=str(welcome_image_file)):
        result = await get_welcome_attachment(bot)

    assert isinstance(result, Attachment)
    assert result.type == AttachmentType.IMAGE.value
    assert result.payload.payload.token == "CACHED"
    bot.upload_media.assert_not_awaited()


# ─── cache miss + upload ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_welcome_uploads_and_caches_on_miss(_clear_cache, welcome_image_file):
    """Cache miss + file exists → upload_media + cache.set + Attachment."""
    from maxbot.welcome import CACHE_KEY, CACHE_TTL_SECONDS, get_welcome_attachment

    bot = MagicMock()
    bot.upload_media = AsyncMock(return_value=_fake_upload("FRESH"))

    with override_settings(MAXBOT_WELCOME_IMAGE_PATH=str(welcome_image_file)):
        result = await get_welcome_attachment(bot)

    assert isinstance(result, Attachment)
    assert result.payload.payload.token == "FRESH"
    bot.upload_media.assert_awaited_once()
    # cache теперь содержит сериализованный dict
    cached = await sync_to_async(cache.get)(CACHE_KEY)
    assert cached is not None
    assert cached["payload"]["token"] == "FRESH"


@pytest.mark.asyncio
async def test_welcome_uses_cache_on_second_call(_clear_cache, welcome_image_file):
    """Первый вызов — upload, второй — cache (1 upload total)."""
    from maxbot.welcome import get_welcome_attachment

    bot = MagicMock()
    bot.upload_media = AsyncMock(return_value=_fake_upload("ONCE"))

    with override_settings(MAXBOT_WELCOME_IMAGE_PATH=str(welcome_image_file)):
        await get_welcome_attachment(bot)
        await get_welcome_attachment(bot)

    bot.upload_media.assert_awaited_once()


# ─── degradation ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_welcome_returns_none_when_file_missing(_clear_cache):
    """Файла нет → None, upload_media не зовётся."""
    from maxbot.welcome import get_welcome_attachment

    bot = MagicMock()
    bot.upload_media = AsyncMock()

    with override_settings(MAXBOT_WELCOME_IMAGE_PATH="/nonexistent/welcome.jpg"):
        result = await get_welcome_attachment(bot)

    assert result is None
    bot.upload_media.assert_not_awaited()


@pytest.mark.asyncio
async def test_welcome_returns_none_when_upload_fails(_clear_cache, welcome_image_file):
    """Upload упал → None, cache не заполнился (retry будет на следующий /start)."""
    from maxbot.welcome import CACHE_KEY, get_welcome_attachment

    bot = MagicMock()
    bot.upload_media = AsyncMock(side_effect=RuntimeError("MAX upload server down"))

    with override_settings(MAXBOT_WELCOME_IMAGE_PATH=str(welcome_image_file)):
        result = await get_welcome_attachment(bot)

    assert result is None
    assert await sync_to_async(cache.get)(CACHE_KEY) is None


@pytest.mark.asyncio
async def test_welcome_clears_corrupt_cache_and_reuploads(_clear_cache, welcome_image_file):
    """Если cache содержит мусор (старый формат / битый dict) — очистить + upload."""
    from maxbot.welcome import CACHE_KEY, get_welcome_attachment

    # Кладём dict без обязательных полей (выбросит ValidationError при AttachmentUpload(**))
    await sync_to_async(cache.set)(CACHE_KEY, {"garbage": "data"}, 60)

    bot = MagicMock()
    bot.upload_media = AsyncMock(return_value=_fake_upload("RECOVERED"))

    with override_settings(MAXBOT_WELCOME_IMAGE_PATH=str(welcome_image_file)):
        result = await get_welcome_attachment(bot)

    assert isinstance(result, Attachment)
    assert result.payload.payload.token == "RECOVERED"
    bot.upload_media.assert_awaited_once()
