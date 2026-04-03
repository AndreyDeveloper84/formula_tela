"""
Заполнение SeoKeywordCluster данными семантического ядра v2
(Wordstat Пенза, февраль 2026).

Использование:
    python manage.py seed_seo_clusters                # создать 13 кластеров
    python manage.py seed_seo_clusters --dry-run      # только показать, без записи в БД
    python manage.py seed_seo_clusters --clear         # удалить все кластеры и создать заново

Источник данных:
    semantic_core_formula_tela_v2.xlsx
    Группировка: 1 кластер = 1 целевая страница (URL)
"""

from django.core.management.base import BaseCommand

from agents.models import SeoKeywordCluster
from services_app.models import ServiceCategory


class Command(BaseCommand):
    help = "Заполнение SeoKeywordCluster данными семантического ядра v2 (Пенза)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Показать что будет создано, без записи в БД",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            default=False,
            help="Удалить ВСЕ существующие кластеры перед заполнением",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        clear = options["clear"]

        S = self.style.SUCCESS
        W = self.style.WARNING
        E = self.style.ERROR
        H = self.style.MIGRATE_HEADING

        CLUSTERS = [
            {
                "name": "Массаж Пенза (главная)",
                "service_slug": "",
                "target_url": "/",
                "category_slug": "",
                "keywords": [
                    "массаж пенза",
                    "массаж в пензе цена",
                    "пенза массаж пнз",
                    "салон массажа пенза",
                    "мужской массаж пенза",
                ],
            },
            {
                "name": "Классический массаж Пенза",
                "service_slug": "klassicheskij-massazh",
                "target_url": "/klassicheskij-massazh",
                "category_slug": "massazh",
                "keywords": [
                    "классический массаж",
                    "парный массаж",
                    "массаж в 4 руки",
                    "расслабляющий массаж спины",
                    "классический массаж спины",
                    "массаж общий классический",
                    "классический массаж цена",
                    "классический массаж пенза",
                ],
            },
            {
                "name": "Массаж спины Пенза",
                "service_slug": "massazh-spiny",
                "target_url": "/massazh-spiny",
                "category_slug": "massazh",
                "keywords": [
                    "массаж спины",
                    "массаж спины и шеи",
                    "массаж спины пенза",
                    "массаж спины женщины",
                    "массаж спины мужчине",
                    "массаж мышц спины",
                    "сколько стоит массаж спины",
                    "где массаж спины",
                    "массаж спины отзывы",
                    "массаж спины позвоночника",
                    "сеанс массажа спины",
                    "курс массажа спины",
                    "как часто делают массаж спины",
                    "сколько делать массаж спины",
                    "массаж спины и поясницы",
                    "массаж спины и воротниковой зоны",
                    "массаж спины при остеохондрозе",
                    "пенза массаж спины цена",
                ],
            },
            {
                "name": "Биоэнергетический массаж Пенза",
                "service_slug": "bioenergeticheskij-massazh",
                "target_url": "/bioenergeticheskij-massazh",
                "category_slug": "massazh",
                "keywords": [
                    "массаж при остеохондрозе",
                    "биоэнергетический массаж",
                    "массаж при остеохондрозе можно",
                    "массаж при остеохондрозе позвоночника",
                    "можно делать массаж при остеохондрозе",
                    "делают ли массаж при остеохондрозе",
                    "биоэнергетический массаж отзывы",
                    "биоэнергетический массаж перчатками",
                    "биоэнергетический массаж противопоказания",
                    "лучший массаж при остеохондрозе",
                    "биоэнергетический массаж что это за процедура",
                    "биоэнергетический массаж тела",
                    "биоэнергетический массаж пенза",
                ],
            },
            {
                "name": "Массаж ШВЗ Пенза",
                "service_slug": "massazh-shvz",
                "target_url": "/massazh-shvz",
                "category_slug": "massazh",
                "keywords": [
                    "массаж при шейном остеохондрозе",
                    "массаж при остеохондрозе шейного отдела",
                    "массаж шеи при остеохондрозе",
                    "массаж воротниковой зоны при остеохондрозе",
                    "можно при шейном остеохондрозе массаж",
                ],
            },
            {
                "name": "Лимфодренажный массаж Пенза",
                "service_slug": "limfodrenazhnyj-massazh",
                "target_url": "/limfodrenazhnyj-massazh",
                "category_slug": "massazh",
                "keywords": [
                    "лимфодренажный массаж",
                    "лимфодренажный массаж тела",
                    "лимфодренажный массаж ног",
                    "лимфодренажный массаж руки",
                    "лимфодренажный массаж цена",
                    "лимфодренажный массаж пенза",
                    "лимфодренажный массаж живота",
                    "ручной лимфодренажный массаж",
                    "лимфодренажный массаж противопоказания",
                    "лимфодренажный массаж сколько",
                    "лимфодренажный массаж отзывы",
                    "лимфодренажный массаж как часто делать",
                    "польза лимфодренажного массажа",
                    "антицеллюлитный лимфодренажный массаж",
                    "лимфодренажный массаж шеи",
                    "лимфодренажный массаж эффект",
                    "лимфодренажный массаж при варикозе нижних конечностей",
                ],
            },
            {
                "name": "Антицеллюлитный массаж Пенза",
                "service_slug": "anticelljulitnyj-massazh",
                "target_url": "/anticelljulitnyj-massazh",
                "category_slug": "massazh",
                "keywords": [
                    "антицеллюлитный массаж",
                    "ручной антицеллюлитный массаж",
                    "антицеллюлитный массаж живота",
                    "антицеллюлитный массаж цена",
                    "антицеллюлитный массаж ягодиц",
                    "антицеллюлитный массаж пенза",
                    "какой массаж антицеллюлитный",
                    "антицеллюлитный массаж тела",
                    "антицеллюлитный массаж бедер",
                    "лучший антицеллюлитный массаж",
                    "как часто делать антицеллюлитный массаж",
                    "антицеллюлитный массаж эффект",
                    "антицеллюлитный массаж противопоказания",
                    "антицеллюлитный массаж сколько сеансов",
                    "антицеллюлитный массаж пенза цена",
                ],
            },
            {
                "name": "Массаж лица Пенза",
                "service_slug": "massazh-litsa",
                "target_url": "/massazh-litsa",
                "category_slug": "kosmetologiya",
                "keywords": [
                    "подтяжка лица массажем",
                    "лимфодренажный массаж лица",
                    "массаж лица отзывы",
                    "скульптурный массаж лица",
                    "миофасциальный массаж лица",
                    "массаж лица от отеков",
                    "массаж лица пенза",
                    "массаж лица овал",
                    "массаж лица от морщин",
                    "лифтинг массаж лица",
                    "первый массаж лица",
                    "вакуумный массаж лица",
                    "массаж лица и шеи",
                    "массаж лица цена",
                    "классический массаж лица",
                    "массаж лица и тела",
                    "массаж лица руками",
                    "массаж лица салон",
                    "ручной массаж лица",
                    "массаж лица польза",
                    "помогает ли массаж лица",
                    "массаж лица до и после",
                ],
            },
            {
                "name": "Чистка лица Пенза",
                "service_slug": "chistka-litsa",
                "target_url": "/chistka-litsa",
                "category_slug": "kosmetologiya",
                "keywords": [
                    "чистка лица",
                    "механическая чистка лица",
                    "чистка лица от прыщей",
                    "чистка лица у косметолога",
                    "чистка лица пенза",
                    "чистка лица от черных точек",
                    "чистка лица сколько",
                    "массаж и чистка лица",
                ],
            },
            {
                "name": "Лазерная эпиляция Пенза",
                "service_slug": "lazernaya-epilyatsiya",
                "target_url": "/lazernaya-epilyatsiya",
                "category_slug": "epilyatsiya",
                "keywords": [
                    "лазерная эпиляция",
                    "лазерная эпиляция бикини",
                    "лазерная эпиляция волос",
                    "делать ли лазерную эпиляцию",
                    "можно ли делать лазерную эпиляцию",
                    "после лазерной эпиляции можно",
                    "глубокая лазерная эпиляция",
                    "лазерная эпиляция цена",
                    "лазерная эпиляция глубокое бикини",
                    "зоны лазерной эпиляции",
                    "курс лазерной эпиляции",
                ],
            },
            {
                "name": "Спортивный массаж Пенза",
                "service_slug": "sportivnyj-massazh",
                "target_url": "/sportivnyj-massazh",
                "category_slug": "massazh",
                "keywords": [
                    "спортивный массаж",
                    "спортивный массаж пенза",
                    "спортивный массаж спины",
                    "спортивный массаж тела",
                    "классический массаж спортивная",
                ],
            },
            {
                "name": "Аппаратные массажи Пенза",
                "service_slug": "apparatnye-massazhi",
                "target_url": "/apparatnye-massazhi",
                "category_slug": "massazh",
                "keywords": [
                    "аппаратный массаж пенза",
                    "аппаратный лимфодренажный массаж",
                    "вакуумный антицеллюлитный массаж",
                    "аппаратный антицеллюлитный массаж",
                ],
            },
            {
                "name": "Подарочные сертификаты",
                "service_slug": "sertifikaty",
                "target_url": "/sertifikaty",
                "category_slug": "",
                "keywords": [
                    "сертификат на парный массаж",
                ],
            },
        ]

        sep = "=" * 60
        self.stdout.write(f"\n{sep}")
        self.stdout.write(H("  seed_seo_clusters -- Semantic Core v2 (Penza)"))
        self.stdout.write(f"{sep}\n")

        if dry_run:
            self.stdout.write(W("[DRY RUN] Izmenenia v BD ne budut vneseny\n"))

        # --clear: удаляем все кластеры
        if clear and not dry_run:
            deleted_count, _ = SeoKeywordCluster.objects.all().delete()
            self.stdout.write(W(f"Udaleno klasterov: {deleted_count}"))

        created = 0
        skipped = 0

        for cluster_data in CLUSTERS:
            name = cluster_data["name"]
            kw_count = len(cluster_data["keywords"])

            if dry_run:
                exists = SeoKeywordCluster.objects.filter(name=name).exists()
                status = "SKIP (uzhe est)" if exists else "CREATE"
                self.stdout.write(f"  [{status}] {name} -- {kw_count} kw, URL: {cluster_data['target_url']}")
                if exists:
                    skipped += 1
                else:
                    created += 1
                continue

            # Ищем категорию по slug (nullable)
            category = None
            cat_slug = cluster_data["category_slug"]
            if cat_slug:
                category = ServiceCategory.objects.filter(slug=cat_slug).first()

            obj, was_created = SeoKeywordCluster.objects.get_or_create(
                name=name,
                defaults={
                    "service_slug": cluster_data["service_slug"],
                    "keywords": cluster_data["keywords"],
                    "target_url": cluster_data["target_url"],
                    "is_active": True,
                    "geo": "Пенза",
                    "service_category": category,
                },
            )

            if was_created:
                created += 1
                self.stdout.write(S(f"  + {name} -- {kw_count} kw"))
            else:
                skipped += 1
                self.stdout.write(f"  = {name} -- uzhe est, propuskaem")

        self.stdout.write(f"\n{sep}")
        self.stdout.write(
            S(f"Gotovo: sozdano {created}, propuscheno {skipped}, vsego {len(CLUSTERS)}")
        )
        self.stdout.write(sep)
