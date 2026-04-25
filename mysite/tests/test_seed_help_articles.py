"""Тесты management command seed_help_articles_from_service_faqs."""
import pytest
from io import StringIO

from django.core.management import call_command
from model_bakery import baker

pytestmark = pytest.mark.django_db


# ─── Helpers ────────────────────────────────────────────────────────────────

def _make_faq_block(service, content):
    return baker.make(
        "services_app.ServiceBlock",
        service=service,
        block_type="faq",
        content=content,
    )


def _run(*args):
    out = StringIO()
    call_command("seed_help_articles_from_service_faqs", *args, stdout=out)
    return out.getvalue()


# ─── Базовый импорт ─────────────────────────────────────────────────────────

def test_seed_creates_help_article_per_qa_pair():
    svc = baker.make("services_app.Service", name="Массаж спины", is_active=True)
    _make_faq_block(svc, content=(
        "Как записаться?\n"
        "Через бот или по телефону.\n"
        "---\n"
        "Болезненно ли?\n"
        "Нет, расслабляющий процесс.\n"
    ))
    _run()
    from services_app.models import HelpArticle
    assert HelpArticle.objects.count() == 2
    names = list(HelpArticle.objects.values_list("question", flat=True))
    assert "Как записаться?" in names
    assert "Болезненно ли?" in names


def test_seed_appends_source_marker_to_answer():
    svc = baker.make("services_app.Service", name="Тест-услуга", is_active=True)
    _make_faq_block(svc, content="Вопрос?\nОтвет.\n")
    _run()
    from services_app.models import HelpArticle
    h = HelpArticle.objects.get(question="Вопрос?")
    assert "Тест-услуга" in h.answer
    assert "Импортировано из FAQ услуги" in h.answer


def test_seed_skips_pairs_without_question_mark():
    """Эвристика: настоящий Q должен содержать '?'."""
    svc = baker.make("services_app.Service", name="X", is_active=True)
    _make_faq_block(svc, content=(
        "Разогрев (5 минут)\n"  # НЕ вопрос
        "Поглаживания и растирания\n"
        "---\n"
        "Это вопрос?\n"
        "Это ответ\n"
    ))
    _run()
    from services_app.models import HelpArticle
    assert HelpArticle.objects.count() == 1
    assert HelpArticle.objects.first().question == "Это вопрос?"


def test_seed_idempotent_on_repeat():
    """Повторный запуск НЕ плодит дубли (update_or_create по question)."""
    svc = baker.make("services_app.Service", name="X", is_active=True)
    _make_faq_block(svc, content="Длинный вопрос?\nA1\n")
    _run()
    _run()
    from services_app.models import HelpArticle
    assert HelpArticle.objects.count() == 1


def test_seed_updates_answer_when_changed():
    """Если контент блока поменяли — повторный seed обновит answer."""
    svc = baker.make("services_app.Service", name="X", is_active=True)
    block = _make_faq_block(svc, content="Q?\nOldAnswer\n")
    _run()
    block.content = "Длинный вопрос?\nNewAnswer\n"
    block.save()
    _run()
    from services_app.models import HelpArticle
    h = HelpArticle.objects.get(question="Длинный вопрос?")
    assert "NewAnswer" in h.answer
    assert "OldAnswer" not in h.answer


def test_seed_dry_run_creates_nothing():
    svc = baker.make("services_app.Service", name="X", is_active=True)
    _make_faq_block(svc, content="Длинный вопрос?\nA\n")
    out = _run("--dry-run")
    from services_app.models import HelpArticle
    assert HelpArticle.objects.count() == 0
    assert "[DRY]" in out


def test_seed_strips_html_from_answer():
    """faq_items добавляет <br> в multiline answer — должны вычистить."""
    svc = baker.make("services_app.Service", name="X", is_active=True)
    _make_faq_block(svc, content="Длинный вопрос?\nLine1\nLine2\n")
    _run()
    from services_app.models import HelpArticle
    h = HelpArticle.objects.get(question="Длинный вопрос?")
    assert "<br>" not in h.answer
    assert "Line1" in h.answer
    assert "Line2" in h.answer


def test_seed_truncates_long_question_at_question_mark():
    """Question >255 chars → обрезается по последнему '?' в пределах лимита."""
    svc = baker.make("services_app.Service", name="X", is_active=True)
    long_q = "A" * 250 + "? Дополнение." * 5  # >255 chars
    _make_faq_block(svc, content=f"{long_q}\nAnswer\n")
    _run()
    from services_app.models import HelpArticle
    h = HelpArticle.objects.first()
    assert h is not None
    assert len(h.question) <= 255
    assert h.question.endswith("?") or h.question.endswith("…")


def test_seed_purge_imported_only():
    """--purge-imported удаляет только импортированные, не трогает ручные."""
    svc = baker.make("services_app.Service", name="X", is_active=True)
    _make_faq_block(svc, content="Длинный вопрос?\nA\n")
    _run()  # создаст 1 импортированный
    # Создадим ручной (без маркера)
    from services_app.models import HelpArticle
    HelpArticle.objects.create(question="Manual?", answer="Ручной ответ без маркера")
    assert HelpArticle.objects.count() == 2

    _run("--purge-imported")

    remaining = list(HelpArticle.objects.values_list("question", flat=True))
    assert remaining == ["Manual?"]


def test_seed_limit_processes_only_n_blocks():
    for i in range(5):
        svc = baker.make("services_app.Service", name=f"S{i}", is_active=True)
        _make_faq_block(svc, content=f"Вопрос N {i}?\nA\n")
    _run("--limit", "2")
    from services_app.models import HelpArticle
    assert HelpArticle.objects.count() == 2
