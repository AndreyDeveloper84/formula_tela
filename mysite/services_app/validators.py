"""
Валидаторы загружаемых файлов (изображения, видео).

Используются на полях ImageField/FileField в моделях ServiceMedia,
GiftCertificate и т.п. Защищают от DoS (слишком большие файлы) и
от загрузки произвольного MIME через Django admin.

MIME берётся из `UploadedFile.content_type` — достаточно для admin
upload (где заголовок выставляет браузер/urllib). Для публичных
форм дополнительно стоит проверять magic bytes, но для админки и
текущих пользовательских форм этого уровня защиты хватает.
"""
from django.core.exceptions import ValidationError

MAX_IMAGE_SIZE = 5 * 1024 * 1024    # 5 МБ
MAX_VIDEO_SIZE = 50 * 1024 * 1024   # 50 МБ

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/webm"}


def _mb(size: int) -> int:
    return size // 1024 // 1024


def validate_image_upload(file):
    """ImageField validator: ≤5 МБ, JPEG/PNG/WebP."""
    if file.size is not None and file.size > MAX_IMAGE_SIZE:
        raise ValidationError(
            f"Файл слишком большой ({_mb(file.size)} МБ). "
            f"Максимум {_mb(MAX_IMAGE_SIZE)} МБ."
        )
    content_type = getattr(file, "content_type", None)
    if content_type and content_type not in ALLOWED_IMAGE_TYPES:
        raise ValidationError(
            f"Недопустимый тип файла: {content_type}. "
            f"Разрешены JPEG, PNG, WebP."
        )


def validate_video_upload(file):
    """FileField validator: ≤50 МБ, MP4/WebM."""
    if file.size is not None and file.size > MAX_VIDEO_SIZE:
        raise ValidationError(
            f"Файл слишком большой ({_mb(file.size)} МБ). "
            f"Максимум {_mb(MAX_VIDEO_SIZE)} МБ."
        )
    content_type = getattr(file, "content_type", None)
    if content_type and content_type not in ALLOWED_VIDEO_TYPES:
        raise ValidationError(
            f"Недопустимый тип файла: {content_type}. "
            f"Разрешены MP4, WebM."
        )
