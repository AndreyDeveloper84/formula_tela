"""Тесты для agents.agents._revenue — извлечение выручки из YClients записей."""
from agents.agents._revenue import extract_record_revenue, sum_records_revenue


def test_extract_from_services_cost():
    record = {"services": [{"title": "Массаж", "cost": 3500, "first_cost": 3500}]}
    assert extract_record_revenue(record) == 3500.0


def test_extract_multiple_services():
    record = {
        "services": [
            {"title": "Ноги", "cost": 2000},
            {"title": "Бикини", "cost": 2500},
        ],
    }
    assert extract_record_revenue(record) == 4500.0


def test_extract_fallback_to_first_cost():
    """cost=None → fallback на first_cost."""
    record = {"services": [{"title": "Массаж", "cost": None, "first_cost": 4000}]}
    assert extract_record_revenue(record) == 4000.0


def test_extract_handles_none_cost():
    """cost и first_cost оба None → 0."""
    record = {"services": [{"title": "Массаж", "cost": None, "first_cost": None}]}
    assert extract_record_revenue(record) == 0.0


def test_extract_empty_services():
    record = {"services": []}
    assert extract_record_revenue(record) == 0.0


def test_extract_no_services_key():
    record = {}
    assert extract_record_revenue(record) == 0.0


def test_sum_records_revenue():
    records = [
        {"services": [{"cost": 3000}]},
        {"services": [{"cost": 2000}, {"cost": 1500}]},
        {"services": []},
    ]
    assert sum_records_revenue(records) == 6500.0


def test_sum_empty_list():
    assert sum_records_revenue([]) == 0.0
