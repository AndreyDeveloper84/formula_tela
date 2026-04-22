from django.db import models
from django.contrib.auth import get_user_model

from agents.managers import LandingPageQuerySet


class AgentTask(models.Model):
    ANALYTICS        = "analytics"
    OFFERS           = "offers"
    OFFER_PACKAGES   = "offer_packages"
    SMM_GROWTH       = "smm_growth"
    SEO_LANDING      = "seo_landing"
    ANALYTICS_BUDGET = "analytics_budget"
    TREND_SCOUT      = "trend_scout"
    SEO_GROWTH       = "seo_growth"
    LANDING_QC       = "landing_qc"
    AGENT_CHOICES = [
        (ANALYTICS,        "Аналитика"),
        (OFFERS,           "Акции"),
        (OFFER_PACKAGES,   "Пакеты предложений"),
        (SMM_GROWTH,       "SMM-контент"),
        (SEO_LANDING,      "SEO-аудит лендингов"),
        (ANALYTICS_BUDGET, "Бюджет и воронка"),
        (TREND_SCOUT,      "Разведка трендов"),
        (SEO_GROWTH,       "SEO & Growth"),
        (LANDING_QC,       "QC лендингов"),
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
    agent_runs     = models.JSONField(
        "Запуски агентов", default=dict, blank=True,
        help_text='{"analytics": {"duration_s": 12, "status": "done"}, ...}'
    )
    total_duration = models.PositiveIntegerField("Общее время агентов (сек)", default=0)
    error_count    = models.PositiveIntegerField("Ошибок за день", default=0)
    created_at     = models.DateTimeField("Создан", auto_now_add=True)
    updated_at     = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Метрика дня"
        verbose_name_plural = "Метрики по дням"
        ordering = ["-date"]

    def __str__(self):
        return f"Метрики {self.date}: {self.total_requests} заявок"


class TrendSnapshot(models.Model):
    """Еженедельный снимок трендов из внешних источников."""
    SOURCE_YANDEX = "yandex_suggest"
    SOURCE_VK = "vk_social"
    SOURCE_CHOICES = [
        (SOURCE_YANDEX, "Яндекс подсказки"),
        (SOURCE_VK, "VK группы"),
    ]

    source = models.CharField("Источник", max_length=20, choices=SOURCE_CHOICES)
    date = models.DateField("Дата сбора")
    raw_data = models.JSONField("Сырые данные")
    summary = models.TextField("Анализ GPT", blank=True)
    trends = models.JSONField("Выделенные тренды", default=list, blank=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Снимок трендов"
        verbose_name_plural = "Снимки трендов"
        ordering = ["-date"]
        unique_together = [("source", "date")]

    def __str__(self):
        return f"{self.get_source_display()} — {self.date}"


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


class SeoKeywordCluster(models.Model):
    """
    Кластер ключевых запросов, привязанный к целевой странице услуги.
    Заполняется вручную в Django admin.
    Пример: "Антицеллюлитный массаж Пенза" → /uslugi/antitsellyulitny-massazh/
    """
    name         = models.CharField("Название кластера", max_length=200)
    service_slug = models.CharField(
        "Slug услуги", max_length=200, blank=True,
        help_text="Slug из модели Service для автосвязи с данными Вебмастера"
    )
    keywords     = models.JSONField(
        "Ключевые запросы", default=list, blank=True,
        help_text='Список запросов, например: ["антицеллюлитный массаж", "массаж пенза"]'
    )
    target_url   = models.CharField(
        "Целевой URL", max_length=500,
        help_text="Канонический URL страницы, например: /uslugi/antitsellyulitny-massazh/"
    )
    is_active    = models.BooleanField("Активен", default=True)
    geo          = models.CharField("Гео", max_length=100, default="Пенза")
    service_category = models.ForeignKey(
        "services_app.ServiceCategory",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Категория услуги",
        related_name="seo_clusters",
    )
    created_at   = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "SEO-кластер запросов"
        verbose_name_plural = "SEO-кластеры запросов"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} → {self.target_url}"


class SeoRankSnapshot(models.Model):
    """
    Ежедневный снимок трафиковых метрик по страницам и запросам
    из Яндекс.Вебмастера (заполняет collect_rank_snapshots, 07:00 MSK).

    Для страниц: page_url заполнен, query пустой.
    Для запросов: query заполнен, page_url пустой.
    """
    week_start   = models.DateField("Дата снимка")
    page_url     = models.CharField(
        "URL страницы", max_length=500, blank=True,
        help_text="Относительный URL, например /uslugi/massazh/"
    )
    query        = models.CharField(
        "Поисковый запрос", max_length=300, blank=True,
        help_text="Текст запроса из Яндекс.Вебмастера или пусто для page-уровня"
    )
    clicks       = models.PositiveIntegerField("Клики", default=0)
    impressions  = models.PositiveIntegerField("Показы", default=0)
    ctr          = models.FloatField("CTR (0–1)", default=0.0)
    avg_position = models.FloatField("Средняя позиция", default=0.0)
    source       = models.CharField("Источник", max_length=50, default="webmaster")
    created_at   = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "SEO-снимок позиций"
        verbose_name_plural = "SEO-снимки позиций"
        ordering = ["-week_start", "-clicks"]
        unique_together = [("week_start", "page_url", "query")]
        indexes = [
            models.Index(fields=["week_start", "page_url"], name="agents_seo_week_page_idx"),
            models.Index(fields=["week_start", "query"], name="agents_seo_week_query_idx"),
        ]

    def __str__(self):
        label = self.page_url or self.query or "—"
        return f"{self.week_start} | {label} | {self.clicks} кл."


class SeoClusterSnapshot(models.Model):
    """
    Ежедневный агрегированный снимок позиций по SEO-кластеру.
    Создаётся задачей collect_rank_snapshots из данных Яндекс.Вебмастера.
    Агрегирует метрики по всем ключевым запросам кластера.
    """
    cluster = models.ForeignKey(
        SeoKeywordCluster,
        on_delete=models.CASCADE,
        related_name="snapshots",
        verbose_name="Кластер",
    )
    date = models.DateField("Дата снимка")
    total_clicks = models.PositiveIntegerField("Суммарные клики", default=0)
    total_impressions = models.PositiveIntegerField("Суммарные показы", default=0)
    avg_ctr = models.FloatField("Средний CTR (0-1)", default=0.0)
    avg_position = models.FloatField("Средняя позиция", default=0.0)
    matched_queries = models.PositiveIntegerField(
        "Совпавших запросов", default=0,
        help_text="Сколько ключей из кластера нашлось в данных Вебмастера",
    )

    class Meta:
        verbose_name = "Снимок кластера"
        verbose_name_plural = "Снимки кластеров"
        ordering = ["-date", "cluster"]
        unique_together = [("cluster", "date")]
        indexes = [
            models.Index(
                fields=["date", "cluster"],
                name="agents_cls_date_cluster_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.cluster.name} | {self.date} | "
            f"{self.total_clicks} кл. | поз. {self.avg_position:.1f}"
        )


class LandingPage(models.Model):
    """
    SEO-посадочная страница, сгенерированная агентом.
    ВСЕГДА создаётся со status='draft'. Публикация — только вручную через Admin.
    """
    STATUS_DRAFT     = "draft"
    STATUS_REVIEW    = "review"
    STATUS_PUBLISHED = "published"
    STATUS_REJECTED  = "rejected"
    STATUS_CHOICES   = [
        (STATUS_DRAFT,     "Черновик"),
        (STATUS_REVIEW,    "На модерации"),
        (STATUS_PUBLISHED, "Опубликована"),
        (STATUS_REJECTED,  "Отклонена"),
    ]

    cluster           = models.ForeignKey(
        SeoKeywordCluster, on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="SEO кластер",
        related_name="landing_pages",
    )
    slug              = models.SlugField("Slug", max_length=200, unique=True)
    status            = models.CharField(
        "Статус", max_length=20,
        choices=STATUS_CHOICES, default=STATUS_DRAFT
    )
    meta_title        = models.CharField("Meta Title", max_length=70)
    meta_description  = models.CharField("Meta Description", max_length=160, blank=True)
    h1                = models.CharField("H1", max_length=200, blank=True)
    blocks            = models.JSONField(
        "Блоки контента", default=dict,
        help_text=(
            "Структура: {intro, how_it_works, who_is_it_for, "
            "contraindications, results, faq:[{question,answer}], "
            "cta_text, internal_links}"
        ), blank=True
    )
    generated_by_agent = models.BooleanField("Сгенерировано агентом", default=True)
    source_markdown   = models.TextField(
        "Исходный маркдаун",
        blank=True,
        help_text="Маркдаун-бриф, переданный при генерации. Хранится для аудита.",
    )
    moderated_by      = models.ForeignKey(
        get_user_model(), on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name="Проверил",
        related_name="moderated_landings",
    )
    created_at        = models.DateTimeField("Создано", auto_now_add=True)
    published_at      = models.DateTimeField("Опубликовано", null=True, blank=True)

    objects = LandingPageQuerySet.as_manager()

    class Meta:
        verbose_name = "Посадочная страница"
        verbose_name_plural = "Посадочные страницы"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.h1} [{self.get_status_display()}]"


class SeoTask(models.Model):
    """
    Задача для SEO-специалиста, сформированная агентом.
    """
    TYPE_CREATE_LANDING    = "create_landing"
    TYPE_UPDATE_META       = "update_meta"
    TYPE_ADD_FAQ           = "add_faq"
    TYPE_FIX_TECHNICAL     = "fix_technical"
    TYPE_REWRITE_CTA       = "rewrite_cta"
    TYPE_ADD_CONTENT_BLOCK = "add_content_block"
    TASK_TYPE_CHOICES = [
        (TYPE_CREATE_LANDING,    "Создать страницу"),
        (TYPE_UPDATE_META,       "Обновить мета-теги"),
        (TYPE_ADD_FAQ,           "Добавить FAQ"),
        (TYPE_FIX_TECHNICAL,     "Технический баг"),
        (TYPE_REWRITE_CTA,       "Переписать CTA"),
        (TYPE_ADD_CONTENT_BLOCK, "Добавить блок"),
    ]

    PRIORITY_HIGH   = "high"
    PRIORITY_MEDIUM = "medium"
    PRIORITY_LOW    = "low"
    PRIORITY_CHOICES = [
        (PRIORITY_HIGH,   "Высокий"),
        (PRIORITY_MEDIUM, "Средний"),
        (PRIORITY_LOW,    "Низкий"),
    ]

    STATUS_OPEN        = "open"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_DONE        = "done"
    STATUS_CHOICES = [
        (STATUS_OPEN,        "Открыта"),
        (STATUS_IN_PROGRESS, "В работе"),
        (STATUS_DONE,        "Готово"),
    ]

    task_type   = models.CharField("Тип задачи", max_length=30, choices=TASK_TYPE_CHOICES)
    priority    = models.CharField(
        "Приоритет", max_length=10,
        choices=PRIORITY_CHOICES, default=PRIORITY_MEDIUM
    )
    status      = models.CharField(
        "Статус", max_length=20,
        choices=STATUS_CHOICES, default=STATUS_OPEN
    )
    title       = models.CharField("Заголовок", max_length=300)
    description = models.TextField("Описание", blank=True)
    target_url  = models.CharField("Целевой URL", max_length=500, blank=True)
    payload     = models.JSONField("Данные", default=dict, blank=True)
    escalation_count = models.PositiveIntegerField("Кол-во эскалаций", default=0)
    created_at  = models.DateTimeField("Создано", auto_now_add=True)

    class Meta:
        verbose_name = "SEO задача"
        verbose_name_plural = "SEO задачи"
        ordering = ["-priority", "-created_at"]

    def __str__(self):
        return f"[{self.get_priority_display()}] {self.title}"


class AgentRecommendationOutcome(models.Model):
    """
    Трекинг рекомендаций агентов с lifecycle: new → accepted/rejected → done.
    Позволяет SupervisorAgent учитывать feedback при планировании.
    """
    STATUS_NEW      = "new"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_DONE     = "done"
    STATUS_CHOICES = [
        (STATUS_NEW,      "Новая"),
        (STATUS_ACCEPTED, "Принята"),
        (STATUS_REJECTED, "Отклонена"),
        (STATUS_DONE,     "Выполнена"),
    ]

    report      = models.ForeignKey(
        AgentReport, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="outcomes", verbose_name="Отчёт"
    )
    agent_type  = models.CharField(
        "Тип агента", max_length=20, choices=AgentTask.AGENT_CHOICES
    )
    title       = models.CharField("Заголовок", max_length=300)
    body        = models.JSONField("Данные рекомендации", default=dict, blank=True)
    status      = models.CharField(
        "Статус", max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW
    )
    decided_by  = models.ForeignKey(
        get_user_model(), on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name="Решение принял",
        related_name="recommendation_decisions",
    )
    decided_at  = models.DateTimeField("Дата решения", null=True, blank=True)
    notes       = models.TextField("Заметки", blank=True)
    created_at  = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Рекомендация агента"
        verbose_name_plural = "Рекомендации агентов"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["agent_type", "status"], name="agents_rec_type_status_idx"),
        ]

    def __str__(self):
        return f"[{self.get_status_display()}] {self.title[:80]}"


