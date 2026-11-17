"""Local development settings. Never used on a server."""

from .base import *
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

# Console backend so no mail escapes during development. Real SMTP is
# configured only in prod.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

INTERNAL_IPS = ["127.0.0.1"]

# The Next.js dev server is a different origin (port 3000), so Django's CSRF
# middleware rejects its POSTs unless the origin is trusted. Production does
# not need this: the two apps share a domain there, which is also why the dev
# frontend must call http://localhost:8000 rather than http://127.0.0.1:8000 --
# `localhost` and `127.0.0.1` are different sites to a browser, and a Lax
# session cookie set by one is never sent to the other.
CSRF_TRUSTED_ORIGINS = env.list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default=["http://localhost:3000", "http://127.0.0.1:3000"],
)

# Password hashing is deliberately NOT weakened here. Development accounts get
# the same PBKDF2 treatment as production; the fast hasher lives in
# settings/test.py where it cannot reach a real database.
