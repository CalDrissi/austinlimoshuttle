"""
Passwordless email-code sign-in.

Mirrors the guarantees the password login already makes -- a successful verify
returns the same payload and sets the same session cookie as `/auth/login/` --
while adding the one-time-code specifics: neutral responses (no enumeration),
hashed storage, expiry, single use, and throttling on both the send and the
guess.
"""

import re
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from accounts.models import LoginCode

User = get_user_model()


@pytest.fixture(autouse=True)
def clear_state():
    mail.outbox.clear()
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="rider@example.com", password="ApiLocal!2026",
        first_name="Sam", last_name="Rider", phone="5125550100",
    )


def code_from_outbox() -> str:
    """Pull the six-digit code out of the most recent email."""
    match = re.search(r"\b(\d{6})\b", mail.outbox[-1].body)
    assert match, "no six-digit code in the email body"
    return match.group(1)


def send_code(client, email):
    return client.post(reverse("api:send_code"), {"email": email},
                       content_type="application/json")


def verify_code(client, email, code):
    return client.post(reverse("api:verify_code"), {"email": email, "code": code},
                       content_type="application/json")


@pytest.mark.django_db
class TestSendCode:
    def test_known_address_is_emailed_a_code(self, client, customer):
        response = send_code(client, "rider@example.com")
        assert response.status_code == 200
        assert len(mail.outbox) == 1
        assert LoginCode.objects.filter(email="rider@example.com").count() == 1
        # The code reaches the inbox but is never stored in the clear.
        assert code_from_outbox() not in LoginCode.objects.first().code_hash

    def test_email_is_case_insensitive(self, client, customer):
        response = send_code(client, "RIDER@Example.COM")
        assert response.status_code == 200
        assert LoginCode.objects.filter(email="rider@example.com").count() == 1

    def test_unknown_address_is_silent_but_looks_identical(self, client, customer):
        known = send_code(client, "rider@example.com")
        mail.outbox.clear()
        unknown = send_code(client, "nobody@example.com")

        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()
        assert len(mail.outbox) == 0

    def test_inactive_account_gets_no_code(self, client, customer):
        customer.is_active = False
        customer.save()
        response = send_code(client, "rider@example.com")
        assert response.status_code == 200
        assert len(mail.outbox) == 0

    def test_malformed_address_does_not_error(self, client):
        response = send_code(client, "not-an-email")
        assert response.status_code == 200
        assert len(mail.outbox) == 0

    def test_a_new_request_supersedes_the_previous_code(self, client, customer):
        send_code(client, "rider@example.com")
        first = code_from_outbox()
        send_code(client, "rider@example.com")
        # The first code is now spent; only the latest one verifies.
        assert verify_code(client, "rider@example.com", first).status_code == 400


@pytest.mark.django_db
class TestVerifyCode:
    def test_valid_code_signs_in_with_the_login_payload(self, client, customer):
        send_code(client, "rider@example.com")
        response = verify_code(client, "rider@example.com", code_from_outbox())

        assert response.status_code == 200
        assert response.json() == {
            "email": "rider@example.com",
            "first_name": "Sam",
            "last_name": "Rider",
        }
        # The session cookie is live: the authenticated /me/ endpoint answers.
        me = client.get(reverse("api:me"))
        assert me.status_code == 200
        assert me.json()["email"] == "rider@example.com"

    def test_payload_is_identical_to_password_login(self, client, customer):
        password_login = client.post(
            reverse("api:login"),
            {"email": "rider@example.com", "password": "ApiLocal!2026"},
            content_type="application/json",
        )
        send_code(client, "rider@example.com")
        code_login = verify_code(client, "rider@example.com", code_from_outbox())
        assert code_login.json() == password_login.json()

    def test_no_password_is_created(self, client, customer):
        legacy = User.objects.create_user(email="legacy@example.com")
        legacy.set_unusable_password()
        legacy.save()

        send_code(client, "legacy@example.com")
        response = verify_code(client, "legacy@example.com", code_from_outbox())

        assert response.status_code == 200
        legacy.refresh_from_db()
        assert not legacy.has_usable_password()

    def test_wrong_code_is_rejected(self, client, customer):
        send_code(client, "rider@example.com")
        response = verify_code(client, "rider@example.com", "000000")
        assert response.status_code == 400

    def test_expired_code_is_rejected(self, client, customer):
        send_code(client, "rider@example.com")
        code = code_from_outbox()
        LoginCode.objects.filter(email="rider@example.com").update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        assert verify_code(client, "rider@example.com", code).status_code == 400

    def test_a_used_code_cannot_be_reused(self, client, customer):
        send_code(client, "rider@example.com")
        code = code_from_outbox()
        assert verify_code(client, "rider@example.com", code).status_code == 200
        assert verify_code(client, "rider@example.com", code).status_code == 400

    def test_missing_fields_are_rejected(self, client, customer):
        assert verify_code(client, "rider@example.com", "").status_code == 400
        assert verify_code(client, "", "123456").status_code == 400


@pytest.mark.django_db
class TestThrottling:
    def test_too_many_sends_to_one_address_are_dropped(self, client, customer):
        for _ in range(LoginCode.objects.model.MAX_ATTEMPTS):
            send_code(client, "rider@example.com")
        # Only LOGIN_CODE_SEND_MAX actually produced mail.
        from api.views import LOGIN_CODE_SEND_MAX
        assert len(mail.outbox) == LOGIN_CODE_SEND_MAX

    def test_guessing_is_capped_so_a_code_cannot_be_brute_forced(self, client, customer):
        send_code(client, "rider@example.com")
        code = code_from_outbox()
        for _ in range(LoginCode.MAX_ATTEMPTS):
            assert verify_code(client, "rider@example.com", "111111").status_code == 400
        # The budget is spent; even the correct code is now refused.
        assert verify_code(client, "rider@example.com", code).status_code == 400
