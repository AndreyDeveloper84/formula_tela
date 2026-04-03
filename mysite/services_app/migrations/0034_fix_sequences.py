from django.db import migrations

# Tables whose PostgreSQL sequences need resetting (INSERT returns 500 due to duplicate PK)
TABLES_TO_FIX = [
    'services_app_serviceblock',
    'services_app_review',
    'services_app_service',
    'services_app_servicemedia',
]

RESET_SQL = (
    "SELECT setval("
    "    pg_get_serial_sequence('{table}', 'id'),"
    "    COALESCE((SELECT MAX(id) FROM {table}), 0) + 1,"
    "    false"
    ")"
)


def fix_sequences(apps, schema_editor):
    """Reset PostgreSQL sequences to max(id)+1 so new INSERTs don't fail."""
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES_TO_FIX:
            cursor.execute(RESET_SQL.format(table=table))


class Migration(migrations.Migration):

    dependencies = [
        ('services_app', '0033_service_emoji_service_related_services_and_more'),
    ]

    operations = [
        migrations.RunPython(fix_sequences, migrations.RunPython.noop),
    ]
