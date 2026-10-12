"""Driver app URLs (mobile portal at /driver/)."""

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "driver"

urlpatterns = [
    path("login/", views.driver_login, name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="driver:login"), name="logout"),
    path("", views.runs, name="runs"),
    path("upcoming/", views.upcoming, name="upcoming"),
    path("trip/<str:reference>/", views.trip_detail, name="trip_detail"),
    path("trip/<str:reference>/action/", views.trip_action, name="trip_action"),
]
