from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("stocks/", views.stocks),
    path("stocks/<str:ticker>/", views.history),
    path("analysis/", views.analysis),
]
