"""FewShotExample — курируемые success-пары для injection в prompt (auto-tune #1).
"""
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("services_app", "0066_message_rendered_text"),
    ]

    operations = [
        migrations.CreateModel(
            name="FewShotExample",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False,
                                        primary_key=True, serialize=False)),
                ("user_text", models.TextField(verbose_name="Сообщение клиента")),
                ("assistant_text", models.TextField(verbose_name="Ответ бота (rendered)")),
                ("is_active", models.BooleanField(
                    default=True, verbose_name="Активен (попадает в prompt)")),
                ("created_at", models.DateTimeField(
                    auto_now_add=True, verbose_name="Создан")),
                ("source_conversation", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=models.deletion.SET_NULL,
                    related_name="few_shot_examples",
                    to="services_app.conversation",
                    verbose_name="Источник (диалог)")),
            ],
            options={
                "verbose_name": "Few-shot пример (auto-tune)",
                "verbose_name_plural": "Few-shot примеры (auto-tune)",
                "ordering": ["-created_at"],
                "indexes": [models.Index(
                    fields=["is_active", "-created_at"],
                    name="services_ap_is_acti_519814_idx",
                )],
            },
        ),
    ]
