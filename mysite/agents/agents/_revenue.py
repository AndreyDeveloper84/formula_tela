"""
Извлечение выручки из записи YClients.

YClients API /records/{company_id} НЕ заполняет поле ``sum`` на корневом
уровне записи (оно отсутствует / None). Фактическая выручка хранится
в ``services[i].cost`` — цена услуги после скидки (то что клиент
заплатил). ``services[i].first_cost`` — цена до скидки.

Подтверждено на продакшн-данных (debug_yclients_records, 2026-04-17).
"""
import logging

logger = logging.getLogger(__name__)


def extract_record_revenue(record: dict) -> float:
    """Выручка одной записи = сумма ``services[i].cost``."""
    total = 0.0
    for svc in record.get("services") or []:
        cost = svc.get("cost")
        if cost is None:
            cost = svc.get("first_cost") or 0
        total += float(cost)
    return total


def sum_records_revenue(records: list[dict]) -> float:
    """Суммирует выручку по списку записей YClients."""
    return sum(extract_record_revenue(r) for r in records)
