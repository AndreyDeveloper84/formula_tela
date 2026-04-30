import uuid
from decimal import Decimal

from django.db import models
from django.db.models import Q

from .managers import (
    BotInquiryQuerySet,
    BundleQuerySet,
    HelpArticleQuerySet,
    MasterQuerySet,
    PromotionQuerySet,
    ReviewQuerySet,
    ServiceCategoryQuerySet,
    ServiceOptionQuerySet,
    ServiceQuerySet,
)
from .validators import validate_image_upload, validate_video_upload


CERTIFICATE_THEME_CHOICES = [
    ("pink", "Для неё"),
    ("graphite", "Для него"),
    ("spring", "8 марта"),
    ("military", "23 февраля"),
    ("birthday", "День рождения"),
    ("winter", "Новый год"),
    ("valentine", "14 февраля"),
    ("spa", "SPA релакс"),
]


def generate_unique_slug(model_cls, name: str, *, pk=None, max_length: int = 200) -> str:
    """Генерирует уникальный slug для модели на основе name.

    Использует unidecode для транслитерации кириллицы в латиницу
    (чтобы получить `klassicheskii-massazh` из «Классический массаж»).
    При коллизии добавляет суффикс `-2`, `-3` и т.д.

    - `model_cls` — класс модели, у которой есть поле slug
    - `name` — исходное название (любой язык)
    - `pk` — если обновляем существующий объект, его pk (чтобы не учитывать
      самого себя при проверке уникальности)
    - `max_length` — max_length поля slug в модели

    Возвращает пустую строку, если `name` пустое или после очистки не
    осталось символов.
    """
    from django.utils.text import slugify
    from unidecode import unidecode

    if not name:
        return ""
    base = slugify(unidecode(name))[:max_length]
    if not base:
        return ""

    qs = model_cls._default_manager.filter(slug=base)
    if pk is not None:
        qs = qs.exclude(pk=pk)
    if not qs.exists():
        return base

    # Коллизия — приклеиваем числовой суффикс
    n = 2
    while True:
        suffix = f"-{n}"
        candidate = base[: max_length - len(suffix)] + suffix
        qs = model_cls._default_manager.filter(slug=candidate)
        if pk is not None:
            qs = qs.exclude(pk=pk)
        if not qs.exists():
            return candidate
        n += 1


