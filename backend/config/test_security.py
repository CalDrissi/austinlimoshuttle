"""
Security regression tests.

Each of these maps to a specific finding in the audit of the legacy system.
They exist so those defects cannot return quietly.
"""

import re

import pytest
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()

# Column names that held cardholder data in the legacy schema.
FORBIDDEN_FIELD_NAMES = {
    "card_number", "cardnumber", "pan",
    "securitycode", "security_code", "cvv", "cvc", "ccv",
    "expiration_date", "expiration_dates", "expiry_date",
    "name_on_card", "name_of_card",
}


class TestNoCardholderDataAnywhere:
    """
    Legacy finding: 3,416 plaintext card numbers and 68 CVVs across two tables.

    The fix is structural -- no model may have a field capable of holding them.
    """

    def test_no_model_has_a_cardholder_field(self):
        offenders = []
        for model in apps.get_models():
            if model._meta.app_label not in {
                "accounts", "fleet", "pricing", "bookings",
                "payments", "content", "enquiries",
            }:
                continue
            for field in model._meta.get_fields():
                if field.name.lower() in FORBIDDEN_FIELD_NAMES:
                    offenders.append(f"{model._meta.label}.{field.name}")
        assert not offenders, f"cardholder fields present: {offenders}"

    def test_card_last4_cannot_hold_more_than_four_digits(self):
        from payments.models import Payment

        assert Payment._meta.get_field("card_last4").max_length == 4

    @pytest.mark.django_db
    def test_no_stored_value_looks_like_a_card_number(self):
        """Scans every char/text column for a 13-19 digit run."""

        pan = re.compile(r"^\d{13,19}$")
        offenders = []

        for model in apps.get_models():
            if model._meta.app_label not in {
                "accounts", "bookings", "payments", "content", "enquiries",
            }:
                continue
            text_fields = [
                f.name for f in model._meta.get_fields()
                if getattr(f, "get_internal_type", None)
                and f.get_internal_type() in {"CharField", "TextField"}
            ]
            if not text_fields:
                continue
            for row in model.objects.values(*text_fields).iterator():
                for name, value in row.items():
                    if isinstance(value, str) and pan.match(value.replace(" ", "")):
                        offenders.append(f"{model._meta.label}.{name}")
        assert not offenders, f"card-shaped values found in: {set(offenders)}"


class TestNoPlaintextPasswords:
    """Legacy finding: 1,251 customer passwords and the admin password in plaintext."""

    @pytest.mark.django_db
    def test_passwords_are_hashed(self):
        user = User.objects.create_user(email="hash@example.com", password="StrongPass!2026")
        assert user.password != "StrongPass!2026"
        assert user.password.startswith(("pbkdf2_", "argon2", "bcrypt", "md5$"))

    def test_no_model_stores_a_recoverable_password(self):
        offenders = []
        for model in apps.get_models():
            for field in model._meta.get_fields():
                if field.name.lower() in {
                    "plain_password", "password_plain", "legacy_password", "raw_password",
                }:
                    offenders.append(f"{model._meta.label}.{field.name}")
        assert not offenders


