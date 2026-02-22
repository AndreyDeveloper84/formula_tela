"""
Юнит-тесты YClientsAPI. Реальных HTTP-запросов нет.
"""
import pytest
import requests as real_requests
from unittest.mock import patch, MagicMock

from services_app.yclients_api import YClientsAPI, YClientsAPIError, get_yclients_api

PARTNER = "test-partner"
USER    = "test-user"
COMPANY = "884045"


def _make_api():
    return YClientsAPI(partner_token=PARTNER, user_token=USER, company_id=COMPANY)


def _mock_response(json_data, status_code=200):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data
    mock_resp.text = str(json_data)
    mock_resp.elapsed.total_seconds.return_value = 0.1
    return mock_resp


# ─── _request ────────────────────────────────────────────────────────────────

def test_request_success():
    """Успешный запрос возвращает полный JSON-словарь."""
    api = _make_api()
    payload = {"success": True, "data": [{"id": 1}]}
    with patch("requests.request", return_value=_mock_response(payload)) as mock_req:
        result = api._request("GET", "/test")
    assert result == payload
    mock_req.assert_called_once()


def test_request_http_400_raises():
    """HTTP 4xx → YClientsAPIError."""
    api = _make_api()
    with patch("requests.request", return_value=_mock_response({}, status_code=400)):
        with pytest.raises(YClientsAPIError, match="HTTP 400"):
            api._request("GET", "/test")


def test_request_timeout_raises():
    """Timeout → YClientsAPIError с 'timeout'."""
    api = _make_api()
    with patch("requests.request", side_effect=real_requests.exceptions.Timeout):
        with pytest.raises(YClientsAPIError, match="timeout"):
            api._request("GET", "/test")


def test_request_connection_error_raises():
    """ConnectionError → YClientsAPIError."""
    api = _make_api()
    with patch("requests.request", side_effect=real_requests.exceptions.ConnectionError):
        with pytest.raises(YClientsAPIError, match="connection error"):
            api._request("GET", "/test")


# ─── get_staff ───────────────────────────────────────────────────────────────

def test_get_staff_filters_hidden_and_fired():
    """hidden=1 и fired=1 отсекаются, активный остаётся."""
    api = _make_api()
    raw = {
        "success": True,
        "data": [
            {"id": 1, "name": "Анна",  "active": True,  "hidden": 0, "fired": 0},
            {"id": 2, "name": "Иван",  "active": True,  "hidden": 1, "fired": 0},
            {"id": 3, "name": "Ольга", "active": True,  "hidden": 0, "fired": 1},
        ],
    }
    with patch.object(api, "_request", return_value=raw):
        result = api.get_staff()
    assert len(result) == 1
    assert result[0]["id"] == 1


def test_get_staff_filters_inactive():
    """active=False → не включается."""
    api = _make_api()
    raw = {
        "success": True,
        "data": [
            {"id": 1, "name": "Активный",   "active": True,  "hidden": 0, "fired": 0},
            {"id": 2, "name": "Неактивный", "active": False, "hidden": 0, "fired": 0},
        ],
    }
    with patch.object(api, "_request", return_value=raw):
        result = api.get_staff()
    assert len(result) == 1
    assert result[0]["id"] == 1


def test_get_staff_returns_empty_on_error():
    """Ошибка API → пустой список, исключение не поднимается."""
    api = _make_api()
    with patch.object(api, "_request", side_effect=YClientsAPIError("ошибка")):
        result = api.get_staff()
    assert result == []


# ─── get_services ────────────────────────────────────────────────────────────

def test_get_services_parses_data():
    api = _make_api()
    raw = {"success": True, "data": [{"id": 10, "title": "Массаж"}, {"id": 11, "title": "Педикюр"}]}
    with patch.object(api, "_request", return_value=raw):
        result = api.get_services()
    assert len(result) == 2
    assert result[0]["id"] == 10


def test_get_services_returns_empty_on_success_false():
    api = _make_api()
    raw = {"success": False, "meta": {"message": "Не найдено"}}
    with patch.object(api, "_request", return_value=raw):
        result = api.get_services()
    assert result == []


# ─── get_book_dates ──────────────────────────────────────────────────────────

def test_get_book_dates_parses_nested():
    """Стандартный формат: data.booking_dates."""
    api = _make_api()
    raw = {
        "success": True,
        "data": {"booking_dates": ["2026-03-01", "2026-03-02", "2026-03-05"]},
    }
    with patch.object(api, "_request", return_value=raw):
        dates = api.get_book_dates(staff_id=1)
    assert dates == ["2026-03-01", "2026-03-02", "2026-03-05"]


def test_get_book_dates_fallback_to_working_dates():
    """Запасной вариант: data.working_dates."""
    api = _make_api()
    raw = {"success": True, "data": {"working_dates": ["2026-04-01"]}}
    with patch.object(api, "_request", return_value=raw):
        dates = api.get_book_dates(staff_id=1)
    assert "2026-04-01" in dates