class Service(models.Model):
    name = models.CharField(max_length=200, verbose_name="Название услуги")
    description = models.TextField(blank=True, verbose_name="Описание")
    is_active = models.BooleanField(default=True, verbose_name="Активна")
    is_popular = models.BooleanField(default=False, verbose_name="Популярная")
    short = models.CharField(max_length=100, blank=True, null=True, verbose_name="Краткое название") 
    category = models.ForeignKey('ServiceCategory', on_delete=models.PROTECT, related_name='services', null=True, blank=True, verbose_name="Категория")
    
    duration = models.PositiveIntegerField(default=60, verbose_name="Длительность (мин)", null=True, blank=True)  # устаревшее поле
    price = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="Цена", null=True, blank=True)
    duration_min = models.PositiveIntegerField(default=60, verbose_name="Длительность (мин)", null=True, blank=True)
    price_from = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="Цена от", null=True, blank=True)
    image = models.ImageField(
        upload_to="services/",
        blank=True,
        null=True,
        verbose_name="Изображение услуги",
        help_text="Рекомендуемый размер: 800x600px"
    )

    image_mobile = models.ImageField(
        upload_to="services/mobile/",
        blank=True,
        null=True,
        verbose_name="Изображение (мобильное)",
        help_text="Для экранов <768px. Если не загружено — используется основное изображение."
    )



    # --- SEO и расширенный контент ---
    slug = models.SlugField(
        max_length=200,
        unique=True,
        blank=True,
        null=True,
        verbose_name="URL-slug",
        help_text="ЧПУ-ссылка, например: klassicheskij-massazh"
    )
    seo_h1 = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="H1 заголовок",
        help_text="Если пусто — используется название услуги."
    )
    seo_title = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="SEO Title",
        help_text="Для тега title. До 60 символов. Если пусто — используется название услуги."
    )
    seo_description = models.CharField(
        max_length=300,
        blank=True,
        verbose_name="SEO Description",
        help_text="Для meta description. До 160 символов."
    )
    subtitle = models.CharField(
        max_length=300,
        blank=True,
        verbose_name="Подзаголовок",
        help_text="Текст под H1 на странице услуги."
    )

    related_services = models.ManyToManyField(
        'self',
        blank=True,
        symmetrical=False,
        verbose_name="Связанные услуги",
        help_text="Блок «Другие виды массажа». Выберите услуги для перелинковки."
    )
    
    short_description = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Краткое описание для карточки",
        help_text="1 строка для карточки перелинковки. Пример: Восстановление после тренировок, снятие крепатуры"
    )
    
    emoji = models.CharField(
        max_length=10,
        blank=True,
        verbose_name="Эмодзи",
        help_text="Иконка для карточки. Пример: 💪 🔥 💧 ⚡"
    )

    order = models.PositiveIntegerField(
        default=0,
        verbose_name="Порядок сортировки"
    )

    # Phase 2.4 T01 — цели/результаты услуги для consultative AI Concierge.
    # Список slug'ов из SERVICE_GOAL_CHOICES (см. ниже). LLM использует goals
    # чтобы рекомендовать услуги под запрос клиента («хочу расслабиться»,
    # «болит спина»).
    goals = models.JSONField(
        "Цели / результаты",
        default=list, blank=True,
        help_text="Список тегов из SERVICE_GOAL_CHOICES. Используется AI-ботом "
                  "для подбора услуг под запрос клиента. Пример: "
                  '["relax", "antistress"] — для расслабляющих услуг.',
    )

    # Phase 2.4 T03 — контр-показания и health screening.
    # requires_health_check=True для услуг где противопоказания критичны
    # (антицеллюлитный, баночный, обёртывания, лимфодренаж, лазер).
    # AI Concierge перед confirm_booking задаст вопрос про беременность/
    # давление/недавние операции. Если клиент сообщил проблему → запись
    # переадресуется менеджеру (BotInquiry), а не отправляется в YClients.
    contraindications = models.TextField(
        "Противопоказания",
        blank=True, default="",
        help_text="Текст противопоказаний — показывается клиенту в карточке "
                  "услуги перед записью. Пример: «беременность, повышенное "
                  "давление, недавние операции».",
    )
    requires_health_check = models.BooleanField(
        "Требует проверки здоровья",
        default=False,
        help_text="Если True — AI-бот спросит клиента о беременности / "
                  "давлении / операциях ПЕРЕД записью. При наличии "
                  "противопоказания запись переадресуется менеджеру.",
    )

    created_at = models.DateTimeField(auto_now_add=True, null=True, verbose_name="Создана")
    updated_at = models.DateTimeField(auto_now=True, null=True, verbose_name="Обновлена")

    objects = ServiceQuerySet.as_manager()

    class Meta:
        verbose_name = "Услуга"
        verbose_name_plural = "Услуги"
        #ordering = ["order", "name"]
        indexes = [
            models.Index(fields=["is_active", "is_popular"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            self.slug = generate_unique_slug(
                Service, self.name, pk=self.pk, max_length=200
            )
        super().save(*args, **kwargs)

    def has_goal(self, goal: str) -> bool:
        """True если услуга помечена тегом goal. Кейс-чувствительно."""
        return goal in (self.goals or [])


# T01 — справочник целей/результатов услуг для AI Concierge consultative flow.
# Slug стабилен (используется в Service.goals и LLM tool).
# Label видит менеджер в админке + LLM использует для подбора.
SERVICE_GOAL_CHOICES = [
    ("relax", "Расслабление, снятие стресса"),
    ("antistress", "Антистресс, эмоциональная разгрузка"),
    ("back_pain", "Боль в спине / шее / суставах"),
    ("posture", "Осанка, мышечный дисбаланс"),
    ("recovery", "Восстановление после нагрузок / тренировок"),
    ("tone", "Тонус, бодрость, энергия"),
    ("weight_loss", "Снижение веса, коррекция фигуры"),
    ("cellulite", "Антицеллюлитный эффект"),
    ("lymph", "Лимфодренаж, отёчность"),
    ("beauty_face", "Уход за лицом, омоложение"),
    ("hair_removal", "Удаление волос (эпиляция)"),
    ("pregnancy_safe", "Безопасно при беременности"),
]
SERVICE_GOAL_VALUES = frozenset(slug for slug, _ in SERVICE_GOAL_CHOICES)


UNIT_CHOICES = [
    ("session", "процедуры"),  # пакет процедур
    ("zone",    "зоны"),       # пакет зон
    ("visit",   "визиты"),     # пакет визитов
]

class ServiceOption(models.Model):

    name = models.CharField(max_length=120, verbose_name="Название варианта услуги", null=True, blank=True)

    service = models.ForeignKey(
        Service, on_delete=models.CASCADE, 
        related_name="options", 
        verbose_name="Услуга"
        )
    duration_min = models.PositiveIntegerField(verbose_name="Длительность (мин)")
    unit_type = models.CharField(
        max_length=16,
        choices=UNIT_CHOICES,
        default="session",
        verbose_name="Единица",
    )
    units = models.PositiveSmallIntegerField(
        default=1,
        verbose_name="Кол-во единиц",
        help_text="Напр.: 5 процедур, 3 зоны, 2 визита",
    )
    price = models.DecimalField(
        max_digits=8, 
        decimal_places=0, 
        verbose_name="Цена",
        help_text="Полная стоимость пакета"
        )
    is_active = models.BooleanField(default=True, verbose_name="Активна")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок показа")

    yclients_service_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="ID услуги в YCLIENTS"
    )

    objects = ServiceOptionQuerySet.as_manager()

    class Meta:
        verbose_name = "Вариант услуги"
        verbose_name_plural = "Варианты услуги"
        unique_together = [("service", "duration_min", "unit_type", "units")]
        ordering = ["order", "duration_min", "unit_type", "units"]
        constraints = [
            models.CheckConstraint(
                condition=Q(duration_min__gte=1), name='svcopt_duration_gte_1'
                ),
            models.CheckConstraint(
                condition=Q(units__gte=1), name="svcopt_units_gte_1"
            )
        ]
        indexes = [
            models.Index(fields=["service", "is_active", "order"]), 
        ]

    def __str__(self):
        # Пример: "VelaShape — 60 мин × 10 процедур"
        base = f"{self.duration_min} мин"
        units_label = self.get_unit_type_display()
        suffix = f" × {self.units} {units_label}" if self.units and self.units > 1 else ""
        return f"{self.service.name} — {base}{suffix}"
    
    @property
    def price_per_session(self):
        return self.price / self.units if self.units else None

class ServiceCategory(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Название категории")
    description = models.TextField(blank=True, verbose_name="Описание категории")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок")
    is_active = models.BooleanField(
        default=True, verbose_name="Активна",
        help_text="Снимите галочку, чтобы скрыть категорию со всех страниц сайта (главная, services, sitemap). Услуги внутри остаются активными, но не отображаются в каталоге.",
    )


    image = models.ImageField(
        upload_to="categories/",
        blank=True,
        null=True,
        verbose_name="Изображение категории (десктоп)"
    )
    image_mobile = models.ImageField(
        upload_to="categories/mobile/",
        blank=True,
        null=True,
        verbose_name="Изображение категории (мобильное)"
    )
    slug = models.SlugField(
        unique=True,
        blank=True,
        null=True,
        verbose_name="URL-slug",
        help_text="Для ЧПУ-ссылок, например: ruchnye-massazhi"
    )

    # --- SEO ---
    seo_title = models.CharField(
        "SEO Title", max_length=120, blank=True, default="",
        help_text="Для title. Без суффикса «| Формула Тела» — шаблон добавит сам.",
    )
    seo_h1 = models.CharField(
        "H1 заголовок", max_length=200, blank=True, default="",
        help_text="Если пусто — используется название категории.",
    )
    seo_description = models.CharField(
        "SEO Description", max_length=300, blank=True, default="",
        help_text="Для meta description. До 160 символов.",
    )

    objects = ServiceCategoryQuerySet.as_manager()

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "Категория услуг"
        verbose_name_plural = "Категории услуг"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            self.slug = generate_unique_slug(
                ServiceCategory, self.name, pk=self.pk, max_length=50
            )
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse
        if self.slug:
            return reverse("website:category_services_by_slug", kwargs={"slug": self.slug})
        return reverse("website:category_services", kwargs={"category_id": self.pk})


# ─────────────────────────────────────────────────────
# Контентные блоки для страниц услуг (SEO-лендинги)
# ─────────────────────────────────────────────────────

BLOCK_TYPE_CHOICES = [
    ("text",            "Текстовый блок"),
    ("accent",          "Акцентный блок (цветной фон)"),
    ("checklist",       "Чеклист (✅ пункты)"),
    ("identification",  "Блок идентификации (Узнаёте себя?)"),
    ("cta",             "CTA-кнопка (Записаться)"),
    ("price_table",     "Таблица цен"),
    ("accordion",       "Аккордеон (раскрывающийся блок)"),
    ("faq",             "FAQ — вопросы и ответы"),
    ("special_formats", "Особые форматы"),
    ("subscriptions",   "Абонементы / экономия"),
    ("navigation",      "Навигация (Не знаете, что выбрать?)"),
    ("html",            "Произвольный HTML"),
]

HEADING_LEVEL_CHOICES = [
    ("h2", "H2 — заголовок блока"),
    ("h3", "H3 — подзаголовок"),
]

class ServiceBlock(models.Model):
    """Контентный блок страницы услуги — конструктор лендинга"""
    
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="blocks",
        verbose_name="Услуга"
    )
    block_type = models.CharField(
        max_length=30,
        choices=BLOCK_TYPE_CHOICES,
        verbose_name="Тип блока"
    )
    title = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Заголовок блока",
        help_text="Заголовок (H2 или H3). Можно оставить пустым."
    )
    heading_level = models.CharField(
        max_length=2,
        choices=HEADING_LEVEL_CHOICES,
        default="h2",
        verbose_name="Уровень заголовка",
        help_text="H2 — основной заголовок блока. H3 — подзаголовок внутри блока."
    )
    content = models.TextField(
        blank=True,
        verbose_name="Содержимое",
        help_text=(
            "HTML разрешён. "
            "Для чеклиста/идентификации — каждый пункт с новой строки. "
            "Для FAQ — формат: Вопрос?\\nОтвет текст.\\n---\\nВопрос?\\nОтвет текст."
        )
    )

    # --- Настройки оформления (вместо JSON-поля extra) ---
    bg_color = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Цвет фона",
        help_text="Для акцентного/навигационного блока. Пример: #9BAE9E"
    )
    text_color = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Цвет текста",
        help_text="Пример: #fff или #333333"
    )
    btn_text = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Текст кнопки",
        help_text="Для CTA-блока. По умолчанию: Записаться онлайн"
    )
    btn_sub = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Подпись под кнопкой",
        help_text="Мелкий текст под кнопкой. Пример: Выберите удобное время — мы подтвердим запись"
    )
    css_class = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="CSS-класс",
        help_text="Дополнительный класс для стилизации блока."
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name="Порядок"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен"
    )

    class Meta:
        verbose_name = "Контентный блок услуги"
        verbose_name_plural = "Контентные блоки услуг"
        ordering = ["order"]
        indexes = [
            models.Index(fields=["service", "is_active", "order"]),
        ]

    def __str__(self):
        type_label = dict(BLOCK_TYPE_CHOICES).get(self.block_type, self.block_type)
        title_str = f" — {self.title}" if self.title else ""
        return f"[{type_label}]{title_str}"

MEDIA_TYPE_CHOICES = [
    ("photo", "Фотография"),
    ("video", "Видео (YouTube-ссылка)"),
]

MEDIA_DISPLAY_CHOICES = [
    ("single", "Одиночное (полная ширина)"),
    ("carousel", "В карусель (группировка)"),
]

