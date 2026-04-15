"""
Утилиты для website views (booking API).

normalize_ru_phone — единая точка очистки клиентского телефона до
формата E.164 (+7XXXXXXXXXX) перед записью в БД и отправкой в YClients.
Поднимает ValidationError на мусоре, чтобы спам-боты не засоряли
BookingRequest и YClients.
"""
import re

from django.core.exceptions import ValidationError

_DIGITS_RE = re.compile(r"\d+")


def normalize_ru_phone(raw: str) -> str:
    """
    Привести российский телефон к формату `+7XXXXXXXXXX`.

    Примеры валидных входов:
        '+7 (927) 123-45-67'  -> '+79271234567'
        '8 927 123 45 67'     -> '+79271234567'
        '79271234567'         -> '+79271234567'
        '9271234567'          -> '+79271234567'

    Поднимает ValidationError на пустой строке, не-цифровом мусоре и
    любой длине, кроме 10/11 цифр.
    """
    if not raw or not raw.strip():
        raise ValidationError("Телефон обязателен")

    digits = "".join(_DIGITS_RE.findall(raw))

    if len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    else:
        raise ValidationError(f"Неверный формат телефона: {raw!r}")

    return "+" + digits
