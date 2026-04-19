"""Тесты SEOLandingQCAgent — Strategy checks + Pipeline orchestrator.

Unit-тесты на каждый QC check + integration тесты на агента.
"""
import json

import pytest
from model_bakery import baker

from agents.agents.qc_checks import (
    ContentDuplicateCheck,
    InternalLinksCheck,
    PublishedAtReadyCheck,
    RequiredBlocksCheck,
    UniqueH1Check,
    UniqueSlugCheck,
)
from agents.agents.seo_landing_qc import SEOLandingQCAgent
from agents.models import AgentTask, LandingPage, SeoTask


def _make_landing(**kwargs):
    """Helper: создать LandingPage с дефолтами для тестов."""
    defaults = {
        "slug": "test-landing",
        "h1": "Уникальный H1 для теста",
        "meta_title": "Test Title",
        "meta_description": "Test description",
        "status": LandingPage.STATUS_DRAFT,
        "blocks": {
            "intro": "Тестовый текст",
            "cta_text": "Записаться",
            "faq": [{"q": "Вопрос?", "a": "Ответ"}],
            "internal_links": ["/uslugi/massazh-spiny/", "/uslugi/klassicheskii-massazh/"],
        },
    }
    defaults.update(kwargs)
    return baker.make("agents.LandingPage", **defaults)


# ── UniqueH1Check ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_unique_h1_passes_when_no_dupes():
    lp = _make_landing(h1="Совершенно уникальный заголовок")
    result = UniqueH1Check().run(lp)
    assert result.passed


@pytest.mark.django_db
def test_unique_h1_fails_on_duplicate_published():
    _make_landing(slug="first", h1="Дубль H1", status=LandingPage.STATUS_PUBLISHED)
    lp2 = _make_landing(slug="second", h1="Дубль H1", status=LandingPage.STATUS_DRAFT)
    result = UniqueH1Check().run(lp2)
    assert not result.passed
    assert result.severity == "critical"
    assert "first" in result.message


@pytest.mark.django_db
def test_unique_h1_fails_when_service_has_same_name():
    baker.make("services_app.Service", name="Массаж спины", is_active=True)
    lp = _make_landing(h1="Массаж спины")
    result = UniqueH1Check().run(lp)
    assert not result.passed


# ── UniqueSlugCheck ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_unique_slug_passes_when_no_conflicts():
    lp = _make_landing(slug="unique-landing-slug")
    result = UniqueSlugCheck().run(lp)
    assert result.passed


@pytest.mark.django_db
def test_unique_slug_fails_when_service_has_same_slug():
    baker.make("services_app.Service", slug="massazh-spiny", is_active=True)
    lp = _make_landing(slug="massazh-spiny")
    result = UniqueSlugCheck().run(lp)
    assert not result.passed
    assert "Service" in result.message


# ── PublishedAtReadyCheck ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_published_at_ready_passes():
    lp = _make_landing(meta_title="Title", h1="H1")
    result = PublishedAtReadyCheck().run(lp)
    assert result.passed


@pytest.mark.django_db
def test_published_at_ready_fails_empty_meta_title():
    lp = _make_landing(meta_title="", h1="H1")
    result = PublishedAtReadyCheck().run(lp)
    assert not result.passed
    assert "meta_title" in result.message


# ── RequiredBlocksCheck ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_required_blocks_passes():
    lp = _make_landing(blocks={"intro": "text", "cta_text": "Записаться"})
    result = RequiredBlocksCheck().run(lp)
    assert result.passed


@pytest.mark.django_db
def test_required_blocks_fails_missing_intro():
    lp = _make_landing(blocks={"cta_text": "Записаться"})
    result = RequiredBlocksCheck().run(lp)
    assert not result.passed
    assert "intro" in result.message


# ── InternalLinksCheck ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_internal_links_passes():
    lp = _make_landing(blocks={
        "intro": "text",
        "internal_links": ["/uslugi/a/", "/uslugi/b/"],
    })
    result = InternalLinksCheck().run(lp)
    assert result.passed


@pytest.mark.django_db
def test_internal_links_warns_when_less_than_2():
    lp = _make_landing(blocks={"intro": "text with /uslugi/a/ link"})
    result = InternalLinksCheck().run(lp)
    assert not result.passed
    assert result.severity == "warning"


# ── ContentDuplicateCheck ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_content_duplicate_passes_unique():
    _make_landing(
        slug="existing",
        blocks={"intro": "Совершенно другой контент про массаж ног"},
        status=LandingPage.STATUS_PUBLISHED,
    )
    lp = _make_landing(
        slug="new-one",
        blocks={"intro": "Уникальный текст про лазерную эпиляцию в Пензе"},
    )
    result = ContentDuplicateCheck().run(lp)
    assert result.passed


