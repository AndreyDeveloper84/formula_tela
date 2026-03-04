"""
Тесты задачи 4.1 / 5.1: LandingPageGenerator.
Покрывает generate_landing, generate_from_markdown,
_get_services_context, _check_markdown_vs_db, _make_slug,
_create_blocks (LandingBlock создание).
Все OpenAI и Telegram вызовы замоканы.
"""
import json
import pytest
from unittest.mock import MagicMock, patch
from model_bakery import baker

from agents.agents.landing_generator import LandingPageGenerator, LandingGeneratorError
from agents.models import LandingBlock


# ── Константы ─────────────────────────────────────────────────────────────────

VALID_GPT_RESPONSE = json.dumps({
    "meta_title":        "Массаж спины в Пензе — цены от 1500 руб.",
    "meta_description":  "Запишитесь на массаж спины. Опытные мастера.",
    "h1":                "Массаж спины в Пензе",
    "intro":             "Боль в спине?\n\nМы поможем.",
    "how_it_works":      "1. Консультация\n2. Массаж\n3. Рекомендации",
    "who_is_it_for":     "\u2022 При болях в спине\n\u2022 При стрессе",
    "contraindications": "\u2022 Острые воспаления\n\u2022 Онкология",
    "results":           "Облегчение уже после первого сеанса",
    "faq": [
        {"question": "Сколько сеансов нужно?",    "answer": "Курс 10 сеансов"},
        {"question": "Есть ли противопоказания?", "answer": "Да, уточните"},
        {"question": "Как записаться?",            "answer": "Онлайн или по телефону"},
        {"question": "Длительность?",              "answer": "60 минут"},
        {"question": "Нужна ли подготовка?",       "answer": "Нет"},
        {"question": "При беременности?",          "answer": "Нет"},
        {"question": "Какой результат?",           "answer": "Снятие напряжения"},
        {"question": "Есть скидки?",               "answer": "Да, при курсе"},
    ],
    "cta_text":       "Запишитесь онлайн прямо сейчас",
    "internal_links": ["klassicheskij-massazh", "sportivnyj-massazh"],
})

SAMPLE_MARKDOWN = """
# Массаж спины в Пензе

Боли в спине? Мы поможем за 5-10 сеансов.

## Как это работает
1. Приходишь на консультацию
2. Мастер подбирает технику
3. Сеанс 60 минут

## Стоимость
- 1 сеанс: 1500 руб.
- Курс 10 сеансов: 12000 руб.

## FAQ
**Больно ли?** — Нет, техника мягкая.
"""


def _make_openai_mock(content: str = VALID_GPT_RESPONSE):
    """Mock OpenAI с фиксированным ответом."""
    mock = MagicMock()
    mock.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=content))]
    )
    return mock


@pytest.fixture
def cluster(db):
    """Кластер без категории."""
    return baker.make(
        "agents.SeoKeywordCluster",
        name="Массаж спины Пенза",
        service_slug="massazh-spiny",
        target_url="/massazh-spiny",
        keywords=["массаж спины", "массаж спины пенза"],
        geo="Пенза",
        is_active=True,
        service_category=None,
    )


@pytest.fixture
def cluster_with_category(db):
    """Кластер с привязанной категорией услуг."""
    category = baker.make("services_app.ServiceCategory", name="Массаж")
    return baker.make(
        "agents.SeoKeywordCluster",
        name="Классический массаж Пенза",
        service_slug="klassicheskij-massazh",
        target_url="/klassicheskij-massazh",
        keywords=["классический массаж"],
        geo="Пенза",
        is_active=True,
        service_category=category,
    )


# ── generate_landing ──────────────────────────────────────────────────────────