class ServiceMedia(models.Model):
    """
    Медиа-файлы для страницы услуги.
    
    Десктоп: отображаются в правой колонке друг под другом.
    Мобильный: вставляются между текстовыми блоками по полю insert_after_order.
    Карусель: несколько фото с одинаковым carousel_group объединяются в слайдер.
    """
    
    service = models.ForeignKey(
        Service,
        on_delete=models.CASCADE,
        related_name="media",
        verbose_name="Услуга"
    )
    media_type = models.CharField(
        max_length=10,
        choices=MEDIA_TYPE_CHOICES,
        default="photo",
        verbose_name="Тип медиа"
    )
    display_mode = models.CharField(
        max_length=10,
        choices=MEDIA_DISPLAY_CHOICES,
        default="single",
        verbose_name="Режим отображения",
        help_text="Одиночное — показывается как отдельная картинка. Карусель — группируется с другими фото той же группы."
    )
    carousel_group = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Группа карусели",
        help_text="Фото с одинаковой группой объединяются в карусель. Пример: hero, cabinet, process"
    )

    image = models.ImageField(
        upload_to="services/gallery/",
        blank=True,
        null=True,
        verbose_name="Изображение",
        help_text="JPG/PNG/WebP до 5 МБ. Рекомендуемый размер: 800×600px.",
        validators=[validate_image_upload],
    )
    image_mobile = models.ImageField(
        upload_to="services/gallery/mobile/",
        blank=True,
        null=True,
        verbose_name="Мобильная версия",
        help_text="JPG/PNG/WebP до 5 МБ. Для экранов <768px.",
        validators=[validate_image_upload],
    )
    video_url = models.URLField(
        blank=True,
        verbose_name="URL видео",
        help_text="YouTube или Vimeo ссылка. Пример: https://www.youtube.com/embed/XXXXX"
    )
    video_file = models.FileField(
        upload_to="services/video/",
        blank=True,
        null=True,
        verbose_name="Видеофайл",
        help_text="MP4/WebM до 50 МБ. Если заполнено — приоритет над YouTube-ссылкой.",
        validators=[validate_video_upload],
    )

    alt_text = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Alt-текст",
        help_text="Описание для SEO. Пример: Процесс классического массажа в студии Формула Тела"
    )
    title_text = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Title-текст",
        help_text="Подсказка при наведении."
    )

    order = models.PositiveIntegerField(
        default=0,
        verbose_name="Порядок (десктоп)",
        help_text="Порядок отображения в правой колонке на десктопе."
    )
    insert_after_order = models.PositiveIntegerField(
        default=0,
        verbose_name="Вставить после блока №",
        help_text=(
            "На мобильном: после какого блока показать это медиа. "
            "Используется значение поля 'Порядок' у блока. "
            "Пример: 20 — вставить после блока с порядком 20 (чеклист)."
        )
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен"
    )

    class Meta:
        verbose_name = "Медиа-файл услуги"
        verbose_name_plural = "📷 Медиа-файлы услуги"
        ordering = ["order"]
        indexes = [
            models.Index(fields=["service", "is_active", "order"]),
        ]

    def __str__(self):
        label = self.alt_text or f"Медиа #{self.pk}"
        mode = "🎠" if self.display_mode == "carousel" else "🖼"
        return f"{mode} {label} (после блока {self.insert_after_order})"

class FAQ(models.Model):
    question = models.CharField(max_length=255, verbose_name="Вопрос")
    answer = models.TextField(verbose_name="Ответ")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок")
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.PROTECT,
        related_name="faqs",
        verbose_name="Категория",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True, verbose_name="Активен")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")

    class Meta:
        verbose_name = "Часто задаваемый вопрос"
        verbose_name_plural = "Часто задаваемые вопросы"
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["is_active", "order"]),
        ]

    def __str__(self):
        return self.question    
    
class SiteSettings(models.Model):
    site_name = models.CharField(max_length=100, verbose_name="Название сайта")
    contact_email = models.EmailField(verbose_name="Контактный email")
    contact_phone = models.CharField(max_length=20, blank=True, verbose_name="Контактный телефон")
    address = models.CharField(max_length=255, blank=True, verbose_name="Адрес")
    working_hours = models.CharField(max_length=255, blank=True, verbose_name="Часы работы")
    salon_name = models.CharField(max_length=100, verbose_name="Название салона")
    logo = models.ImageField(upload_to="logo/", blank=True, null=True, verbose_name="Логотип")
    description = models.TextField(blank=True, null=True, verbose_name="Описание")
    social_media = models.JSONField(blank=True, null=True, verbose_name="Социальные сети")
    payment_methods = models.JSONField(blank=True, null=True, verbose_name="Методы оплаты")
    cancellation_policy = models.TextField(blank=True, null=True, verbose_name="Политика отмены")
    privacy_policy = models.TextField(blank=True, null=True, verbose_name="Политика конфиденциальности")
    terms_of_service = models.TextField(blank=True, null=True, verbose_name="Условия использования")
    copyright = models.CharField(max_length=100, blank=True, null=True, verbose_name="Copyright")
    google_maps_link = models.URLField(blank=True, null=True, verbose_name="Ссылка на Google Maps")
    yandex_maps_link = models.URLField(blank=True, null=True, verbose_name="Ссылка на Yandex Maps")
    yclients_link = models.URLField(blank=True, null=True, verbose_name="Ссылка на YClients")
    yclients_company_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="ID компании в YClients")
    notification_emails = models.TextField(
        "Email для уведомлений о заявках",
        blank=True,
        default="",
        help_text=(
            "По одному email на строку (можно через запятую). Сюда падают "
            "уведомления о заявках с формы «Записаться онлайн» (wizard). "
            "Если пусто — используется ADMIN_NOTIFICATION_EMAIL из окружения."
        ),
    )

    # ── Мессенджеры для быстрых контактов в header ──
    # Каждое поле blank=True — иконка показывается в header только если URL задан.
    contact_whatsapp = models.URLField(
        "WhatsApp", blank=True, default="",
        help_text="Например: https://wa.me/78412393433",
    )
    contact_telegram = models.URLField(
        "Telegram", blank=True, default="",
        help_text="Например: https://t.me/formulatela58",
    )
    contact_vk = models.URLField(
        "VK-сообщения", blank=True, default="",
        help_text="Например: https://vk.me/formulatela",
    )
    contact_max = models.URLField(
        "MAX", blank=True, default="",
        help_text="Например: https://max.ru/formulatela",
    )
    contact_manager_url = models.URLField(
        "Личный контакт менеджера", blank=True, default="",
        help_text="Ссылка на прямой чат с менеджером, например https://t.me/manager_username",
    )

    # ── Реквизиты организации (для YooKassa, оферты, footer) ──
    legal_name = models.CharField(
        "Полное юр. наименование", max_length=200, blank=True, default="",
        help_text="Например: ИП Иванов Иван Иванович или ООО «Название»",
    )
    legal_address = models.CharField(
        "Юридический адрес", max_length=300, blank=True, default="",
    )
    inn = models.CharField(
        "ИНН", max_length=12, blank=True, default="",
        help_text="10 цифр (ООО) или 12 цифр (ИП)",
    )
    ogrn = models.CharField(
        "ОГРН / ОГРНИП", max_length=15, blank=True, default="",
        help_text="13 цифр (ООО) или 15 цифр (ИП)",
    )
    bank_name = models.CharField(
        "Банк", max_length=100, blank=True, default="",
    )
    bank_account = models.CharField(
        "Расчётный счёт", max_length=20, blank=True, default="",
    )
    bank_bik = models.CharField(
        "БИК банка", max_length=9, blank=True, default="",
    )
    bank_corr_account = models.CharField(
        "Корреспондентский счёт", max_length=20, blank=True, default="",
    )

    # ── Feature flags ─────────────────────────────────────────────────
    online_payment_enabled = models.BooleanField(
        "Онлайн-оплата через YooKassa",
        default=False,
        help_text=(
            "Пока выключено — на сайте при записи на услугу клиент видит только "
            "офлайн-способы (наличные/картой в салоне). Включать после модерации "
            "YooKassa и прописанных YOOKASSA_SHOP_ID / YOOKASSA_SECRET_KEY в .env."
        ),
    )

    class Meta:
        verbose_name = "Настройки сайта"
        verbose_name_plural = "Настройки сайта"

    def __str__(self):
        return "Настройки сайта"

    def get_notification_emails(self) -> list[str]:
        """Список email-адресов для уведомлений (по одному на строку)."""
        if not self.notification_emails:
            return []
        result = []
        for raw in self.notification_emails.replace(",", "\n").splitlines():
            email = raw.strip()
            if email and "@" in email:
                result.append(email)
        return result

