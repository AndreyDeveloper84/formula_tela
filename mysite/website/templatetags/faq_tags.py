from django import template

register = template.Library()


@register.simple_tag
def faq_items(content):
    """
    Парсит FAQ-контент из поля content.
    
    Формат в админке:
        Сколько стоит классический массаж?
        Стоимость зависит от длительности: 30 минут — 1 500 ₽, 60 минут — 2 000 ₽.
        ---
        Больно ли делать массаж?
        Классический массаж — это расслабляющая техника. Без боли.
        ---
        Как подготовиться к массажу?
        Никакой специальной подготовки не нужно.
    
    Возвращает список словарей: [{"question": "...", "answer": "..."}, ...]
    """
    if not content:
        return []

    # Разделяем блоки по ---
    raw_blocks = content.split('---')
    items = []

    for raw in raw_blocks:
        lines = raw.strip().splitlines()
        if not lines:
            continue

        # Первая непустая строка = вопрос, остальное = ответ
        question = lines[0].strip()
        answer_lines = [ln for ln in lines[1:] if ln.strip()]
        answer = '<br>'.join(ln.strip() for ln in answer_lines) if answer_lines else ''

        if question:
            items.append({
                'question': question,
                'answer': answer,
            })

    return items