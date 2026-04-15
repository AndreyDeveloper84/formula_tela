from django.urls import path
from . import views

app_name = 'website'

urlpatterns = [
    path("", views.home, name="home"),
    path("services/", views.services, name="services"),
    path('uslugi/<slug:slug>/', views.service_detail_by_slug, name='service_detail_by_slug'),
    path("service/<int:service_id>/", views.service_detail, name="service_detail"),
    path("services/<int:category_id>/", views.category_services, name="category_services"),  
    path("promotions/", views.promotions, name="promotions"),
    path("masters/", views.masters, name="masters"),
    path("contacts/", views.contacts, name="contacts"),
    path("book/", views.book_service, name="book_service"),
    path("bundles/", views.bundles, name="bundles"),
    path("kompleks/<slug:slug>/", views.bundle_detail_by_slug, name="bundle_detail_by_slug"),
    path("bundle/<int:bundle_id>/", views.bundle_detail, name="bundle_detail"),
    path("certificates/", views.certificates, name="certificates"),

    # API endpoints
    path('api/booking/get_staff/', views.api_get_staff, name='api_get_staff'),
    path('api/booking/available_dates/', views.api_available_dates, name='api_available_dates'),  
    path('api/booking/available_times/', views.api_available_times, name='api_available_times'),
    path('api/booking/create/', views.api_create_booking, name='api_create_booking'),
    path('api/booking/service_options/', views.api_service_options, name='api_service_options'),
    # API endpoints для комплексов
    path('api/bundle/request/', views.api_bundle_request, name='api_bundle_request'),
    # API endpoints для сертификатов
    path('api/certificates/request/', views.api_certificate_request, name='api_certificate_request'),
    path('api/certificates/check/', views.api_certificate_check, name='api_certificate_check'),
    # API endpoints для визарда
    path('api/wizard/categories/', views.api_wizard_categories, name='api_wizard_categories'),
    path('api/wizard/categories/<int:category_id>/services/', views.api_wizard_services, name='api_wizard_services'),
    path('api/wizard/booking/', views.api_wizard_booking, name='api_wizard_booking'),
]