class Master(models.Model):
    name = models.CharField(max_length=150, verbose_name="ФИО")
    slug = models.SlugField(
        max_length=100, unique=True, blank=True, null=True,
        verbose_name="URL-slug",
        help_text="ЧПУ для /masters/[slug]/. Автозаполняется из ФИО.",
    )
    bio = models.TextField(blank=True, verbose_name="Описание / опыт")
    photo = models.ImageField(upload_to="masters/", blank=True, null=True, verbose_name="Фото")
    services = models.ManyToManyField(Service, related_name="masters", verbose_name="Оказывает услуги")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    specialization = models.CharField(max_length=100, blank=True, null=True, verbose_name="Специализация")
    experience = models.CharField(max_length=100, blank=True, null=True, verbose_name="Опыт")
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Телефон")
    email = models.EmailField(blank=True, null=True, verbose_name="Email")
    working_hours = models.CharField(max_length=255, blank=True, null=True, verbose_name="Часы работы")
    rating = models.DecimalField(max_digits=3, decimal_places=1, blank=True, null=True, verbose_name="Рейтинг")
    photo_mobile = models.ImageField(upload_to="masters/", blank=True, null=True, verbose_name="Фото (мобильное)")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок сортировки")
    education = models.TextField(blank=True, verbose_name="Образование и квалификация", help_text="Разрешён HTML: заголовки h2, списки ul/li")
    work_experience = models.TextField(blank=True, verbose_name="Опыт работы", help_text="HTML разрешён")
    approach = models.TextField(blank=True, verbose_name="Подход к работе", help_text="HTML разрешён")
    reviews_text = models.TextField(blank=True, verbose_name="Отзывы и статистика", help_text="HTML разрешён")

    # Phase 2.3 — маппинг на YClients staff для нативного booking через AI Concierge.
    # Заполняется менеджером через /admin/services_app/master/. Берётся из
    # YClients (Настройки → Сотрудники → ID). Без него native booking невозможен.
    yclients_staff_id = models.CharField(
        "ID сотрудника в YClients",
        max_length=20,
        blank=True,
        null=True,
        db_index=True,
        help_text="Маппинг для AI-помощника на нативную запись через YClients API. "
                  "Возьмите ID из YClients (Настройки → Сотрудники).",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")

    objects = MasterQuerySet.as_manager()

    class Meta:
        verbose_name = "Мастер"
        verbose_name_plural = "Мастера"
        ordering = ["order", "name"]
        indexes = [
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            self.slug = generate_unique_slug(
                Master, self.name, pk=self.pk, max_length=100
            )
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse
        if self.slug:
            return reverse("website:master_detail_by_slug", kwargs={"slug": self.slug})
        return reverse("website:master_detail", kwargs={"master_id": self.pk})

class ServicePackage(models.Model):
    title = models.CharField(max_length=200, verbose_name="Название комплекса")
    description = models.TextField(blank=True, verbose_name="Описание")
    services = models.ManyToManyField(Service, related_name="packages", verbose_name="Услуги в комплексе")
    total_price = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="Цена за комплекс")
    is_popular = models.BooleanField(default=False, verbose_name="Популярный")
    class Meta:
        verbose_name = "Комплекс услуг"
        verbose_name_plural = "Комплексы услуг"
        indexes = [
            models.Index(fields=["is_popular"]),
        ]

    def __str__(self):
        return self.title

class Bundle(models.Model):
    name = models.CharField(max_length=120, verbose_name="Название комплекса", null=True, blank=True)
    fixed_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    description = models.TextField(blank=True, verbose_name="Описание комплекса")
    image = models.ImageField(
        upload_to="bundles/", blank=True, null=True,
        verbose_name="Фото",
        validators=[validate_image_upload],
    )
    image_mobile = models.ImageField(
        upload_to="bundles/", blank=True, null=True,
        verbose_name="Фото (мобильное)",
        validators=[validate_image_upload],
    )
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок сортировки")

    options = models.ManyToManyField('ServiceOption', through='BundleItem', related_name='bundles')

    # --- SEO и ЧПУ ---
    slug = models.SlugField(
        max_length=200, unique=True, blank=True, null=True,
        verbose_name="URL-slug",
        help_text="ЧПУ, например: kompleks-iz-3-massazhei",
    )
    seo_h1 = models.CharField(
        max_length=200, blank=True, default="",
        verbose_name="H1 заголовок",
        help_text="Если пусто — используется название комплекса.",
    )
    seo_title = models.CharField(
        max_length=120, blank=True, default="",
        verbose_name="SEO Title",
        help_text="Для тега title. Если пусто — «название — комплекс услуг».",
    )
    seo_description = models.CharField(
        max_length=300, blank=True, default="",
        verbose_name="SEO Description",
        help_text="Для meta description. До 160 символов.",
    )
    subtitle = models.CharField(
        max_length=300, blank=True, default="",
        verbose_name="Подзаголовок под H1",
    )

    is_active = models.BooleanField(default=True, verbose_name="Активен")
    is_popular = models.BooleanField(default=False, verbose_name="Популярный")
    is_certificate = models.BooleanField(
        default=False, verbose_name="Доступен как сертификат",
        help_text="Показывать на странице /certificates/ как подарочный сертификат.",
    )
    certificate_theme = models.CharField(
        max_length=16,
        choices=CERTIFICATE_THEME_CHOICES,
        default="pink",
        verbose_name="Тема сертификата",
    )

    created_at = models.DateTimeField(auto_now_add=True, null=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, null=True, verbose_name="Обновлён")

    objects = BundleQuerySet.as_manager()

    class Meta:
        verbose_name = "Комплекс (набор услуг)"
        verbose_name_plural = "Комплексы (наборы услуг)"
        indexes = [
            models.Index(fields=["is_active", "is_popular"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        return self.name or f"Bundle #{self.pk}"

    def save(self, *args, **kwargs):
        if not self.slug and self.name:
            self.slug = generate_unique_slug(
                Bundle, self.name, pk=self.pk, max_length=200
            )
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        from django.urls import reverse
        if self.slug:
            return reverse("website:bundle_detail_by_slug", kwargs={"slug": self.slug})
        return reverse("website:bundle_detail", kwargs={"bundle_id": self.pk})

    def total_price(self) -> Decimal:
        """Итоговая цена комплекса.

        Если задано `fixed_price` — возвращает его. Иначе сумма
        `option.price × quantity` по всем BundleItem.
        """
        if self.fixed_price is not None:
            return self.fixed_price
        items = self.items.select_related("option").all()
        total = Decimal("0.00")
        for it in items:
            if it.option and it.option.price is not None:
                total += Decimal(it.option.price) * it.quantity
        return max(Decimal("0.00"), total)

    def total_duration_min(self) -> int:
        """Сумма длительностей всех элементов комплекса (простая сумма)."""
        items = self.items.select_related("option").all()
        return sum((it.option.duration_min if it.option else 0) * it.quantity for it in items)

    def compute_min_totals(self) -> tuple[Decimal, int]:
        """Цена и минимальная длительность с учётом параллельных групп.

        Элементы группируются по `BundleItem.parallel_group`: внутри одной
        группы процедуры идут одновременно — длительность берётся как
        максимум в группе, цены складываются. Между группами длительности
        суммируются, плюс `gap_after_min` каждого элемента.

        Используется на детальной странице/списке комплексов, когда нужно
        показать клиенту, сколько он проведёт в салоне.
        """
        from collections import defaultdict

        items = list(self.items.select_related("option").all())
        if not items:
            return Decimal("0.00"), 0

        groups: dict[int, list] = defaultdict(list)
        gaps_total = 0
        for it in items:
            groups[it.parallel_group].append(it)
            gaps_total += int(it.gap_after_min or 0)

        total_price = Decimal("0.00")
        total_duration = 0
        for group_items in groups.values():
            group_max_duration = 0
            for it in group_items:
                opt = it.option
                if not opt:
                    continue
                if opt.price is not None:
                    total_price += Decimal(opt.price)
                group_max_duration = max(group_max_duration, int(opt.duration_min or 0))
            total_duration += group_max_duration

        total_duration += gaps_total
        return total_price, total_duration

class BundleItem(models.Model):
    bundle = models.ForeignKey(Bundle, on_delete=models.CASCADE, related_name="items")
    option = models.ForeignKey(
        ServiceOption, on_delete=models.PROTECT, related_name="bundle_items", null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    
    order = models.PositiveIntegerField(default=1)
    parallel_group = models.PositiveIntegerField(default=1)
    gap_after_min = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

class BundleRequest(models.Model):
    """Заявка на комплекс — сохраняется в БД + уведомление админу"""
    bundle = models.ForeignKey(
        Bundle, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="requests", verbose_name="Комплекс"
    )
    bundle_name = models.CharField(max_length=200, verbose_name="Название комплекса")
    client_name = models.CharField(max_length=150, verbose_name="Имя клиента")
    client_phone = models.CharField(max_length=30, verbose_name="Телефон")
    client_email = models.EmailField(blank=True, verbose_name="Email")
    comment = models.TextField(blank=True, verbose_name="Комментарий")
    is_processed = models.BooleanField(default=False, verbose_name="Обработана")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата заявки")

    class Meta:
        verbose_name = "Заявка на комплекс"
        verbose_name_plural = "Заявки на комплексы"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.client_name} — {self.bundle_name} ({self.created_at:%d.%m.%Y %H:%M})"



class Promotion(models.Model):
    title = models.CharField(max_length=200, verbose_name="Название акции")
    subtitle = models.CharField(max_length=200, blank=True, verbose_name="Подзаголовок")
    description = models.TextField(blank=True, verbose_name="Описание")
    features = models.JSONField(blank=True, null=True, verbose_name="Особенности/преимущества")
    image = models.ImageField(upload_to="promotions/", blank=True, null=True, verbose_name="Изображение")
    
    options = models.ManyToManyField(
        ServiceOption, blank=True, related_name="promotions", verbose_name="Варианты услуг"
    )

    discount_percent = models.PositiveSmallIntegerField(default=0, verbose_name="Скидка, %")
    price_note = models.CharField(max_length=200, blank=True, verbose_name="Примечание по цене")
    promo_code = models.CharField(max_length=50, blank=True, verbose_name="Промокод")

    starts_at = models.DateField(blank=True, null=True, verbose_name="Начало")
    ends_at = models.DateField(blank=True, null=True, verbose_name="Окончание")
    is_active = models.BooleanField(default=True, verbose_name="Активна")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок показа")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")

    objects = PromotionQuerySet.as_manager()

    class Meta:
        verbose_name = "Акция"
        verbose_name_plural = "Акции"
        ordering = ["order", "-starts_at", "title"]
        indexes = [
            models.Index(fields=["is_active", "order"]),
        ]

    def __str__(self) -> str:
        return self.title

class Review(models.Model):
    """Модель отзывов клиентов"""
    author_name = models.CharField(max_length=100, verbose_name="Имя автора")
    text = models.TextField(verbose_name="Текст отзыва")
    rating = models.PositiveSmallIntegerField(
        default=5,
        choices=[(i, i) for i in range(1, 6)],
        verbose_name="Рейтинг (1-5)"
    )
    date = models.DateField(verbose_name="Дата отзыва")
    is_active = models.BooleanField(default=True, verbose_name="Активен")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок показа")
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")

    objects = ReviewQuerySet.as_manager()

    class Meta:
        verbose_name = "Отзыв"
        verbose_name_plural = "Отзывы"
        ordering = ["order", "-date", "-created_at"]
        indexes = [
            models.Index(fields=["is_active", "order"]),
        ]

    def __str__(self):
        return f"{self.author_name} - {self.date}"

    def get_initial_letter(self):
        """Возвращает первую букву имени для аватара"""
        return self.author_name[0].upper() if self.author_name else "?"


class BotUser(models.Model):
    """Пользователь MAX-бота (для персонализации диалога между визитами)."""

    SOURCE_NAME = "MAX"

    max_user_id = models.BigIntegerField("ID в MAX", unique=True, db_index=True)
    display_name = models.CharField("Имя из MAX", max_length=200, blank=True, default="")
    client_name = models.CharField("Имя как назвался боту", max_length=150, blank=True, default="")
    client_phone = models.CharField("Телефон", max_length=20, blank=True, default="")
    chat_id = models.BigIntegerField(
        "Chat ID в MAX",
        null=True, blank=True, db_index=True,
        help_text="Для проактивных сообщений (напоминания о записях). "
                  "Обновляется на каждом event'е от пользователя.",
    )
    first_seen = models.DateTimeField("Первый визит", auto_now_add=True)
    last_seen = models.DateTimeField("Последний визит", auto_now=True)
    context = models.JSONField(
        "Контекст", default=dict, blank=True,
        help_text='JSON: {"services_viewed": [slug], "faqs_viewed": [id], "bookings_count": N}',
    )
    food_scanner_consent_at = models.DateTimeField(
        "152-ФЗ согласие food scanner",
        null=True, blank=True,
        help_text=(
            "Timestamp когда пользователь нажал «Согласен» на обработку "
            "фото еды (152-ФЗ). NULL = не давал согласия, scanner недоступен."
        ),
    )

    class Meta:
        verbose_name = "Пользователь MAX-бота"
        verbose_name_plural = "Пользователи MAX-бота"
        ordering = ["-last_seen"]

    def __str__(self):
        name = self.client_name or self.display_name or f"#{self.max_user_id}"
        return f"{name} ({self.SOURCE_NAME}: {self.max_user_id})"


class HelpArticle(models.Model):
    """FAQ-статья для MAX-бота (отдельно от модели FAQ — та привязана к категориям услуг)."""

    question = models.CharField("Вопрос", max_length=255)
    answer = models.TextField("Ответ")
    order = models.PositiveIntegerField("Порядок", default=0)
    is_active = models.BooleanField("Активна", default=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    objects = HelpArticleQuerySet.as_manager()

    class Meta:
        verbose_name = "Статья помощи (бот)"
        verbose_name_plural = "Статьи помощи (бот)"
        ordering = ["order", "id"]

    def __str__(self):
        return self.question


class BotInquiry(models.Model):
    """Вопрос клиента, на который AI-помощник не нашёл ответ → передан менеджеру.

    Workflow (Фаза 2.1):
    1. Клиент пишет свободный текст в MAX-бот
    2. AI-помощник через MCP+RAG не нашёл подходящую HelpArticle
    3. Создаётся BotInquiry, клиенту: «Передал вопрос менеджеру, ответит в течение часа»
    4. Менеджер видит inquiry в админке (фильтр unanswered), пишет reply_text
    5. Action «📤 Отправить ответ клиенту» → bot.send_message в исходный chat_id +
       sent_to_max=True + replied_by + replied_at
    """

    bot_user = models.ForeignKey(
        "BotUser",
        on_delete=models.PROTECT,  # PROTECT — не теряем историю при ошибке cleanup
        related_name="inquiries",
        verbose_name="Пользователь бота",
    )
    chat_id = models.BigIntegerField(
        "ID чата в MAX",
        help_text="Куда отправить ответ менеджера. У одного BotUser может быть несколько чатов.",
    )
    question = models.TextField("Вопрос клиента")
    asked_at = models.DateTimeField("Задан", auto_now_add=True)

    reply_text = models.TextField(
        "Ответ менеджера",
        blank=True,
        default="",
        help_text="Заполните чтобы action «Отправить» стал доступен.",
    )
    replied_at = models.DateTimeField("Отвечен", null=True, blank=True)
    replied_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,  # удаление автора не должно стирать ответ
        null=True, blank=True,
        related_name="bot_inquiries_replied",
        verbose_name="Кто ответил",
    )
    sent_to_max = models.BooleanField(
        "Доставлен в MAX",
        default=False,
        help_text="True после успешного bot.send_message клиенту.",
    )

    objects = BotInquiryQuerySet.as_manager()

    class Meta:
        verbose_name = "Вопрос клиента (бот)"
        verbose_name_plural = "Вопросы клиентов (бот)"
        ordering = ["-asked_at"]

    def __str__(self):
        preview = self.question[:60] + ("…" if len(self.question) > 60 else "")
        status = "✓" if self.sent_to_max else ("📝" if self.reply_text else "❓")
        return f"{status} {preview}"


BOOKING_SOURCE_CHOICES = [
    ("wizard", "Форма-мастер"),
    ("bot_max", "MAX-бот"),
    ("yclients_admin", "YClients админка"),
    ("other", "Другое"),
]


class BookingRequest(models.Model):
    """Заявка на запись (визард на сайте или MAX-бот)."""
    category_name = models.CharField("Категория", max_length=200, blank=True, default="")
    service_name = models.CharField("Услуга", max_length=200)
    master_name = models.CharField("Предпочитаемый мастер", max_length=150, blank=True, default="")
    client_name = models.CharField("Имя клиента", max_length=100)
    client_phone = models.CharField("Телефон", max_length=30)
    comment = models.TextField("Комментарий", blank=True, default="")
    is_processed = models.BooleanField("Обработана", default=False)
    created_at = models.DateTimeField("Дата заявки", auto_now_add=True)
    source = models.CharField(
        "Источник", max_length=20, choices=BOOKING_SOURCE_CHOICES, default="wizard",
    )
    bot_user = models.ForeignKey(
        BotUser, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="booking_requests", verbose_name="Пользователь бота",
    )

    class Meta:
        verbose_name = "Заявка на запись"
        verbose_name_plural = "Заявки на запись"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.client_name} — {self.service_name} ({self.created_at:%d.%m.%Y %H:%M})"


# ── Заказы и сертификаты ──────────────────────────────────────────────

ORDER_TYPE_CHOICES = [
    ("certificate", "Сертификат"),
    ("bundle", "Комплекс"),
    ("booking", "Запись"),
    ("service", "Услуга"),
]

ORDER_STATUS_CHOICES = [
    ("pending", "Ожидает"),
    ("confirmed", "Подтверждён"),
    ("paid", "Оплачен"),
    ("completed", "Выполнен"),
    ("cancelled", "Отменён"),
]

PAYMENT_METHOD_CHOICES = [
    ("online", "Онлайн"),
    ("cash", "Наличными в салоне"),
    ("card_offline", "Картой в салоне"),
]

PAYMENT_STATUS_CHOICES = [
    ("not_required", "Не требуется"),
    ("pending", "Ожидает оплаты"),
    ("waiting_for_capture", "Ожидает подтверждения"),
    ("succeeded", "Оплачен"),
    ("canceled", "Отменён"),
]


class Order(models.Model):
    """Универсальный заказ — сертификат, комплекс, запись, услуга"""
    number = models.CharField(
        max_length=20, unique=True, blank=True,
        verbose_name="Номер заказа",
    )
    order_type = models.CharField(
        max_length=20, choices=ORDER_TYPE_CHOICES,
        verbose_name="Тип заказа",
    )
    status = models.CharField(
        max_length=20, choices=ORDER_STATUS_CHOICES,
        default="pending", verbose_name="Статус",
    )

    client_name = models.CharField(max_length=150, verbose_name="Имя клиента")
    client_phone = models.CharField(max_length=30, verbose_name="Телефон")
    client_email = models.EmailField(blank=True, verbose_name="Email")

    total_amount = models.DecimalField(
        max_digits=8, decimal_places=0, default=0,
        verbose_name="Сумма",
    )

    # ── Платёжные поля (YooKassa) ─────────────────────────────────────
    payment_method = models.CharField(
        max_length=20, blank=True, default="",
        choices=PAYMENT_METHOD_CHOICES,
        verbose_name="Способ оплаты",
    )
    payment_status = models.CharField(
        max_length=25, default="not_required",
        choices=PAYMENT_STATUS_CHOICES,
        verbose_name="Статус оплаты",
    )
    payment_id = models.CharField(
        max_length=100, blank=True, verbose_name="ID платежа",
        help_text="YooKassa payment id (uuid)",
    )
    payment_url = models.URLField(
        blank=True, default="", verbose_name="Ссылка на оплату",
        help_text="confirmation_url от YooKassa",
    )
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата оплаты")

    comment = models.TextField(blank=True, verbose_name="Комментарий")
    admin_note = models.TextField(blank=True, verbose_name="Заметка администратора")

    # ── Связи с товаром/услугой ───────────────────────────────────────
    # Для order_type="bundle"
    bundle = models.ForeignKey(
        "Bundle", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="orders",
        verbose_name="Комплекс",
    )
    # Для order_type="service"
    service = models.ForeignKey(
        "Service", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="orders",
        verbose_name="Услуга",
    )
    service_option = models.ForeignKey(
        "ServiceOption", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="orders",
        verbose_name="Вариант услуги",
    )

    # ── Параметры записи (service/booking) ────────────────────────────
    staff_id = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="ID мастера (YClients)",
    )
    scheduled_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Дата/время визита",
    )
    yclients_record_id = models.CharField(
        max_length=50, blank=True, default="",
        verbose_name="YClients record id",
    )
    yclients_record_hash = models.CharField(
        max_length=100, blank=True, default="",
        verbose_name="YClients record hash",
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлён")

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "order_type"]),
            models.Index(fields=["number"]),
            models.Index(fields=["payment_status"]),
        ]

    def __str__(self):
        return f"{self.number} — {self.get_order_type_display()} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self._generate_number()
        super().save(*args, **kwargs)

    def _generate_number(self):
        import random
        import string
        from django.utils import timezone
        date_part = timezone.now().strftime("%Y%m%d")
        rand_part = "".join(random.choices(string.digits, k=4))
        return f"FT-{date_part}-{rand_part}"


