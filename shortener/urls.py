from django.urls import path
from . import views

app_name = 'shortener'

urlpatterns = [
    path('', views.home, name='home'),
    path('api/shorten/', views.ShortenAPIView.as_view(), name='api_shorten'),
    path('<str:short_code>', views.redirect_short_url, name='redirect'),
]