class TestGenerateLanding:

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_creates_draft(self, mock_openai_cls, mock_notify, cluster):
        """Создаётся LandingPage со status='draft'."""
        mock_openai_cls.return_value = _make_openai_mock()
        from agents.models import LandingPage

        landing = LandingPageGenerator().generate_landing(cluster)

        assert landing.pk is not None
        assert landing.status == LandingPage.STATUS_DRAFT
        assert landing.generated_by_agent is True
        assert landing.cluster == cluster

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_fields_from_gpt(self, mock_openai_cls, mock_notify, cluster):
        """Поля берутся из GPT-ответа."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        assert landing.meta_title == "Массаж спины в Пензе — цены от 1500 руб."
        assert landing.h1 == "Массаж спины в Пензе"
        assert "intro" in landing.blocks
        assert "faq" in landing.blocks
        assert len(landing.blocks["faq"]) == 8

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_slug_from_target_url(self, mock_openai_cls, mock_notify, cluster):
        """Slug берётся из cluster.target_url."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        assert landing.slug == "massazh-spiny"

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_slug_collision_adds_v2(self, mock_openai_cls, mock_notify, cluster):
        """Если slug занят — добавляется суффикс -v2."""
        mock_openai_cls.return_value = _make_openai_mock()
        baker.make("agents.LandingPage", slug="massazh-spiny")

        landing = LandingPageGenerator().generate_landing(cluster)

        assert landing.slug == "massazh-spiny-v2"

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_creates_seotask(self, mock_openai_cls, mock_notify, cluster):
        """Создаётся SeoTask с task_type=create_landing, priority=high."""
        mock_openai_cls.return_value = _make_openai_mock()
        from agents.models import SeoTask

        landing = LandingPageGenerator().generate_landing(cluster)

        task = SeoTask.objects.get(
            task_type=SeoTask.TYPE_CREATE_LANDING,
            target_url=cluster.target_url,
        )
        assert task.priority == SeoTask.PRIORITY_HIGH
        assert task.status == SeoTask.STATUS_OPEN
        assert task.payload["landing_id"] == landing.id

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_calls_notify(self, mock_openai_cls, mock_notify, cluster):
        """notify_new_landing вызывается с созданным LandingPage."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        mock_notify.assert_called_once_with(landing)

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_returns_existing_draft(self, mock_openai_cls, mock_notify, cluster):
        """Если draft уже есть — GPT не вызывается."""
        existing = baker.make("agents.LandingPage", cluster=cluster, status="draft")

        result = LandingPageGenerator().generate_landing(cluster)

        assert result.pk == existing.pk
        mock_openai_cls.return_value.chat.completions.create.assert_not_called()
        mock_notify.assert_not_called()

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_notify_error_does_not_block(self, mock_openai_cls, mock_notify, cluster):
        """Ошибка Telegram не мешает сохранению."""
        mock_openai_cls.return_value = _make_openai_mock()
        mock_notify.side_effect = Exception("telegram down")
        from agents.models import LandingPage

        landing = LandingPageGenerator().generate_landing(cluster)

        assert LandingPage.objects.filter(pk=landing.pk).exists()

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.OpenAI")
    def test_raises_on_invalid_json(self, mock_openai_cls, cluster):
        """Невалидный JSON -> LandingGeneratorError."""
        mock_openai_cls.return_value = _make_openai_mock("not json {{{")

        with pytest.raises(LandingGeneratorError, match="невалидный JSON"):
            LandingPageGenerator().generate_landing(cluster)

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.OpenAI")
    def test_raises_on_missing_fields(self, mock_openai_cls, cluster):
        """JSON без обязательных полей -> LandingGeneratorError."""
        mock_openai_cls.return_value = _make_openai_mock(
            json.dumps({"meta_title": "Только заголовок"})
        )

        with pytest.raises(LandingGeneratorError, match="обязательные поля"):
            LandingPageGenerator().generate_landing(cluster)

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.OpenAI")
    def test_raises_on_gpt_api_error(self, mock_openai_cls, cluster):
        """Ошибка GPT API -> LandingGeneratorError."""
        mock_openai_cls.return_value.chat.completions.create.side_effect = (
            RuntimeError("quota exceeded")
        )

        with pytest.raises(LandingGeneratorError, match="GPT API error"):
            LandingPageGenerator().generate_landing(cluster)

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_meta_title_truncated(self, mock_openai_cls, mock_notify, cluster):
        """meta_title обрезается до 70 символов."""
        resp = json.loads(VALID_GPT_RESPONSE)
        resp["meta_title"] = "A" * 100
        mock_openai_cls.return_value = _make_openai_mock(json.dumps(resp))

        landing = LandingPageGenerator().generate_landing(cluster)

        assert len(landing.meta_title) <= 70

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_source_markdown_empty_string(self, mock_openai_cls, mock_notify, cluster):
        """generate_landing сохраняет source_markdown='' (не None)."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        assert landing.source_markdown == ""


