"""
Path-scoped CSRF cookie (config.session.ScopedCsrfMiddleware).

The session cookie is scoped per path so the storefront (/api/) and the staff
dashboard/driver portal can't clobber each other's login. The CSRF cookie must
be scoped the same way: Django's ``login()`` rotates the CSRF token, so with one
site-wide ``csrftoken`` cookie a customer signing in on the storefront would
invalidate the token already baked into an open dashboard or driver form -- the
next staff/driver POST then fails with "CSRF token from POST incorrect".
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from config.session import (
    DRIVER_CSRF_COOKIE_NAME,
    STOREFRONT_CSRF_COOKIE_NAME,
    csrf_cookie_name_for,
)


class _Req:
    def __init__(self, path):
        self.path = path


def test_cookie_name_is_scoped_by_path():
    assert csrf_cookie_name_for(_Req("/api/auth/csrf/")) == STOREFRONT_CSRF_COOKIE_NAME
    assert csrf_cookie_name_for(_Req("/driver/login/")) == DRIVER_CSRF_COOKIE_NAME
    assert csrf_cookie_name_for(_Req("/dashboard/")) == "csrftoken"


@pytest.mark.django_db
def test_api_csrf_endpoint_sets_only_the_storefront_cookie():
    resp = Client().get(reverse("api:csrf"))
    assert STOREFRONT_CSRF_COOKIE_NAME in resp.cookies
    assert "csrftoken" not in resp.cookies


@pytest.mark.django_db
def test_driver_login_page_sets_its_own_cookie():
    resp = Client().get(reverse("driver:login"))
    assert DRIVER_CSRF_COOKIE_NAME in resp.cookies
    assert "csrftoken" not in resp.cookies
    assert STOREFRONT_CSRF_COOKIE_NAME not in resp.cookies


@pytest.mark.django_db
def test_dashboard_login_does_not_clobber_the_driver_csrf_token():
    """The reported regression: logging into the dashboard rotates `csrftoken`,
    which must NOT invalidate an open /driver/login/ form (its own cookie)."""
    User = get_user_model()
    staff = User.objects.create_user(email="staff@example.com", password="StaffPass!2026")
    staff.is_staff = True
    staff.save()
    client = Client(enforce_csrf_checks=True)

    # Driver login page issues its own CSRF cookie.
    client.get(reverse("driver:login"))
    driver_token = client.cookies[DRIVER_CSRF_COOKIE_NAME].value

    # Dashboard login rotates the DEFAULT csrftoken on success.
    client.get(reverse("dashboard:login"))
    dash_token = client.cookies["csrftoken"].value
    client.post(
        reverse("dashboard:login"),
        data={"username": "staff@example.com", "password": "StaffPass!2026",
              "csrfmiddlewaretoken": dash_token},
    )

    # The driver cookie is untouched by the dashboard login.
    assert client.cookies[DRIVER_CSRF_COOKIE_NAME].value == driver_token


@pytest.mark.django_db
def test_storefront_login_does_not_clobber_the_staff_csrf_token():
    """The regression: a login under /api/ rotates the storefront token but must
    leave the staff/driver ``csrftoken`` cookie untouched."""
    User = get_user_model()
    User.objects.create_user(email="rider@example.com", password="RiderPass!2026")
    client = Client(enforce_csrf_checks=True)

    # The dashboard page issues the default csrftoken cookie.
    client.get(reverse("dashboard:login"))
    staff_token = client.cookies["csrftoken"].value

    # Prime + log in on the storefront, which rotates the CSRF token on login().
    client.get(reverse("api:csrf"))
    store_token = client.cookies[STOREFRONT_CSRF_COOKIE_NAME].value
    resp = client.post(
        reverse("api:login"),
        data={"email": "rider@example.com", "password": "RiderPass!2026"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=store_token,
    )
    assert resp.status_code == 200

    # The storefront token rotated; the staff token did not.
    assert client.cookies[STOREFRONT_CSRF_COOKIE_NAME].value != store_token
    assert client.cookies["csrftoken"].value == staff_token


@pytest.mark.django_db
def test_authenticated_storefront_write_uses_the_scoped_csrf_cookie():
    """DRF's SessionAuthentication runs its own CSRF check; it must read the
    storefront's scoped cookie, or every authenticated storefront write 403s."""
    User = get_user_model()
    User.objects.create_user(email="rider2@example.com", password="RiderPass!2026")
    client = Client(enforce_csrf_checks=True)

    client.get(reverse("api:csrf"))
    token = client.cookies[STOREFRONT_CSRF_COOKIE_NAME].value
    login = client.post(
        reverse("api:login"),
        data={"email": "rider2@example.com", "password": "RiderPass!2026"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert login.status_code == 200

    # Still authenticated: a write WITHOUT the token is genuinely rejected (the
    # PermissionDenied is raised in auth, so the session survives for the next
    # assertion).
    bad = client.post(reverse("api:logout"))
    assert bad.status_code == 403

    # The same write WITH the scoped token passes -- the whole point of the fix.
    token = client.cookies[STOREFRONT_CSRF_COOKIE_NAME].value  # rotated on login
    ok = client.post(reverse("api:logout"), HTTP_X_CSRFTOKEN=token)
    assert ok.status_code != 403, ok.content
