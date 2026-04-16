from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("agents", "0009_seotask_escalation_count"),
    ]

    operations = [
        # AgentRecommendationOutcome
        migrations.CreateModel(
            name="AgentRecommendationOutcome",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("agent_type", models.CharField(choices=[
                    ("analytics", "Аналитика"),
                    ("offers", "Акции"),
                    ("offer_packages", "Пакеты предложений"),
                    ("smm_growth", "SMM-контент"),
                    ("seo_landing", "SEO-аудит лендингов"),
                    ("analytics_budget", "Бюджет и воронка"),
                    ("trend_scout", "Разведка трендов"),
                ], max_length=20, verbose_name="Тип агента")),
                ("title", models.CharField(max_length=300, verbose_name="Заголовок")),
                ("body", models.JSONField(blank=True, default=dict, verbose_name="Данные рекомендации")),
                ("status", models.CharField(choices=[
                    ("new", "Новая"),
                    ("accepted", "Принята"),
                    ("rejected", "Отклонена"),
                    ("done", "Выполнена"),
                ], default="new", max_length=20, verbose_name="Статус")),
                ("decided_at", models.DateTimeField(blank=True, null=True, verbose_name="Дата решения")),
                ("notes", models.TextField(blank=True, verbose_name="Заметки")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                ("decided_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="recommendation_decisions",
                    to=settings.AUTH_USER_MODEL,
                    verbose_name="Решение принял",
                )),
                ("report", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="outcomes",
                    to="agents.agentreport",
                    verbose_name="Отчёт",
                )),
            ],
            options={
                "verbose_name": "Рекомендация агента",
                "verbose_name_plural": "Рекомендации агентов",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="agentrecommendationoutcome",
            index=models.Index(
                fields=["agent_type", "status"],
                name="agents_rec_type_status_idx",
            ),
        ),
        # WeeklyBacklog
        migrations.CreateModel(
            name="WeeklyBacklog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("week_start", models.DateField(unique=True, verbose_name="Начало недели")),
                ("raw_text", models.TextField(verbose_name="Синтез GPT")),
                ("items", models.JSONField(blank=True, default=list, verbose_name="Задачи бэклога")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
            ],
            options={
                "verbose_name": "Еженедельный бэклог",
                "verbose_name_plural": "Еженедельные бэклоги",
                "ordering": ["-week_start"],
            },
        ),
        # DailyMetric timing fields
        migrations.AddField(
            model_name="dailymetric",
            name="agent_runs",
            field=models.JSONField(
                blank=True, default=dict,
                help_text='{"analytics": {"duration_s": 12, "status": "done"}, ...}',
                verbose_name="Запуски агентов",
            ),
        ),
        migrations.AddField(
            model_name="dailymetric",
            name="total_duration",
            field=models.PositiveIntegerField(default=0, verbose_name="Общее время агентов (сек)"),
        ),
        migrations.AddField(
            model_name="dailymetric",
            name="error_count",
            field=models.PositiveIntegerField(default=0, verbose_name="Ошибок за день"),
        ),
    ]