# ── generate_from_markdown ────────────────────────────────────────────────────

class TestGenerateFromMarkdown:

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_saves_source_markdown(self, mock_openai_cls, mock_notify, cluster):
        """LandingPage.source_markdown = переданный текст."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_from_markdown(cluster, SAMPLE_MARKDOWN)

        assert landing.source_markdown == SAMPLE_MARKDOWN
        assert landing.status == "draft"

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_markdown_in_gpt_prompt(self, mock_openai_cls, mock_notify, cluster):
        """Текст маркдауна попадает в промпт GPT."""
        mock_openai_cls.return_value = _make_openai_mock()

        LandingPageGenerator().generate_from_markdown(cluster, SAMPLE_MARKDOWN)

        call_kwargs = mock_openai_cls.return_value.chat.completions.create.call_args
        all_content = " ".join(
            m["content"]
            for m in call_kwargs[1]["messages"]
            if isinstance(m.get("content"), str)
        )
        assert "Массаж спины в Пензе" in all_content

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_seotask_payload_source_markdown(
        self, mock_openai_cls, mock_notify, cluster
    ):
        """SeoTask.payload['source'] == 'markdown'."""
        mock_openai_cls.return_value = _make_openai_mock()
        from agents.models import SeoTask

        landing = LandingPageGenerator().generate_from_markdown(cluster, SAMPLE_MARKDOWN)

        task = SeoTask.objects.get(
            task_type=SeoTask.TYPE_CREATE_LANDING,
            target_url=cluster.target_url,
        )
        assert task.payload["source"] == "markdown"
        assert task.payload["landing_id"] == landing.id

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_returns_existing_draft(self, mock_openai_cls, mock_notify, cluster):
        """Если draft уже есть — GPT не вызывается."""
        existing = baker.make("agents.LandingPage", cluster=cluster, status="draft")

        result = LandingPageGenerator().generate_from_markdown(cluster, SAMPLE_MARKDOWN)

        assert result.pk == existing.pk
        mock_openai_cls.return_value.chat.completions.create.assert_not_called()

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_calls_notify(self, mock_openai_cls, mock_notify, cluster):
        """notify_new_landing вызывается после создания."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_from_markdown(cluster, SAMPLE_MARKDOWN)

        mock_notify.assert_called_once_with(landing)

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_notify_error_does_not_block(self, mock_openai_cls, mock_notify, cluster):
        """Ошибка Telegram не мешает сохранению."""
        mock_openai_cls.return_value = _make_openai_mock()
        mock_notify.side_effect = Exception("telegram down")
        from agents.models import LandingPage

        landing = LandingPageGenerator().generate_from_markdown(cluster, SAMPLE_MARKDOWN)

        assert LandingPage.objects.filter(pk=landing.pk).exists()

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.OpenAI")
    def test_raises_on_invalid_json(self, mock_openai_cls, cluster):
        """Невалидный JSON -> LandingGeneratorError."""
        mock_openai_cls.return_value = _make_openai_mock("broken {{")

        with pytest.raises(LandingGeneratorError):
            LandingPageGenerator().generate_from_markdown(cluster, SAMPLE_MARKDOWN)


# ── _get_services_context ─────────────────────────────────────────────────────