class WeeklyBacklog(models.Model):
    """
    Персистентный еженедельный бэклог от SupervisorAgent.weekly_run().
    Ранее результат отправлялся только в Telegram — теперь сохраняется в БД.
    """
    week_start  = models.DateField("Начало недели", unique=True)
    raw_text    = models.TextField("Синтез GPT")
    items       = models.JSONField("Задачи бэклога", default=list, blank=True)
    created_at  = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Еженедельный бэклог"
        verbose_name_plural = "Еженедельные бэклоги"
        ordering = ["-week_start"]

    def __str__(self):
        return f"Бэклог {self.week_start}"


class RetentionSnapshot(models.Model):
    """
    Ежедневный снимок метрик удержания клиентов.
    Рассчитывается из YClients записей за 180-дневный период
    задачей collect_retention_metrics (Celery beat, 08:00 ежедневно).
    """
    date = models.DateField("Дата снимка", unique=True)
    period_days = models.IntegerField("Период анализа (дней)", default=180)

    # Клиенты
    total_clients = models.IntegerField("Всего клиентов", default=0)
    new_clients = models.IntegerField("Новых клиентов", default=0)
    returning_clients = models.IntegerField("Повторных клиентов", default=0)

    # Удержание
    retention_30d = models.FloatField("Удержание 30д (%)", default=0.0)
    retention_60d = models.FloatField("Удержание 60д (%)", default=0.0)
    retention_90d = models.FloatField("Удержание 90д (%)", default=0.0)

    # Экономика
    avg_frequency = models.FloatField(
        "Средняя частота (визитов/мес на клиента)", default=0.0,
    )
    avg_check = models.FloatField("Средний чек (руб)", default=0.0)
    avg_ltv_180d = models.FloatField("Средний LTV 180д (руб)", default=0.0)

    # Отток
    churn_count = models.IntegerField("Ушедших клиентов (90д+)", default=0)
    churn_rate = models.FloatField("Процент оттока (%)", default=0.0)
    top_churned_services = models.JSONField(
        "Услуги с макс. оттоком", default=list, blank=True,
    )

    # Когорты
    cohort_data = models.JSONField(
        "Когортная матрица", default=dict, blank=True,
        help_text='Месячные когорты: {"2026-01": {"m0": 100, "m1": 45, ...}}',
    )

    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Снимок удержания"
        verbose_name_plural = "Снимки удержания"
        ordering = ["-date"]

    def __str__(self):
        return (
            f"Удержание {self.date}: {self.total_clients} клиентов, "
            f"R30={self.retention_30d:.0f}%, отток={self.churn_rate:.0f}%"
        )
