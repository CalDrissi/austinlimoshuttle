"""
API documentation routes.

Served from our own domain via drf-spectacular-sidecar: the Content-Security-
Policy forbids external scripts, so the default CDN-hosted Swagger UI would
render a blank page.

The schema and documentation are intentionally public in all environments.
"""

from django.urls import path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.permissions import AllowAny


urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(
        permission_classes=[AllowAny]), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(
        url_name="api-docs:schema", permission_classes=[AllowAny]), name="swagger"),
    path("redoc/", SpectacularRedocView.as_view(
        url_name="api-docs:schema", permission_classes=[AllowAny]), name="redoc"),
]
