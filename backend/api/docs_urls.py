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

from config.middleware import CSP_DIRECTIVES


class DocsCSPMixin:
    """Allow spectacular's inline bootstrap only on the static docs shells."""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        directives = {
            **CSP_DIRECTIVES,
            "script-src": "'self' 'unsafe-inline'",
            "connect-src": "'self'",
        }
        response["Content-Security-Policy"] = "; ".join(
            f"{directive} {value}" for directive, value in directives.items()
        )
        return response


class DocsSwaggerView(DocsCSPMixin, SpectacularSwaggerView):
    pass


class DocsRedocView(DocsCSPMixin, SpectacularRedocView):
    pass


urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(
        permission_classes=[AllowAny]), name="schema"),
    path("docs/", DocsSwaggerView.as_view(
        url_name="api-docs:schema", permission_classes=[AllowAny]), name="swagger"),
    path("redoc/", DocsRedocView.as_view(
        url_name="api-docs:schema", permission_classes=[AllowAny]), name="redoc"),
]