CERT_TYPE_CHOICES = [
    ("nominal", "На сумму"),
    ("service", "На услугу"),
    ("bundle", "Комплекс"),
]

CERT_STATUS_CHOICES = [
    ("pending", "Ожидает оплаты"),
    ("paid", "Оплачен"),
    ("delivered", "Вручён"),
    ("redeemed", "Использован"),
    ("expired", "Истёк"),
    ("cancelled", "Отменён"),
]


class GiftCertificate(models.Model):
    """Подарочный сертификат"""
    order = models.ForeignKey(
        Order, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="certificates", verbose_name="Заказ",
    )
    code = models.CharField(
        max_length=16, unique=True, blank=True,
        verbose_name="Код сертификата",
    )
    certificate_type = models.CharField(
        max_length=10, choices=CERT_TYPE_CHOICES,
        default="nominal", verbose_name="Тип",
    )

    # Номинал (для типа nominal)
    nominal = models.DecimalField(
        max_digits=8, decimal_places=0, default=0,
        verbose_name="Номинал (руб.)",
    )
    # Услуга (для типа service)
    service = models.ForeignKey(
        Service, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="gift_certificates", verbose_name="Услуга",
    )
    service_option = models.ForeignKey(
        ServiceOption, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="gift_certificates", verbose_name="Вариант услуги",
    )
    # Комплекс (для типа bundle)
    bundle = models.ForeignKey(
        "Bundle", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="gift_certificates", verbose_name="Комплекс",
    )

    # Оформление (тема) сертификата
    theme = models.CharField(
        max_length=16, choices=CERTIFICATE_THEME_CHOICES,
        default="pink", verbose_name="Оформление",
    )

    # Изображение сертификата
    image = models.ImageField(
        upload_to="certificates/",
        blank=True, null=True,
        verbose_name="Изображение сертификата",
        help_text="JPG/PNG/WebP до 5 МБ. Дизайн сертификата для отправки клиенту.",
        validators=[validate_image_upload],
    )

    # Покупатель
    buyer_name = models.CharField(max_length=150, verbose_name="Имя покупателя")
    buyer_phone = models.CharField(max_length=30, verbose_name="Телефон покупателя")
    buyer_email = models.EmailField(blank=True, verbose_name="Email покупателя")

    # Получатель
    recipient_name = models.CharField(
        max_length=150, blank=True, verbose_name="Имя получателя",
    )
    recipient_phone = models.CharField(
        max_length=30, blank=True, verbose_name="Телефон получателя",
    )
    message = models.TextField(blank=True, verbose_name="Пожелание на сертификате")

    # Статус и даты
    status = models.CharField(
        max_length=12, choices=CERT_STATUS_CHOICES,
        default="pending", verbose_name="Статус",
    )
    valid_from = models.DateField(verbose_name="Действует с")
    valid_until = models.DateField(verbose_name="Действует до")
    paid_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата оплаты")
    delivered_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Дата вручения",
    )
    redeemed_at = models.DateTimeField(
        null=True, blank=True, verbose_name="Дата использования",
    )

    is_active = models.BooleanField(default=True, verbose_name="Активен")
    admin_note = models.TextField(blank=True, verbose_name="Заметка администратора")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")

    class Meta:
        verbose_name = "Подарочный сертификат"
        verbose_name_plural = "Подарочные сертификаты"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "is_active"]),
            models.Index(fields=["code"]),
            models.Index(fields=["valid_until"]),
        ]

    def __str__(self):
        value = (
            f"{self.nominal} \u20bd"
            if self.certificate_type == "nominal"
            else str(self.service or "\u2014")
        )
        return f"{self.code} \u2014 {value} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self._generate_code()
        super().save(*args, **kwargs)

    def _generate_code(self):
        import random
        import string
        while True:
            part1 = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
            part2 = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
            code = f"FT-{part1}-{part2}"
            if not GiftCertificate.objects.filter(code=code).exists():
                return code

    @property
    def is_valid(self):
        from django.utils import timezone
        # localdate() уважает settings.TIME_ZONE (Europe/Moscow), а now().date()
        # всегда возвращает UTC и ломает сравнение в 00:00–03:00 MSK.
        today = timezone.localdate()
        return (
            self.status in ("paid", "delivered")
            and self.is_active
            and self.valid_from <= today <= self.valid_until
        )

    @property
    def remaining_value(self):
        if self.certificate_type != "nominal":
            return None
        used = sum(r.amount for r in self.redemptions.all())
        return max(self.nominal - used, Decimal("0"))


