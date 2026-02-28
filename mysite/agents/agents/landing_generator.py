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

from django.conf import settings
from openai import OpenAI

from agents.models import LandingPage, SeoKeywordCluster, SeoTask
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

    REQUIRED_JSON_FIELDS = {
        "meta_title", "meta_description", "h1",
        "intro", "how_it_works", "who_is_it_for",
        "contraindications", "results", "faq",
        "cta_text", "internal_links",
    }

    def __init__(self):
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
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
        if existing:
            logger.info(
                "generate_landing: черновик уже существует (id=%s), возвращаем его",
                existing.pk,
            )
            return existing

        services_context = self._get_services_context(cluster)
        prompt = self._build_prompt(cluster, services_context)
        raw_json = self._call_gpt(prompt)
        data = self._parse_gpt_response(raw_json, cluster)

        slug = self._make_slug(cluster)
        landing = LandingPage.objects.create(
            cluster=cluster,
            slug=slug,
            status=LandingPage.STATUS_DRAFT,
            meta_title=data["meta_title"][:70],
            meta_description=data["meta_description"][:160],
            h1=data["h1"][:200],
            blocks={
                "intro":             data.get("intro", ""),
                "how_it_works":      data.get("how_it_works", ""),
                "who_is_it_for":     data.get("who_is_it_for", ""),
                "contraindications": data.get("contraindications", ""),
                "results":           data.get("results", ""),
                "faq":               data.get("faq", []),
                "cta_text":          data.get("cta_text", ""),
                "internal_links":    data.get("internal_links", []),
            },
            generated_by_agent=True,
            source_markdown="",
        )
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
            ),
            target_url=cluster.target_url,
            payload={"landing_id": landing.id, "cluster_id": cluster.pk},
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
        if existing:
            logger.info(
                "generate_from_markdown: черновик уже существует (id=%s)",
                existing.pk,
            )
            return existing

        services_context = self._get_services_context(cluster)
        warnings = self._check_markdown_vs_db(markdown_text, services_context)
        if warnings:
            logger.warning(
                "generate_from_markdown: расхождения маркдауна с БД — %s", warnings
            )

        prompt = self._build_prompt_with_markdown(cluster, services_context, markdown_text)
        raw_json = self._call_gpt(prompt)
        data = self._parse_gpt_response(raw_json, cluster)

        slug = self._make_slug(cluster)
        landing = LandingPage.objects.create(
            cluster=cluster,
            slug=slug,
            status=LandingPage.STATUS_DRAFT,
            meta_title=data["meta_title"][:70],
            meta_description=data["meta_description"][:160],
            h1=data["h1"][:200],
            blocks={
                "intro":             data.get("intro", ""),
                "how_it_works":      data.get("how_it_works", ""),
                "who_is_it_for":     data.get("who_is_it_for", ""),
                "contraindications": data.get("contraindications", ""),
                "results":           data.get("results", ""),
                "faq":               data.get("faq", []),
                "cta_text":          data.get("cta_text", ""),
                "internal_links":    data.get("internal_links", []),
            },
            generated_by_agent=True,
            source_markdown=markdown_text,
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
            ),
            target_url=cluster.target_url,
            payload={
                "landing_id": landing.id,
                "cluster_id": cluster.pk,
                "source":     "markdown",
                "warnings":   warnings,
            },
        )

        try:
            notify_new_landing(landing)
        except Exception as exc:
            logger.warning("generate_from_markdown: ошибка уведомления — %s", exc)

        return landing

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
    ) -> str:
        """
        Промпт для generate_from_markdown — маркдаун как «БРИФ РЕДАКТОРА».

        Маркдаун обрезается до 3000 символов (~750 токенов) чтобы не
        превысить контекстное окно вместе с services_context и JSON-схемой.
        Цены — только из блока ДАННЫЕ ОБ УСЛУГЕ, даже если в брифе другие.
        """
        geo = cluster.geo or "Пенза"
        keywords_str = ", ".join(cluster.keywords[:8])

        md_truncated = markdown_text[:3000]
        if len(markdown_text) > 3000:
            md_truncated += "\n\n[...бриф обрезан до 3000 символов...]"

        return (
            f"Ты SEO-копирайтер салона красоты \u00abФормула тела\u00bb в городе {geo}.\n"
            f"Создай SEO-лендинг для страницы: {cluster.target_url}\n\n"

            f"БРИФ РЕДАКТОРА (используй как основу структуры и смыслов):\n"
            f"---\n"
            f"{md_truncated}\n"
            f"---\n\n"

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
            "8. Улучшай SEO-формулировки брифа, но не меняй факты\n\n"

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

    def _call_gpt(self, prompt: str) -> str:
        """
        Вызывает GPT с response_format=json_object.
        Raises LandingGeneratorError при ошибке API.
        """
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
