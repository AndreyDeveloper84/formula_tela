"""
Тесты view и URL для посадочных страниц.
"""
import pytest
from django.urls import reverse, resolve
from model_bakery import baker


def _create_sample_blocks(landing):
    baker.make(
        "agents.LandingBlock",
        landing_page=landing,
        block_type="text",
        title="О процедуре",
        content="Боль в спине?\n\nМы поможем.",
        order=10,
        is_active=True,
    )
    baker.make(
        "agents.LandingBlock",
        landing_page=landing,
        block_type="faq",
        title="FAQ",
        content=(
            "Больно ли?\n"
            "Нет, подбираем интенсивность.\n"
            "---\n"
            "Как часто?\n"
            "Курс 5-10 сеансов."
        ),
        order=20,
        is_active=True,
    )
    baker.make(
        "agents.LandingBlock",
        landing_page=landing,
        block_type="navigation",
        title="Похожие процедуры",
        content="massazh-shvz\nklassicheskij-massazh",
        order=30,
        is_active=True,
    )


@pytest.fixture
def published_landing(db):
    landing = baker.make(
        "agents.LandingPage",
        slug="massazh-spiny",
        status="published",
        meta_title="Массаж спины в Пензе — от 1500 руб.",
        meta_description="Записывайтесь на массаж спины в Пензе.",
        h1="Массаж спины в Пензе",
        generated_by_agent=True,
    )
    _create_sample_blocks(landing)
    return landing


@pytest.fixture
def draft_landing(db):
    return baker.make(
        "agents.LandingPage",
        slug="massazh-draft",
        status="draft",
        meta_title="Черновик",
        meta_description="Черновик",
        h1="Черновик",
    )


class TestLandingPageUrl:
    def test_url_resolves_to_landing_view(self):
        from agents.views import landing_page_view
        resolved = resolve("/massazh-spiny/")
        assert resolved.func == landing_page_view

    def test_url_name_landing_page(self):
        url = reverse("landing_page", kwargs={"slug": "massazh-spiny"})
        assert url == "/massazh-spiny/"

    def test_admin_not_intercepted(self, client):
        response = client.get("/admin/")
        assert response.status_code in (200, 302)
        assert "/admin/" in response.get("Location", "/admin/")

    def test_healthz_not_intercepted(self, client):
        response = client.get("/healthz/")
        assert response.status_code == 200


class TestLandingPageView:
    @pytest.mark.django_db
    def test_published_returns_200(self, client, published_landing):
        response = client.get(f"/{published_landing.slug}/")
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_draft_returns_404(self, client, draft_landing):
        response = client.get(f"/{draft_landing.slug}/")
        assert response.status_code == 404

    @pytest.mark.django_db
    def test_review_returns_404(self, client):
        baker.make(
            "agents.LandingPage",
            slug="on-review",
            status="review",
            meta_title="x",
            meta_description="x",
            h1="x",
        )
        response = client.get("/on-review/")
        assert response.status_code == 404

    @pytest.mark.django_db
    def test_rejected_returns_404(self, client):
        baker.make(
            "agents.LandingPage",
            slug="rejected-page",
            status="rejected",
            meta_title="x",
            meta_description="x",
            h1="x",
        )
        response = client.get("/rejected-page/")
        assert response.status_code == 404

    @pytest.mark.django_db
    def test_nonexistent_slug_returns_404(self, client):
        response = client.get("/ne-sushchestvuet/")
        assert response.status_code == 404


