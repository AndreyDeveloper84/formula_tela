from django.db import models
from django.db.models import Q 
from decimal import Decimal

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
        help_text="Для <meta description>. До 160 символов."
    )
    seo_h1 = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="H1 заголовок",
        help_text="Если пусто — используется название услуги."
    )
    subtitle = models.CharField(
        max_length=300,
        blank=True,
        verbose_name="Подзаголовок",
        help_text="Текст под H1 на странице услуги."
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name="Порядок сортировки"
    )
    
    class Meta:
        verbose_name = "Услуга"
        verbose_name_plural = "Услуги"
        #ordering = ["order", "name"]
        indexes = [
            models.Index(fields=["is_active", "is_popular"]),
        ]

    def __str__(self):
        return self.name
    

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
    
    class Meta:
        ordering = ["order", "name"]
        verbose_name = "Категория услуг"
        verbose_name_plural = "Категории услуг"

    def __str__(self):
        return self.name


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
    ("video", "Видео (YouTube/ссылка)"),
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
        help_text="JPG/PNG/WebP. Рекомендуемый размер: 800×600px."
    )
    image_mobile = models.ImageField(
        upload_to="services/gallery/mobile/",
        blank=True,
        null=True,
        verbose_name="Мобильная версия",
        help_text="Для экранов <768px. Если пусто — используется основное."
    )
    video_url = models.URLField(
        blank=True,
        verbose_name="URL видео",
        help_text="YouTube или Vimeo ссылка. Пример: https://www.youtube.com/embed/XXXXX"
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

    class Meta:
        verbose_name = "Настройки сайта"
        verbose_name_plural = "Настройки сайта"

    def __str__(self):
        return "Настройки сайта"

class Master(models.Model):
    name = models.CharField(max_length=150, verbose_name="ФИО")
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
    education = models.TextField(blank=True, verbose_name="Образование и квалификация", help_text="HTML: <h2>, <ul>, <li>")
    work_experience = models.TextField(blank=True, verbose_name="Опыт работы", help_text="HTML разрешён")
    approach = models.TextField(blank=True, verbose_name="Подход к работе", help_text="HTML разрешён")
    reviews_text = models.TextField(blank=True, verbose_name="Отзывы и статистика", help_text="HTML разрешён")

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата обновления")
    
    class Meta:
        verbose_name = "Мастер"
        verbose_name_plural = "Мастера"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

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
    discount = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))

    description = models.TextField(blank=True, verbose_name="Описание комплекса")
    image = models.ImageField(upload_to="bundles/", blank=True, null=True, verbose_name="Фото")
    image_mobile = models.ImageField(upload_to="bundles/", blank=True, null=True, verbose_name="Фото (мобильное)")
    order = models.PositiveIntegerField(default=0, verbose_name="Порядок сортировки")

    options = models.ManyToManyField('ServiceOption', through='BundleItem', related_name='bundles')

    is_active = models.BooleanField(default=True, verbose_name="Активен")
    is_popular = models.BooleanField(default=False, verbose_name="Популярный")
    
    class Meta:
        verbose_name = "Комплекс (набор услуг)"
        verbose_name_plural = "Комплексы (наборы услуг)"
        indexes = [
            models.Index(fields=["is_active", "is_popular"]),
        ]

    def __str__(self):
        return self.name

    def total_price(self) -> Decimal:
        if self.fixed_price is not None:
            return self.fixed_price
        items = self.items.select_related("option").all()
        total = Decimal("0.00")
        for it in items:
            if it.option and it.option.price is not None:
                total += Decimal(it.option.price) * it.quantity
        return max(Decimal("0.00"), total - self.discount)

    def total_duration_min(self) -> int:
        items = self.items.select_related("option").all()
        return sum((it.option.duration_min if it.option else 0) * it.quantity for it in items)

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


class BookingRequest(models.Model):
    """Заявка на запись через визард на сайте"""
    category_name = models.CharField("Категория", max_length=200, blank=True, default="")
    service_name = models.CharField("Услуга", max_length=200)
    client_name = models.CharField("Имя клиента", max_length=100)
    client_phone = models.CharField("Телефон", max_length=30)
    comment = models.TextField("Комментарий", blank=True, default="")
    is_processed = models.BooleanField("Обработана", default=False)
    created_at = models.DateTimeField("Дата заявки", auto_now_add=True)

    class Meta:
        verbose_name = "Заявка на запись"
        verbose_name_plural = "Заявки на запись"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.client_name} — {self.service_name} ({self.created_at:%d.%m.%Y %H:%M})"