class TestGetServicesContext:

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.OpenAI")
    def test_includes_service_name_and_price(self, mock_openai_cls, cluster_with_category):
        """Услуга с ServiceOption -> имя и цена в контексте."""
        service = baker.make(
            "services_app.Service",
            name="Массаж спины",
            category=cluster_with_category.service_category,
            is_active=True,
        )
        baker.make(
            "services_app.ServiceOption",
            service=service,
            duration_min=60,
            units=1,
            unit_type="session",
            price=1500,
            is_active=True,
        )

        ctx = LandingPageGenerator()._get_services_context(cluster_with_category)

        assert "Массаж спины" in ctx
        assert "1500" in ctx

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.OpenAI")
    def test_no_price_shows_placeholder(self, mock_openai_cls, cluster_with_category):
        """Нет цен -> НУЖНО УТОЧНИТЬ."""
        baker.make(
            "services_app.Service",
            name="Уход без цен",
            category=cluster_with_category.service_category,
            is_active=True,
            price=None,
            price_from=None,
        )

        ctx = LandingPageGenerator()._get_services_context(cluster_with_category)

        assert "НУЖНО УТОЧНИТЬ" in ctx

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.OpenAI")
    def test_no_category_no_slug_shows_placeholder(self, mock_openai_cls):
        """Кластер без категории и slug -> НУЖНО УТОЧНИТЬ."""
        cluster = baker.make(
            "agents.SeoKeywordCluster",
            service_category=None,
            service_slug="",
            keywords=["тест"],
            geo="Пенза",
        )

        ctx = LandingPageGenerator()._get_services_context(cluster)

        assert "НУЖНО УТОЧНИТЬ" in ctx

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.OpenAI")
    def test_keywords_in_context(self, mock_openai_cls):
        """Ключевые слова попадают в контекст."""
        cluster = baker.make(
            "agents.SeoKeywordCluster",
            service_category=None,
            service_slug="",
            keywords=["массаж спины", "массаж спины пенза"],
            geo="Пенза",
        )

        ctx = LandingPageGenerator()._get_services_context(cluster)

        assert "массаж спины" in ctx


# ── _check_markdown_vs_db ─────────────────────────────────────────────────────

class TestCheckMarkdownVsDb:

    @patch("agents.agents.landing_generator.OpenAI")
    def test_no_warnings_when_prices_match(self, mock_openai_cls):
        """Число из маркдауна есть в БД -> нет предупреждений."""
        gen = LandingPageGenerator()
        assert gen._check_markdown_vs_db(
            "Цена 1500 руб.",
            "Варианты:\n  \u2013 60 мин: 1500 руб.",
        ) == []

    @patch("agents.agents.landing_generator.OpenAI")
    def test_warning_on_price_mismatch(self, mock_openai_cls):
        """Цена в маркдауне не совпадает с БД -> предупреждение."""
        gen = LandingPageGenerator()
        warnings = gen._check_markdown_vs_db(
            "Цена 2000 руб.",
            "Варианты:\n  \u2013 60 мин: 1500 руб.",
        )
        assert len(warnings) == 1
        assert "2000" in warnings[0]

    @patch("agents.agents.landing_generator.OpenAI")
    def test_warning_when_db_has_no_prices(self, mock_openai_cls):
        """Числа в маркдауне, в БД — НУЖНО УТОЧНИТЬ -> предупреждение."""
        gen = LandingPageGenerator()
        warnings = gen._check_markdown_vs_db(
            "Цена 1500 руб.",
            "НУЖНО УТОЧНИТЬ: цены не заданы",
        )
        assert len(warnings) == 1

    @patch("agents.agents.landing_generator.OpenAI")
    def test_no_warnings_without_numbers(self, mock_openai_cls):
        """Маркдаун без чисел -> нет предупреждений."""
        gen = LandingPageGenerator()
        assert gen._check_markdown_vs_db(
            "# Массаж\nОтличная процедура.",
            "Варианты:\n  \u2013 60 мин: 1500 руб.",
        ) == []

    @patch("agents.agents.landing_generator.OpenAI")
    def test_no_warnings_empty_inputs(self, mock_openai_cls):
        """Пустые входные данные -> нет предупреждений."""
        assert LandingPageGenerator()._check_markdown_vs_db("", "") == []

    @patch("agents.agents.landing_generator.OpenAI")
    def test_prompt_truncates_long_markdown(self, mock_openai_cls):
        """Маркдаун > 3000 символов обрезается в промпте."""
        cluster = MagicMock()
        cluster.geo = "Пенза"
        cluster.keywords = ["тест"]
        cluster.target_url = "/test"

        prompt = LandingPageGenerator()._build_prompt_with_markdown(
            cluster, "контекст", "x" * 5000
        )
        md_section = prompt[prompt.find("БРИФ РЕДАКТОРА"):prompt.find("ДАННЫЕ ОБ УСЛУГЕ")]

        assert "x" * 3001 not in md_section
        assert "обрезан" in prompt