class TestLandingPageContent:
    @pytest.mark.django_db
    def test_h1_in_response(self, client, published_landing):
        response = client.get(f"/{published_landing.slug}/")
        assert "Массаж спины в Пензе" in response.content.decode("utf-8")

    @pytest.mark.django_db
    def test_meta_description_in_response(self, client, published_landing):
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Записывайтесь на массаж спины" in content

    @pytest.mark.django_db
    def test_jsonld_service_and_breadcrumb_present(self, client, published_landing):
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert '"@type": "Service"' in content
        assert '"@type": "BreadcrumbList"' in content

    @pytest.mark.django_db
    def test_jsonld_faq_present_when_faq_exists(self, client, published_landing):
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert '"@type": "FAQPage"' in content

    @pytest.mark.django_db
    def test_faq_rendered(self, client, published_landing):
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Больно ли?" in content
        assert "Нет, подбираем интенсивность." in content

    @pytest.mark.django_db
    def test_navigation_links_rendered(self, client, published_landing):
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "massazh-shvz" in content
        assert "klassicheskij-massazh" in content

    @pytest.mark.django_db
    def test_custom_css_class_rendered(self, client):
        landing = baker.make(
            "agents.LandingPage",
            slug="landing-css-class",
            status="published",
            meta_title="Тест",
            meta_description="Тест",
            h1="Тест CSS классов",
        )
        baker.make(
            "agents.LandingBlock",
            landing_page=landing,
            block_type="text",
            title="О процедуре",
            content="Контент",
            css_class="my-custom-class",
            order=10,
            is_active=True,
        )
        response = client.get("/landing-css-class/")
        content = response.content.decode("utf-8")
        assert "my-custom-class" in content

    @pytest.mark.django_db
    def test_cta_button_and_subtext_rendered(self, client):
        landing = baker.make(
            "agents.LandingPage",
            slug="landing-cta",
            status="published",
            meta_title="Тест",
            meta_description="Тест",
            h1="Тест CTA",
        )
        baker.make(
            "agents.LandingBlock",
            landing_page=landing,
            block_type="cta",
            title="Запись",
            btn_text="Записаться сейчас",
            btn_sub="Выберите удобное время",
            order=10,
            is_active=True,
        )
        response = client.get("/landing-cta/")
        content = response.content.decode("utf-8")
        assert "Записаться сейчас" in content
        assert "Выберите удобное время" in content

    @pytest.mark.django_db
    def test_identification_block_emoji_rendered(self, client):
        landing = baker.make(
            "agents.LandingPage",
            slug="landing-identification",
            status="published",
            meta_title="Тест",
            meta_description="Тест",
            h1="Тест identification",
        )
        baker.make(
            "agents.LandingBlock",
            landing_page=landing,
            block_type="identification",
            title="Узнаёте себя?",
            content="💻 Работа за компьютером\n🤕 Болит поясница",
            order=10,
            is_active=True,
        )
        response = client.get("/landing-identification/")
        content = response.content.decode("utf-8")
        assert "💻" in content
        assert "🤕" in content

    @pytest.mark.django_db
    def test_empty_blocks_no_error(self, client):
        baker.make(
            "agents.LandingPage",
            slug="empty-blocks",
            status="published",
            meta_title="Тест",
            meta_description="Тест",
            h1="Тест пустых блоков",
        )
        response = client.get("/empty-blocks/")
        assert response.status_code == 200
        assert "Тест пустых блоков" in response.content.decode("utf-8")

    @pytest.mark.django_db
    def test_correct_template_used(self, client, published_landing):
        response = client.get(f"/{published_landing.slug}/")
        assert "agents/landing_page.html" in [t.name for t in response.templates]

    @pytest.mark.django_db
    def test_context_contains_landing(self, client, published_landing):
        response = client.get(f"/{published_landing.slug}/")
        assert response.context["landing"] == published_landing

    @pytest.mark.django_db
    def test_context_contains_faq(self, client, published_landing):
        response = client.get(f"/{published_landing.slug}/")
        assert len(response.context["faq"]) == 2

    @pytest.mark.django_db
    def test_context_uses_service_media(self, client):
        service = baker.make("services_app.Service", name="Тестовая услуга", is_active=True)
        baker.make(
            "services_app.ServiceMedia",
            service=service,
            is_active=True,
            media_type="video",
            order=1,
        )
        landing = baker.make(
            "agents.LandingPage",
            slug="landing-with-media",
            status="published",
            meta_title="Тест",
            meta_description="Тест",
            h1="Тест",
            service=service,
        )
        response = client.get(f"/{landing.slug}/")
        assert len(response.context["media_items"]) == 1


class TestLandingTags:
    def test_split_lines_basic(self):
        from agents.templatetags.landing_tags import split_lines
        assert split_lines("Шаг 1\nШаг 2\nШаг 3") == ["Шаг 1", "Шаг 2", "Шаг 3"]

    def test_split_lines_removes_bullets(self):
        from agents.templatetags.landing_tags import split_lines
        assert split_lines("• Пункт 1\n- Пункт 2\n* Пункт 3") == ["Пункт 1", "Пункт 2", "Пункт 3"]

    def test_split_lines_removes_numbers(self):
        from agents.templatetags.landing_tags import split_lines
        assert split_lines("1. Шаг первый\n2. Шаг второй") == ["Шаг первый", "Шаг второй"]

    def test_split_lines_empty_string(self):
        from agents.templatetags.landing_tags import split_lines
        assert split_lines("") == []

    def test_split_lines_none(self):
        from agents.templatetags.landing_tags import split_lines
        assert split_lines(None) == []

    def test_slugify_to_title_basic(self):
        from agents.templatetags.landing_tags import slugify_to_title
        assert slugify_to_title("massazh-spiny") == "Massazh spiny"

    def test_slugify_to_title_empty(self):
        from agents.templatetags.landing_tags import slugify_to_title
        assert slugify_to_title("") == ""
