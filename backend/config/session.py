"""
Path-scoped session cookies.

The storefront (Next.js) authenticates against the API under ``/api/`` using
DRF's ``SessionAuthentication`` -- i.e. an ordinary Django session. The staff
dashboard and Django admin use a Django session too. On a single host (every
port is ``localhost`` in dev; cookies are not scoped by port) both surfaces
would share the one ``sessionid`` cookie -- so signing in as a customer on the
storefront overwrites the staff session, and the dashboard then sees a non-staff
account and answers 403.

Giving ``/api/`` its own cookie name keeps the two logins independent: a
customer session is written to ``mm_store_sessionid`` and is invisible to the
dashboard, which only ever reads ``sessionid`` (and vice versa). This mirrors
production, where the two live on different subdomains and never collide.

This is a faithful subclass of Django 5.2's ``SessionMiddleware`` -- the only
change is that the cookie name is chosen per request instead of read straight
from ``settings.SESSION_COOKIE_NAME``.
"""

import time

from django.conf import settings
from django.contrib.sessions.backends.base import UpdateError
from django.contrib.sessions.exceptions import SessionInterrupted
from django.contrib.sessions.middleware import SessionMiddleware
from django.utils.cache import patch_vary_headers
from django.utils.http import http_date

# Requests under this path get the storefront's own session cookie; everything
# else (dashboard, admin, password-reset) keeps the default cookie.
STOREFRONT_PATH_PREFIX = "/api/"
STOREFRONT_COOKIE_NAME = "mm_store_sessionid"


def cookie_name_for(request) -> str:
    if request.path.startswith(STOREFRONT_PATH_PREFIX):
        return STOREFRONT_COOKIE_NAME
    return settings.SESSION_COOKIE_NAME


class ScopedSessionMiddleware(SessionMiddleware):
    """SessionMiddleware with a per-path cookie name (see module docstring)."""

    def process_request(self, request):
        cookie_name = cookie_name_for(request)
        session_key = request.COOKIES.get(cookie_name)
        request.session = self.SessionStore(session_key)

    def process_response(self, request, response):
        cookie_name = cookie_name_for(request)
        try:
            accessed = request.session.accessed
            modified = request.session.modified
            empty = request.session.is_empty()
        except AttributeError:
            return response
        # Delete the cookie only if the session is entirely empty.
        if cookie_name in request.COOKIES and empty:
            response.delete_cookie(
                cookie_name,
                path=settings.SESSION_COOKIE_PATH,
                domain=settings.SESSION_COOKIE_DOMAIN,
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )
            need_vary_cookie = True
        else:
            need_vary_cookie = accessed
            if (modified or settings.SESSION_SAVE_EVERY_REQUEST) and not empty:
                if request.session.get_expire_at_browser_close():
                    max_age = None
                    expires = None
                else:
                    max_age = request.session.get_expiry_age()
                    expires_time = time.time() + max_age
                    expires = http_date(expires_time)
                # Skip session save for 5xx responses.
                if response.status_code < 500:
                    try:
                        request.session.save()
                    except UpdateError:
                        raise SessionInterrupted(
                            "The request's session was deleted before the "
                            "request completed. The user may have logged "
                            "out in a concurrent request, for example."
                        )
                    response.set_cookie(
                        cookie_name,
                        request.session.session_key,
                        max_age=max_age,
                        expires=expires,
                        domain=settings.SESSION_COOKIE_DOMAIN,
                        path=settings.SESSION_COOKIE_PATH,
                        secure=settings.SESSION_COOKIE_SECURE or None,
                        httponly=settings.SESSION_COOKIE_HTTPONLY or None,
                        samesite=settings.SESSION_COOKIE_SAMESITE,
                    )
                    need_vary_cookie = True
        if need_vary_cookie:
            patch_vary_headers(response, ("Cookie",))
        return response


# ---------------------------------------------------------------------------
# Path-scoped CSRF cookie
# ---------------------------------------------------------------------------
# The session cookie is scoped per path (above); the CSRF cookie must be too,
# for the same reason. Django's ``login()`` rotates the CSRF token to defeat
# token fixation. With one site-wide ``csrftoken`` cookie (Path=/), a customer
# signing in on the storefront (/api/) rotates the token that the dashboard and
# driver portal already baked into any open form -- so the next staff/driver
# POST fails with "CSRF token from POST incorrect". Giving /api/ its own CSRF
# cookie keeps the two surfaces' tokens independent, exactly as with sessions.

from django.middleware.csrf import (  # noqa: E402
    CSRF_TOKEN_LENGTH,
    CsrfViewMiddleware,
    _check_token_format,
    _unmask_cipher_token,
    get_token,
)
from django.utils.decorators import decorator_from_middleware  # noqa: E402

STOREFRONT_CSRF_COOKIE_NAME = "mm_store_csrftoken"
# The driver portal is a third surface. It shares the session cookie with the
# dashboard (staff/driver are one Django session), but its CSRF cookie must be
# its own: Django's login() rotates the CSRF token, so a dashboard login would
# otherwise invalidate an open /driver/login/ form (and vice versa) because they
# shared the one `csrftoken`. Give /driver/ its own cookie to stop that clobber.
DRIVER_PATH_PREFIX = "/driver/"
DRIVER_CSRF_COOKIE_NAME = "mm_driver_csrftoken"


