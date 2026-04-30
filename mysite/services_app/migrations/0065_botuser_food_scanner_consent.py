"""Add BotUser.food_scanner_consent_at for 152-FZ consent (DRF-246).

Tracks the moment a bot user agreed to send food photos to Ayla / OpenAI
Vision. Photo scan is blocked until consent timestamp is set.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("services_app", "0064_booking_source_yclients_admin"),
    ]

    operations = [
        migrations.AddField(
            model_name="botuser",
            name="food_scanner_consent_at",
            field=models.DateTimeField(
                null=True,
                blank=True,
                verbose_name="152-ФЗ согласие food scanner",
                help_text=(
                    "Timestamp когда пользователь нажал «Согласен» на обработку "
                    "фото еды (152-ФЗ). NULL = не давал согласия, scanner недоступен."
                ),
            ),
        ),
    ]
