"""
T-02 RED tests: модели MAX-бота — BotUser, HelpArticle + расширение BookingRequest.

Сначала пишем тесты, ожидая что они FAIL (модели/поля не существуют).
Потом добавляем модели → тесты проходят.
"""
import pytest
from model_bakery import baker


# ─── BotUser ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_bot_user_creation():
    """BotUser создаётся через baker и сохраняется в БД."""
    from services_app.models import BotUser
    bu = baker.make("services_app.BotUser", max_user_id=254116108, display_name="Иван")
    assert bu.id is not None
    assert bu.max_user_id == 254116108
    assert bu.display_name == "Иван"


@pytest.mark.django_db
def test_bot_user_context_defaults_to_empty_dict():
    """JSONField context при создании без параметра == {}."""
    bu = baker.make("services_app.BotUser", max_user_id=1, _fill_optional=False)
    assert bu.context == {}


@pytest.mark.django_db
def test_bot_user_max_user_id_unique():
    """max_user_id имеет unique constraint."""
    from django.db import IntegrityError
    baker.make("services_app.BotUser", max_user_id=42)
    with pytest.raises(IntegrityError):
        baker.make("services_app.BotUser", max_user_id=42)


@pytest.mark.django_db
def test_bot_user_str():
    bu = baker.make("services_app.BotUser", max_user_id=42, client_name="Анна")
    assert "Анна" in str(bu) or "42" in str(bu)


# ─── HelpArticle ────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_help_article_ordering():
    """Статьи возвращаются в порядке поля order, потом id."""
    a2 = baker.make("services_app.HelpArticle", question="Q2", answer="A2", order=2, is_active=True)
    a1 = baker.make("services_app.HelpArticle", question="Q1", answer="A1", order=1, is_active=True)
    from services_app.models import HelpArticle
    ids = list(HelpArticle.objects.values_list("id", flat=True))
    assert ids.index(a1.id) < ids.index(a2.id)


@pytest.mark.django_db
def test_help_article_active_default():
    """is_active=True по умолчанию (можно создать без явного параметра)."""
    a = baker.make("services_app.HelpArticle", question="Q", answer="A", _fill_optional=False)
    assert a.is_active is True


# ─── BookingRequest расширения ──────────────────────────────────────────────

@pytest.mark.django_db
def test_booking_request_source_default():
    """Существующие записи (без явного source) дефолтятся на 'wizard' — обратная совместимость."""
    br = baker.make(
        "services_app.BookingRequest",
        service_name="Массаж",
        client_name="Тест",
        client_phone="+79001234567",
        _fill_optional=False,
    )
    assert br.source == "wizard"


@pytest.mark.django_db
def test_booking_request_with_bot_user_fk():
    """BookingRequest можно связать с BotUser через FK."""
    bu = baker.make("services_app.BotUser", max_user_id=99)
    br = baker.make(
        "services_app.BookingRequest",
        service_name="Массаж",
        client_name="Тест",
        client_phone="+79001234567",
        source="bot_max",
        bot_user=bu,
    )
    assert br.bot_user == bu
    assert br.source == "bot_max"


@pytest.mark.django_db
def test_booking_request_bot_user_set_null_on_botuser_delete():
    """Удаление BotUser не каскадит — ставит bot_user=NULL (история заявок не теряется)."""
    bu = baker.make("services_app.BotUser", max_user_id=100)
    br = baker.make(
        "services_app.BookingRequest",
        service_name="Массаж",
        client_name="Тест",
        client_phone="+79001234567",
        source="bot_max",
        bot_user=bu,
    )
    bu.delete()
    br.refresh_from_db()
    assert br.bot_user is None
    assert br.source == "bot_max"  # source остаётся