def csrf_cookie_name_for(request) -> str:
    if request.path.startswith(STOREFRONT_PATH_PREFIX):
        return STOREFRONT_CSRF_COOKIE_NAME
    if request.path.startswith(DRIVER_PATH_PREFIX):
        return DRIVER_CSRF_COOKIE_NAME
    return settings.CSRF_COOKIE_NAME


class ScopedCsrfMiddleware(CsrfViewMiddleware):
    """CsrfViewMiddleware with a per-path cookie name (see section docstring).

    Only the cookie read/write is overridden; token generation, the Origin and
    Referer checks, and the header lookup are untouched. The session-backed
    variant (CSRF_USE_SESSIONS) needs no scoping -- the session is already
    scoped -- so it defers to the parent there.
    """

    def _get_secret(self, request):
        if settings.CSRF_USE_SESSIONS:
            return super()._get_secret(request)
        try:
            csrf_secret = request.COOKIES[csrf_cookie_name_for(request)]
        except KeyError:
            return None
        # Can raise InvalidTokenFormat, which process_request handles by
        # minting a fresh cookie -- identical to the stock middleware.
        _check_token_format(csrf_secret)
        if len(csrf_secret) == CSRF_TOKEN_LENGTH:
            csrf_secret = _unmask_cipher_token(csrf_secret)
        return csrf_secret

    def _set_csrf_cookie(self, request, response):
        if settings.CSRF_USE_SESSIONS:
            return super()._set_csrf_cookie(request, response)
        response.set_cookie(
            csrf_cookie_name_for(request),
            request.META["CSRF_COOKIE"],
            max_age=settings.CSRF_COOKIE_AGE,
            domain=settings.CSRF_COOKIE_DOMAIN,
            path=settings.CSRF_COOKIE_PATH,
            secure=settings.CSRF_COOKIE_SECURE,
            httponly=settings.CSRF_COOKIE_HTTPONLY,
            samesite=settings.CSRF_COOKIE_SAMESITE,
        )
        patch_vary_headers(response, ("Cookie",))


class _ScopedEnsureCsrfCookie(ScopedCsrfMiddleware):
    """Scoped counterpart of Django's private _EnsureCsrfCookie.

    Django's ``@ensure_csrf_cookie`` is a per-view decorator built on the stock
    middleware, so it would set the default ``csrftoken`` cookie even for the
    storefront's priming endpoint under /api/. This variant forces the cookie
    the same way but through the scoped middleware, so /api/ gets its own cookie.
    """

    def _reject(self, request, reason):
        return None

    def process_view(self, request, callback, callback_args, callback_kwargs):
        retval = super().process_view(request, callback, callback_args, callback_kwargs)
        get_token(request)  # force process_response to send the cookie
        return retval


# Drop-in replacement for django.views.decorators.csrf.ensure_csrf_cookie that
# honours the per-path cookie name. Used by the storefront's /api/auth/csrf/.
scoped_ensure_csrf_cookie = decorator_from_middleware(_ScopedEnsureCsrfCookie)


# ---------------------------------------------------------------------------
# DRF SessionAuthentication that honours the scoped CSRF cookie
# ---------------------------------------------------------------------------
# DRF enforces CSRF on authenticated session requests with its OWN check built
# on the stock CsrfViewMiddleware (rest_framework.authentication.CSRFCheck),
# which reads settings.CSRF_COOKIE_NAME directly -- it does not go through our
# ScopedCsrfMiddleware. So an authenticated storefront write (amend, cancel,
# save-card, logout) would be validated against the default `csrftoken` cookie
# instead of the storefront's `mm_store_csrftoken`, and fail. This subclass runs
# the same check through the scoped middleware so the right cookie is read.

from rest_framework import exceptions as _drf_exceptions  # noqa: E402
from rest_framework.authentication import (  # noqa: E402
    SessionAuthentication as _DrfSessionAuthentication,
)


class _ScopedCSRFCheck(ScopedCsrfMiddleware):
    def _reject(self, request, reason):
        return reason  # DRF wants the reason string, not an HttpResponse


class ScopedSessionAuthentication(_DrfSessionAuthentication):
    """DRF SessionAuthentication whose CSRF check reads the per-path cookie."""

    def enforce_csrf(self, request):
        def dummy_get_response(request):  # pragma: no cover
            return None

        check = _ScopedCSRFCheck(dummy_get_response)
        check.process_request(request)
        reason = check.process_view(request, None, (), {})
        if reason:
            raise _drf_exceptions.PermissionDenied(f"CSRF Failed: {reason}")


# Teach drf-spectacular to document the subclass exactly like the stock
# SessionAuthentication (cookie-based), so schema generation stays warning-free.
from drf_spectacular.authentication import SessionScheme as _SessionScheme  # noqa: E402


class ScopedSessionScheme(_SessionScheme):
    target_class = "config.session.ScopedSessionAuthentication"
