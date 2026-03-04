"""
Тесты задачи 4.2 / 5.1: view и URL для посадочных страниц.

Что проверяем:
- 200 для опубликованной страницы
- 404 для черновика, модерации, отклонённой
- 404 для несуществующего slug
- Контент: h1, meta_title, meta_description в ответе
- LandingBlock-блоки рендерятся (новый подход)
- JSON fallback для старых записей (обратная совместимость)
- Пустые блоки не вызывают ошибок
- URL резолвится правильно
"""
import pytest
from django.urls import reverse, resolve
from model_bakery import baker


# ── Фикстуры JSON (для fallback-теста) ──────────────────────────────────────

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
    """Опубликованная страница с LandingBlock-блоками (новый подход)."""
    landing = baker.make(
        "agents.LandingPage",
        slug="massazh-spiny",
        status="published",
        meta_title="Массаж спины в Пензе \u2014 от 1500 руб.",
        meta_description="Записывайтесь на массаж спины в Пензе.",
        h1="Массаж спины в Пензе",
        blocks={},
        generated_by_agent=True,
    )
    # Создаём LandingBlock записи
    baker.make(
        "agents.LandingBlock",
        landing_page=landing,
        block_type="accent",
        title="",
        content="Боль в спине? Мы поможем.",
        order=1,
        is_active=True,
    )
    baker.make(
        "agents.LandingBlock",
        landing_page=landing,
        block_type="checklist",
        title="Что вы почувствуете",
        content="Консультация\nМассаж\nРекомендации",
        order=2,
        is_active=True,
    )
    baker.make(
        "agents.LandingBlock",
        landing_page=landing,
        block_type="identification",
        title="Ваш случай?",
        content="При болях в спине\nПри стрессе",
        order=3,
        is_active=True,
    )
    baker.make(
        "agents.LandingBlock",
        landing_page=landing,
        block_type="checklist",
        title="Противопоказания",
        content="Острые воспаления\nОнкология",
        order=4,
        is_active=True,
    )
    baker.make(
        "agents.LandingBlock",
        landing_page=landing,
        block_type="text",
        title="Результат",
        content="Облегчение после первого сеанса",
        order=5,
        is_active=True,
    )
    baker.make(
        "agents.LandingBlock",
        landing_page=landing,
        block_type="cta",
        title="",
        btn_text="Запишитесь на массаж спины",
        order=6,
        is_active=True,
    )
    baker.make(
        "agents.LandingBlock",
        landing_page=landing,
        block_type="faq",
        title="Частые вопросы",
        content="Больно ли?\nНет, подбираем интенсивность.\n---\nКак часто?\nКурс 5-10 сеансов.",
        order=7,
        is_active=True,
    )
    baker.make(
        "agents.LandingBlock",
        landing_page=landing,
        block_type="navigation",
        title="Похожие процедуры",
        content="massazh-shvz\nklassicheskij-massazh",
        order=8,
        is_active=True,
    )
    return landing


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


