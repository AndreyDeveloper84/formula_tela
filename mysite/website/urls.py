from django.urls import path
from . import views

app_name = 'website'

urlpatterns = [
    path("", views.home, name="home"),
    path("services/", views.services, name="services"),
    path("promotions/", views.promotions, name="promotions"),
    path("masters/", views.masters, name="masters"),
    path("contacts/", views.contacts, name="contacts"),
    path("book/", views.book_service, name="book_service"),
    path("bundles/", views.bundles, name="bundles"),

     # Пошаговая запись (4 шага)
    path("booking/step1/", views.booking_step1, name="booking_step1"),
    path("booking/step2/", views.booking_step2, name="booking_step2"),
    path("booking/step3/", views.booking_step3, name="booking_step3"),
    path("booking/step4/", views.booking_step4, name="booking_step4"),
    path("booking/success/", views.booking_success, name="booking_success"),
    
    # Быстрая запись (одна страница)
    path("booking/quick/", views.booking_quick, name="booking_quick"),
    
    # AJAX API для записи
    path("api/booking/staff/", views.api_get_staff, name="api_get_staff"),
    path("api/booking/times/", views.api_get_available_times, name="api_get_times"),
    path("api/booking/quick-submit/", views.booking_quick_submit, name="api_quick_submit"),
    
    # Старый endpoint (оставляем для совместимости)
    path("book/", views.book_service, name="book_service"),
]