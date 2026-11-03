"""
Branded 403 / 404 / 500 pages.

Django's own default error pages are stark grey text. For the server-rendered
surfaces (admin, dashboard, driver) we serve on-brand pages instead, by placing
403.html / 404.html / 500.html in the project template dir -- Django's default
handlers (django.views.defaults) pick those up automatically when DEBUG=False,
so no handler wiring in the root URLconf is required.

Under DEBUG=True the technical debug page is shown instead, so these only ever
appear in production (testmode). Every assertion below therefore pins
DEBUG=False, which is what exercises the real code path.
"""

from pathlib import Path

import pytest
from django.conf import settings
from django.template.loader import get_template
from django.test import RequestFactory, override_settings
from django.views.defaults import page_not_found, permission_denied, server_error

TEMPLATE_DIR = Path(settings.BASE_DIR) / "templates"

# A marker only our templates carry, so a passing assertion proves OUR page
# rendered and not Django's default (which says "Not Found" / "Server Error"
# with no branding).
BRAND_MARKER = "M&amp;M Austin Limo"


def test_error_templates_exist():
    for name in ("403.html", "404.html", "500.html", "error_base.html"):
        assert (TEMPLATE_DIR / name).exists(), f"{name} missing from {TEMPLATE_DIR}"


def test_templates_are_self_contained_and_csp_safe():
    """
    The RENDERED page must carry no <script> (CSP blocks inline scripts, and an
    external one would need a static pipeline the 500 page cannot rely on) and no
    unrendered template tags (the 500 handler renders with an empty context, so a
    {% static %}/{% url %} that needed context would leak or blow up). Checking
    the rendered output -- not the source -- avoids false hits on the templates'
    own explanatory comments.
    """
    for name in ("403.html", "404.html", "500.html"):
        rendered = get_template(name).render({})
        assert "<script" not in rendered.lower(), f"{name} rendered a <script>"
        assert "{%" not in rendered, f"{name} left an unrendered template tag"
        assert "{{" not in rendered, f"{name} left an unrendered variable"


@override_settings(DEBUG=False)
def test_404_renders_custom_template():
    request = RequestFactory().get("/no-such-page/")
    response = page_not_found(request, Exception("not found"))
    assert response.status_code == 404
    body = response.content.decode()
    assert BRAND_MARKER in body
    assert "Page not found" in body


@override_settings(DEBUG=False)
def test_403_renders_custom_template():
    request = RequestFactory().get("/forbidden/")
    response = permission_denied(request, Exception("denied"))
    assert response.status_code == 403
    body = response.content.decode()
    assert BRAND_MARKER in body
    assert "You don't have access to this page" in body


@override_settings(DEBUG=False)
def test_500_renders_custom_template():
    """
    The 500 handler renders with NO request context, so this proves the template
    needs none. If it referenced {{ request }} or a context processor it would
    render blank here.
    """
    request = RequestFactory().get("/boom/")
    response = server_error(request)
    assert response.status_code == 500
    body = response.content.decode()
    assert BRAND_MARKER in body
    assert "Something went wrong" in body


@override_settings(DEBUG=False)
def test_404_through_the_client_hits_the_branded_page():
    """End-to-end: a real request to a missing URL returns the branded 404."""
    from django.test import Client

    response = Client().get("/this-path-does-not-exist/")
    assert response.status_code == 404
    assert BRAND_MARKER in response.content.decode()


def test_get_template_resolves_each_error_page():
    for name in ("403.html", "404.html", "500.html"):
        assert get_template(name) is not None
