"""
Management command: fill_seo_fields
Генерирует seo_h1, seo_title, seo_description для услуг с пустыми SEO-полями.

Использование:
    python manage.py fill_seo_fields            # только пустые поля
    python manage.py fill_seo_fields --force    # перезаписать все
    python manage.py fill_seo_fields --dry-run  # только показать, не сохранять
"""
import re

from django.core.management.base import BaseCommand

from services_app.models import Service


GEO = "в Пензе"
PHONE = "8 (8412) 39-34-33"
MAX_TITLE = 65
MAX_DESC = 160

# Маппинг slug-части категории → категорийный ключевик для H1
CATEGORY_KEYS = {
    "lazernaya-epilyaciya": "Лазерная эпиляция",
    "lazernaya-epilyaciya-kombo": "Лазерная эпиляция",
    "ruchnye-massazhi": "Массаж",
    "sportivnyj-massazh": "Спортивный массаж",
    "antitsellyulitnyj-massazh": "Антицеллюлитный массаж",
    "limfodrenazhnyi-massazh": "Лимфодренажный массаж",
    "massazh-problemnyh-zon": "Массаж",
    "massazh-lica": "Массаж лица",
    "bioenergeticheskij-massazh": "Биоэнергетический массаж",
    "kvantovyj-massazh": "Квантовый массаж",
    "apparatnye-massazhi": "Аппаратный массаж",
    "massazhnye-kompleksy": "Массажный комплекс",
    "uhody-dlya-lica": "Уход за лицом",
    "podarochnye-sertifikaty-i-abonementy": "Подарочный сертификат",
}


def _strip_emoji(text: str) -> str:
    """Удаляет emoji-символы из строки."""
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F9FF"
        "\U00002600-\U000027BF"
        "\U0001FA00-\U0001FA9F"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()


def _clean_description(text: str, max_len: int = MAX_DESC) -> str:
    """Убирает переносы строк, эмодзи, обрезает до max_len."""
    clean = _strip_emoji(text.replace("\n", " ").replace("\r", " "))
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > max_len:
        clean = clean[: max_len - 3].rsplit(" ", 1)[0] + "..."
    return clean


def _trunc_title(text: str, max_len: int = MAX_TITLE) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rsplit(" ", 1)[0].rstrip(" —,")


def generate_seo(service: Service) -> dict:
    """Возвращает dict с seo_h1, seo_title, seo_description."""
    cat_slug = service.category.slug if service.category else ""
    cat_key = CATEGORY_KEYS.get(cat_slug, service.category.name if service.category else "")

    price_str = f" — от {int(service.price_from)} ₽" if service.price_from else ""

    # --- H1 ---
    # Для лазерной эпиляции: "Лазерная эпиляция [зона] в Пензе"
    if "epilyaciya" in cat_slug or "epilyatsiya" in (service.slug or ""):
        h1 = f"Лазерная эпиляция {service.name.lower()} {GEO}"
    elif cat_key in ("Массаж", "Спортивный массаж", "Антицеллюлитный массаж",
                     "Лимфодренажный массаж", "Биоэнергетический массаж",
                     "Квантовый массаж", "Аппаратный массаж", "Массажный комплекс"):
        h1 = f"{service.name} {GEO}"
    elif cat_key == "Уход за лицом":
        h1 = f"{service.name} — уход за лицом {GEO}"
    else:
        h1 = f"{service.name} {GEO}"

    # --- Title (≤65 символов) ---
    raw_title = f"{service.name}{price_str} | Пенза | Формула Тела"
    title = _trunc_title(raw_title)

    # --- Description (≤160 символов) ---
    if service.description:
        base = _clean_description(service.description, max_len=110)
        desc = f"{service.name} {GEO}{price_str}. {base} Запись: {PHONE}."
        if len(desc) > MAX_DESC:
            desc = f"{service.name} {GEO}{price_str}. Запись: {PHONE}."
    else:
        desc = f"{service.name} {GEO}{price_str}. Профессиональные процедуры. Запись: {PHONE}."

    desc = desc[:MAX_DESC]

    return {"seo_h1": h1, "seo_title": title, "seo_description": desc}


class Command(BaseCommand):
    help = "Генерирует seo_h1, seo_title, seo_description для услуг с пустыми полями"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Перезаписать поля даже если они уже заполнены",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Только показать результат, не сохранять",
        )
        parser.add_argument(
            "--category",
            type=str,
            default=None,
            help="Ограничить по slug категории",
        )

    def handle(self, *args, **options):
        force = options["force"]
        dry_run = options["dry_run"]
        cat_filter = options["category"]

        qs = Service.objects.filter(is_active=True).select_related("category")
        if cat_filter:
            qs = qs.filter(category__slug=cat_filter)

        updated = 0
        skipped = 0

        for svc in qs:
            needs_update = force or not svc.seo_h1 or not svc.seo_title or not svc.seo_description
            if not needs_update:
                skipped += 1
                continue

            data = generate_seo(svc)

            if dry_run:
                self.stdout.write(f"\n[{svc.id}] {svc.name}")
                self.stdout.write(f"  H1:    {data['seo_h1']}")
                self.stdout.write(f"  Title: {data['seo_title']} ({len(data['seo_title'])} chars)")
                self.stdout.write(f"  Desc:  {data['seo_description']} ({len(data['seo_description'])} chars)")
            else:
                if not svc.seo_h1 or force:
                    svc.seo_h1 = data["seo_h1"]
                if not svc.seo_title or force:
                    svc.seo_title = data["seo_title"]
                if not svc.seo_description or force:
                    svc.seo_description = data["seo_description"]
                svc.save(update_fields=["seo_h1", "seo_title", "seo_description"])
                self.stdout.write(self.style.SUCCESS(f"✓ [{svc.id}] {svc.name}"))

            updated += 1

        mode = "DRY RUN" if dry_run else "SAVED"
        self.stdout.write(
            f"\n[{mode}] Обновлено: {updated}, пропущено (уже заполнены): {skipped}"
        )
