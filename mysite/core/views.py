from django.shortcuts import render
from django.http import HttpResponse
from datetime import datetime

def home(request):
    context = {}
    return render(request, 'core/home.html', context)

def about(request):
    context = {
        'current_time': datetime.now()
    }
    return render(request, 'core/about.html', context)  




# Create your views here.
