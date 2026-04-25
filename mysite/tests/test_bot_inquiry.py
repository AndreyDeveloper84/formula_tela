"""T-02 RED: модель BotInquiry — вопросы которые AI-помощник не смог разрулить."""
import pytest
from model_bakery import baker


@pytest.mark.django_db
def test_bot_inquiry_creation():
    """Базовое создание BotInquiry с FK на BotUser."""
    bu = baker.make("services_app.BotUser", max_user_id=12001)
    inq = baker.make(
        "services_app.BotInquiry",
        bot_user=bu,
        chat_id=987654,
        question="Можно ли записаться на сегодня?",
    )
    assert inq.id is not None
    assert inq.bot_user == bu
    assert inq.chat_id == 987654
    assert inq.question == "Можно ли записаться на сегодня?"
    assert inq.asked_at is not None
    # По умолчанию ещё не отвечен
    assert inq.reply_text == ""
    assert inq.replied_at is None
    assert inq.replied_by is None
    assert inq.sent_to_max is False


@pytest.mark.django_db
def test_bot_inquiry_str_contains_question_preview():
    bu = baker.make("services_app.BotUser", max_user_id=12002)
    inq = baker.make(
        "services_app.BotInquiry",
        bot_user=bu,
        chat_id=1,
        question="Очень длинный вопрос про массаж и его пользу для здоровья " * 5,
    )
    s = str(inq)
    # __str__ должен быть коротким (не вся длинная question)
    assert len(s) < 200


@pytest.mark.django_db
def test_bot_inquiry_unanswered_queryset():
    """BotInquiry.objects.unanswered() — записи где reply_text пуст."""
    from services_app.models import BotInquiry
    bu = baker.make("services_app.BotUser", max_user_id=12003)
    unanswered = baker.make("services_app.BotInquiry", bot_user=bu, chat_id=1, question="Q1", reply_text="")
    answered = baker.make(
        "services_app.BotInquiry", bot_user=bu, chat_id=1,
        question="Q2", reply_text="Готовый ответ", sent_to_max=True,
    )
    ids = list(BotInquiry.objects.unanswered().values_list("id", flat=True))
    assert unanswered.id in ids
    assert answered.id not in ids


@pytest.mark.django_db
def test_bot_inquiry_protect_on_botuser_delete():
    """PROTECT — нельзя удалить BotUser у которого есть незакрытые inquiry'и."""
    from django.db.models.deletion import ProtectedError
    bu = baker.make("services_app.BotUser", max_user_id=12004)
    baker.make("services_app.BotInquiry", bot_user=bu, chat_id=1, question="X")
    with pytest.raises(ProtectedError):
        bu.delete()


@pytest.mark.django_db
def test_bot_inquiry_replied_by_set_null_on_user_delete():
    """SET_NULL — удаление автора-менеджера не каскадит, оставляет inquiry с replied_by=NULL."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    bu = baker.make("services_app.BotUser", max_user_id=12005)
    manager = baker.make(User)
    inq = baker.make(
        "services_app.BotInquiry",
        bot_user=bu, chat_id=1, question="X",
        reply_text="Ответ", replied_by=manager, sent_to_max=True,
    )
    manager.delete()
    inq.refresh_from_db()
    assert inq.replied_by is None
    assert inq.reply_text == "Ответ"  # ответ не теряется


@pytest.mark.django_db
def test_bot_inquiry_default_ordering_newest_first():
    """Ordering = -asked_at. На Windows/SQLite разница timestamps может быть 0мкс
    (одинаковые), поэтому проставляем asked_at явно через update."""
    from services_app.models import BotInquiry
    from django.utils import timezone
    from datetime import timedelta
    bu = baker.make("services_app.BotUser", max_user_id=12006)
    a = baker.make("services_app.BotInquiry", bot_user=bu, chat_id=1, question="A")
    b = baker.make("services_app.BotInquiry", bot_user=bu, chat_id=1, question="B")
    now = timezone.now()
    BotInquiry.objects.filter(id=a.id).update(asked_at=now - timedelta(minutes=5))
    BotInquiry.objects.filter(id=b.id).update(asked_at=now)
    ids = list(BotInquiry.objects.values_list("id", flat=True))
    assert ids.index(b.id) < ids.index(a.id)
