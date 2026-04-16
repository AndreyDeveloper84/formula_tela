"""Тесты для retention dashboard — модель + Celery задача."""
import datetime
from unittest.mock import MagicMock, patch

import pytest

from agents.models import RetentionSnapshot


def _make_record(client_id, phone, date, services_cost, service_name="Массаж"):
    """Helper: создаёт мок-запись YClients."""
    return {
        "date": f"{date} 10:00:00",
        "client": {"id": client_id, "phone": phone, "name": f"Client {client_id}"},
        "services": [{"title": service_name, "cost": services_cost, "amount": 1}],
        "staff": {"id": 1, "name": "Ольга"},
        "paid_full": 1,
    }


@pytest.mark.django_db
def test_retention_snapshot_model():
    s = RetentionSnapshot.objects.create(
        date=datetime.date(2026, 4, 15),
        total_clients=50,
        new_clients=20,
        returning_clients=30,
        retention_30d=45.0,
        churn_rate=15.0,
    )
    assert s.pk is not None
    assert "50 клиентов" in str(s)
    assert "R30=45%" in str(s)


@pytest.mark.django_db
def test_retention_snapshot_unique_date():
    RetentionSnapshot.objects.create(date=datetime.date(2026, 4, 15))
    with pytest.raises(Exception):
        RetentionSnapshot.objects.create(date=datetime.date(2026, 4, 15))


@pytest.mark.django_db
@patch("agents.telegram.send_retention_summary", return_value=True)
@patch("agents.telegram.send_retention_report", return_value=True)
@patch("services_app.yclients_api.get_yclients_api")
def test_collect_retention_basic(mock_api_factory, mock_report, mock_summary):
    """Task создаёт RetentionSnapshot с правильными метриками."""
    today = datetime.date.today()
    api = MagicMock()
    mock_api_factory.return_value = api
    api.get_records.return_value = [
        # Клиент 1: 3 визита (returning)
        _make_record(101, "79001111111", str(today - datetime.timedelta(days=60)), 3000),
        _make_record(101, "79001111111", str(today - datetime.timedelta(days=30)), 3500),
        _make_record(101, "79001111111", str(today - datetime.timedelta(days=5)), 4000),
        # Клиент 2: 1 визит давно (churned)
        _make_record(102, "79002222222", str(today - datetime.timedelta(days=120)), 2000, "Депиляция"),
        # Клиент 3: 1 визит недавно (new, not churned)
        _make_record(103, "79003333333", str(today - datetime.timedelta(days=10)), 2500),
    ]

    from agents.tasks import collect_retention_metrics
    collect_retention_metrics()

    snap = RetentionSnapshot.objects.get(date=today)
    assert snap.total_clients == 3
    assert snap.new_clients == 2  # clients 102 and 103 have 1 visit
    assert snap.returning_clients == 1  # client 101
    assert snap.churn_count == 1  # client 102 (last visit 120 days ago)
    assert snap.churn_rate > 0
    assert snap.avg_check > 0
    assert snap.avg_ltv_180d > 0
    assert snap.avg_frequency > 0

    # Retention: client 101 had 2nd visit 30 days after 1st (60d - 30d = 30d gap)
    assert snap.retention_30d > 0

    # Top churned services
    assert len(snap.top_churned_services) >= 1
    assert snap.top_churned_services[0]["service"] == "Депиляция"


@pytest.mark.django_db
@patch("agents.telegram.send_retention_summary", return_value=True)
@patch("agents.telegram.send_retention_report", return_value=True)
@patch("services_app.yclients_api.get_yclients_api")
def test_collect_retention_empty_records(mock_api_factory, mock_report, mock_summary):
    """При 0 записей snapshot не создаётся."""
    api = MagicMock()
    mock_api_factory.return_value = api
    api.get_records.return_value = []

    from agents.tasks import collect_retention_metrics
    collect_retention_metrics()

    assert RetentionSnapshot.objects.count() == 0


@pytest.mark.django_db
@patch("agents.telegram.send_retention_summary", return_value=True)
@patch("agents.telegram.send_retention_report", return_value=True)
@patch("services_app.yclients_api.get_yclients_api")
def test_collect_retention_all_returning(mock_api_factory, mock_report, mock_summary):
    """Все клиенты повторные."""
    today = datetime.date.today()
    api = MagicMock()
    mock_api_factory.return_value = api
    api.get_records.return_value = [
        _make_record(201, "79011111111", str(today - datetime.timedelta(days=50)), 3000),
        _make_record(201, "79011111111", str(today - datetime.timedelta(days=20)), 3500),
        _make_record(202, "79022222222", str(today - datetime.timedelta(days=40)), 2000),
        _make_record(202, "79022222222", str(today - datetime.timedelta(days=10)), 2500),
    ]

    from agents.tasks import collect_retention_metrics
    collect_retention_metrics()

    snap = RetentionSnapshot.objects.get(date=today)
    assert snap.total_clients == 2
    assert snap.new_clients == 0
    assert snap.returning_clients == 2
    assert snap.retention_30d > 0
    assert snap.churn_count == 0


def test_send_retention_summary_no_changes():
    """Если нет значимых изменений — не отправляем."""
    from agents.telegram import send_retention_summary

    current = MagicMock()
    current.retention_30d = 40.0
    current.churn_rate = 15.0
    current.total_clients = 50
    current.new_clients = 20
    current.returning_clients = 30
    current.avg_check = 3000
    current.avg_frequency = 1.5
    current.churn_count = 5
    current.date = datetime.date(2026, 4, 15)

    previous = MagicMock()
    previous.retention_30d = 41.0  # small drop, < 10%
    previous.churn_rate = 14.0  # small increase, < 10%

    result = send_retention_summary(current, previous)
    assert result is True  # silenced — no telegram sent


@patch("agents.telegram.send_telegram", return_value=True)
def test_send_retention_summary_alert_on_drop(mock_tg):
    """При падении retention >10% — отправляем алерт."""
    from agents.telegram import send_retention_summary

    current = MagicMock()
    current.retention_30d = 25.0
    current.churn_rate = 30.0
    current.total_clients = 50
    current.new_clients = 20
    current.returning_clients = 30
    current.avg_check = 3000
    current.avg_frequency = 1.5
    current.churn_count = 15
    current.date = datetime.date(2026, 4, 15)

    previous = MagicMock()
    previous.retention_30d = 40.0  # drop 15% — should alert
    previous.churn_rate = 15.0

    result = send_retention_summary(current, previous)
    assert result is True
    mock_tg.assert_called_once()
    msg = mock_tg.call_args[0][0]
    assert "Удержание упало" in msg
