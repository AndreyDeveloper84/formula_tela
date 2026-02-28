from django import template

register = template.Library()


@register.filter
def split_lines(value):
    """
    Разбивает строку на список по переносам строки.
    Убирает маркеры списков (bullet, -, *, цифры с точкой).

    Использование: {{ blocks.how_it_works|split_lines }}
    """
    if not value:
        return []
    import re
    lines = value.split("\n")
    cleaned = []
    for line in lines:
        line = line.strip()
        # Убираем маркеры списка: bullet, -, *, 1., 2.
        line = re.sub(r"^[\u2022\-\*]\s*", "", line)
        line = re.sub(r"^\d+\.\s*", "", line)
        if line:
            cleaned.append(line)
    return cleaned


@register.filter
def slugify_to_title(value):
    """
    Превращает slug в читаемый заголовок.
    'massazh-spiny' -> 'Massazh spiny' (убирает дефисы, capitalizes)

    Использование: {{ slug|slugify_to_title }}
    """
    if not value:
        return value
    return value.replace("-", " ").replace("_", " ").capitalize()