@pytest.fixture
def json_fallback_landing(db):
    """Старая запись с JSON blocks, без LandingBlock (fallback)."""
    return baker.make(
        "agents.LandingPage",
        slug="json-fallback",
        status="published",
        meta_title="Массаж шеи в Пензе",
        meta_description="Запишитесь на массаж шеи.",
        h1="Массаж шеи в Пензе",
        blocks=SAMPLE_BLOCKS,
        generated_by_agent=True,
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


# ── Контент страницы (LandingBlock) ──────────────────────────────────────────

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
    def test_accent_block_rendered(self, client, published_landing):
        """Акцентный блок (intro) присутствует в HTML без заголовка."""
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Боль в спине" in content

    @pytest.mark.django_db
    def test_checklist_block_rendered(self, client, published_landing):
        """Чеклист-блок рендерится с галочками."""
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Что вы почувствуете" in content
        assert "Консультация" in content

    @pytest.mark.django_db
    def test_identification_block_rendered(self, client, published_landing):
        """Блок идентификации рендерится."""
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Ваш случай?" in content
        assert "При болях в спине" in content

    @pytest.mark.django_db
    def test_text_block_rendered(self, client, published_landing):
        """Текстовый блок (results) рендерится."""
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Результат" in content
        assert "Облегчение после первого сеанса" in content

    @pytest.mark.django_db
    def test_cta_block_rendered(self, client, published_landing):
        """CTA-кнопка рендерится с модалкой."""
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Запишитесь на массаж спины" in content
        assert 'data-bs-toggle="modal"' in content
        assert 'data-bs-target="#exampleModal"' in content

    @pytest.mark.django_db
    def test_faq_block_rendered(self, client, published_landing):
        """FAQ вопросы и ответы присутствуют в HTML."""
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Больно ли?" in content
        assert "Нет, подбираем интенсивность." in content
        assert "Частые вопросы" in content

    @pytest.mark.django_db
    def test_navigation_block_rendered(self, client, published_landing):
        """Ссылки на связанные услуги присутствуют в HTML."""
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "massazh-shvz" in content
        assert "klassicheskij-massazh" in content
        assert "Похожие процедуры" in content

    @pytest.mark.django_db
    def test_inactive_block_not_rendered(self, client, published_landing):
        """Неактивный блок не рендерится."""
        baker.make(
            "agents.LandingBlock",
            landing_page=published_landing,
            block_type="text",
            title="Скрытый блок",
            content="Этот текст не должен показываться",
            order=99,
            is_active=False,
        )
        response = client.get(f"/{published_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Этот текст не должен показываться" not in content

    @pytest.mark.django_db
    def test_empty_blocks_no_error(self, client, db):
        """Страница без блоков рендерится без ошибок."""
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
    def test_context_has_blocks_true(self, client, published_landing):
        """Контекст has_blocks=True когда есть LandingBlock."""
        response = client.get(f"/{published_landing.slug}/")
        assert response.context["has_blocks"] is True

    @pytest.mark.django_db
    def test_context_blocks_queryset(self, client, published_landing):
        """Контекст blocks содержит LandingBlock queryset."""
        response = client.get(f"/{published_landing.slug}/")
        assert response.context["blocks"].count() == 8


# ── JSON fallback (обратная совместимость) ───────────────────────────────────

class TestLandingPageJsonFallback:

    @pytest.mark.django_db
    def test_json_fallback_renders(self, client, json_fallback_landing):
        """Старая запись без LandingBlock → рендер через JSON fallback."""
        response = client.get(f"/{json_fallback_landing.slug}/")
        assert response.status_code == 200

    @pytest.mark.django_db
    def test_json_fallback_has_blocks_false(self, client, json_fallback_landing):
        """Контекст has_blocks=False для старой записи."""
        response = client.get(f"/{json_fallback_landing.slug}/")
        assert response.context["has_blocks"] is False

    @pytest.mark.django_db
    def test_json_fallback_intro(self, client, json_fallback_landing):
        """JSON intro рендерится в fallback."""
        response = client.get(f"/{json_fallback_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Боль в спине" in content

    @pytest.mark.django_db
    def test_json_fallback_faq(self, client, json_fallback_landing):
        """JSON FAQ рендерится в fallback."""
        response = client.get(f"/{json_fallback_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Больно ли?" in content
        assert "Нет, подбираем интенсивность." in content

    @pytest.mark.django_db
    def test_json_fallback_cta(self, client, json_fallback_landing):
        """JSON CTA рендерится в fallback."""
        response = client.get(f"/{json_fallback_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "Запишитесь на массаж спины" in content

    @pytest.mark.django_db
    def test_json_fallback_internal_links(self, client, json_fallback_landing):
        """JSON internal_links рендерятся в fallback."""
        response = client.get(f"/{json_fallback_landing.slug}/")
        content = response.content.decode("utf-8")
        assert "massazh-shvz" in content


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

    def test_split_lines_removes_emoji_checkmarks(self):
        """split_lines убирает эмодзи-маркеры ✅, ✓, 💚."""
        from agents.templatetags.landing_tags import split_lines
        result = split_lines("\u2705 Пункт 1\n\u2713 Пункт 2\n\U0001F49A Пункт 3")
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
