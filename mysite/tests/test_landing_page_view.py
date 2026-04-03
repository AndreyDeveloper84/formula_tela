"""
Тесты задачи 4.2: view и URL для посадочных страниц.

Что проверяем:
- 200 для опубликованной страницы
- 404 для черновика, модерации, отклонённой
- 404 для несуществующего slug
- Контент: h1, meta_title, meta_description в ответе
- FAQ рендерится если есть
- Блоки рендерятся если заполнены
- Пустые блоки не вызывают ошибок
- URL резолвится правильно
"""
import pytest
from django.urls import reverse, resolve
from model_bakery import baker


# ── Фикстуры ─────────────────────────────────────────────────────────────────

SAMPLE_BLOCKS = {
    "intro":             "Боль в спине?\n\nМы поможем.",
    "how_it_works":      "1. Консультация\n2. Массаж\n3. Рекомендации",
    "who_is_it_for":     "\u2022 При болях в спине\n\u2022 При стрессе",
    "contraindications": "\u2022 Острые воспаления\n\u2022 Онкология",
    "results":           "Облегчение после первого сеанса",
    "faq": [
        {"question": "Больно ли?",  "answer": "Нет, подбираем интенсивность."},
        {"question": "Как часто?",  "answer": "Курс 5-10 сеансов."},
    ],
    "cta_text":       "Запишитесь на массаж спины",
    "internal_links": ["massazh-shvz", "klassicheskij-massazh"],
}


@pytest.fixture
def published_landing(db):
    """Опубликованная посадочная страница."""
    return baker.make(
        "agents.LandingPage",
        slug="massazh-spiny",
        status="published",
        meta_title="Массаж спины в Пензе \u2014 от 1500 руб.",
        meta_description="Записывайтесь на массаж спины в Пензе.",
        h1="Массаж спины в Пензе",
        blocks=SAMPLE_BLOCKS,
        generated_by_agent=True,
    )


@pytest.fixture
def draft_landing(db):
    """Черновик — не должен быть доступен публично."""
    return baker.make(
        "agents.LandingPage",
        slug="massazh-draft",
        status="draft",
        meta_title="Черновик",
        meta_description="Черновик",
        h1="Черновик",
        blocks={},
    )


# ── URL резолвинг ─────────────────────────────────────────────────────────────

class TestLandingPageUrl:

    def test_url_resolves_to_landing_view(self):
        """URL /massazh-spiny/ резолвится в landing_page_view."""
        from agents.views import landing_page_view
        resolved = resolve("/massazh-spiny/")
        assert resolved.func == landing_page_view

    def test_url_name_landing_page(self):
        """URL с именем 'landing_page' генерируется правильно."""
        url = reverse("landing_page", kwargs={"slug": "massazh-spiny"})
        assert url == "/massazh-spiny/"

    def test_admin_not_intercepted(self, client):
        """admin/ не перехватывается slug-маршрутом."""
        response = client.get("/admin/")
        # Редирект на логин — значит admin работает
        assert response.status_code in (200, 302)
        assert "/admin/" in response.get("Location", "/admin/")

    def test_healthz_not_intercepted(self, client):
        """healthz/ не перехватывается slug-маршрутом."""
        response = client.get("/healthz/")
        assert response.status_code == 200


# ── HTTP ответы ───────────────────────────────────────────────────────────────

class TestLandingPageView:

    @pytest.mark.django_db
    def test_published_returns_200(self, client, published_landing):
        """Опубликованная страница возвращает 200."""
        response = client.get(f"/{published_landing.slug}/")
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_draft_returns_404(self, client, draft_landing):
        """Черновик возвращает 404."""
        response = client.get(f"/{draft_landing.slug}/")
        assert response.status_code == 404

    @pytest.mark.django_db
    def test_review_returns_404(self, client, db):
        """Страница на модерации возвращает 404."""
        baker.make(
            "agents.LandingPage",
            slug="on-review",
            status="review",
            meta_title="x", meta_description="x", h1="x", blocks={},
        )
        response = client.get("/on-review/")
        assert response.status_code == 404

    @pytest.mark.django_db
    def test_rejected_returns_404(self, client, db):
        """Отклонённая страница возвращает 404."""
        baker.make(
            "agents.LandingPage",
            slug="rejected-page",
            status="rejected",
            meta_title="x", meta_description="x", h1="x", blocks={},
        )
        response = client.get("/rejected-page/")
        assert response.status_code == 404

    @pytest.mark.django_db
    def test_nonexistent_slug_returns_404(self, client, db):
        """Несуществующий slug -> 404."""
        response = client.get("/ne-sushchestvuet/")
        assert response.status_code == 404


# ── Контент страницы ──────────────────────────────────────────────────────────

