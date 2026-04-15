"""
Тесты валидаторов загрузки файлов (services_app/validators.py).
Покрываем: превышение размера, запрещённый MIME, валидные файлы.
"""
import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from services_app.validators import (
    MAX_IMAGE_SIZE,
    MAX_VIDEO_SIZE,
    validate_image_upload,
    validate_video_upload,
)


def _fake_upload(size_bytes: int, content_type: str, name: str = "file") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"x" * size_bytes, content_type=content_type)


# ---------- изображения ----------

def test_valid_image_passes():
    validate_image_upload(_fake_upload(100 * 1024, "image/jpeg", "ok.jpg"))
    validate_image_upload(_fake_upload(100 * 1024, "image/png", "ok.png"))
    validate_image_upload(_fake_upload(100 * 1024, "image/webp", "ok.webp"))


def test_oversize_image_rejected():
    big = _fake_upload(MAX_IMAGE_SIZE + 1, "image/jpeg", "big.jpg")
    with pytest.raises(ValidationError, match="слишком большой"):
        validate_image_upload(big)


def test_wrong_mime_image_rejected():
    exe = _fake_upload(1024, "application/x-msdownload", "virus.exe")
    with pytest.raises(ValidationError, match="Недопустимый тип файла"):
        validate_image_upload(exe)


def test_html_as_image_rejected():
    html = _fake_upload(1024, "text/html", "page.html")
    with pytest.raises(ValidationError):
        validate_image_upload(html)


# ---------- видео ----------

def test_valid_video_passes():
    validate_video_upload(_fake_upload(1024 * 1024, "video/mp4", "ok.mp4"))
    validate_video_upload(_fake_upload(1024 * 1024, "video/webm", "ok.webm"))


def test_oversize_video_rejected():
    big = _fake_upload(MAX_VIDEO_SIZE + 1, "video/mp4", "big.mp4")
    with pytest.raises(ValidationError, match="слишком большой"):
        validate_video_upload(big)


def test_wrong_mime_video_rejected():
    bogus = _fake_upload(1024, "application/octet-stream", "f.bin")
    with pytest.raises(ValidationError, match="Недопустимый тип файла"):
        validate_video_upload(bogus)


def test_missing_content_type_skipped():
    """Если браузер не прислал content_type — не валим, размер всё равно проверен."""
    no_ct = SimpleUploadedFile("ok.jpg", b"x" * 1024, content_type=None)
    validate_image_upload(no_ct)  # не должен бросить
