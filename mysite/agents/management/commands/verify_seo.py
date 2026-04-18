"""
Проверяет SEO-метаданные страниц услуг и категорий.

Рендерит каждую страницу через Django test client, парсит <title>, <h1>,
<meta description> и сравнивает с ожидаемыми значениями из _seo_audit_data.py.

Использование:
    python manage.py verify_seo               # проверить все
    python manage.py verify_seo --only-errors  # только ошибки
"""
import re

from django.core.management.base import BaseCommand


def _extract(html: str, tag: str) -> str:
    """Извлекает содержимое тега из HTML."""
    if tag == "title":
        m = re.search(r"<title>(.*?)</title>", html, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""
    if tag == "h1":
        m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL | re.IGNORECASE)
        return re.sub(r"\s+", " ", m.group(1).strip()) if m else ""
    if tag == "description":
        m = re.search(
            r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']',
            html, re.IGNORECASE,
        )
        return m.group(1).strip() if m else ""
    return ""


class Command(BaseCommand):
    help = "Проверяет SEO-метаданные страниц услуг и категорий"

    def add_arguments(self, parser):
        parser.add_argument(
            "--only-errors", action="store_true", default=False,
            help="Показать только проблемы",
        )

    def handle(self, *args, **options):
        from django.test import Client
        from agents.management.commands._seo_audit_data import (
            CATEGORIES_SEO,
            SERVICES_SEO,
        )

        S = self.style.SUCCESS
        E = self.style.ERROR
        W = self.style.WARNING
        H = self.style.MIGRATE_HEADING
        only_errors = options["only_errors"]
        sep = "=" * 60
        client = Client()
        errors = []
        checked = 0

        # ── Услуги ────────────────────────────────────────────────────
        self.stdout.write(H(f"\n{sep}\n=== Проверка услуг ({len(SERVICES_SEO)}) ===\n{sep}"))

        for slug, expected in SERVICES_SEO.items():
            url = f"/uslugi/{slug}/"
            try:
                r = client.get(url)
            except Exception as exc:
                errors.append(f"{url}: render error — {exc}")
                self.stdout.write(E(f"  [ERR] {url}: {exc}"))
                continue

            if r.status_code != 200:
                errors.append(f"{url}: HTTP {r.status_code}")
                self.stdout.write(E(f"  [ERR] {url}: HTTP {r.status_code}"))
                continue

            html = r.content.decode("utf-8", errors="replace")
            checked += 1
            page_errors = []

            # Title check
            title = _extract(html, "title")
            if expected["seo_title"] not in title:
                page_errors.append(f"title: expected '{expected['seo_title'][:50]}...' not in '{title[:60]}'")

            # Дубли в title
            if "| |" in title or title.lower().count("формула тела") > 1:
                page_errors.append(f"title DUPLICATE: '{title[:80]}'")

            # H1 check
            h1 = _extract(html, "h1")
            if expected["seo_h1"] not in h1 and h1 != expected["seo_h1"]:
                page_errors.append(f"h1: expected '{expected['seo_h1'][:50]}' got '{h1[:50]}'")

            # Description check
            desc = _extract(html, "description")
            if expected["seo_description"] and expected["seo_description"][:40] not in desc:
                page_errors.append(f"desc mismatch: got '{desc[:60]}...'")

            # Description length
            if len(desc) > 170:
                page_errors.append(f"desc too long: {len(desc)} chars")

            if page_errors:
                errors.extend([f"{url}: {e}" for e in page_errors])
                self.stdout.write(E(f"  [FAIL] {url}"))
                for pe in page_errors:
                    self.stdout.write(E(f"         {pe}"))
            elif not only_errors:
                self.stdout.write(S(f"  [OK] {url}"))

        # ── Категории ─────────────────────────────────────────────────
        self.stdout.write(H(f"\n{sep}\n=== Проверка категорий ({len(CATEGORIES_SEO)}) ===\n{sep}"))

        for slug, expected in CATEGORIES_SEO.items():
            url = f"/kategorii/{slug}/"
            try:
                r = client.get(url)
            except Exception as exc:
                errors.append(f"{url}: render error — {exc}")
                self.stdout.write(E(f"  [ERR] {url}: {exc}"))
                continue

            if r.status_code != 200:
                errors.append(f"{url}: HTTP {r.status_code}")
                self.stdout.write(E(f"  [ERR] {url}: HTTP {r.status_code}"))
                continue

            html = r.content.decode("utf-8", errors="replace")
            checked += 1
            page_errors = []

            # Title
            title = _extract(html, "title")
            if expected["seo_title"] not in title:
                page_errors.append(f"title: '{expected['seo_title'][:50]}...' not in '{title[:60]}'")

            # H1 — должен быть, и именно H1 (не H2)
            h1 = _extract(html, "h1")
            if not h1:
                page_errors.append("H1 отсутствует!")
            elif expected["seo_h1"] not in h1:
                page_errors.append(f"h1: expected '{expected['seo_h1'][:50]}' got '{h1[:50]}'")

            # Description
            desc = _extract(html, "description")
            if expected["seo_description"] and expected["seo_description"][:40] not in desc:
                page_errors.append(f"desc mismatch: got '{desc[:60]}...'")

            if page_errors:
                errors.extend([f"{url}: {e}" for e in page_errors])
                self.stdout.write(E(f"  [FAIL] {url}"))
                for pe in page_errors:
                    self.stdout.write(E(f"         {pe}"))
            elif not only_errors:
                self.stdout.write(S(f"  [OK] {url}"))

        # ── Итог ──────────────────────────────────────────────────────
        self.stdout.write(H(f"\n{sep}\n=== Итог ===\n{sep}"))
        self.stdout.write(f"  Проверено страниц: {checked}")
        if errors:
            self.stdout.write(E(f"  Проблем найдено: {len(errors)}"))
        else:
            self.stdout.write(S("  Все страницы в порядке!"))
        self.stdout.write("")
