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
    
    class Meta:
        verbose_name = "Услуга"
        verbose_name_plural = "Услуги"
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
    name = models.CharField(max_length=120, verbose_name="Название комплекса", null=True, blank=True)  # название комплекса (набор услуг)
    # простая логика цены: либо фиксированная, либо сумма услуг минус скидка
    fixed_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    discount = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))

    # связь «многие-ко-многим» через промежуточную таблицу,
    # в которой хранится порядок услуг внутри комплекса
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

    # посчитаем итоговую цену: либо fixed, либо сумма - скидка
    def total_price(self) -> Decimal:
        if self.fixed_price is not None:
            return self.fixed_price
        # суммируем цену вариантов с учётом количества
        items = self.items.select_related("option").all()
        total = Decimal("0.00")
        for it in items:
            if it.option and it.option.price is not None:
                total += Decimal(it.option.price) * it.quantity
        return max(Decimal("0.00"), total - self.discount)

    # простая длительность: сумма длительностей всех услуг
    # (без параллельности и пауз — чтобы было максимально понятно)
    def total_duration_min(self) -> int:
        # простая сумма длительностей вариантов с учётом количества
        items = self.items.select_related("option").all()
        return sum((it.option.duration_min if it.option else 0) * it.quantity for it in items)

class BundleItem(models.Model):
    bundle = models.ForeignKey(Bundle, on_delete=models.CASCADE, related_name="items")
    option = models.ForeignKey(
        ServiceOption, on_delete=models.PROTECT, related_name="bundle_items", null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    
    order = models.PositiveIntegerField(default=1)  # порядок в комплексе

    parallel_group = models.PositiveIntegerField(default=1)  # группа параллельности
    gap_after_min = models.PositiveIntegerField(default=0)  # пауза после услуги в минутах

    class Meta:
        ordering = ['order']


class Promotion(models.Model):
    title = models.CharField(max_length=200, verbose_name="Название акции")
    subtitle = models.CharField(max_length=200, blank=True, verbose_name="Подзаголовок")
    description = models.TextField(blank=True, verbose_name="Описание")
    features = models.JSONField(blank=True, null=True, verbose_name="Особенности/преимущества")
    image = models.ImageField(upload_to="promotions/", blank=True, null=True, verbose_name="Изображение")

    # Привязка к конкретным вариантам услуг (может быть пусто — тогда акция общая)
    options = models.ManyToManyField(
        ServiceOption, blank=True, related_name="promotions", verbose_name="Варианты услуг"
    )

    discount_percent = models.PositiveSmallIntegerField(default=0, verbose_name="Скидка, %")
    price_note = models.CharField(max_length=200, blank=True, verbose_name="Примечание по цене")

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