class TestLandingPageContent:

    @pytest.mark.django_db
    def test_h1_in_response(self, client, published_landing):
        """H1 присутствует в HTML ответе."""
        response = client.get(f"/{published_landing.slug}/")
        assert "Массаж спины в Пензе" in response.content.decode("utf-8")

    @pytest.mark.django_db
    def test_meta_title_in_response(self, client, published_landing):
        """meta_title используется в теге <title>."""
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Массаж спины в Пензе" in content

    @pytest.mark.django_db
    def test_meta_description_in_response(self, client, published_landing):
        """meta_description присутствует в HTML."""
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Записывайтесь на массаж спины" in content

    @pytest.mark.django_db
    def test_faq_rendered(self, client, published_landing):
        """FAQ вопросы и ответы присутствуют в HTML."""
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Больно ли?" in content
        assert "Нет, подбираем интенсивность." in content

    @pytest.mark.django_db
    def test_intro_in_response(self, client, published_landing):
        """Блок intro присутствует в HTML."""
        response = client.get(f"/{published_landing.slug}/")
        assert "Боль в спине" in response.content.decode("utf-8")

    @pytest.mark.django_db
    def test_cta_text_in_response(self, client, published_landing):
        """CTA текст присутствует в HTML."""
        response = client.get(f"/{published_landing.slug}/")
        assert "Запишитесь на массаж спины" in response.content.decode("utf-8")

    @pytest.mark.django_db
    def test_internal_links_rendered(self, client, published_landing):
        """Ссылки на связанные услуги присутствуют в HTML."""
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "massazh-shvz" in content
        assert "klassicheskij-massazh" in content

    @pytest.mark.django_db
    def test_empty_blocks_no_error(self, client, db):
        """Страница с пустыми блоками рендерится без ошибок."""
        baker.make(
            "agents.LandingPage",
            slug="empty-blocks",
            status="published",
            meta_title="Тест",
            meta_description="Тест",
            h1="Тест пустых блоков",
            blocks={},
        )
        response = client.get("/empty-blocks/")
        assert response.status_code == 200
        assert "Тест пустых блоков" in response.content.decode("utf-8")

    @pytest.mark.django_db
    def test_correct_template_used(self, client, published_landing):
        """Используется шаблон agents/landing_page.html."""
        response = client.get(f"/{published_landing.slug}/")
        assert "agents/landing_page.html" in [
            t.name for t in response.templates
        ]

    @pytest.mark.django_db
    def test_context_contains_landing(self, client, published_landing):
        """Контекст содержит объект landing."""
        response = client.get(f"/{published_landing.slug}/")
        assert response.context["landing"] == published_landing

    @pytest.mark.django_db
    def test_context_contains_faq(self, client, published_landing):
        """Контекст содержит список faq."""
        response = client.get(f"/{published_landing.slug}/")
        assert len(response.context["faq"]) == 2


# ── Templatetags ──────────────────────────────────────────────────────────────

class TestLandingTags:

    def test_split_lines_basic(self):
        """split_lines разбивает текст по переносам."""
        from agents.templatetags.landing_tags import split_lines
        result = split_lines("Шаг 1\nШаг 2\nШаг 3")
        assert result == ["Шаг 1", "Шаг 2", "Шаг 3"]

    def test_split_lines_removes_bullets(self):
        """split_lines убирает маркеры bullet, -, *."""
        from agents.templatetags.landing_tags import split_lines
        result = split_lines("\u2022 Пункт 1\n- Пункт 2\n* Пункт 3")
        assert result == ["Пункт 1", "Пункт 2", "Пункт 3"]

    def test_split_lines_removes_numbers(self):
        """split_lines убирает нумерованные маркеры 1., 2."""
        from agents.templatetags.landing_tags import split_lines
        result = split_lines("1. Шаг первый\n2. Шаг второй")
        assert result == ["Шаг первый", "Шаг второй"]

    def test_split_lines_empty_string(self):
        """split_lines на пустой строке возвращает []."""
        from agents.templatetags.landing_tags import split_lines
        assert split_lines("") == []

    def test_split_lines_none(self):
        """split_lines на None возвращает []."""
        from agents.templatetags.landing_tags import split_lines
        assert split_lines(None) == []

    def test_slugify_to_title_basic(self):
        """slugify_to_title превращает slug в заголовок."""
        from agents.templatetags.landing_tags import slugify_to_title
        assert slugify_to_title("massazh-spiny") == "Massazh spiny"

    def test_slugify_to_title_empty(self):
        """slugify_to_title на пустой строке возвращает пустую."""
        from agents.templatetags.landing_tags import slugify_to_title
        assert slugify_to_title("") == ""
