from django.shortcuts import render

def booking(request):
    context = {}
    return render(request, 'booking/booking.html', context)

