"""maxbot.master_image — кэшированный upload фото мастера (DRF-354 / B26).

Зеркалит test_welcome.py паттерн: cache hit, upload+cache, file missing,
upload failure. Master ORM-объект мокается через MagicMock с .id и .photo
полями — Master БД не нужен для unit-тестов модуля.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from asgiref.sync import sync_to_async
from django.core.cache import cache
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
def master_photo_file(tmp_path):
    """Фейковый JPEG на диске — bot.upload_media мокается, реальный декод не нужен."""
    f = tmp_path / "anna.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0fake jpeg")
    return f


def _master_with_photo(master_id: int, path):
    """Mock Master с .id и .photo (ImageField-like) указывающим на path."""
    photo = SimpleNamespace(name=str(path), path=str(path))
    photo.__bool__ = lambda self: True  # type: ignore[attr-defined]
    return SimpleNamespace(id=master_id, photo=photo)


def _master_without_photo(master_id: int):
    """Mock Master без photo (None — пустой ImageField)."""
    return SimpleNamespace(id=master_id, photo=None)


def _fake_upload(token: str = "TOKEN_M") -> AttachmentUpload:
    return AttachmentUpload(
        type=UploadType.IMAGE,
        payload=AttachmentPayload(token=token),
    )


# ─── 1. no photo → None ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_master_attachment_no_photo_returns_none(_clear_cache):
    """Master.photo=None → None, upload_media не зовётся."""
    from maxbot.master_image import get_master_attachment

    master = _master_without_photo(master_id=42)
    bot = MagicMock()
    bot.upload_media = AsyncMock()

    result = await get_master_attachment(bot, master)

    assert result is None
    bot.upload_media.assert_not_awaited()


# ─── 2. cache hit → no upload ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_master_attachment_cache_hit(_clear_cache, master_photo_file):
    """Второй вызов с тем же master_id берёт upload из кэша → 1 upload total."""
    from maxbot.master_image import get_master_attachment

    master = _master_with_photo(master_id=42, path=master_photo_file)
    bot = MagicMock()
    bot.upload_media = AsyncMock(return_value=_fake_upload("ONCE"))

    first = await get_master_attachment(bot, master)
    second = await get_master_attachment(bot, master)

    assert isinstance(first, Attachment)
    assert isinstance(second, Attachment)
    assert first.type == AttachmentType.IMAGE.value
    assert second.payload.payload.token == "ONCE"
    bot.upload_media.assert_awaited_once()


# ─── 3. upload failure → None + warning ───────────────────────────────────


@pytest.mark.asyncio
async def test_get_master_attachment_upload_failure_returns_none(
    _clear_cache, master_photo_file, caplog,
):
    """upload_media raises → None + log warning + cache не заполнился."""
    import logging

    from maxbot.master_image import _cache_key, get_master_attachment

    master = _master_with_photo(master_id=99, path=master_photo_file)
    bot = MagicMock()
    bot.upload_media = AsyncMock(side_effect=RuntimeError("MAX upload server 503"))

    with caplog.at_level(logging.WARNING, logger="maxbot.master_image"):
        result = await get_master_attachment(bot, master)

    assert result is None
    # warning записан с master id и причиной
    assert any(
        "master photo upload failed" in rec.message and "99" in rec.message
        for rec in caplog.records
    ), f"expected upload-failed warning for master=99, got: {[r.message for r in caplog.records]}"
    # cache пуст — следующий запрос попробует upload снова
    assert await sync_to_async(cache.get)(_cache_key(99)) is None
