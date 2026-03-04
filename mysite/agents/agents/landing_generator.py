"""
LandingPageGenerator — генерация SEO-посадочных страниц через GPT.

Два режима:
  generate_landing(cluster)
      Генерирует страницу только из данных БД.

  generate_from_markdown(cluster, markdown_text)
      Генерирует страницу используя маркдаун как редакторский бриф.
      GPT следует структуре брифа, но цены берёт только из БД.
      Расхождения цен попадают в warnings → payload SeoTask.

Оба метода:
  - Всегда создают LandingPage со status='draft'
  - Не создают дубли (проверяют существующий draft)
  - Создают SeoTask для модератора
  - Отправляют notify_new_landing()

Вызывается вручную или из Celery. НЕ запускается по расписанию сам.
"""
import json
import logging
import re
from collections import Counter

from django.conf import settings
from openai import OpenAI

from agents.models import LandingBlock, LandingPage, SeoKeywordCluster, SeoTask
from agents.telegram import notify_new_landing

logger = logging.getLogger(__name__)


class LandingGeneratorError(Exception):
    """Ошибка генерации посадочной страницы."""


class LandingPageGenerator:
    """
    Генерирует черновик SEO-лендинга для заданного кластера ключевых запросов.

    Гарантии:
    - LandingPage всегда status='draft'
    - Цены — только из БД
    - Дубли не создаются
    """

    MAX_TOKENS = 4000
    MD_PROMPT_MAX_CHARS = 12000
    MD_SECTION_MAX_CHARS = 1400
    BLOCK_STYLE_DEFAULTS = {
        "text": {"css_class": "lb-text"},
        "checklist": {"css_class": "lb-checklist"},
        "identification": {
            "css_class": "lb-identification",
            "bg_color": "#f7fbf8",
            "text_color": "#333333",
        },
        "accent": {
            "css_class": "lb-accent",
            "bg_color": "#9BAE9E",
            "text_color": "#ffffff",
        },
        "cta": {"css_class": "lb-cta"},
        "price_table": {"css_class": "lb-price-table"},
        "accordion": {"css_class": "lb-accordion"},
        "faq": {"css_class": "lb-faq"},
        "special_formats": {"css_class": "lb-special"},
        "subscriptions": {"css_class": "lb-subscriptions"},
        "navigation": {
            "css_class": "lb-navigation",
            "bg_color": "#f5f5f5",
            "text_color": "#333333",
        },
        "html": {"css_class": "lb-html"},
    }

    REQUIRED_JSON_FIELDS = {
        "meta_title", "meta_description", "h1",
        "intro", "how_it_works", "who_is_it_for",
        "contraindications", "results", "faq",
        "cta_text", "internal_links",
    }
    RISKY_CLAIM_PATTERNS = [
        r"\b\d{1,3}\s*%",
        r"\bпосле первого сеанса\b",
        r"\bзаменяют?\b.+\bчас",
    ]
    NON_CONTENT_SECTION_PATTERNS = [
        r"^страница:",
        r"\bмета[-\s]?теги\b",
        r"\bмикроразметка\b",
        r"\bschema\.org\b",
        r"\bbreadcrumb(list)?\b",
        r"\bfaqpage\b",
        r"\bхлебные крошки\b",
        r"\bконтент страницы\b",
        r"\bфото .*(сводка|страницы)\b",
        r"\bключевые запросы\b",
        r"\bпроверка заголовков\b",
        r"\bструктура h[-\s]?тегов\b",
        r"\bтехнические требования\b",
        r"\bзаметки для разработчика\b",
        r"\bseo[-\s]?контрольный список\b",
        r"\bservice\s*\(основная\)\b",
        r"\bвиджет записи\b",
    ]

    def __init__(self):
        self.api_key = (getattr(settings, "OPENAI_API_KEY", "") or "").strip()
        self.client = OpenAI(api_key=self.api_key)
        self.model = settings.OPENAI_MODEL

    # ── Публичные методы ──────────────────────────────────────────────────────

    def generate_landing(self, cluster: SeoKeywordCluster) -> LandingPage:
        """
        Генерирует черновик лендинга из данных БД.

        1. Проверяет дубли (draft для этого кластера уже есть?)
        2. _get_services_context — реальные данные из БД
        3. _build_prompt — промпт «только факты»
        4. GPT → JSON
        5. LandingPage.objects.create(status='draft', source_markdown='')
        6. SeoTask(task_type='create_landing', priority='high')
        7. notify_new_landing()
        8. return landing

        Raises LandingGeneratorError при невалидном JSON или ошибке GPT.
        """
        logger.info(
            "LandingPageGenerator.generate_landing: кластер '%s' (id=%s)",
            cluster.name, cluster.pk,
        )

        existing = LandingPage.objects.filter(
            cluster=cluster,
            status=LandingPage.STATUS_DRAFT,
        ).first()
        existing_draft = None
        if existing:
            if self._landing_has_content(existing):
                logger.info(
                    "generate_landing: черновик уже существует (id=%s), возвращаем его",
                    existing.pk,
                )
                return existing
            logger.info(
                "generate_landing: найден пустой draft (id=%s), перегенерируем в ту же запись",
                existing.pk,
            )
            existing_draft = existing

        services_context = self._get_services_context(cluster)
        prompt = self._build_prompt(cluster, services_context)
        raw_json = self._call_gpt(prompt)
        data = self._parse_gpt_response(raw_json, cluster)

        slug = existing_draft.slug if existing_draft else self._make_slug(cluster)
        if existing_draft:
            landing = existing_draft
            landing.cluster = cluster
            landing.service = self._resolve_service_for_landing(cluster)
            landing.slug = slug
            landing.status = LandingPage.STATUS_DRAFT
            landing.meta_title = data["meta_title"][:70]
            landing.meta_description = data["meta_description"][:160]
            landing.h1 = data["h1"][:200]
            landing.generated_by_agent = True
            landing.source_markdown = ""
            landing.landing_blocks.all().delete()
            landing.save()
        else:
            landing = LandingPage.objects.create(
                cluster=cluster,
                service=self._resolve_service_for_landing(cluster),
                slug=slug,
                status=LandingPage.STATUS_DRAFT,
                meta_title=data["meta_title"][:70],
                meta_description=data["meta_description"][:160],
                h1=data["h1"][:200],
                generated_by_agent=True,
                source_markdown="",
            )
        self._create_landing_blocks(landing, data)
        quality_warnings = self._audit_landing_quality(landing, source_markdown="")
        logger.info(
            "generate_landing: LandingPage создан (id=%s, slug='%s')",
            landing.pk, landing.slug,
        )

        SeoTask.objects.create(
            task_type=SeoTask.TYPE_CREATE_LANDING,
            priority=SeoTask.PRIORITY_HIGH,
            status=SeoTask.STATUS_OPEN,
            title=f"Проверить черновик: {landing.h1}",
            description=(
                f"Агент сгенерировал черновик лендинга для кластера "
                f"'{cluster.name}'. Требует проверки перед публикацией."
                + (
                    f" Обнаружены замечания качества: {'; '.join(quality_warnings)}"
                    if quality_warnings else ""
                )
            ),
            target_url=cluster.target_url,
            payload={
                "landing_id": landing.id,
                "cluster_id": cluster.pk,
                "quality_ok": not quality_warnings,
                "quality_warnings": quality_warnings,
            },
        )

        try:
            notify_new_landing(landing)
        except Exception as exc:
            logger.warning("generate_landing: ошибка уведомления — %s", exc)

        return landing

    def generate_from_markdown(
        self,
        cluster: SeoKeywordCluster,
        markdown_text: str,
    ) -> LandingPage:
        """
        Генерирует черновик лендинга используя маркдаун как редакторский бриф.

        Отличия от generate_landing():
        - markdown_text идёт в промпт как «БРИФ РЕДАКТОРА»
        - GPT следует структуре и смыслам брифа, улучшает SEO
        - Цены — только из БД, даже если в маркдауне другие
        - _check_markdown_vs_db проверяет расхождения → warnings в payload SeoTask
        - source_markdown сохраняется в LandingPage для аудита

        Raises LandingGeneratorError при ошибке GPT или невалидном JSON.
        """
        logger.info(
            "LandingPageGenerator.generate_from_markdown: кластер '%s' (id=%s), "
            "маркдаун %d символов",
            cluster.name, cluster.pk, len(markdown_text),
        )

        existing = LandingPage.objects.filter(
            cluster=cluster,
            status=LandingPage.STATUS_DRAFT,
        ).first()
        existing_draft = None
        if existing:
            if self._landing_has_content(existing):
                logger.info(
                    "generate_from_markdown: черновик уже существует (id=%s)",
                    existing.pk,
                )
                return existing
            logger.info(
                "generate_from_markdown: найден пустой draft (id=%s), перегенерируем в ту же запись",
                existing.pk,
            )
            existing_draft = existing

        services_context = self._get_services_context(cluster)
        section_plan = self._build_markdown_block_plan(markdown_text)
        warnings = self._check_markdown_vs_db(markdown_text, services_context)
        if warnings:
            logger.warning(
                "generate_from_markdown: расхождения маркдауна с БД — %s", warnings
            )

        prompt = self._build_prompt_with_markdown(
            cluster,
            services_context,
            markdown_text,
            section_plan=section_plan,
        )
        raw_json = self._call_gpt(prompt)
        data = self._parse_gpt_response(raw_json, cluster)

        slug = existing_draft.slug if existing_draft else self._make_slug(cluster)
        if existing_draft:
            landing = existing_draft
            landing.cluster = cluster
            landing.service = self._resolve_service_for_landing(cluster)
            landing.slug = slug
            landing.status = LandingPage.STATUS_DRAFT
            landing.meta_title = data["meta_title"][:70]
            landing.meta_description = data["meta_description"][:160]
            landing.h1 = data["h1"][:200]
            landing.generated_by_agent = True
            landing.source_markdown = markdown_text
            landing.landing_blocks.all().delete()
            landing.save()
        else:
            landing = LandingPage.objects.create(
                cluster=cluster,
                service=self._resolve_service_for_landing(cluster),
                slug=slug,
                status=LandingPage.STATUS_DRAFT,
                meta_title=data["meta_title"][:70],
                meta_description=data["meta_description"][:160],
                h1=data["h1"][:200],
                generated_by_agent=True,
                source_markdown=markdown_text,
            )
        self._create_landing_blocks(
            landing,
            data,
            markdown_text=markdown_text,
            section_plan=section_plan,
        )
        quality_warnings = self._audit_landing_quality(
            landing,
            source_markdown=markdown_text,
            extra_warnings=warnings,
        )
        logger.info(
            "generate_from_markdown: LandingPage создан (id=%s, slug='%s')",
            landing.pk, landing.slug,
        )

        SeoTask.objects.create(
            task_type=SeoTask.TYPE_CREATE_LANDING,
            priority=SeoTask.PRIORITY_HIGH,
            status=SeoTask.STATUS_OPEN,
            title=f"Проверить черновик (из маркдауна): {landing.h1}",
            description=(
                f"Агент сгенерировал черновик на основе маркдауна "
                f"для кластера '{cluster.name}'."
                + (
                    f" Расхождения с БД: {'; '.join(warnings)}"
                    if warnings else ""
                )
                + (
                    f" Замечания качества: {'; '.join(quality_warnings)}"
                    if quality_warnings else ""
                )
            ),
            target_url=cluster.target_url,
            payload={
                "landing_id": landing.id,
                "cluster_id": cluster.pk,
                "source":     "markdown",
                "warnings":   warnings,
                "quality_ok": not quality_warnings,
                "quality_warnings": quality_warnings,
            },
        )

        try:
            notify_new_landing(landing)
        except Exception as exc:
            logger.warning("generate_from_markdown: ошибка уведомления — %s", exc)

        return landing

    def audit_existing_landing(self, landing: LandingPage) -> list[str]:
        """Public quality audit entrypoint for admin workflows."""
        return self._audit_landing_quality(
            landing,
            source_markdown=landing.source_markdown or "",
            extra_warnings=[],
        )

    def _landing_has_content(self, landing: LandingPage) -> bool:
        """Return True if draft has meaningful generated content."""
        if (landing.source_markdown or "").strip():
            return True
        return landing.landing_blocks.filter(is_active=True).exists()

    # ── Вспомогательные методы ────────────────────────────────────────────────

    def _get_services_context(self, cluster: SeoKeywordCluster) -> str:
        """
        Собирает реальные данные об услугах из БД для промпта GPT.

        Приоритет:
        1. cluster.service_category → Service.objects.filter(category=...)
        2. cluster.service_slug → Service.objects.get(slug=...)
        3. Ничего не найдено → «НУЖНО УТОЧНИТЬ»

        Если цен нет → явно пишет «НУЖНО УТОЧНИТЬ: цены не заданы».
        """
        from services_app.models import Service

        lines = []
        lines.append(f"Кластер: {cluster.name}")
        lines.append(f"Гео: {cluster.geo}")
        lines.append(f"Ключевые запросы: {', '.join(cluster.keywords[:10])}")
        lines.append(f"Целевой URL: {cluster.target_url}")

        if cluster.service_category:
            lines.append(f"\nКатегория услуг: {cluster.service_category.name}")
            if cluster.service_category.description:
                lines.append(
                    f"Описание категории: {cluster.service_category.description[:300]}"
                )

            services = list(
                Service.objects.filter(
                    category=cluster.service_category,
                    is_active=True,
                ).prefetch_related("options")[:10]
            )

            if services:
                lines.append("\nУСЛУГИ (реальные данные из БД):")
                for svc in services:
                    lines.append(f"\n\u2022 {svc.name}")
                    if svc.description:
                        lines.append(f"  Описание: {svc.description[:200]}")

                    options = list(
                        svc.options.filter(is_active=True).order_by("order")[:5]
                    )
                    if options:
                        lines.append("  Варианты:")
                        for opt in options:
                            unit_label = opt.get_unit_type_display()
                            pkg = (
                                f"{opt.units} {unit_label}"
                                if opt.units > 1
                                else f"{opt.duration_min} мин"
                            )
                            lines.append(f"    \u2013 {pkg}: {int(opt.price)} руб.")
                    else:
                        if svc.price_from:
                            lines.append(f"  Цена от: {int(svc.price_from)} руб.")
                        elif svc.price:
                            lines.append(f"  Цена: {int(svc.price)} руб.")
                        else:
                            lines.append(
                                "  НУЖНО УТОЧНИТЬ: цены не заданы в системе"
                            )

                    if svc.duration_min:
                        lines.append(f"  Длительность: {svc.duration_min} мин")
            else:
                lines.append(
                    "\nНУЖНО УТОЧНИТЬ: услуги для этой категории не найдены в БД"
                )

        elif cluster.service_slug:
            try:
                svc = Service.objects.prefetch_related("options").get(
                    slug=cluster.service_slug, is_active=True
                )
                lines.append(f"\nУслуга: {svc.name}")
                if svc.description:
                    lines.append(f"Описание: {svc.description[:300]}")
                options = list(svc.options.filter(is_active=True)[:5])
                if options:
                    lines.append("Варианты:")
                    for opt in options:
                        pkg = (
                            f"{opt.units} {opt.get_unit_type_display()}"
                            if opt.units > 1
                            else f"{opt.duration_min} мин"
                        )
                        lines.append(f"  \u2013 {pkg}: {int(opt.price)} руб.")
                else:
                    lines.append(
                        "НУЖНО УТОЧНИТЬ: варианты и цены не заданы в системе"
                    )
            except Service.DoesNotExist:
                lines.append(
                    f"\nНУЖНО УТОЧНИТЬ: услуга с slug='{cluster.service_slug}' "
                    f"не найдена в БД"
                )
        else:
            lines.append(
                "\nНУЖНО УТОЧНИТЬ: категория и slug услуги не заданы для кластера"
            )

        return "\n".join(lines)

    def _resolve_service_for_landing(self, cluster: SeoKeywordCluster):
        """Определяет базовую услугу для лендинга (для наследования медиа)."""
        from services_app.models import Service

        if cluster.service_slug:
            service = (
                Service.objects.filter(slug=cluster.service_slug, is_active=True)
                .order_by("id")
                .first()
            )
            if service:
                return service

        if cluster.service_category:
            return (
                Service.objects.filter(category=cluster.service_category, is_active=True)
                .order_by("order", "name", "id")
                .first()
            )
        return None

    def _create_landing_blocks(
        self,
        landing: LandingPage,
        data: dict,
        markdown_text: str = "",
        section_plan: list[tuple] | None = None,
    ) -> None:
        """Создает LandingBlock записи на основе JSON-ответа GPT."""
        faq_items = data.get("faq") or []
        internal_links = data.get("internal_links") or []
        faq_content = "\n---\n".join(
            f"{item.get('question', '').strip()}\n{item.get('answer', '').strip()}"
            for item in faq_items
            if item.get("question")
        )
        nav_content = "\n".join(str(slug).strip().strip("/") for slug in internal_links if slug)

        block_rows = [
            ("text", "О процедуре", data.get("intro", ""), 10, {}),
            ("checklist", "Как проходит процедура", data.get("how_it_works", ""), 20, {}),
            ("checklist", "Кому подходит", data.get("who_is_it_for", ""), 30, {}),
            ("checklist", "Противопоказания", data.get("contraindications", ""), 40, {}),
            ("text", "Результат", data.get("results", ""), 50, {}),
            ("faq", "Частые вопросы", faq_content, 60, {}),
            ("cta", "Запись", "", 70, {"btn_text": "Записаться онлайн", "btn_sub": data.get("cta_text", "")}),
            ("navigation", "Похожие процедуры", nav_content, 80, {}),
        ]
        if section_plan:
            block_rows = self._apply_gpt_improvements_to_plan(section_plan, data)
            block_rows = self._apply_cta_positioning(block_rows, data)
        elif markdown_text:
            block_rows.extend(self._contract_blocks_from_markdown(markdown_text, block_rows))

        to_create = []
        for block_type, title, content, order, extra in block_rows:
            has_content = bool(str(content or "").strip())
            has_extra = bool(str(extra.get("btn_sub", "")).strip() or str(extra.get("btn_text", "")).strip())
            if not has_content and not has_extra:
                continue
            styled_extra = self._merge_block_style_defaults(block_type, extra)
            to_create.append(
                LandingBlock(
                    landing_page=landing,
                    block_type=block_type,
                    title=title,
                    heading_level="h2",
                    content=content or "",
                    order=order,
                    is_active=True,
                    **styled_extra,
                )
            )

        if to_create:
            LandingBlock.objects.bulk_create(to_create)

    def _build_markdown_block_plan(self, markdown_text: str) -> list[tuple]:
        """
        Stage A: deterministic block plan from markdown sections.
        GPT should not change this structure later.
        """
        sections = self._extract_markdown_sections(markdown_text)
        rows = []
        order = 10
        for section in sections:
            title = (section.get("title") or "").strip()
            content = (section.get("content") or "").strip()
            block_type = section.get("block_type") or "text"
            if not title and not content:
                continue
            if self._should_skip_section(title, content, block_type):
                continue

            extra = {}
            if block_type == "cta":
                title = "Запись"
                extra = {"btn_text": "Записаться онлайн", "btn_sub": content[:200]}
                content = ""

            rows.append((block_type, title[:200], content, order, extra))
            order += 10
        return rows

    def _apply_gpt_improvements_to_plan(self, section_plan: list[tuple], data: dict) -> list[tuple]:
        """
        Stage B: improve text inside planned sections without changing block set.
        """
        faq_items = data.get("faq") or []
        faq_content = "\n---\n".join(
            f"{item.get('question', '').strip()}\n{item.get('answer', '').strip()}"
            for item in faq_items
            if item.get("question")
        )
        nav_content = "\n".join(
            str(slug).strip().strip("/")
            for slug in (data.get("internal_links") or [])
            if slug
        )

        improved = []
        for block_type, title, content, order, extra in section_plan:
            title_lower = (title or "").lower()
            new_content = content
            new_extra = dict(extra or {})

            if block_type == "faq" and faq_content:
                new_content = self._prefer_markdown_when_emoji_lost(content, faq_content)
            elif block_type == "navigation" and nav_content:
                new_content = nav_content
            elif block_type == "cta":
                if data.get("cta_text"):
                    new_extra["btn_sub"] = self._prefer_markdown_when_emoji_lost(
                        new_extra.get("btn_sub", ""),
                        data["cta_text"],
                    )
            elif block_type == "checklist":
                if "противопоказ" in title_lower and data.get("contraindications"):
                    new_content = self._prefer_markdown_when_emoji_lost(
                        content,
                        data["contraindications"],
                    )
                elif "как проходит" in title_lower and data.get("how_it_works"):
                    new_content = self._prefer_markdown_when_emoji_lost(
                        content,
                        data["how_it_works"],
                    )
                elif "кому подходит" in title_lower and data.get("who_is_it_for"):
                    new_content = self._prefer_markdown_when_emoji_lost(
                        content,
                        data["who_is_it_for"],
                    )
            elif block_type == "identification":
                # Preserve original markdown meaning for self-identification section.
                new_content = content
            elif block_type == "text":
                if "результат" in title_lower and data.get("results"):
                    new_content = self._prefer_markdown_when_emoji_lost(
                        content,
                        data["results"],
                    )
                elif data.get("intro") and content:
                    new_content = self._prefer_markdown_when_emoji_lost(
                        content,
                        data["intro"],
                    )
            new_content = self._dedupe_text_content(new_content)

            improved.append((block_type, title, new_content, order, new_extra))
        return improved

    def _apply_cta_positioning(self, rows: list[tuple], data: dict) -> list[tuple]:
        """
        Ensure CTA appears in the conversion flow:
        - after a key section (middle CTA);
        - final CTA at the end.
        """
        if not rows:
            return [self._make_cta_row(data.get("cta_text", ""), 10)]

        planned = [(bt, t, c, o, dict(e or {})) for bt, t, c, o, e in rows]
        cta_text = (data.get("cta_text") or "").strip()

        has_middle_cta = any(
            bt == "cta" and idx not in (0, len(planned) - 1)
            for idx, (bt, _t, _c, _o, _e) in enumerate(planned)
        )
        if not has_middle_cta:
            anchor_idx = self._find_mid_cta_anchor(planned)
            if anchor_idx is not None:
                planned.insert(anchor_idx + 1, self._make_cta_row(cta_text, 0))

        if planned[-1][0] != "cta":
            planned.append(self._make_cta_row(cta_text, 0))

        reindexed = []
        for idx, (bt, t, c, _o, e) in enumerate(planned, start=1):
            reindexed.append((bt, t, c, idx * 10, e))
        return reindexed

    def _merge_block_style_defaults(self, block_type: str, extra: dict) -> dict:
        """Apply style defaults while preserving explicit block settings."""
        merged = dict(self.BLOCK_STYLE_DEFAULTS.get(block_type, {}))
        for key, value in (extra or {}).items():
            if value in (None, "") and key in {"css_class", "bg_color", "text_color"}:
                continue
            merged[key] = value
        return merged

    def _find_mid_cta_anchor(self, rows: list[tuple]) -> int | None:
        """Pick the first meaningful section where middle CTA should be inserted."""
        for idx, (block_type, title, _content, _order, _extra) in enumerate(rows):
            title_lower = (title or "").lower()
            if block_type in {"identification", "checklist"}:
                return idx
            if block_type == "text" and (
                "результат" in title_lower
                or "кому подходит" in title_lower
                or "как проходит" in title_lower
            ):
                return idx
        return None

    def _make_cta_row(self, cta_text: str, order: int) -> tuple:
        """Create canonical CTA row."""
        return (
            "cta",
            "Запись",
            "",
            order,
            {
                "btn_text": "Записаться онлайн",
                "btn_sub": cta_text,
            },
        )

    def _prefer_markdown_when_emoji_lost(self, markdown_text: str, gpt_text: str) -> str:
        """
        Keep markdown text if it has emoji and GPT variant removes them.
        """
        left = (markdown_text or "").strip()
        right = (gpt_text or "").strip()
        if not right:
            return left
        if self._contains_emoji(left) and not self._contains_emoji(right):
            return left
        return right

    def _contains_emoji(self, text: str) -> bool:
        """Heuristic emoji detector."""
        if not text:
            return False
        for ch in text:
            code = ord(ch)
            if (
                0x1F300 <= code <= 0x1FAFF
                or 0x2600 <= code <= 0x27BF
                or 0xFE00 <= code <= 0xFE0F
            ):
                return True
        return False

    def _dedupe_text_content(self, text: str) -> str:
        """Remove obvious duplicate lines in generated content."""
        lines = [line.rstrip() for line in (text or "").splitlines()]
        seen = set()
        kept = []
        for line in lines:
            key = re.sub(r"\s+", " ", line).strip().lower()
            if not key:
                kept.append(line)
                continue
            if key in seen:
                continue
            seen.add(key)
            kept.append(line)
        return "\n".join(kept).strip()

    def _contract_blocks_from_markdown(self, markdown_text: str, existing_rows: list[tuple]) -> list[tuple]:
        """
        Контрактная привязка секций markdown к типам LandingBlock.

        На первом шаге добавляет отсутствующий блок identification
        (например, секция "[БЛОК 3] Узнаёте себя?").
        """
        existing_keys = {
            (row[0], (row[1] or "").strip().lower())
            for row in existing_rows
        }
        next_order = max((row[3] for row in existing_rows), default=0) + 10
        rows = []

        for section in self._extract_markdown_sections(markdown_text):
            block_type = section["block_type"]
            if block_type != "identification":
                continue

            title = (section["title"] or "").strip() or "Узнаёте себя?"
            content = (section["content"] or "").strip()
            if not content:
                continue

            key = (block_type, title.lower())
            if key in existing_keys:
                continue

            rows.append((block_type, title, content, next_order, {}))
            existing_keys.add(key)
            next_order += 10

        return rows

    def _extract_markdown_sections(self, markdown_text: str) -> list[dict]:
        """Делит markdown на секции и определяет контрактный тип блока для каждой."""
        sections = []
        current_heading = None
        current_lines: list[str] = []
        preface_lines: list[str] = []

        def flush():
            if not current_heading:
                return
            title, content = self._normalize_markdown_section(current_heading, current_lines)
            if not title and not content:
                return
            sections.append(
                {
                    "title": title,
                    "content": content,
                    "block_type": self._map_markdown_section_to_block_type(title, content),
                }
            )

        for raw_line in (markdown_text or "").splitlines():
            match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", raw_line)
            if match:
                if current_heading is None and preface_lines:
                    sections.append(
                        {
                            "title": "Введение",
                            "content": "\n".join(preface_lines).strip(),
                            "block_type": "text",
                        }
                    )
                    preface_lines = []
                flush()
                current_heading = match.group(1).strip()
                current_lines = []
                continue
            if current_heading is not None:
                current_lines.append(raw_line)
            else:
                preface_lines.append(raw_line)

        if current_heading is None and preface_lines:
            sections.append(
                {
                    "title": "Введение",
                    "content": "\n".join(preface_lines).strip(),
                    "block_type": "text",
                }
            )
        flush()
        return sections

    def _normalize_markdown_section(self, heading: str, lines: list[str]) -> tuple[str, str]:
        """Очищает заголовок/контент секции markdown от служебных маркеров."""
        title = re.sub(r"^\s*\[\s*блок\s*\d+\s*\]\s*", "", heading, flags=re.IGNORECASE).strip()
        title = re.sub(r"^\s*\[(.*?)\]\s*$", r"\1", title).strip()
        title = title.strip("*_` ").strip()

        cleaned_lines = []
        h2_override = None
        for line in lines:
            if self._is_media_instruction_line(line):
                continue
            h2_match = re.match(r"^\s*\*\*H2:\*\*\s*(.+?)\s*$", line, flags=re.IGNORECASE)
            if h2_match:
                h2_override = h2_match.group(1).strip()
                continue
            cleaned_lines.append(line.rstrip())

        if h2_override:
            title = h2_override

        content = "\n".join(cleaned_lines).strip()
        return title, content

    def _should_skip_section(self, title: str, content: str, block_type: str) -> bool:
        """Hard filter for non-content sections from SEO/spec markdown."""
        haystack = f"{title}\n{content}".lower()
        if any(re.search(p, haystack, flags=re.IGNORECASE) for p in self.NON_CONTENT_SECTION_PATTERNS):
            return True
        if "<meta " in haystack or "@context" in haystack or "@type" in haystack:
            return True
        if "```json" in haystack and ("schema" in haystack or "@context" in haystack):
            return True
        if block_type == "faq" and "вопрос" not in haystack and "?" not in haystack:
            # prevent technical checklists from becoming faq blocks
            return True
        return False

    def _is_media_instruction_line(self, line: str) -> bool:
        """Filter out technical media notes from content sections."""
        txt = (line or "").strip().lower()
        if not txt:
            return False
        markers = (
            "📸",
            "тип а:",
            "тип б:",
            "alt:",
            "размер:",
            "загрузка:",
            "og-картинка",
            "место на странице",
        )
        return any(m in txt for m in markers)

    def _map_markdown_section_to_block_type(self, title: str, content: str) -> str:
        """Контрактный маппинг секции markdown -> block_type."""
        haystack = f"{title}\n{content}".lower()
        title_l = (title or "").lower()
        content_l = (content or "").lower()

        if "узна" in haystack and "себ" in haystack:
            return "identification"
        if "faq" in haystack or "частые вопросы" in haystack:
            return "faq"
        if "cta" in haystack or "запиш" in haystack:
            return "cta"
        if "противопоказ" in haystack or "кому подходит" in haystack or "как проходит" in haystack:
            return "checklist"
        if (
            "стоимост" in title_l
            or "цены" in title_l
            or "прайс" in title_l
            or ("|" in content and "₽" in content)
            or ("```" in content_l and "₽" in content_l)
        ):
            return "price_table"
        if "навигац" in haystack or "похожие" in haystack:
            return "navigation"
        return "text"

    def _build_prompt(self, cluster: SeoKeywordCluster, services_context: str) -> str:
        """
        Промпт для generate_landing — только факты из БД, без брифа.
        """
        geo = cluster.geo or "Пенза"
        keywords_str = ", ".join(cluster.keywords[:8])

        return (
            f"Ты SEO-копирайтер салона красоты \u00abФормула тела\u00bb в городе {geo}.\n"
            f"Создай SEO-лендинг для страницы: {cluster.target_url}\n\n"

            f"ДАННЫЕ ОБ УСЛУГЕ (используй ТОЛЬКО эти факты):\n"
            f"{services_context}\n\n"

            f"КЛЮЧЕВЫЕ ЗАПРОСЫ (вписывай органично):\n{keywords_str}\n\n"

            "ТРЕБОВАНИЯ К КОНТЕНТУ:\n"
            "1. meta_title: до 60 символов, ключ + город\n"
            "2. meta_description: до 160 символов, ключ + CTA\n"
            "3. h1: естественный заголовок с ключом, не копируй meta_title\n"
            "4. intro: 2-3 абзаца: боль \u2192 решение \u2192 почему Формула тела\n"
            "5. how_it_works: 3-5 конкретных шагов процедуры\n"
            "6. who_is_it_for: список кому подходит (4-6 пунктов)\n"
            "7. contraindications: список противопоказаний (3-5 пунктов)\n"
            "8. results: результат через N сеансов \u2014 ТОЛЬКО если есть данные\n"
            "9. faq: ровно 8-10 вопросов/ответов, реальные вопросы клиентов\n"
            "10. cta_text: призыв к записи (1-2 предложения)\n"
            "11. internal_links: slug\u2019и 2-3 связанных услуг\n\n"

            "СТРОГИЕ ПРАВИЛА:\n"
            "- Если цены не указаны \u2192 пиши 'НУЖНО УТОЧНИТЬ: цена'\n"
            "- Не выдумывай цены, сроки, количество процедур\n"
            "- Не используй шаблонные фразы вроде 'высококвалифицированные специалисты'\n"
            "- Пиши живым языком\n\n"

            "Отвечай СТРОГО валидным JSON без markdown:\n"
            "{\n"
            '  "meta_title": "до 60 символов",\n'
            '  "meta_description": "до 160 символов",\n'
            '  "h1": "заголовок",\n'
            '  "intro": "2-3 абзаца через \\n\\n",\n'
            '  "how_it_works": "шаги через \\n",\n'
            '  "who_is_it_for": "список через \\n",\n'
            '  "contraindications": "список через \\n",\n'
            '  "results": "текст или НУЖНО УТОЧНИТЬ",\n'
            '  "faq": [{"question": "...", "answer": "..."}, ...],\n'
            '  "cta_text": "призыв к записи",\n'
            '  "internal_links": ["slug1", "slug2"]\n'
            "}"
        )

    def _build_prompt_with_markdown(
        self,
        cluster: SeoKeywordCluster,
        services_context: str,
        markdown_text: str,
        section_plan: list[tuple] | None = None,
    ) -> str:
        """
        Промпт для generate_from_markdown — маркдаун как «БРИФ РЕДАКТОРА».

        Маркдаун обрезается до 3000 символов (~750 токенов) чтобы не
        превысить контекстное окно вместе с services_context и JSON-схемой.
        Цены — только из блока ДАННЫЕ ОБ УСЛУГЕ, даже если в брифе другие.
        """
        geo = cluster.geo or "Пенза"
        keywords_str = ", ".join(cluster.keywords[:8])

        md_truncated, markdown_is_truncated = self._prepare_markdown_brief_for_prompt(markdown_text)
        truncation_note = ""
        if markdown_is_truncated:
            truncation_note = (
                "\nПримечание: исходный markdown сокращен по секциям и лимитам, "
                "но структура заголовков сохранена.\n"
            )
        section_plan_text = self._format_section_plan_for_prompt(section_plan or [])

        return (
            f"Ты SEO-копирайтер салона красоты \u00abФормула тела\u00bb в городе {geo}.\n"
            f"Создай SEO-лендинг для страницы: {cluster.target_url}\n\n"

            f"БРИФ РЕДАКТОРА (используй как основу структуры и смыслов):\n"
            f"---\n"
            f"{md_truncated}\n"
            f"---\n"
            f"{truncation_note}\n"
            f"FIXED SECTION PLAN (do not add/remove sections, only improve wording):\n"
            f"{section_plan_text}\n\n"

            f"ДАННЫЕ ОБ УСЛУГЕ из БД (ЦЕНЫ ТОЛЬКО ОТСЮДА \u2014 не из брифа):\n"
            f"{services_context}\n\n"

            f"КЛЮЧЕВЫЕ ЗАПРОСЫ (вписывай органично):\n{keywords_str}\n\n"

            "ИНСТРУКЦИИ:\n"
            "1. Следуй структуре и смыслам из брифа редактора\n"
            "2. meta_title, meta_description, h1 \u2014 генерируй сам с учётом SEO\n"
            "3. meta_title: до 60 символов, ключ + город\n"
            "4. meta_description: до 160 символов, ключ + CTA\n"
            "5. ЦЕНЫ \u2014 только из блока 'ДАННЫЕ ОБ УСЛУГЕ'.\n"
            "   Если в брифе другие цены \u2014 игнорируй их\n"
            "6. Если цен в БД нет \u2014 пиши 'НУЖНО УТОЧНИТЬ: цена'\n"
            "7. faq: 8-10 вопросов, можешь брать из брифа или дополнять\n"
            "8. Улучшай SEO-формулировки брифа, но не меняй факты\n"
            "9. Не меняй структуру секций из FIXED SECTION PLAN\n\n"
            "10. Не удаляй эмодзи из секций markdown: сохраняй их в итоговом тексте\n\n"

            "Отвечай СТРОГО валидным JSON без markdown:\n"
            "{\n"
            '  "meta_title": "до 60 символов",\n'
            '  "meta_description": "до 160 символов",\n'
            '  "h1": "заголовок",\n'
            '  "intro": "2-3 абзаца",\n'
            '  "how_it_works": "шаги",\n'
            '  "who_is_it_for": "список",\n'
            '  "contraindications": "список",\n'
            '  "results": "текст",\n'
            '  "faq": [{"question": "...", "answer": "..."}],\n'
            '  "cta_text": "призыв",\n'
            '  "internal_links": ["slug1"]\n'
            "}"
        )

    def _prepare_markdown_brief_for_prompt(self, markdown_text: str) -> tuple[str, bool]:
        """
        Готовит markdown-бриф для GPT без потери структуры секций.

        Вместо жесткого среза по первым N символам:
        - оставляет заголовки всех секций;
        - ограничивает объём контента каждой секции;
        - ограничивает общий объём брифа.
        """
        raw = (markdown_text or "").strip()
        if not raw:
            return "", False

        sections = self._extract_markdown_sections(raw)
        if not sections:
            if len(raw) <= self.MD_PROMPT_MAX_CHARS:
                return raw, False
            return (
                raw[: self.MD_PROMPT_MAX_CHARS].rstrip()
                + "\n\n[...бриф обрезан до лимита символов...]",
                True,
            )

        truncated = False
        parts = []
        used = 0

        for i, section in enumerate(sections, start=1):
            title = (section.get("title") or f"Секция {i}").strip()
            content = (section.get("content") or "").strip()

            if len(content) > self.MD_SECTION_MAX_CHARS:
                content = (
                    content[: self.MD_SECTION_MAX_CHARS].rstrip()
                    + "\n\n[...секция обрезана до лимита...]"
                )
                truncated = True

            chunk = f"### {title}\n{content}\n\n"
            if used + len(chunk) <= self.MD_PROMPT_MAX_CHARS:
                parts.append(chunk)
                used += len(chunk)
                continue

            truncated = True
            tail_titles = [
                (s.get("title") or f"Секция {idx}").strip()
                for idx, s in enumerate(sections[i - 1 :], start=i)
            ]
            if tail_titles:
                rest = "Оставшиеся секции: " + "; ".join(tail_titles)
                placeholder = (
                    f"[...часть контента пропущена из-за лимита...]\n{rest}\n"
                )
                remaining = self.MD_PROMPT_MAX_CHARS - used
                if remaining > 32:
                    parts.append(placeholder[:remaining].rstrip() + "\n")
            break

        brief = "".join(parts).strip()
        return brief, truncated

    def _audit_landing_quality(
        self,
        landing: LandingPage,
        source_markdown: str,
        extra_warnings: list[str] | None = None,
    ) -> list[str]:
        """Quality gate checks for generated landing."""
        warnings = list(extra_warnings or [])
        blocks = list(landing.landing_blocks.filter(is_active=True).order_by("order"))
        if not blocks:
            warnings.append("Страница не содержит активных блоков.")
            return sorted(set(warnings))

        block_types = [b.block_type for b in blocks]
        if "faq" not in block_types:
            warnings.append("Отсутствует FAQ блок.")
        if "cta" not in block_types:
            warnings.append("Отсутствует CTA блок.")

        cta_count = sum(1 for t in block_types if t == "cta")
        if cta_count < 2:
            warnings.append("Недостаточно CTA блоков (рекомендуется минимум 2).")

        md_required_h2 = self._extract_required_h2_from_markdown(source_markdown)
        if md_required_h2:
            page_h2 = {(b.title or "").strip().lower() for b in blocks if (b.title or "").strip()}
            missing_h2 = [h for h in md_required_h2 if h.lower() not in page_h2]
            if missing_h2:
                warnings.append(f"Не все обязательные H2 из markdown перенесены: {missing_h2[:5]}")

        dupes = self._find_duplicate_paragraphs(blocks)
        if dupes:
            warnings.append(f"Обнаружены дубли абзацев: {dupes[:3]}")

        risky = self._find_risky_claims(blocks)
        if risky:
            warnings.append(f"Есть рискованные/неподтвержденные claims: {risky[:3]}")

        return sorted(set(warnings))

    def _extract_required_h2_from_markdown(self, markdown_text: str) -> list[str]:
        """Extract expected H2 titles from markdown for structure checks."""
        if not markdown_text:
            return []
        h2 = []
        for line in markdown_text.splitlines():
            m = re.match(r"^\s{0,3}##\s+(.+?)\s*$", line)
            if not m:
                continue
            title = re.sub(r"^\[\s*блок\s*\d+\s*\]\s*", "", m.group(1), flags=re.IGNORECASE).strip(" *_`")
            if title:
                h2.append(title)
        return h2

    def _find_duplicate_paragraphs(self, blocks: list[LandingBlock]) -> list[str]:
        """Find repeated long paragraphs across blocks."""
        paragraphs = []
        for b in blocks:
            for para in re.split(r"\n\s*\n", b.content or ""):
                cleaned = re.sub(r"\s+", " ", para).strip()
                if len(cleaned) >= 120:
                    paragraphs.append(cleaned.lower())
        counts = Counter(paragraphs)
        return [p[:80] + "..." for p, n in counts.items() if n > 1]

    def _find_risky_claims(self, blocks: list[LandingBlock]) -> list[str]:
        """Detect risky factual claims that should be manually reviewed."""
        snippets = []
        for b in blocks:
            text = f"{b.title or ''}\n{b.content or ''}"
            lower = text.lower()
            for pattern in self.RISKY_CLAIM_PATTERNS:
                m = re.search(pattern, lower)
                if m:
                    start = max(0, m.start() - 20)
                    end = min(len(text), m.end() + 20)
                    snippets.append(text[start:end].strip())
                    break
        return snippets

    def _format_section_plan_for_prompt(self, section_plan: list[tuple]) -> str:
        """Serialize section plan for prompt."""
        if not section_plan:
            return "- sections are not defined"
        lines = []
        for block_type, title, content, order, _extra in section_plan:
            content_preview = (content or "").replace("\n", " ").strip()
            if len(content_preview) > 120:
                content_preview = content_preview[:120].rstrip() + "..."
            lines.append(
                f"- order={order}; type={block_type}; title={title or 'без заголовка'}; content={content_preview}"
            )
        return "\n".join(lines)

    def _call_gpt(self, prompt: str) -> str:
        """
        Вызывает GPT с response_format=json_object.
        Raises LandingGeneratorError при ошибке API.
        """
        if not self.api_key:
            raise LandingGeneratorError(
                "OPENAI_API_KEY не настроен. Добавьте ключ в переменные окружения "
                "контейнера `web` и перезапустите его."
            )
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты SEO-копирайтер. "
                            "Отвечай ТОЛЬКО валидным JSON без markdown-обёртки."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
                max_tokens=self.MAX_TOKENS,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            raise LandingGeneratorError(f"GPT API error: {exc}") from exc

    def _parse_gpt_response(self, raw_json: str, cluster: SeoKeywordCluster) -> dict:
        """
        Парсит и валидирует JSON от GPT.
        Raises LandingGeneratorError при невалидном JSON или отсутствии полей.
        """
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise LandingGeneratorError(
                f"GPT вернул невалидный JSON для кластера '{cluster.name}': {exc}\n"
                f"Сырой ответ: {raw_json[:500]}"
            ) from exc

        missing = self.REQUIRED_JSON_FIELDS - set(data.keys())
        if missing:
            raise LandingGeneratorError(
                f"GPT не вернул обязательные поля {missing} "
                f"для кластера '{cluster.name}'"
            )

        if not isinstance(data.get("faq"), list):
            data["faq"] = []
        if not isinstance(data.get("internal_links"), list):
            data["internal_links"] = []

        return data

    def _check_markdown_vs_db(
        self,
        markdown_text: str,
        services_context: str,
    ) -> list[str]:
        """
        Проверяет расхождения цен/чисел между маркдауном и БД.

        Эвристика (не парсер): ищет числа от 100 до 99999 в маркдауне,
        сравнивает с числами из services_context. Возвращает список
        строк-предупреждений. Пустой список = расхождений нет.
        """
        import re

        md_numbers = set()
        for m in re.finditer(r"\b\d[\d\s\u00a0]{2,6}\b", markdown_text):
            try:
                n = int(m.group().replace(" ", "").replace("\u00a0", ""))
                if 100 <= n <= 99999:
                    md_numbers.add(n)
            except ValueError:
                pass

        if not md_numbers:
            return []

        db_numbers = set(
            int(m.group())
            for m in re.finditer(r"\b\d{3,5}\b", services_context)
        )

        db_has_prices = bool(db_numbers) and "НУЖНО УТОЧНИТЬ" not in services_context

        warnings = []
        if db_has_prices:
            suspicious = md_numbers - db_numbers
            if suspicious:
                warnings.append(
                    f"Цены/числа в маркдауне не совпадают с БД: "
                    f"{sorted(suspicious)}. Проверьте актуальность данных."
                )
        else:
            warnings.append(
                "Маркдаун содержит числа (возможно цены), "
                "но в БД цены не заданы. Убедитесь что данные актуальны."
            )

        return warnings

    def _make_slug(self, cluster: SeoKeywordCluster) -> str:
        """
        Генерирует уникальный slug из cluster.target_url.
        Если занят — добавляет суффикс -v2, -v3 (до -v10), затем -<pk>.
        """
        base = cluster.target_url.strip("/").replace("/", "-")
        if not base:
            base = cluster.service_slug or f"landing-{cluster.pk}"

        slug = base
        attempt = 2
        while LandingPage.objects.filter(slug=slug).exists():
            slug = f"{base}-v{attempt}"
            attempt += 1
            if attempt > 10:
                slug = f"{base}-{cluster.pk}"
                break

        return slug