# ── _make_slug ────────────────────────────────────────────────────────────────

class TestMakeSlug:

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.OpenAI")
    def test_slug_from_target_url(self, mock_openai_cls):
        cluster = baker.make(
            "agents.SeoKeywordCluster",
            target_url="/massazh-spiny",
            service_slug="massazh-spiny",
        )
        assert LandingPageGenerator()._make_slug(cluster) == "massazh-spiny"

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.OpenAI")
    def test_collision_v2(self, mock_openai_cls):
        cluster = baker.make(
            "agents.SeoKeywordCluster",
            target_url="/test-slug",
            service_slug="test-slug",
        )
        baker.make("agents.LandingPage", slug="test-slug")
        assert LandingPageGenerator()._make_slug(cluster) == "test-slug-v2"

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.OpenAI")
    def test_collision_v3(self, mock_openai_cls):
        cluster = baker.make(
            "agents.SeoKeywordCluster",
            target_url="/test",
            service_slug="test",
        )
        baker.make("agents.LandingPage", slug="test")
        baker.make("agents.LandingPage", slug="test-v2")
        assert LandingPageGenerator()._make_slug(cluster) == "test-v3"


# ── _create_blocks (LandingBlock) ────────────────────────────────────────────

class TestCreateBlocks:
    """Тесты создания LandingBlock записей из GPT-ответа."""

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_blocks_created_count(self, mock_openai_cls, mock_notify, cluster):
        """generate_landing создаёт ожидаемое количество LandingBlock."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        # VALID_GPT_RESPONSE содержит: intro, how_it_works, who_is_it_for,
        # contraindications, results (5 из BLOCK_MAPPING) + cta + faq + navigation = 8
        assert LandingBlock.objects.filter(landing_page=landing).count() == 8

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_intro_becomes_accent(self, mock_openai_cls, mock_notify, cluster):
        """intro → block_type='accent', title пустой (не выводится на фронте)."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        block = LandingBlock.objects.get(
            landing_page=landing, block_type="accent", order=1
        )
        assert block.title == ""
        assert "Боль в спине" in block.content

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_how_it_works_becomes_checklist(self, mock_openai_cls, mock_notify, cluster):
        """how_it_works → block_type='checklist'."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        block = LandingBlock.objects.get(
            landing_page=landing, block_type="checklist", title="Что вы почувствуете"
        )
        assert "Консультация" in block.content

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_who_is_it_for_becomes_identification(self, mock_openai_cls, mock_notify, cluster):
        """who_is_it_for → block_type='identification'."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        block = LandingBlock.objects.get(
            landing_page=landing, block_type="identification"
        )
        assert block.title == "Ваш случай?"

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_results_becomes_text(self, mock_openai_cls, mock_notify, cluster):
        """results → block_type='text', title='Результат'."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        block = LandingBlock.objects.get(
            landing_page=landing, block_type="text", title="Результат"
        )
        assert "Облегчение" in block.content

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_cta_block_created(self, mock_openai_cls, mock_notify, cluster):
        """cta_text → block_type='cta', btn_text заполнен."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        block = LandingBlock.objects.get(
            landing_page=landing, block_type="cta"
        )
        assert block.btn_text == "Запишитесь онлайн прямо сейчас"
        assert block.title == ""

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_faq_block_created(self, mock_openai_cls, mock_notify, cluster):
        """faq → block_type='faq', content содержит вопросы через ---."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        block = LandingBlock.objects.get(
            landing_page=landing, block_type="faq"
        )
        assert block.title == "Частые вопросы"
        assert "---" in block.content
        assert "Сколько сеансов нужно?" in block.content
        assert "Курс 10 сеансов" in block.content

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_navigation_block_created(self, mock_openai_cls, mock_notify, cluster):
        """internal_links → block_type='navigation'."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        block = LandingBlock.objects.get(
            landing_page=landing, block_type="navigation"
        )
        assert block.title == "Похожие процедуры"
        assert "klassicheskij-massazh" in block.content
        assert "sportivnyj-massazh" in block.content

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_block_order_sequential(self, mock_openai_cls, mock_notify, cluster):
        """Порядок блоков последовательный (1, 2, 3, ...)."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        orders = list(
            LandingBlock.objects.filter(landing_page=landing)
            .order_by("order")
            .values_list("order", flat=True)
        )
        assert orders == list(range(1, len(orders) + 1))

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_empty_fields_skip_blocks(self, mock_openai_cls, mock_notify, cluster):
        """Пустые поля GPT-ответа не создают блоков."""
        minimal = json.dumps({
            "meta_title":        "Тест",
            "meta_description":  "Тест",
            "h1":                "Тест",
            "intro":             "Введение",
            "faq":               [],
            "cta_text":          "",
            "internal_links":    [],
        })
        mock_openai_cls.return_value = _make_openai_mock(minimal)

        landing = LandingPageGenerator().generate_landing(cluster)

        # Только intro → accent
        assert LandingBlock.objects.filter(landing_page=landing).count() == 1
        block = LandingBlock.objects.get(landing_page=landing)
        assert block.block_type == "accent"

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_generate_from_markdown_creates_blocks(self, mock_openai_cls, mock_notify, cluster):
        """generate_from_markdown тоже создаёт LandingBlock записи."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_from_markdown(cluster, SAMPLE_MARKDOWN)

        assert LandingBlock.objects.filter(landing_page=landing).count() == 8

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_blocks_all_active(self, mock_openai_cls, mock_notify, cluster):
        """Все созданные блоки is_active=True по умолчанию."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        assert (
            LandingBlock.objects.filter(landing_page=landing, is_active=True).count()
            == LandingBlock.objects.filter(landing_page=landing).count()
        )

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_checklist_content_normalized(self, mock_openai_cls, mock_notify, cluster):
        """Пункты чеклиста нормализованы к sentence case."""
        resp = json.loads(VALID_GPT_RESPONSE)
        resp["how_it_works"] = "КОНСУЛЬТАЦИЯ\nМАССАЖ\nРЕКОМЕНДАЦИИ"
        mock_openai_cls.return_value = _make_openai_mock(json.dumps(resp))

        landing = LandingPageGenerator().generate_landing(cluster)

        block = LandingBlock.objects.get(
            landing_page=landing, block_type="checklist", title="Что вы почувствуете"
        )
        assert block.content == "Консультация\nМассаж\nРекомендации"

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_cta_btn_text_normalized(self, mock_openai_cls, mock_notify, cluster):
        """Текст CTA-кнопки нормализован к sentence case."""
        resp = json.loads(VALID_GPT_RESPONSE)
        resp["cta_text"] = "ЗАПИШИТЕСЬ ОНЛАЙН ПРЯМО СЕЙЧАС"
        mock_openai_cls.return_value = _make_openai_mock(json.dumps(resp))

        landing = LandingPageGenerator().generate_landing(cluster)

        block = LandingBlock.objects.get(landing_page=landing, block_type="cta")
        assert block.btn_text == "Запишитесь онлайн прямо сейчас"

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_faq_content_normalized(self, mock_openai_cls, mock_notify, cluster):
        """Вопросы и ответы FAQ нормализованы к sentence case."""
        resp = json.loads(VALID_GPT_RESPONSE)
        resp["faq"] = [
            {"question": "СКОЛЬКО СЕАНСОВ НУЖНО?", "answer": "КУРС 10 СЕАНСОВ"},
        ]
        mock_openai_cls.return_value = _make_openai_mock(json.dumps(resp))

        landing = LandingPageGenerator().generate_landing(cluster)

        block = LandingBlock.objects.get(landing_page=landing, block_type="faq")
        assert "Сколько сеансов нужно?" in block.content
        assert "Курс 10 сеансов" in block.content

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_html_block_not_normalized(self, mock_openai_cls, mock_notify, cluster):
        """HTML-блоки (price_table и др.) не нормализуются."""
        resp = json.loads(VALID_GPT_RESPONSE)
        resp["price_table"] = "<table><tr><td>МАССАЖ 60 МИН</td></tr></table>"
        mock_openai_cls.return_value = _make_openai_mock(json.dumps(resp))

        landing = LandingPageGenerator().generate_landing(cluster)

        block = LandingBlock.objects.get(landing_page=landing, block_type="price_table")
        assert "МАССАЖ 60 МИН" in block.content


# ── _sentence_case ───────────────────────────────────────────────────────────

class TestSentenceCase:
    """Тесты нормализации регистра текста."""

    @patch("agents.agents.landing_generator.OpenAI")
    def test_basic(self, mock_openai_cls):
        """РАССЛАБЛЕНИЕ МЫШЦ → Расслабление мышц."""
        result = LandingPageGenerator._sentence_case("РАССЛАБЛЕНИЕ МЫШЦ")
        assert result == "Расслабление мышц"

    @patch("agents.agents.landing_generator.OpenAI")
    def test_multiline(self, mock_openai_cls):
        """Каждая строка нормализуется отдельно."""
        result = LandingPageGenerator._sentence_case("ПУНКТ ОДИН\nПУНКТ ДВА")
        assert result == "Пункт один\nПункт два"

    @patch("agents.agents.landing_generator.OpenAI")
    def test_preserves_separator(self, mock_openai_cls):
        """Разделитель --- не трогаем."""
        result = LandingPageGenerator._sentence_case("ВОПРОС?\nОТВЕТ\n---\nВОПРОС 2?\nОТВЕТ 2")
        assert "---" in result
        assert result.split("\n")[2] == "---"

    @patch("agents.agents.landing_generator.OpenAI")
    def test_skips_html(self, mock_openai_cls):
        """Строки с HTML-тегами не трогаем."""
        text = "<table><tr><td>ЗАГОЛОВОК</td></tr></table>"
        assert LandingPageGenerator._sentence_case(text) == text

    @patch("agents.agents.landing_generator.OpenAI")
    def test_strips_markers(self, mock_openai_cls):
        """Эмодзи-маркеры убираются, текст нормализуется."""
        result = LandingPageGenerator._sentence_case("\u2705 РАССЛАБЛЕНИЕ МЫШЦ")
        assert result == "Расслабление мышц"

    @patch("agents.agents.landing_generator.OpenAI")
    def test_empty_string(self, mock_openai_cls):
        """Пустая строка → пустая строка."""
        assert LandingPageGenerator._sentence_case("") == ""

    @patch("agents.agents.landing_generator.OpenAI")
    def test_none(self, mock_openai_cls):
        """None → None."""
        assert LandingPageGenerator._sentence_case(None) is None

    @patch("agents.agents.landing_generator.OpenAI")
    def test_already_sentence_case(self, mock_openai_cls):
        """Уже в sentence case → не меняем."""
        result = LandingPageGenerator._sentence_case("Расслабление мышц")
        assert result == "Расслабление мышц"

    @patch("agents.agents.landing_generator.OpenAI")
    def test_preserves_proper_nouns(self, mock_openai_cls):
        """Смешанный регистр с именами собственными → не трогаем."""
        result = LandingPageGenerator._sentence_case("Массаж спины в Пензе")
        assert result == "Массаж спины в Пензе"

    @patch("agents.agents.landing_generator.OpenAI")
    def test_lowercase_start_capitalized(self, mock_openai_cls):
        """Строка с маленькой первой буквой → заглавная, остальное не трогаем."""
        result = LandingPageGenerator._sentence_case("шея и плечи «каменные» от работы")
        assert result == "Шея и плечи «каменные» от работы"

    @patch("agents.agents.landing_generator.OpenAI")
    def test_numbered_markers(self, mock_openai_cls):
        """Нумерованные маркеры убираются."""
        result = LandingPageGenerator._sentence_case("1. КОНСУЛЬТАЦИЯ\n2. МАССАЖ")
        assert result == "Консультация\nМассаж"
