from django import template

register = template.Library()

@register.simple_tag
def get_media_after(media_by_position, block_order):
    """
    Возвращает список медиа-элементов для вставки после блока с указанным order.
    Используется на мобильном для вставки фото/видео между текстовыми блоками.
    
    Пример: {% get_media_after media_by_position block.order as media_here %}
    """
    if not media_by_position or not block_order:
        return []
    return media_by_position.get(block_order, [])