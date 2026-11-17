"""
Self-service account endpoints.

The property that carries the weight here: a profile edit cannot take an email
another account already uses -- the email is the sign-in identity.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(
        email="owner@example.com", password="ApiLocal!2026",
        first_name="Owner", last_name="One", phone="5125550100",
    )


@pytest.fixture
def auth(client, user):
    # ScopedClient.login mirrors the scoped /api/ session cookie (see conftest).
    assert client.login(username="owner@example.com", password="ApiLocal!2026")
    return client


@pytest.mark.django_db
class TestProfileEdit:
    def test_requires_authentication(self, client):
        response = client.patch(reverse("api:account_profile"),
                                {"first_name": "X"}, content_type="application/json")
        assert response.status_code == 403

    def test_updates_name_phone_and_email(self, auth, user):
        response = auth.patch(
            reverse("api:account_profile"),
            {"first_name": "Jo", "last_name": "Rider", "phone": "5125559999",
             "email": "jo@example.com"},
            content_type="application/json",
        )
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.first_name == "Jo"
        assert user.last_name == "Rider"
        assert user.phone == "5125559999"
        assert user.email == "jo@example.com"
        assert response.json()["email"] == "jo@example.com"

    def test_email_is_lowercased(self, auth, user):
        auth.patch(reverse("api:account_profile"),
                   {"email": "MixedCase@Example.COM"}, content_type="application/json")
        user.refresh_from_db()
        assert user.email == "mixedcase@example.com"

    def test_rejects_an_email_another_account_uses(self, auth, user):
        User.objects.create_user(email="taken@example.com", password="ApiLocal!2026")
        response = auth.patch(reverse("api:account_profile"),
                              {"email": "taken@example.com"},
                              content_type="application/json")
        assert response.status_code == 400
        assert "email" in response.json()
        user.refresh_from_db()
        assert user.email == "owner@example.com"

    def test_uniqueness_check_is_case_insensitive(self, auth, user):
        User.objects.create_user(email="taken@example.com", password="ApiLocal!2026")
        response = auth.patch(reverse("api:account_profile"),
                              {"email": "TAKEN@example.com"},
                              content_type="application/json")
        assert response.status_code == 400

    def test_keeping_your_own_email_is_allowed(self, auth, user):
        response = auth.patch(reverse("api:account_profile"),
                              {"email": "owner@example.com", "first_name": "Keep"},
                              content_type="application/json")
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.first_name == "Keep"

    def test_rejects_a_malformed_email(self, auth, user):
        response = auth.patch(reverse("api:account_profile"),
                              {"email": "not-an-email"},
                              content_type="application/json")
        assert response.status_code == 400
        user.refresh_from_db()
        assert user.email == "owner@example.com"

    def test_a_partial_patch_leaves_other_fields_untouched(self, auth, user):
        auth.patch(reverse("api:account_profile"),
                   {"phone": "5125551234"}, content_type="application/json")
        user.refresh_from_db()
        assert user.phone == "5125551234"
        assert user.first_name == "Owner"
        assert user.email == "owner@example.com"
