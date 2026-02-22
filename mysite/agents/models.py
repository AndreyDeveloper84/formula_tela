from django.db import models


class AgentTask(models.Model):
    ANALYTICS        = "analytics"
    OFFERS           = "offers"
    OFFER_PACKAGES   = "offer_packages"
    SMM_GROWTH       = "smm_growth"
    SEO_LANDING      = "seo_landing"
    ANALYTICS_BUDGET = "analytics_budget"
    AGENT_CHOICES = [
        (ANALYTICS,        "Аналитика"),
        (OFFERS,           "Акции"),
        (OFFER_PACKAGES,   "Пакеты предложений"),
        (SMM_GROWTH,       "SMM-контент"),
        (SEO_LANDING,      "SEO-аудит лендингов"),
        (ANALYTICS_BUDGET, "Бюджет и воронка"),
    ]

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    STATUS_CHOICES = [
        (PENDING, "В очереди"),
        (RUNNING, "Выполняется"),
        (DONE, "Готово"),
        (ERROR, "Ошибка"),
    ]

    agent_type    = models.CharField("Тип агента", max_length=20, choices=AGENT_CHOICES)
    status        = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default=PENDING)
    triggered_by  = models.CharField("Запущен", max_length=50, default="scheduler")
    input_context = models.JSONField("Входной контекст", default=dict, blank=True)
    raw_response  = models.TextField("Ответ LLM", blank=True)
    error_message = models.TextField("Ошибка", blank=True)
    created_at    = models.DateTimeField("Создан", auto_now_add=True)
    finished_at   = models.DateTimeField("Завершён", null=True, blank=True)

    class Meta:
        verbose_name = "Задача агента"
        verbose_name_plural = "Задачи агентов"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_agent_type_display()} [{self.status}] {self.created_at:%d.%m.%Y %H:%M}"

    @property
    def duration_seconds(self):
        if self.finished_at and self.created_at:
            return int((self.finished_at - self.created_at).total_seconds())
        return None


class AgentReport(models.Model):
    task            = models.OneToOneField(
        AgentTask, on_delete=models.CASCADE, related_name="report", verbose_name="Задача"
    )
    summary         = models.TextField("Резюме")
    recommendations = models.JSONField("Рекомендации", default=list, blank=True)
    created_at      = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Отчёт агента"
        verbose_name_plural = "Отчёты агентов"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Отчёт: {self.task}"


class DailyMetric(models.Model):
    date           = models.DateField("Дата", unique=True)
    total_requests = models.PositiveIntegerField("Всего заявок", default=0)
    processed      = models.PositiveIntegerField("Обработано", default=0)
    unprocessed    = models.PositiveIntegerField("Не обработано", default=0)
    top_services   = models.JSONField("Топ услуг", default=list, blank=True)
    masters_load   = models.JSONField("Загрузка мастеров", default=dict, blank=True)
    created_at     = models.DateTimeField("Создан", auto_now_add=True)
    updated_at     = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Метрика дня"
        verbose_name_plural = "Метрики по дням"
        ordering = ["-date"]

    def __str__(self):
        return f"Метрики {self.date}: {self.total_requests} заявок"


class ContentPlan(models.Model):
    PLATFORM_VK        = "vk"
    PLATFORM_INSTAGRAM = "instagram"
    PLATFORM_TELEGRAM  = "telegram"
    PLATFORM_CHOICES = [
        (PLATFORM_VK,        "ВКонтакте"),
        (PLATFORM_INSTAGRAM, "Instagram"),
        (PLATFORM_TELEGRAM,  "Telegram"),
    ]

    POST_TYPE_POST  = "post"
    POST_TYPE_STORY = "story"
    POST_TYPE_REEL  = "reel"
    POST_TYPE_CHOICES = [
        (POST_TYPE_POST,  "Пост"),
        (POST_TYPE_STORY, "Stories"),
        (POST_TYPE_REEL,  "Reels/Клип"),
    ]

    WEEKDAY_CHOICES = [
        (0, "Понедельник"), (1, "Вторник"), (2, "Среда"),
        (3, "Четверг"),     (4, "Пятница"), (5, "Суббота"), (6, "Воскресенье"),
    ]

    week_start      = models.DateField("Начало недели")
    platform        = models.CharField("Платформа", max_length=20, choices=PLATFORM_CHOICES)
    day_of_week     = models.PositiveSmallIntegerField("День недели", choices=WEEKDAY_CHOICES)
    post_type       = models.CharField("Тип публикации", max_length=20, choices=POST_TYPE_CHOICES)
    theme           = models.CharField("Тема", max_length=300)
    description     = models.TextField("Описание контента")
    hashtags        = models.TextField("Хэштеги", blank=True)
    cta             = models.CharField("Призыв к действию", max_length=200, blank=True)
    created_by_task = models.ForeignKey(
        AgentTask, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="content_plans", verbose_name="Задача агента"
    )
    is_published    = models.BooleanField("Опубликован", default=False)
    created_at      = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Контент-план"
        verbose_name_plural = "Контент-планы"
        ordering = ["week_start", "day_of_week", "platform"]
        indexes = [
            models.Index(fields=["week_start", "platform"], name="agents_cp_week_platform_idx"),
            models.Index(fields=["is_published"], name="agents_cp_is_published_idx"),
        ]

    def __str__(self):
        day_name = dict(self.WEEKDAY_CHOICES).get(self.day_of_week, str(self.day_of_week))
        return f"{self.get_platform_display()} | {day_name} | {self.theme[:60]}"