class CertificateRedemption(models.Model):
    """Журнал использования сертификата"""
    certificate = models.ForeignKey(
        GiftCertificate, on_delete=models.CASCADE,
        related_name="redemptions", verbose_name="Сертификат",
    )
    amount = models.DecimalField(
        max_digits=8, decimal_places=0, verbose_name="Списано (руб.)",
    )
    service_name = models.CharField(max_length=200, verbose_name="Услуга")
    redeemed_by = models.CharField(max_length=150, verbose_name="Клиент")
    note = models.TextField(blank=True, verbose_name="Комментарий")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата списания")

    class Meta:
        verbose_name = "Списание по сертификату"
        verbose_name_plural = "Списания по сертификатам"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.certificate.code}: -{self.amount} \u20bd ({self.created_at:%d.%m.%Y})"


# \u2500\u2500 Phase 2.3 AI Concierge \u2014 Conversation + Message \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500


class Conversation(models.Model):
    """\u0414\u0438\u0430\u043b\u043e\u0433 \u043a\u043b\u0438\u0435\u043d\u0442-AI \u0432 MAX-\u0431\u043e\u0442\u0435 \u2014 single sit-down (\u0437\u0430\u043a\u0440\u044b\u0432\u0430\u0435\u0442\u0441\u044f \u043f\u0440\u0438 /start).

    \u0418\u0441\u0442\u043e\u0440\u0438\u044f \u043d\u0443\u0436\u043d\u0430 \u0434\u043b\u044f:
    - Multi-turn \u0432 LLM (\u043f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 ~10 messages \u0432 context'\u0435)
    - Admin-\u0438\u043d\u0441\u043f\u0435\u043a\u0446\u0438\u044f \u043a\u043e\u043d\u0444\u043b\u0438\u043a\u0442\u043e\u0432 \u00ab\u0431\u043e\u0442 \u0441\u043a\u0430\u0437\u0430\u043b X\u00bb
    - \u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a\u0430: \u043a\u0430\u043a\u0438\u0435 \u0438\u043d\u0442\u0435\u043d\u0442\u044b \u0437\u0430\u0432\u0435\u0440\u0448\u0430\u044e\u0442\u0441\u044f booking'\u043e\u043c, \u0447\u0430\u0441\u0442\u044b\u0435 off-topic, etc.

    \u041e\u0434\u0438\u043d BotUser \u2192 \u043c\u043d\u043e\u0433\u043e Conversation. \u0410\u043a\u0442\u0438\u0432\u043d\u0430\u044f (is_active=True) \u043e\u0434\u043d\u0430;
    \u043f\u0440\u0438 /start \u0438\u043b\u0438 bot_started \u0441\u0442\u0430\u0440\u0430\u044f \u0437\u0430\u043a\u0440\u044b\u0432\u0430\u0435\u0442\u0441\u044f, \u043e\u0442\u043a\u0440\u044b\u0432\u0430\u0435\u0442\u0441\u044f \u043d\u043e\u0432\u0430\u044f.

    `outcome` (Phase 1 Learning Roadmap 2026-04-28) \u2014 \u0434\u043b\u044f analytics \u0438 LLM
    meta-analysis: success / abandoned / redirected / error. \u0417\u0430\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f
    \u043f\u0440\u0438 \u0437\u0430\u043a\u0440\u044b\u0442\u0438\u0438 conversation. \u041f\u0443\u0441\u0442\u043e\u0435 \u0434\u043b\u044f is_active=True (\u0434\u0438\u0430\u043b\u043e\u0433 \u0438\u0434\u0451\u0442).
    """

    class Outcome(models.TextChoices):
        SUCCESS = "success", "\u0417\u0430\u043a\u0440\u044b\u0442\u0430 \u0437\u0430\u043f\u0438\u0441\u044c\u044e"
        ABANDONED = "abandoned", "\u041a\u043b\u0438\u0435\u043d\u0442 \u0443\u0448\u0451\u043b / \u043e\u0442\u043c\u0435\u043d\u0438\u043b"
        REDIRECTED = "redirected", "\u041f\u0435\u0440\u0435\u0434\u0430\u043d \u043c\u0435\u043d\u0435\u0434\u0436\u0435\u0440\u0443"
        ERROR = "error", "\u0422\u0435\u0445\u043d\u0438\u0447\u0435\u0441\u043a\u0438\u0439 \u0441\u0431\u043e\u0439"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bot_user = models.ForeignKey(
        "BotUser",
        on_delete=models.CASCADE,
        related_name="conversations",
        verbose_name="\u041f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u044c \u0431\u043e\u0442\u0430",
    )
    is_active = models.BooleanField(
        "\u0410\u043a\u0442\u0438\u0432\u043d\u044b\u0439",
        default=True,
        help_text="False \u043a\u043e\u0433\u0434\u0430 \u0434\u0438\u0430\u043b\u043e\u0433 \u0437\u0430\u043a\u0440\u044b\u0442 (\u043d\u043e\u0432\u044b\u0439 /start, \u044f\u0432\u043d\u044b\u0439 cancel, "
                  "\u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0439 cleanup \u0447\u0435\u0440\u0435\u0437 7+ \u0434\u043d\u0435\u0439 \u0431\u0435\u0437 \u0430\u043a\u0442\u0438\u0432\u043d\u043e\u0441\u0442\u0438).",
    )
    outcome = models.CharField(
        "\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442",
        max_length=16,
        choices=Outcome.choices,
        blank=True,
        default="",
        db_index=True,
        help_text="\u0417\u0430\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f \u043f\u0440\u0438 \u0437\u0430\u043a\u0440\u044b\u0442\u0438\u0438 conversation. \u041f\u0443\u0441\u0442\u043e\u0435 \u2014 \u0434\u0438\u0430\u043b\u043e\u0433 \u0430\u043a\u0442\u0438\u0432\u0435\u043d.",
    )
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="\u0423\u0434\u0430\u043b\u0451\u043d")
    last_message_at = models.DateTimeField(
        null=True, blank=True, verbose_name="\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0435\u0435 \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="\u0421\u043e\u0437\u0434\u0430\u043d")

    class Meta:
        verbose_name = "\u0414\u0438\u0430\u043b\u043e\u0433 AI (\u0431\u043e\u0442)"
        verbose_name_plural = "\u0414\u0438\u0430\u043b\u043e\u0433\u0438 AI (\u0431\u043e\u0442)"
        ordering = ["-last_message_at", "-created_at"]
        indexes = [
            models.Index(fields=["bot_user", "-last_message_at"]),
            models.Index(fields=["is_active", "-last_message_at"]),
        ]

    def __str__(self):
        short = str(self.id)[:8]
        return f"Conversation {short} (bot_user={self.bot_user_id})"


class BookingReminder(models.Model):
    """Напоминание о YClients-записи: T-24h + T-2h.

    Создаётся в execute_confirm_booking сразу после успешного yclients_record_id.
    Обрабатывается Celery beat (send_due_reminders + escalate_stale_reminders).
    Закрывается клиентом (CONFIRMED/CANCELLED) или эскалацией менеджеру.
    """

    class Kind(models.TextChoices):
        DAY_BEFORE = "day_before", "За день (T-24h)"
        TWO_HOURS = "two_hours", "За 2 часа (T-2h)"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает отправки"
        SENT_NO_REPLY = "sent_no_reply", "Отправлено, без ответа"
        SENT = "sent", "Отправлено (T-2h без кнопок)"
        CONFIRMED = "confirmed", "Клиент подтвердил"
        RESCHEDULE_REQUESTED = "reschedule", "Клиент просит перенести"
        CANCELLED = "cancelled", "Клиент отменил"
        ESCALATED = "escalated", "Менеджер уведомлён"
        FAILED = "failed", "Ошибка отправки"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bot_user = models.ForeignKey(
        "BotUser", on_delete=models.CASCADE, related_name="reminders",
        verbose_name="Пользователь бота",
    )
    booking_request = models.ForeignKey(
        "BookingRequest", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reminders", verbose_name="Заявка",
    )
    yclients_record_id = models.CharField(
        "YClients record ID", max_length=64, db_index=True, blank=True,
    )
    chat_id = models.BigIntegerField(
        "Chat ID (snapshot)",
        help_text="Snapshot — chat_id может протухнуть в BotUser",
    )
    visit_at = models.DateTimeField("Время визита")
    kind = models.CharField("Вид", max_length=16, choices=Kind.choices)
    status = models.CharField(
        "Статус", max_length=16, choices=Status.choices,
        default=Status.PENDING, db_index=True,
    )
    scheduled_at = models.DateTimeField("Запланировано на")
    sent_at = models.DateTimeField("Отправлено", null=True, blank=True)
    replied_at = models.DateTimeField("Ответ клиента", null=True, blank=True)
    master_name = models.CharField("Мастер", max_length=120, blank=True)
    service_name = models.CharField("Услуга", max_length=200, blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "Напоминание о записи"
        verbose_name_plural = "Напоминания о записях"
        unique_together = [("yclients_record_id", "kind")]
        indexes = [
            models.Index(fields=["status", "scheduled_at"]),
            models.Index(fields=["kind", "visit_at"]),
        ]
        ordering = ["scheduled_at"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.master_name} {self.visit_at:%d.%m %H:%M}"


class Message(models.Model):
    """\u041e\u0434\u043d\u043e \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u0432 \u0434\u0438\u0430\u043b\u043e\u0433\u0435 AI Concierge \u2014 user / assistant / tool / system.

    \u0414\u043b\u044f assistant-\u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0439 \u0441 tool-call:
    - action_type = \u00abshow_masters\u00bb / \u00abshow_slots\u00bb / \u00abconfirm_booking\u00bb / ...
    - action_data = JSON c \u043f\u043e\u043b\u0435\u0437\u043d\u043e\u0439 \u043d\u0430\u0433\u0440\u0443\u0437\u043a\u043e\u0439 \u0434\u043b\u044f \u0440\u0435\u043d\u0434\u0435\u0440\u0430 UI

    \u0414\u043b\u044f tool-result \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0439:
    - tool_call = raw OpenAI tool_call object (audit/debug)
    - tool_call_id = \u0441\u0432\u044f\u0437\u044c \u0441 originating tool_call

    Telemetry (assistant only): tokens_in/out + latency_ms \u2014 observability.
    """

    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        TOOL = "tool", "Tool"
        SYSTEM = "system", "System"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="\u0414\u0438\u0430\u043b\u043e\u0433",
    )
    role = models.CharField("\u0420\u043e\u043b\u044c", max_length=16, choices=Role.choices)
    content = models.TextField("\u0421\u043e\u0434\u0435\u0440\u0436\u0438\u043c\u043e\u0435", blank=True, default="")
    rendered_text = models.TextField(
        "\u041e\u0442\u0440\u0435\u043d\u0434\u0435\u0440\u0435\u043d\u043d\u044b\u0439 \u0442\u0435\u043a\u0441\u0442 (\u0447\u0442\u043e \u0443\u0432\u0438\u0434\u0435\u043b \u043a\u043b\u0438\u0435\u043d\u0442)",
        blank=True, default="",
    )

    # Action attached to assistant message \u2014 \u0434\u043b\u044f \u0440\u0435\u043d\u0434\u0435\u0440\u0430 UI \u043a\u0430\u0440\u0442\u043e\u0447\u043a\u0438.
    # action_type \u043a\u0430\u043a raw string (\u043d\u0435 enum) \u2014 \u0440\u0430\u0441\u0448\u0438\u0440\u044f\u0435\u0442\u0441\u044f \u0431\u0435\u0437 \u043c\u0438\u0433\u0440\u0430\u0446\u0438\u0439.
    action_type = models.CharField("\u0422\u0438\u043f action", max_length=32, blank=True, default="")
    action_data = models.JSONField("\u0414\u0430\u043d\u043d\u044b\u0435 action", null=True, blank=True)

    # Raw OpenAI tool_call object \u2014 kept for audit/debug.
    tool_call = models.JSONField("Tool call (raw)", null=True, blank=True)
    tool_call_id = models.CharField("ID tool_call", max_length=64, blank=True, default="")

    # Telemetry \u2014 populated for assistant messages.
    tokens_in = models.IntegerField("\u0422\u043e\u043a\u0435\u043d\u044b \u0432\u0445\u043e\u0434", default=0)
    tokens_out = models.IntegerField("\u0422\u043e\u043a\u0435\u043d\u044b \u0432\u044b\u0445\u043e\u0434", default=0)
    latency_ms = models.IntegerField("Latency, \u043c\u0441", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="\u0421\u043e\u0437\u0434\u0430\u043d\u043e")

    class Meta:
        verbose_name = "\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 AI (\u0431\u043e\u0442)"
        verbose_name_plural = "\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u044f AI (\u0431\u043e\u0442)"
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self):
        preview = self.content[:50] + ("\u2026" if len(self.content) > 50 else "")
        return f"{self.role}: {preview}"


