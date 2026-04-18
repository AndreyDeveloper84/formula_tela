"""QC-проверки для LandingPage перед публикацией.

Паттерн Strategy: каждая проверка — отдельный класс с методом run().
Pipeline-оркестратор SEOLandingQCAgent вызывает их последовательно.

Severity:
- "critical" — блокирует публикацию, LandingPage остаётся в review.
- "warning"  — попадает в отчёт, но не блокирует.
"""
import json
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


@dataclass
class QCResult:
    """Результат одной QC-проверки."""
    check_name: str
    passed: bool
    severity: str  # "critical" | "warning"
    message: str
    details: dict = field(default_factory=dict)


class BaseQCCheck:
    """Strategy interface. Каждая проверка наследует и реализует run()."""
    name: str = ""
    severity: str = "critical"

    def run(self, landing) -> QCResult:
        raise NotImplementedError

    def _ok(self, message: str = "OK", **details) -> QCResult:
        return QCResult(
            check_name=self.name, passed=True,
            severity=self.severity, message=message, details=details,
        )

    def _fail(self, message: str, **details) -> QCResult:
        return QCResult(
            check_name=self.name, passed=False,
            severity=self.severity, message=message, details=details,
        )


class UniqueH1Check(BaseQCCheck):
    """H1 не дублирует другие published LandingPage или Service.name/seo_h1."""
    name = "unique_h1"
    severity = "critical"

    def run(self, landing) -> QCResult:
        from agents.models import LandingPage
        from services_app.models import Service

        h1 = (landing.h1 or "").strip()
        if not h1:
            return self._fail("H1 пустой")

        # Дубли среди других published LandingPage
        dupes = (
            LandingPage.objects
            .filter(h1=h1, status=LandingPage.STATUS_PUBLISHED)
            .exclude(pk=landing.pk)
            .values_list("slug", flat=True)
        )
        if dupes:
            return self._fail(
                f"H1 дублирует published лендинг: {', '.join(dupes)}",
                duplicate_slugs=list(dupes),
            )

        # Совпадение с Service.name или seo_h1
        from django.db.models import Q
        svc_match = (
            Service.objects
            .filter(is_active=True)
            .filter(Q(name=h1) | Q(seo_h1=h1))
            .values_list("slug", flat=True)[:5]
        )
        if svc_match:
            return self._fail(
                f"H1 совпадает с Service: {', '.join(str(s) for s in svc_match)}",
                service_slugs=list(svc_match),
            )

        return self._ok()


class UniqueSlugCheck(BaseQCCheck):
    """Slug не пересекается с Service, ServiceCategory, Bundle, Master."""
    name = "unique_slug"
    severity = "critical"

    def run(self, landing) -> QCResult:
        from services_app.models import Service, ServiceCategory, Bundle, Master

        slug = landing.slug
        if not slug:
            return self._fail("Slug пустой")

        conflicts = []
        if Service.objects.filter(slug=slug).exists():
            conflicts.append(f"Service(slug={slug})")
        if ServiceCategory.objects.filter(slug=slug).exists():
            conflicts.append(f"ServiceCategory(slug={slug})")
        if Bundle.objects.filter(slug=slug).exists():
            conflicts.append(f"Bundle(slug={slug})")
        if Master.objects.filter(slug=slug).exists():
            conflicts.append(f"Master(slug={slug})")

        if conflicts:
            return self._fail(
                f"Slug конфликтует: {', '.join(conflicts)}",
                conflicts=conflicts,
            )
        return self._ok()


class PublishedAtReadyCheck(BaseQCCheck):
    """published_at будет заполнен агентом при публикации — здесь проверяем
    что лендинг готов к этому (есть meta_title и slug)."""
    name = "published_at_ready"
    severity = "critical"

    def run(self, landing) -> QCResult:
        issues = []
        if not landing.meta_title:
            issues.append("meta_title пустой")
        if not landing.slug:
            issues.append("slug пустой")
        if not landing.h1:
            issues.append("h1 пустой")
        if issues:
            return self._fail("; ".join(issues), missing_fields=issues)
        return self._ok()


class RequiredBlocksCheck(BaseQCCheck):
    """blocks JSON содержит минимум intro и cta_text."""
    name = "required_blocks"
    severity = "warning"

    REQUIRED_KEYS = {"intro", "cta_text"}

    def run(self, landing) -> QCResult:
        blocks = landing.blocks or {}
        if isinstance(blocks, str):
            try:
                blocks = json.loads(blocks)
            except (json.JSONDecodeError, TypeError):
                return self._fail("blocks не валидный JSON")

        if not isinstance(blocks, dict):
            return self._fail("blocks должен быть словарём")

        missing = []
        for key in self.REQUIRED_KEYS:
            val = blocks.get(key)
            if not val or (isinstance(val, str) and not val.strip()):
                missing.append(key)

        if missing:
            return self._fail(
                f"Отсутствуют блоки: {', '.join(missing)}",
                missing_blocks=missing,
            )
        return self._ok()


class InternalLinksCheck(BaseQCCheck):
    """blocks содержит ≥2 внутренних ссылки на /uslugi/<slug>/."""
    name = "internal_links"
    severity = "warning"

    MIN_LINKS = 2

    def run(self, landing) -> QCResult:
        blocks = landing.blocks or {}
        text = json.dumps(blocks, ensure_ascii=False) if isinstance(blocks, dict) else str(blocks)

        links = re.findall(r'/uslugi/[\w-]+/', text)
        unique_links = set(links)

        if len(unique_links) < self.MIN_LINKS:
            return self._fail(
                f"Найдено {len(unique_links)} внутренних ссылок (минимум {self.MIN_LINKS})",
                found_links=list(unique_links),
            )
        return self._ok(found_links=list(unique_links))


class ContentDuplicateCheck(BaseQCCheck):
    """Fuzzy-match контента с другими published LandingPage (порог 0.85)."""
    name = "content_duplicate"
    severity = "critical"

    SIMILARITY_THRESHOLD = 0.85

    def run(self, landing) -> QCResult:
        from agents.models import LandingPage

        blocks = landing.blocks or {}
        text = json.dumps(blocks, ensure_ascii=False) if isinstance(blocks, dict) else str(blocks)

        if len(text) < 50:
            return self._fail("Контент слишком короткий (< 50 символов)")

        published = (
            LandingPage.objects
            .filter(status=LandingPage.STATUS_PUBLISHED)
            .exclude(pk=landing.pk)
            .only("slug", "blocks")
        )

        for other in published:
            other_blocks = other.blocks or {}
            other_text = (
                json.dumps(other_blocks, ensure_ascii=False)
                if isinstance(other_blocks, dict)
                else str(other_blocks)
            )
            ratio = SequenceMatcher(None, text, other_text).ratio()
            if ratio >= self.SIMILARITY_THRESHOLD:
                return self._fail(
                    f"Дубль контента с /{other.slug}/ (similarity {ratio:.0%})",
                    duplicate_slug=other.slug,
                    similarity=round(ratio, 3),
                )

        return self._ok()
