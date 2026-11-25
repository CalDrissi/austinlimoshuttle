"""
Self-service account endpoints: profile edit and cards on file.

Two properties carry the weight here:
  * a profile edit cannot take an email another account already uses
  * every card action is scoped to the signed-in customer -- someone else's
    card id is a 404, never a way to touch their card

Stripe is stubbed the same way the payment tests stub it: `payments.gateway._client`
is replaced so nothing reaches the network or a real account.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from payments.models import PaymentSettings, SavedCard

User = get_user_model()


@pytest.fixture
def configured(db):
    config = PaymentSettings.load()
    config.mode = PaymentSettings.Mode.TEST
    config.publishable_key = "pk_test_51ABCDEFexamplepublishable"
    config.secret_key = "sk_test_example0000wxyz"
    config.webhook_secret = "whsec_ABCDEFexamplewebhooksecret00"
    config.is_enabled = True
    config.save()
    return config


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
class TestAuthMe:
    """
    Every storefront page asks "who am I?" on load. Anonymous must be a quiet
    2xx (204, no body) -- a 403 here lands in the browser console as a failed
    request on every page a signed-out visitor opens.
    """

    def test_anonymous_get_is_a_quiet_204(self, client, db):
        response = client.get(reverse("api:me"))
        assert response.status_code == 204
        assert not response.content

    def test_signed_in_get_returns_the_profile(self, auth, user):
        response = auth.get(reverse("api:me"))
        assert response.status_code == 200
        assert response.json()["email"] == "owner@example.com"

    def test_anonymous_patch_is_still_rejected(self, client, db):
        response = client.patch(reverse("api:me"), {"first_name": "X"},
                                content_type="application/json")
        assert response.status_code == 403


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


def stub_setup_client(secret="seti_test_secret_123"):
    """A StripeClient stub for the SetupIntent + customer-create path."""
    client = MagicMock()
    client.customers.create.return_value = MagicMock(id="cus_test_123")
    client.setup_intents.create.return_value = MagicMock(client_secret=secret)
    return client


@pytest.mark.django_db
class TestSetupIntent:
    def test_requires_authentication(self, client, configured):
        assert client.post(reverse("api:my_card_setup_intent")).status_code == 403

    def test_returns_a_client_secret(self, auth, user, configured):
        with patch("payments.gateway._client", return_value=stub_setup_client()):
            response = auth.post(reverse("api:my_card_setup_intent"))
        assert response.status_code == 200
        body = response.json()
        assert body["client_secret"] == "seti_test_secret_123"
        assert body["publishable_key"] == configured.publishable_key

    def test_reuses_an_existing_stripe_customer(self, auth, user, configured):
        user.stripe_customer_id = "cus_existing"
        user.save(update_fields=["stripe_customer_id"])
        client = stub_setup_client()
        with patch("payments.gateway._client", return_value=client):
            auth.post(reverse("api:my_card_setup_intent"))
        # A customer already on file is reused, not recreated.
        client.customers.create.assert_not_called()
        _, kwargs = client.setup_intents.create.call_args
        assert kwargs["params"]["customer"] == "cus_existing"

    def test_unavailable_when_not_configured(self, auth, user):
        # No PaymentSettings configured -> 503, not a 500.
        assert auth.post(reverse("api:my_card_setup_intent")).status_code == 503


@pytest.mark.django_db
class TestAddCard:
    def test_saves_a_card_from_a_payment_method(self, auth, user, configured):
        user.stripe_customer_id = "cus_test_123"
        user.save(update_fields=["stripe_customer_id"])
        client = MagicMock()
        client.payment_methods.retrieve.return_value = MagicMock(
            customer="cus_test_123",
            card=MagicMock(brand="visa", last4="4242", exp_month=12, exp_year=2030),
        )
        with patch("payments.gateway._client", return_value=client):
            response = auth.post(reverse("api:my_cards"),
                                 {"payment_method_id": "pm_abc"},
                                 content_type="application/json")
        assert response.status_code == 201
        assert user.saved_cards.count() == 1
        card = user.saved_cards.first()
        assert card.last4 == "4242"
        assert card.is_default is True  # first card becomes the default

    def test_rejects_a_payment_method_that_isnt_the_users(self, auth, user, configured):
        user.stripe_customer_id = "cus_mine"
        user.save(update_fields=["stripe_customer_id"])
        client = MagicMock()
        client.payment_methods.retrieve.return_value = MagicMock(
            customer="cus_somebody_else", card=MagicMock(),
        )
        with patch("payments.gateway._client", return_value=client):
            response = auth.post(reverse("api:my_cards"),
                                 {"payment_method_id": "pm_theirs"},
                                 content_type="application/json")
        assert response.status_code == 502
        assert user.saved_cards.count() == 0


@pytest.mark.django_db
class TestSetDefaultCard:
    def _card(self, owner, pm, default=False):
        return SavedCard.objects.create(
            customer=owner, stripe_payment_method_id=pm, brand="visa",
            last4="4242", exp_month=12, exp_year=2030, is_default=default,
        )

    def test_sets_a_card_as_default_and_clears_the_others(self, auth, user):
        first = self._card(user, "pm_1", default=True)
        second = self._card(user, "pm_2")
        response = auth.post(reverse("api:my_card_set_default", args=[second.pk]))
        assert response.status_code == 200
        assert response.json()["is_default"] is True
        first.refresh_from_db(); second.refresh_from_db()
        assert second.is_default is True
        assert first.is_default is False

    def test_another_customers_card_is_404(self, auth, user, db):
        other = User.objects.create_user(email="other@example.com",
                                         password="ApiLocal!2026")
        theirs = self._card(other, "pm_other", default=True)
        response = auth.post(reverse("api:my_card_set_default", args=[theirs.pk]))
        assert response.status_code == 404
        theirs.refresh_from_db()
        assert theirs.is_default is True  # untouched

    def test_requires_authentication(self, client, user):
        card = self._card(user, "pm_x", default=True)
        assert client.post(
            reverse("api:my_card_set_default", args=[card.pk])).status_code == 403


@pytest.mark.django_db
class TestCardScoping:
    def test_cannot_delete_another_customers_card(self, auth, user, db):
        other = User.objects.create_user(email="other@example.com",
                                         password="ApiLocal!2026")
        theirs = SavedCard.objects.create(
            customer=other, stripe_payment_method_id="pm_other", brand="visa",
            last4="4242", is_default=True,
        )
        assert auth.delete(
            reverse("api:my_card_delete", args=[theirs.pk])).status_code == 404
        assert SavedCard.objects.filter(pk=theirs.pk).exists()
