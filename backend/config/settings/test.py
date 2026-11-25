"""
Test settings. Used by pytest via pytest.ini -- never by a running server.

The weakened password hasher belongs here and nowhere else: PBKDF2 otherwise
dominates suite runtime, but a fast hasher must never be reachable from an
environment that touches real user data.
"""

from .dev import *

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Fail loudly if a test tries to send mail.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Booking-confirmation fan-out runs inline: tests assert on mail.outbox and
# EmailLog rows, which a background thread would race.
NOTIFICATIONS_SYNC = True

# Tests must never reach the network.
GOOGLE_MAPS_API_KEY = "test-key-not-real"

# Keep migrations on: they are part of what we are testing, and the legacy
# import depends on the real schema.
