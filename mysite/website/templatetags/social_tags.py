# Файл: website/templatetags/social_tags.py

from django import template

register = template.Library()


@register.filter
def dictget(d, key):
    """Безопасное получение значения из словаря по ключу.
    Использование: {{ mydict|dictget:"key_name" }}
    """
    if isinstance(d, dict):
        return d.get(key, "")
    return ""


@register.filter
def pluralize_ru(value, variants):
    """Русское склонение: {{ count|pluralize_ru:"услуга,услуги,услуг" }}
    """
    try:
        value = int(value)
    except (ValueError, TypeError):
        return ""
    parts = variants.split(",")
    if len(parts) != 3:
        return parts[0] if parts else ""
    n = abs(value) % 100
    if 11 <= n <= 19:
        return parts[2]
    n = n % 10
    if n == 1:
        return parts[0]
    if 2 <= n <= 4:
        return parts[1]
    return parts[2]