class FewShotExample(models.Model):
    """\u041a\u0443\u0440\u0438\u0440\u0443\u0435\u043c\u0430\u044f user\u2192assistant \u043f\u0430\u0440\u0430 \u0438\u0437 \u0443\u0441\u043f\u0435\u0448\u043d\u043e\u0433\u043e \u0434\u0438\u0430\u043b\u043e\u0433\u0430 \u2014 \u0434\u043b\u044f injection \u0432 prompt.

    Phase 2.4 \u00abAuto-tune #1\u00bb. Cron `collect_success_examples` (\u0432\u043e\u0441\u043a\u0440\u0435\u0441\u0435\u043d\u044c\u0435
    22:00 \u041c\u0421\u041a) \u043a\u0430\u0436\u0434\u0443\u044e \u043d\u0435\u0434\u0435\u043b\u044e \u0432\u044b\u0431\u0438\u0440\u0430\u0435\u0442 \u0434\u0438\u0430\u043b\u043e\u0433\u0438 \u0441 `outcome=success`, \u0440\u0435\u0436\u0435\u0442 \u0438\u0445
    \u043d\u0430 user\u2192assistant \u043f\u0430\u0440\u044b, \u0434\u0435\u0434\u0443\u043f\u0438\u0442 \u0438 \u0441\u043e\u0445\u0440\u0430\u043d\u044f\u0435\u0442. `ai_prompts.render_system_prompt`
    \u043f\u043e\u0434\u0433\u0440\u0443\u0436\u0430\u0435\u0442 top-10 active \u0438 \u0432\u0441\u0442\u0430\u0432\u043b\u044f\u0435\u0442 \u0431\u043b\u043e\u043a \u00ab\u041f\u0420\u0418\u041c\u0415\u0420\u042b \u0425\u041e\u0420\u041e\u0428\u0418\u0425 \u041e\u0422\u0412\u0415\u0422\u041e\u0412\u00bb.

    \u041c\u0435\u043d\u0435\u0434\u0436\u0435\u0440 \u0432 admin \u043c\u043e\u0436\u0435\u0442 \u0432\u044b\u043a\u043b\u044e\u0447\u0438\u0442\u044c \u043a\u0440\u0438\u0432\u043e\u0439 \u043f\u0440\u0438\u043c\u0435\u0440 (is_active=False) \u2014 \u043e\u043d
    \u0438\u0441\u0447\u0435\u0437\u043d\u0435\u0442 \u0438\u0437 prompt'\u0430 \u043d\u0430 \u0441\u043b\u0435\u0434\u0443\u044e\u0449\u0435\u043c turn'\u0435.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_text = models.TextField("\u0421\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435 \u043a\u043b\u0438\u0435\u043d\u0442\u0430")
    assistant_text = models.TextField("\u041e\u0442\u0432\u0435\u0442 \u0431\u043e\u0442\u0430 (rendered)")
    source_conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="few_shot_examples",
        verbose_name="\u0418\u0441\u0442\u043e\u0447\u043d\u0438\u043a (\u0434\u0438\u0430\u043b\u043e\u0433)",
    )
    is_active = models.BooleanField("\u0410\u043a\u0442\u0438\u0432\u0435\u043d (\u043f\u043e\u043f\u0430\u0434\u0430\u0435\u0442 \u0432 prompt)", default=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="\u0421\u043e\u0437\u0434\u0430\u043d")

    class Meta:
        verbose_name = "Few-shot \u043f\u0440\u0438\u043c\u0435\u0440 (auto-tune)"
        verbose_name_plural = "Few-shot \u043f\u0440\u0438\u043c\u0435\u0440\u044b (auto-tune)"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "-created_at"]),
        ]

    def __str__(self):
        prv = self.user_text[:60] + ("\u2026" if len(self.user_text) > 60 else "")
        return f"{prv}"