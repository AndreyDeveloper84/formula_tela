from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("agents", "0008_alter_agenttask_agent_type_trendsnapshot"),
    ]

    operations = [
        migrations.AddField(
            model_name="seotask",
            name="escalation_count",
            field=models.PositiveIntegerField(
                default=0, verbose_name="Кол-во эскалаций"
            ),
        ),
    ]
