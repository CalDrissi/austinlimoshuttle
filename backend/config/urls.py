"""
Root URL configuration.

The dashboard lives under /dashboard/ (Phase 5) and the API under /api/
(Phase 6). Django's own admin stays at /admin/ for model CRUD that does not
warrant a bespoke screen.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as static_serve

from dashboard.views import admin_login_redirect

admin.site.site_header = "M&M Austin Limousine"
admin.site.site_title = "M&M Austin Limousine"
admin.site.index_title = "Administration"

# Django's admin is a superuser-only safety net; day-to-day staff (Dispatcher,
# Manager, Editor) work entirely in /dashboard/. The default has_permission only
# checks is_staff, which would let any staff role reach /admin/ by typing the URL
# -- and the admin has no set-level validation on, e.g., rate cards. Require
# superuser so a dispatcher can never open it.
admin.site.has_permission = lambda request: bool(
    request.user.is_active and request.user.is_superuser
)

urlpatterns = [
    # Ahead of admin.site.urls so it wins: the admin's own login screen is
    # never reached, and staff see one sign-in page rather than two.
    path("admin/login/", admin_login_redirect),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("driver/", include("driver.urls")),
    path("api/", include("api.urls")),
    path("api/", include(("api.docs_urls", "api-docs"), namespace="api-docs")),
    # User-uploaded media (vehicle photos). Served by Django through gunicorn --
    # the volume is small (a handful of fleet images) so this is fine, and nginx
    # routes /media/ here in prod. (STATIC is handled separately by WhiteNoise.)
    re_path(r"^media/(?P<path>.*)$", static_serve, {"document_root": settings.MEDIA_ROOT}),
]