@pytest.mark.django_db
def test_content_duplicate_fails_on_copy():
    blocks = {"intro": "Точная копия длинного текста " * 20, "cta_text": "Записаться"}
    _make_landing(slug="original", blocks=blocks, status=LandingPage.STATUS_PUBLISHED)
    lp = _make_landing(slug="copy", blocks=blocks)
    result = ContentDuplicateCheck().run(lp)
    assert not result.passed
    assert result.severity == "critical"


# ── SEOLandingQCAgent (integration) ────────────────────────────────────────

@pytest.mark.django_db
def test_qc_agent_marks_passing_landing_as_review_not_publish(mock_telegram):
    """CLAUDE.md запрещает автопубликацию: QC-passed → review + SeoTask, НЕ published."""
    lp = _make_landing(slug="good-landing", status=LandingPage.STATUS_DRAFT)
    task = AgentTask.objects.create(agent_type=AgentTask.LANDING_QC)
    agent = SEOLandingQCAgent()
    agent.run(task)

    lp.refresh_from_db()
    assert lp.status == LandingPage.STATUS_REVIEW
    assert lp.published_at is None  # публикация только вручную

    # SeoTask создаётся как «готов к публикации» для модерации человеком
    ready_task = SeoTask.objects.get(
        task_type=SeoTask.TYPE_CREATE_LANDING,
        target_url="/good-landing/",
    )
    assert ready_task.priority == SeoTask.PRIORITY_HIGH
    assert "Готов к публикации" in ready_task.title
    assert f"/admin/agents/landingpage/{lp.pk}/change/" in ready_task.description


@pytest.mark.django_db
def test_qc_agent_rejects_failing_landing(mock_telegram):
    # Дубль H1 → critical fail
    _make_landing(slug="existing", h1="Дубль", status=LandingPage.STATUS_PUBLISHED)
    lp = _make_landing(slug="new", h1="Дубль", status=LandingPage.STATUS_DRAFT)
    task = AgentTask.objects.create(agent_type=AgentTask.LANDING_QC)
    agent = SEOLandingQCAgent()
    agent.run(task)

    lp.refresh_from_db()
    assert lp.status == LandingPage.STATUS_REVIEW
    assert lp.published_at is None

    fix_task = SeoTask.objects.get(
        task_type=SeoTask.TYPE_FIX_TECHNICAL,
        target_url="/new/",
    )
    assert fix_task.priority == SeoTask.PRIORITY_HIGH
    assert "QC failed" in fix_task.title

    task.refresh_from_db()
    assert task.status == AgentTask.DONE


@pytest.mark.django_db
def test_qc_agent_does_not_duplicate_open_task_when_multiple_exist(mock_telegram):
    """filter().first() паттерн: повторный запуск при 2+ открытых задачах не падает."""
    _make_landing(slug="existing", h1="Дубль", status=LandingPage.STATUS_PUBLISHED)
    lp = _make_landing(slug="dup", h1="Дубль", status=LandingPage.STATUS_DRAFT)

    # Симулируем ситуацию: в БД уже есть 2 открытые задачи для того же URL
    # (get_or_create упал бы с MultipleObjectsReturned, filter().first() — нет)
    SeoTask.objects.create(
        task_type=SeoTask.TYPE_FIX_TECHNICAL,
        target_url="/dup/",
        title="QC failed: /dup/ (старая)",
        priority=SeoTask.PRIORITY_HIGH,
        status=SeoTask.STATUS_OPEN,
    )
    SeoTask.objects.create(
        task_type=SeoTask.TYPE_FIX_TECHNICAL,
        target_url="/dup/",
        title="QC failed: /dup/ (ещё одна)",
        priority=SeoTask.PRIORITY_HIGH,
        status=SeoTask.STATUS_IN_PROGRESS,
    )

    task = AgentTask.objects.create(agent_type=AgentTask.LANDING_QC)
    agent = SEOLandingQCAgent()
    agent.run(task)  # не должно бросить MultipleObjectsReturned

    task.refresh_from_db()
    assert task.status == AgentTask.DONE
    # Новых задач не создалось — переиспользовали существующую
    assert SeoTask.objects.filter(
        task_type=SeoTask.TYPE_FIX_TECHNICAL, target_url="/dup/",
    ).count() == 2


@pytest.mark.django_db
def test_qc_agent_no_landings_still_succeeds():
    task = AgentTask.objects.create(agent_type=AgentTask.LANDING_QC)
    agent = SEOLandingQCAgent()
    agent.run(task)
    task.refresh_from_db()
    assert task.status == AgentTask.DONE


# ── Sitemap + template ─────────────────────────────────────────────────────

@pytest.mark.django_db
def test_published_landing_in_sitemap(client):
    from django.utils import timezone
    _make_landing(
        slug="in-sitemap",
        status=LandingPage.STATUS_PUBLISHED,
        published_at=timezone.now(),
    )
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "/in-sitemap/" in resp.content.decode()


@pytest.mark.django_db
def test_draft_landing_not_in_sitemap(client):
    _make_landing(slug="not-in-sitemap", status=LandingPage.STATUS_DRAFT)
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "/not-in-sitemap/" not in resp.content.decode()
