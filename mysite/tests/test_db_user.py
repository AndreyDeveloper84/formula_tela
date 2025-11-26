import pytest
from django.contrib.auth import get_user_model

@pytest.mark.django_db
def test_create_user():
    User = get_user_model()
    u = User.objects.create_user(username="demo_user", password="pass12345")
    assert u.pk and u.is_active
