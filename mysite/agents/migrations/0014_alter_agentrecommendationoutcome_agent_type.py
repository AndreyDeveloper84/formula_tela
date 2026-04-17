from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agents", "0013_alter_agenttask_agent_type_seo_growth"),
    ]

    operations = [
        migrations.AlterField(
            model_name="agentrecommendationoutcome",
            name="agent_type",
            field=models.CharField(
                choices=[
                    ("analytics", "Аналитика"),
                    ("offers", "Акции"),
                    ("offer_packages", "Пакеты предложений"),
                    ("smm_growth", "SMM-контент"),
                    ("seo_landing", "SEO-аудит лендингов"),
                    ("analytics_budget", "Бюджет и воронка"),
                    ("trend_scout", "Разведка трендов"),
                    ("seo_growth", "SEO & Growth"),
                ],
                max_length=20,
                verbose_name="Тип агента",
            ),
        ),
    ]
