"""Phase 2.4 T01 — тесты для Service.goals + tag_services_goals команды."""
from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from model_bakery import baker

from services_app.models import (
    SERVICE_GOAL_CHOICES,
    SERVICE_GOAL_VALUES,
    Service,
    ServiceCategory,
)


# ─── Model basics ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_service_goals_default_empty_list():
    s = baker.make(Service, is_active=True)
    assert s.goals == []
    assert s.has_goal("relax") is False


@pytest.mark.django_db
def test_service_has_goal_returns_true_for_present():
    s = baker.make(Service, is_active=True, goals=["relax", "antistress"])
    assert s.has_goal("relax") is True
    assert s.has_goal("antistress") is True
    assert s.has_goal("cellulite") is False


@pytest.mark.django_db
def test_service_goals_with_goal_helper():
    """ServiceQuerySet.with_goal — кросс-БД фильтр (Postgres + SQLite)."""
    baker.make(Service, name="Релакс", is_active=True, goals=["relax"])
    baker.make(Service, name="Спортивный", is_active=True, goals=["recovery", "tone"])
    baker.make(Service, name="Без тегов", is_active=True, goals=[])

    relax_qs = Service.objects.with_goal("relax")
    recovery_qs = Service.objects.with_goal("recovery")

    assert set(relax_qs.values_list("name", flat=True)) == {"Релакс"}
    assert set(recovery_qs.values_list("name", flat=True)) == {"Спортивный"}


@pytest.mark.django_db
def test_service_goals_with_any_goal():
    """with_any_goal — OR фильтр для нескольких тегов."""
    baker.make(Service, name="Релакс", is_active=True, goals=["relax"])
    baker.make(Service, name="Спорт", is_active=True, goals=["recovery"])
    baker.make(Service, name="Лимфодренаж", is_active=True, goals=["lymph"])

    qs = Service.objects.with_any_goal(["relax", "recovery"])
    names = set(qs.values_list("name", flat=True))
    assert names == {"Релакс", "Спорт"}


@pytest.mark.django_db
def test_with_goal_does_not_match_substring():
    """with_goal('relax') не должен матчить услугу с тегом 'relax_special'."""
    baker.make(Service, name="A", is_active=True, goals=["relax"])
    baker.make(Service, name="B", is_active=True, goals=["relax_special"])

    matched = list(Service.objects.with_goal("relax").values_list("name", flat=True))
    # Только точное совпадение
    assert matched == ["A"]


def test_service_goal_choices_values_match():
    """SERVICE_GOAL_VALUES содержит все ключи из SERVICE_GOAL_CHOICES."""
    for slug, _ in SERVICE_GOAL_CHOICES:
        assert slug in SERVICE_GOAL_VALUES


def test_service_goal_choices_no_duplicates():
    slugs = [slug for slug, _ in SERVICE_GOAL_CHOICES]
    assert len(slugs) == len(set(slugs))


# ─── tag_services_goals command ───────────────────────────────────────────


def _mock_openai_response(goals: list[str]):
    """Build a fake OpenAI ChatCompletion response with the given goals."""
    msg = MagicMock()
    msg.content = '{"goals": ' + str(goals).replace("'", '"') + '}'
    choice = MagicMock(message=msg)
    completion = MagicMock(choices=[choice])
    return completion


@pytest.mark.django_db
def test_tag_services_goals_writes_to_db():
    """Happy path: LLM возвращает теги → записываются в Service.goals."""
    s = baker.make(Service, name="Антистресс массаж", is_active=True, goals=[])

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_openai_response(
        ["relax", "antistress"]
    )
    out = StringIO()

    with patch("agents.agents.get_openai_client", return_value=fake_client):
        call_command("tag_services_goals", stdout=out)

    s.refresh_from_db()
    assert s.goals == ["relax", "antistress"]


@pytest.mark.django_db
def test_tag_services_goals_dry_run_does_not_save():
    s = baker.make(Service, name="Spa", is_active=True, goals=[])

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_openai_response(["relax"])
    out = StringIO()

    with patch("agents.agents.get_openai_client", return_value=fake_client):
        call_command("tag_services_goals", "--dry-run", stdout=out)

    s.refresh_from_db()
    assert s.goals == []
    assert "DRY-RUN" in out.getvalue()


@pytest.mark.django_db
def test_tag_services_goals_skips_already_tagged_without_force():
    """По умолчанию untagged only — услуги с goals не трогаем."""
    tagged = baker.make(Service, name="Уже тегирована", is_active=True, goals=["relax"])
    untagged = baker.make(Service, name="Без тегов", is_active=True, goals=[])

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_openai_response(
        ["antistress"]
    )

    with patch("agents.agents.get_openai_client", return_value=fake_client):
        call_command("tag_services_goals", stdout=StringIO())

    tagged.refresh_from_db()
    untagged.refresh_from_db()
    assert tagged.goals == ["relax"]  # не тронули
    assert untagged.goals == ["antistress"]


@pytest.mark.django_db
def test_tag_services_goals_force_retags_existing():
    s = baker.make(Service, name="Тест", is_active=True, goals=["old_tag"])

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_openai_response(
        ["relax", "tone"]
    )

    with patch("agents.agents.get_openai_client", return_value=fake_client):
        call_command("tag_services_goals", "--force", stdout=StringIO())

    s.refresh_from_db()
    assert s.goals == ["relax", "tone"]


@pytest.mark.django_db
def test_tag_services_goals_filters_invalid_tags():
    """LLM выдумал свой тег — отфильтровываем."""
    s = baker.make(Service, name="Тест", is_active=True, goals=[])

    fake_client = MagicMock()
    # 'super_relax' не в словаре → должен быть отфильтрован
    fake_client.chat.completions.create.return_value = _mock_openai_response(
        ["relax", "super_relax", "antistress"]
    )

    with patch("agents.agents.get_openai_client", return_value=fake_client):
        call_command("tag_services_goals", stdout=StringIO())

    s.refresh_from_db()
    assert s.goals == ["relax", "antistress"]


@pytest.mark.django_db
def test_tag_services_goals_handles_invalid_json():
    """LLM вернул не-JSON — пропускаем без падения."""
    s = baker.make(Service, name="Тест", is_active=True, goals=[])

    fake_client = MagicMock()
    msg = MagicMock(content="not a json")
    fake_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=msg)]
    )

    with patch("agents.agents.get_openai_client", return_value=fake_client):
        call_command("tag_services_goals", stdout=StringIO())

    s.refresh_from_db()
    assert s.goals == []


@pytest.mark.django_db
def test_tag_services_goals_single_service_id():
    s1 = baker.make(Service, is_active=True, goals=[])
    s2 = baker.make(Service, is_active=True, goals=[])

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = _mock_openai_response(["relax"])

    with patch("agents.agents.get_openai_client", return_value=fake_client):
        call_command(
            "tag_services_goals", f"--service-id={s1.id}", stdout=StringIO(),
        )

    s1.refresh_from_db()
    s2.refresh_from_db()
    assert s1.goals == ["relax"]
    assert s2.goals == []
