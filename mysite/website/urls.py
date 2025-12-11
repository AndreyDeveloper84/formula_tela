from django.urls import path
from . import views

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
import json

app_name = 'website'

urlpatterns = [
    path("", views.home, name="home"),
    path("services/", views.services, name="services"),
    path("promotions/", views.promotions, name="promotions"),
    path("masters/", views.masters, name="masters"),
    path("contacts/", views.contacts, name="contacts"),
    path("book/", views.book_service, name="book_service"),
    path("bundles/", views.bundles, name="bundles"),

    path("api/booking/get_staff/", views.api_get_staff, name="api_get_staff"),
    path('api/booking/available_times/', views.api_available_times, name='api_available_times'),
    path('api/booking/create/', views.api_create_booking, name='api_create_booking'),
]