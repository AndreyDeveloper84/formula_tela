from django.urls import path

from payments import views

app_name = "payments"

urlpatterns = [
    path("yookassa/webhook/", views.yookassa_webhook, name="yookassa_webhook"),
]
