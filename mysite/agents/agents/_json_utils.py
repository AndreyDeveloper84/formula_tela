"""
Утилита для безопасной подготовки данных перед записью в `JSONField`.

Зачем: ORM-результаты содержат `Decimal` (цены), `datetime.date`, иногда
кортежи. На разных комбинациях Django/psycopg путь сериализации JSONField
может миновать `DjangoJSONEncoder` и упасть с
`Object of type Decimal is not JSON serializable`.

Санитизация на стороне приложения убирает эту зависимость.
"""
import datetime
from decimal import Decimal


def to_jsonable(value):
    """Рекурсивно превращает значение в JSON-совместимое.

    - `Decimal` → `float`
    - `date` / `datetime` → ISO-строка
    - `tuple` / `set` → `list`
    - `dict` — рекурсия по значениям (ключи приводятся к str)
    - остальное — как есть
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    return str(value)
