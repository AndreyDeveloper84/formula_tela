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