"""Add Message.rendered_text — то что юзер реально увидел в чате.

Заполняется в ai_assistant.run_ai_turn после render_action(...). Облегчает
admin-аудит: для tool-call ассистент-сообщений content="" (только action_data
JSON), а в rendered_text — финальный человекочитаемый текст с карточками.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("services_app", "0065_botuser_food_scanner_consent"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="rendered_text",
            field=models.TextField(
                blank=True, default="",
                verbose_name="Отрендеренный текст (что увидел клиент)",
            ),
        ),
    ]
