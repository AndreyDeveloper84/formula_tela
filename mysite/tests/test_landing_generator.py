"""
Тесты задачи 4.1: LandingPageGenerator.
Покрывает generate_landing, generate_from_markdown,
_get_services_context, _check_markdown_vs_db, _make_slug.
Все OpenAI и Telegram вызовы замоканы.
"""
import json
import pytest
from unittest.mock import MagicMock, patch
from model_bakery import baker

from agents.agents.landing_generator import LandingPageGenerator, LandingGeneratorError


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
    def test_applies_default_block_styles(self, mock_openai_cls, mock_notify, cluster):
        """Генератор проставляет дефолтные css/bg/text стили по типу блока."""
        mock_openai_cls.return_value = _make_openai_mock()

        landing = LandingPageGenerator().generate_landing(cluster)

        text_block = landing.landing_blocks.filter(block_type="text").first()
        cta_block = landing.landing_blocks.filter(block_type="cta").first()
        nav_block = landing.landing_blocks.filter(block_type="navigation").first()

        assert text_block is not None
        assert text_block.css_class == "lb-text"
        assert cta_block is not None
        assert cta_block.css_class == "lb-cta"
        assert nav_block is not None
        assert nav_block.css_class == "lb-navigation"
        assert nav_block.bg_color == "#f5f5f5"

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
        assert landing.landing_blocks.filter(block_type="text").exists()
        assert landing.landing_blocks.filter(block_type="faq").exists()
        assert landing.landing_blocks.count() >= 6

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
        existing = baker.make(
            "agents.LandingPage",
            cluster=cluster,
            status="draft",
            source_markdown="already generated",
        )

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
    def test_hard_section_filter_skips_technical_sections(
        self, mock_openai_cls, mock_notify, cluster
    ):
        """Служебные секции SEO/TZ отфильтровываются и не попадают в контентный план."""
        mock_openai_cls.return_value = _make_openai_mock()
        gen = LandingPageGenerator()
        markdown = """
## МЕТА-ТЕГИ
<meta name="description" content="x">

## Service (основная)
{"@context":"https://schema.org"}

## Что вы получите
✅ Снятие боли

## [CTA-КНОПКА №1]
Запишитесь на массаж

## Технические требования
- [ ] Title до 70
"""
        plan = gen._build_markdown_block_plan(markdown)
        titles = [row[1] for row in plan]

        assert "МЕТА-ТЕГИ" not in titles
        assert "Service (основная)" not in titles
        assert "Технические требования" not in titles
        assert "Что вы получите" in titles
        assert "Запись" in titles

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_quality_warnings_saved_to_task_payload(
        self, mock_openai_cls, mock_notify, cluster
    ):
        """Результат quality-аудита сохраняется в payload SeoTask."""
        mock_openai_cls.return_value = _make_openai_mock()
        from agents.models import SeoTask

        markdown = """
## Что вы получите
Текст.
"""
        landing = LandingPageGenerator().generate_from_markdown(cluster, markdown)
        task = SeoTask.objects.get(payload__landing_id=landing.id)

        assert "quality_ok" in task.payload
        assert "quality_warnings" in task.payload
        assert isinstance(task.payload["quality_warnings"], list)

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_cta_positioning_adds_middle_and_final_cta(
        self, mock_openai_cls, mock_notify, cluster
    ):
        """Стратегия CTA: добавляется промежуточный CTA и финальный CTA."""
        mock_openai_cls.return_value = _make_openai_mock()
        markdown = """
## [БЛОК 3] УЗНАЁТЕ СЕБЯ?
💻 Работа за компьютером

## Противопоказания
- Температура
"""

        landing = LandingPageGenerator().generate_from_markdown(cluster, markdown)
        cta_blocks = list(landing.landing_blocks.filter(block_type="cta").order_by("order"))

        assert len(cta_blocks) >= 2
        last_block = landing.landing_blocks.order_by("order").last()
        assert last_block.block_type == "cta"

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_keeps_markdown_emoji_when_gpt_drops_them(
        self, mock_openai_cls, mock_notify, cluster
    ):
        """Если в markdown есть эмодзи, а GPT их убрал, сохраняем markdown-вариант."""
        resp = json.loads(VALID_GPT_RESPONSE)
        resp["how_it_works"] = "1. Консультация\n2. Массаж\n3. Рекомендации"
        mock_openai_cls.return_value = _make_openai_mock(json.dumps(resp))
        markdown = """
## Как проходит процедура
💆 Консультация
🧘 Массаж
"""

        landing = LandingPageGenerator().generate_from_markdown(cluster, markdown)
        block = landing.landing_blocks.filter(block_type="checklist").first()

        assert block is not None
        assert "💆" in block.content
        assert "🧘" in block.content

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_two_stage_plan_preserves_markdown_structure(
        self, mock_openai_cls, mock_notify, cluster
    ):
        """Этап A задаёт структуру секций, этап B только улучшает тексты внутри неё."""
        mock_openai_cls.return_value = _make_openai_mock()
        markdown = """
# Массаж спины
## [БЛОК 3] УЗНАЁТЕ СЕБЯ?
💻 Работа за компьютером
## Противопоказания
- Температура
## CTA
Запишитесь на удобное время
"""
        landing = LandingPageGenerator().generate_from_markdown(cluster, markdown)
        block_types = list(landing.landing_blocks.order_by("order").values_list("block_type", flat=True))

        assert "identification" in block_types
        assert "cta" in block_types
        # В двухэтапном режиме не подмешивается шаблонный блок "Похожие процедуры",
        # если его нет в markdown плане.
        assert block_types.count("navigation") == 0

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_contract_mapping_adds_identification_block(
        self, mock_openai_cls, mock_notify, cluster
    ):
        """Секция '[БЛОК 3] Узнаёте себя?' конвертируется в LandingBlock.identification."""
        mock_openai_cls.return_value = _make_openai_mock()
        markdown = """
## [БЛОК 3] УЗНАЁТЕ СЕБЯ?
**H2:** Узнаёте себя?

💻 Работаете за компьютером целый день
🤕 Болит поясница к вечеру
"""

        landing = LandingPageGenerator().generate_from_markdown(cluster, markdown)

        block = landing.landing_blocks.filter(block_type="identification").first()
        assert block is not None
        assert block.title == "Узнаёте себя?"
        assert "💻" in block.content
        assert "🤕" in block.content

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
        existing = baker.make(
            "agents.LandingPage",
            cluster=cluster,
            status="draft",
            source_markdown="already generated",
        )

        result = LandingPageGenerator().generate_from_markdown(cluster, SAMPLE_MARKDOWN)

        assert result.pk == existing.pk
        mock_openai_cls.return_value.chat.completions.create.assert_not_called()

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing")
    @patch("agents.agents.landing_generator.OpenAI")
    def test_regenerates_when_existing_draft_is_empty(
        self, mock_openai_cls, mock_notify, cluster
    ):
        """Пустой draft (без markdown/блоков) не возвращается, а перегенерируется."""
        mock_openai_cls.return_value = _make_openai_mock()
        existing = baker.make(
            "agents.LandingPage",
            cluster=cluster,
            status="draft",
            source_markdown="",
            h1="Пустой",
        )

        result = LandingPageGenerator().generate_from_markdown(cluster, SAMPLE_MARKDOWN)

        assert result.pk == existing.pk
        assert result.source_markdown == SAMPLE_MARKDOWN
        assert result.landing_blocks.filter(is_active=True).exists()
        assert mock_openai_cls.return_value.chat.completions.create.called

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
        """Длинный markdown сокращается, но структура секций в промпте сохраняется."""
        cluster = MagicMock()
        cluster.geo = "Пенза"
        cluster.keywords = ["тест"]
        cluster.target_url = "/test"

        markdown = (
            "## Блок 1\n"
            + ("x" * 8000)
            + "\n\n## [БЛОК 3] УЗНАЁТЕ СЕБЯ?\n"
            + "💻 Работаю за компьютером\n"
            + ("y" * 8000)
        )
        prompt = LandingPageGenerator()._build_prompt_with_markdown(cluster, "контекст", markdown)
        md_section = prompt[prompt.find("БРИФ РЕДАКТОРА"):prompt.find("ДАННЫЕ ОБ УСЛУГЕ")]

        assert "УЗНАЁТЕ СЕБЯ" in md_section
        assert "обрезан" in prompt

    @patch("agents.agents.landing_generator.OpenAI")
    def test_prepare_markdown_brief_preserves_late_titles(self, mock_openai_cls):
        """Поздние заголовки секций сохраняются даже при большом markdown."""
        markdown = (
            "## Блок 1\n"
            + ("x" * 9000)
            + "\n\n## [БЛОК 3] УЗНАЁТЕ СЕБЯ?\n"
            + "🤕 Болит поясница\n"
        )
        brief, truncated = LandingPageGenerator()._prepare_markdown_brief_for_prompt(markdown)

        assert truncated is True
        assert "УЗНАЁТЕ СЕБЯ" in brief


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