class TestProductionHardening:
    """Legacy finding: PHP 5.4, no CSRF, no HSTS, secrets in the web root."""

    def test_csrf_middleware_is_enabled(self):
        # We run a path-scoped subclass (so a storefront login can't rotate the
        # token out from under a dashboard/driver form), but CSRF protection is
        # the stock CsrfViewMiddleware's -- only the cookie name is per-path.
        from django.middleware.csrf import CsrfViewMiddleware
        from django.utils.module_loading import import_string
        assert any(
            isinstance(import_string(m), type)
            and issubclass(import_string(m), CsrfViewMiddleware)
            for m in settings.MIDDLEWARE
        )

    def test_clickjacking_protection_is_enabled(self):
        assert "django.middleware.clickjacking.XFrameOptionsMiddleware" in settings.MIDDLEWARE

    @pytest.mark.django_db
    def test_csp_and_permissions_policy_headers_are_sent(self, client):
        response = client.get(reverse("admin:login"))
        csp = response.headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "object-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        # Scripts must NOT be granted unsafe-inline.
        script_src = [d for d in csp.split(";") if d.strip().startswith("script-src")]
        assert script_src and "unsafe-inline" not in script_src[0]
        assert "payment=()" in response.headers.get("Permissions-Policy", "")

    @pytest.mark.django_db
    def test_csp_allows_osm_tiles_in_img_src_without_loosening_scripts(self, client):
        # The dashboard's self-hosted Leaflet map pulls raster tiles from
        # OpenStreetMap, so img-src must allow that host -- but Leaflet's own
        # JS/CSS are self-hosted, so script-src must gain no new host and must
        # still forbid external/inline scripts.
        response = client.get(reverse("admin:login"))
        csp = response.headers.get("Content-Security-Policy", "")

        img_src = [d for d in csp.split(";") if d.strip().startswith("img-src")]
        assert img_src and "https://*.tile.openstreetmap.org" in img_src[0]

        script_src = [d for d in csp.split(";") if d.strip().startswith("script-src")]
        assert script_src
        # script-src stays exactly as before: self + Stripe + Google Maps only.
        assert "openstreetmap" not in script_src[0]
        assert "unsafe-inline" not in script_src[0]
        assert "'self' https://js.stripe.com https://maps.googleapis.com https://maps.gstatic.com" in script_src[0]

    @pytest.mark.django_db
    def test_permissions_policy_allows_same_origin_geolocation_only(self, client):
        # The driver app (same-origin, /driver/) reads navigator.geolocation to
        # stamp each status event with coords, so geolocation must be granted to
        # 'self'. It must NOT be granted to any third party, and every other
        # Permissions-Policy directive must stay locked off.
        response = client.get(reverse("admin:login"))
        policy = response.headers.get("Permissions-Policy", "")

        directives = {d.split("=", 1)[0].strip(): d.split("=", 1)[1].strip()
                      for d in policy.split(",") if "=" in d}

        assert directives.get("geolocation") == "(self)"
        # No wildcard / third-party origin crept in.
        assert "*" not in directives["geolocation"]
        # Everything else remains fully disabled, exactly as before.
        assert directives.get("camera") == "()"
        assert directives.get("microphone") == "()"
        assert directives.get("payment") == "()"

    def test_production_settings_are_hardened(self, monkeypatch):
        import importlib

        monkeypatch.setenv("DJANGO_SECRET_KEY", "x" * 60)
        monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "example.com")
        prod = importlib.reload(importlib.import_module("config.settings.prod"))

        assert prod.DEBUG is False
        assert prod.SECURE_SSL_REDIRECT is True
        assert prod.SECURE_HSTS_SECONDS >= 31536000
        assert prod.SESSION_COOKIE_SECURE is True
        assert prod.CSRF_COOKIE_SECURE is True
        assert prod.SESSION_COOKIE_HTTPONLY is True
        assert prod.SECURE_CONTENT_TYPE_NOSNIFF is True
        assert prod.X_FRAME_OPTIONS == "DENY"

    def test_media_root_is_outside_the_web_root(self, monkeypatch):
        import importlib

        monkeypatch.setenv("DJANGO_SECRET_KEY", "x" * 60)
        monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "example.com")
        prod = importlib.reload(importlib.import_module("config.settings.prod"))
        assert "public_html" not in str(prod.MEDIA_ROOT)

    def test_password_validators_require_reasonable_length(self):
        validators = {v["NAME"]: v for v in settings.AUTH_PASSWORD_VALIDATORS}
        length = validators[
            "django.contrib.auth.password_validation.MinimumLengthValidator"
        ]
        assert length["OPTIONS"]["min_length"] >= 10


class TestNoRawSql:
    """
    Legacy finding: 27 SQL injection sites across 16 files.

    The ORM parameterises everything; raw SQL is prohibited outside reviewed
    read-only paths.
    """

    def test_application_code_contains_no_raw_sql_execution(self):
        from pathlib import Path

        root = Path(settings.BASE_DIR)
        offenders = []
        patterns = re.compile(r"\.raw\(|cursor\(\)\.execute\(|RawSQL\(")

        for path in root.rglob("*.py"):
            parts = set(path.parts)
            if parts & {".venv", "migrations", "tests", "__pycache__"}:
                continue
            # The legacy importer reads the old database over PyMySQL by design;
            # its queries are static strings with no request data in them.
            if "legacy_import" in parts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if patterns.search(text):
                offenders.append(str(path.relative_to(root)))

        assert not offenders, f"raw SQL found in: {offenders}"


@pytest.mark.django_db
class TestThrottling:
    def test_sensitive_scopes_are_configured(self):
        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        for scope in ("anon", "quote", "enquiry"):
            assert rates.get(scope)


@pytest.mark.django_db
class TestAdminExposure:
    def test_admin_requires_authentication(self, client):
        response = client.get(reverse("admin:index"))
        assert response.status_code == 302
        assert "/admin/login/" in response["Location"]

    def test_dashboard_requires_authentication(self, client):
        response = client.get(reverse("dashboard:home"))
        assert response.status_code == 302


@pytest.mark.django_db
class TestAdminIsSuperuserOnly:
    """Django's /admin/ is a superuser-only safety net; staff use /dashboard/."""

    def test_non_superuser_staff_cannot_open_admin(self, client):
        User.objects.create_user(
            email="disp@example.com", password="StaffLocal!2026", is_staff=True,
        )
        client.login(username="disp@example.com", password="StaffLocal!2026")
        # has_permission is False -> admin bounces to its login, never the index.
        assert client.get("/admin/").status_code in (302, 403)

    def test_superuser_can_open_admin(self, client):
        User.objects.create_superuser(email="root@example.com", password="RootLocal!2026")
        client.login(username="root@example.com", password="RootLocal!2026")
        assert client.get("/admin/").status_code == 200
