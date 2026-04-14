"""
Тесты website.utils.normalize_ru_phone.
Покрываем популярные форматы ввода, мусор и пустые значения.
"""
import pytest
from django.core.exceptions import ValidationError

from website.utils import normalize_ru_phone


@pytest.mark.parametrize("raw", [
    "+79271234567",
    "79271234567",
    "89271234567",
    "8 (927) 123-45-67",
    "+7 927 123 45 67",
    "+7 (927) 123-45-67",
    " 8-927-123-45-67 ",
    "9271234567",  # без кода страны
])
def test_normalize_valid_variants(raw):
    assert normalize_ru_phone(raw) == "+79271234567"


@pytest.mark.parametrize("raw", [
    "",
    "   ",
    "abc",
    "1234",                 # слишком мало цифр
    "+1 212 555 0100",      # не RU, 11 цифр но первая не 7/8
    "+7 927 123 45",        # мало цифр
    "+7 927 123 45 67 89",  # лишние цифры
])
def test_normalize_invalid_raises(raw):
    with pytest.raises(ValidationError):
        normalize_ru_phone(raw)
