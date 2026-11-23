"""
OpenAPI schema and documentation.

The frontend is generated against this schema, so a silent regression here
produces a client that compiles and then fails at runtime.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
class TestSchema:
    def test_schema_generates_without_warnings(self):
        from io import StringIO

        from django.core.management import call_command

        out, err = StringIO(), StringIO()
        call_command("spectacular", "--fail-on-warn", stdout=out, stderr=err)
        assert out.getvalue().strip()

    def test_every_endpoint_is_documented(self, client, settings):
        settings.DEBUG = True
        schema = client.get(reverse("api-docs:schema")).content.decode()
        for path in [
            "/api/quotes/", "/api/bookings/", "/api/payments/intent/",
            "/api/payments/webhook/", "/api/auth/login/", "/api/enquiries/",
            "/api/account/bookings/{reference}/",
        ]:
            assert path in schema, f"{path} missing from the schema"

    def test_swagger_ui_renders(self, client, settings):
        settings.DEBUG = True
        response = client.get(reverse("api-docs:swagger"))
        assert response.status_code == 200
        assert b"swagger" in response.content.lower()

    def test_redoc_renders(self, client, settings):
        settings.DEBUG = True
        assert client.get(reverse("api-docs:redoc")).status_code == 200

    def test_ui_assets_are_served_locally_not_from_a_cdn(self, client, settings):
        """Our CSP forbids external scripts, so a CDN-hosted UI would be blank."""
        settings.DEBUG = True
        body = client.get(reverse("api-docs:swagger")).content.decode()
        assert "cdn.jsdelivr.net" not in body
        assert "unpkg.com" not in body

    @pytest.mark.parametrize("view", ["schema", "swagger", "redoc"])
    def test_docs_are_public_outside_debug(self, client, settings, view):
        settings.DEBUG = False
        assert client.get(reverse(f"api-docs:{view}")).status_code == 200

    def test_staff_can_read_the_schema_in_production(self, client, settings):
        settings.DEBUG = False
        User.objects.create_user(email="staff@example.com", password="DocsLocal!2026",
                                 is_staff=True)
        client.login(username="staff@example.com", password="DocsLocal!2026")
        assert client.get(reverse("api-docs:schema")).status_code == 200

    def test_quote_request_schema_has_no_price_or_distance_property(self, client, settings):
        """
        The central guarantee, asserted against the schema itself rather than
        its prose -- the description deliberately mentions `distance_miles` to
        explain its absence, so a substring scan would be misleading.
        """
        import yaml

        settings.DEBUG = True
        schema = yaml.safe_load(client.get(reverse("api-docs:schema")).content)

        component = schema["components"]["schemas"]["QuoteRequestRequest"]
        properties = set(component["properties"])

        assert not (properties & {"distance_miles", "total", "price", "subtotal", "amount"})
        assert {"pickup_address", "pickup_at"} <= properties

    def test_booking_creation_schema_has_no_money_field(self, client, settings):
        import yaml

        settings.DEBUG = True
        schema = yaml.safe_load(client.get(reverse("api-docs:schema")).content)
        component = schema["components"]["schemas"]["BookingCreateRequest"]
        properties = set(component["properties"])

        assert "quote_token" in properties
        assert not (properties & {"total", "price", "subtotal", "amount", "fare"})

    @pytest.mark.parametrize("view", ["swagger", "redoc"])
    def test_inline_bootstrap_csp_is_scoped_to_docs(self, client, settings, view):
        settings.DEBUG = False

        def directives(response):
            assert response.status_code == 200
            return dict(
                directive.strip().split(" ", 1)
                for directive in response["Content-Security-Policy"].split(";")
            )

        docs_csp = directives(client.get(reverse(f"api-docs:{view}")))
        assert docs_csp["script-src"].split() == ["'self'", "'unsafe-inline'"]
        assert docs_csp["style-src"] == "'self' 'unsafe-inline'"
        assert docs_csp["connect-src"] == "'self'"

        normal_csp = directives(client.get("/dashboard/login/"))
        assert "'unsafe-inline'" not in normal_csp["script-src"].split()
        # The raw schema keeps the global policy, too.
        assert directives(client.get(reverse("api-docs:schema"))) == normal_csp
