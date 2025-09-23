""" from django.shortcuts import render

from django.db.models import Prefetch
from .models import Service, ServiceOption, ServiceCategory

def services(request):
    options_qs = ServiceOption.objects.filter(is_active=True).order_by(
        "order", "duration_min", "unit_type", "units"
        )
    services_qs = Service.objects.filter(is_active=True).prefetch_related(
        Prefetch("options", queryset=options_qs)
    ).select_related("category").order_by("category__order", "name")

    categories = ServiceCategory.objects.prefetch_related(
        Prefetch("services", queryset=services_qs)
    ).order_by("order", "name")

    return render(request, "website/services.html", {"categories": categories})
 """