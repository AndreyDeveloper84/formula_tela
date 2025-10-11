import pytest
from django.core.management import call_command

@pytest.mark.django_db
def test_no_unapplied_migrations():
    # падаем, если есть неприменённые миграции
    call_command("makemigrations", "--check", "--dry-run")