def test_get_book_dates_sorted():
    """Даты возвращаются в отсортированном порядке."""
    api = _make_api()
    raw = {
        "success": True,
        "data": {"booking_dates": ["2026-03-10", "2026-03-01", "2026-03-05"]},
    }
    with patch.object(api, "_request", return_value=raw):
        dates = api.get_book_dates(staff_id=1)
    assert dates == sorted(dates)


def test_get_book_dates_returns_empty_on_error():
    api = _make_api()
    with patch.object(api, "_request", side_effect=YClientsAPIError("ошибка")):
        assert api.get_book_dates(staff_id=1) == []


# ─── get_available_times ─────────────────────────────────────────────────────

def test_get_available_times_dict_format():
    """Ответ — список словарей с 'time'."""
    api = _make_api()
    raw = {
        "success": True,
        "data": [
            {"time": "10:00", "seance_length": 3600},
            {"time": "11:00", "seance_length": 3600},
        ],
    }
    with patch.object(api, "_request", return_value=raw):
        times = api.get_available_times(staff_id=1, date="2026-03-01")
    assert times == ["10:00", "11:00"]


def test_get_available_times_string_format():
    """Ответ — список строк (старый формат API)."""
    api = _make_api()
    raw = {"success": True, "data": ["09:00", "13:00", "15:30"]}
    with patch.object(api, "_request", return_value=raw):
        times = api.get_available_times(staff_id=1, date="2026-03-01")
    assert times == ["09:00", "13:00", "15:30"]


def test_get_available_times_datetime_format():
    """Ответ — список словарей с ISO datetime."""
    api = _make_api()
    raw = {"success": True, "data": [{"datetime": "2026-03-01T14:30:00"}]}
    with patch.object(api, "_request", return_value=raw):
        times = api.get_available_times(staff_id=1, date="2026-03-01")
    assert "14:30" in times


def test_get_available_times_success_false_returns_empty():
    api = _make_api()
    raw = {"success": False, "data": []}
    with patch.object(api, "_request", return_value=raw):
        assert api.get_available_times(staff_id=1, date="2026-03-01") == []


def test_get_available_times_error_returns_empty():
    api = _make_api()
    with patch.object(api, "_request", side_effect=YClientsAPIError("ошибка")):
        assert api.get_available_times(staff_id=1, date="2026-03-01") == []


# ─── get_records ─────────────────────────────────────────────────────────────

def test_get_records_returns_data_list():
    api = _make_api()
    raw = {"success": True, "data": [{"id": 100}, {"id": 101}]}
    with patch.object(api, "_request", return_value=raw):
        records = api.get_records("2026-03-01", "2026-03-31")
    assert len(records) == 2
    assert records[0]["id"] == 100


def test_get_records_error_returns_empty():
    api = _make_api()
    with patch.object(api, "_request", side_effect=YClientsAPIError("ошибка")):
        assert api.get_records("2026-03-01", "2026-03-31") == []


# ─── authenticate ────────────────────────────────────────────────────────────

def test_authenticate_success_returns_user_token():
    raw = {"success": True, "data": {"user_token": "abc123"}}
    with patch("requests.post", return_value=_mock_response(raw)):
        token = YClientsAPI.authenticate("79001234567", "password", "partner-token")
    assert token == "abc123"


def test_authenticate_success_false_raises():
    """API вернул success=False → YClientsAPIError."""
    raw = {"success": False, "meta": {"message": "Неверный пароль"}}
    mock_resp = _mock_response(raw)
    mock_resp.raise_for_status = MagicMock()
    with patch("requests.post", return_value=mock_resp):
        with pytest.raises(YClientsAPIError, match="Authentication failed"):
            YClientsAPI.authenticate("79001234567", "wrong", "token")


def test_authenticate_http_error_raises():
    with patch("requests.post", side_effect=real_requests.exceptions.HTTPError("403 Forbidden")):
        with pytest.raises(YClientsAPIError):
            YClientsAPI.authenticate("79001234567", "pass", "token")


# ─── get_yclients_api ────────────────────────────────────────────────────────

def test_get_yclients_api_missing_settings_raises():
    """Пустые токены → YClientsAPIError."""
    from django.test import override_settings
    with override_settings(
        YCLIENTS_PARTNER_TOKEN="",
        YCLIENTS_USER_TOKEN="",
        YCLIENTS_COMPANY_ID="",
    ):
        with pytest.raises(YClientsAPIError, match="Missing YClients settings"):
            get_yclients_api()


def test_get_yclients_api_returns_instance():
    """При наличии всех токенов — возвращает YClientsAPI."""
    from django.test import override_settings
    with override_settings(
        YCLIENTS_PARTNER_TOKEN="p-token",
        YCLIENTS_USER_TOKEN="u-token",
        YCLIENTS_COMPANY_ID="12345",
    ):
        api = get_yclients_api()
    assert isinstance(api, YClientsAPI)
    assert api.company_id == "12345"
