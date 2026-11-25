"""
Stripe gateway and the payment endpoints.

Every Stripe call is stubbed -- the suite never reaches the network or touches
a real account. The properties under test are the ones that lose money or leak
data when they are wrong:

  * the charged amount comes from the booking, never from the request
  * an unsigned webhook cannot confirm a booking
  * a replayed webhook does not double-process
  * a card number has nowhere to be stored, whatever Stripe sends back
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import stripe
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking
from dashboard.permissions import DISPATCHER, MANAGER, sync_roles
from fleet.models import Vehicle
from payments import gateway
from payments.models import Payment, PaymentSettings, Refund, WebhookEvent

User = get_user_model()

TEST_SECRET = "sk_test_example0000wxyz"
TEST_PUBLISHABLE = "pk_test_51ABCDEFexamplepublishable"
WEBHOOK_SECRET = "whsec_ABCDEFexamplewebhooksecret00"


@pytest.fixture
def configured(db):
    config = PaymentSettings.load()
    config.mode = PaymentSettings.Mode.TEST
    config.publishable_key = TEST_PUBLISHABLE
    config.secret_key = TEST_SECRET
    config.webhook_secret = WEBHOOK_SECRET
    config.is_enabled = True
    config.save()
    return config


@pytest.fixture
def booking(db):
    vehicle = Vehicle.objects.create(name="Business Class", slug="bc", hourly_rate=85)
    return Booking.objects.create(
        vehicle=vehicle, pickup_address="ABIA", dropoff_address="Downtown",
        pickup_at=timezone.now() + timezone.timedelta(days=2),
        total=Decimal("145.10"), subtotal=Decimal("145.10"), currency="USD",
    )


def fake_intent(**overrides):
    data = {
        "id": "pi_test_123",
        "status": "requires_payment_method",
        "amount": 14510,
        "currency": "usd",
        "client_secret": "pi_test_123_secret_abc",
        "metadata": {"booking_reference": ""},
        "charges": {"data": []},
    }
    data.update(overrides)
    return data


def stub_client(intent=None):
    """A StripeClient whose calls return canned objects."""
    client = MagicMock()
    obj = MagicMock()
    payload = intent or fake_intent()
    for key, value in payload.items():
        setattr(obj, key, value)
    obj.get = payload.get
    obj.__getitem__ = lambda _self, key: payload[key]
    client.payment_intents.create.return_value = obj
    client.payment_intents.retrieve.return_value = obj
    return client, obj


@pytest.mark.django_db
class TestConfigurationGuards:
    def test_disabled_payments_refuse_to_charge(self, booking, configured):
        configured.is_enabled = False
        configured.save()
        with pytest.raises(gateway.PaymentConfigurationError, match="switched off"):
            gateway.create_payment_intent(booking)

    def test_missing_secret_key_refuses(self, booking, configured):
        configured._secret_key = ""
        configured.save()
        with pytest.raises(gateway.PaymentConfigurationError, match="secret key"):
            gateway.create_payment_intent(booking)

    def test_live_mode_with_a_test_key_refuses(self, booking, configured):
        """Would otherwise report success while taking no money."""
        PaymentSettings.objects.filter(pk=1).update(mode="live")
        with pytest.raises(gateway.PaymentConfigurationError, match="does not match"):
            gateway.create_payment_intent(booking)

    def test_publishable_key_is_hidden_while_disabled(self, configured):
        configured.is_enabled = False
        configured.save()
        assert gateway.publishable_key() == ""


@pytest.mark.django_db
class TestPaymentIntent:
    def test_amount_comes_from_the_booking(self, booking, configured):
        client, _ = stub_client()
        with patch("payments.gateway._client", return_value=client):
            gateway.create_payment_intent(booking)

        params = client.payment_intents.create.call_args.kwargs["params"]
        assert params["amount"] == 14510  # 145.10 in cents
        assert params["currency"] == "usd"

    def test_uses_an_idempotency_key(self, booking, configured):
        """A retried request must not create a second charge."""
        client, _ = stub_client()
        with patch("payments.gateway._client", return_value=client):
            gateway.create_payment_intent(booking)

        options = client.payment_intents.create.call_args.kwargs["options"]
        assert booking.reference in options["idempotency_key"]

    def test_reuses_a_live_intent_rather_than_stacking_them(self, booking, configured):
        client, _ = stub_client()
        with patch("payments.gateway._client", return_value=client):
            first = gateway.create_payment_intent(booking)
            second = gateway.create_payment_intent(booking)

        assert first.pk == second.pk
        assert client.payment_intents.create.call_count == 1

    def test_zero_amount_is_refused(self, booking, configured):
        booking.total = Decimal("0.00")
        booking.save()
        with pytest.raises(gateway.PaymentGatewayError, match="no amount"):
            gateway.create_payment_intent(booking)

    def test_stripe_errors_become_gateway_errors(self, booking, configured):
        client = MagicMock()
        client.payment_intents.create.side_effect = stripe.APIConnectionError("down")
        with patch("payments.gateway._client", return_value=client), \
             pytest.raises(gateway.PaymentGatewayError):
            gateway.create_payment_intent(booking)

    def test_client_secret_is_not_stored(self):
        """A stored client secret is a stored credential that can leak."""
        fields = {f.name for f in Payment._meta.get_fields()}
        assert "client_secret" not in fields


@pytest.mark.django_db
class TestIntentEndpoint:
    def test_returns_a_client_secret(self, client, booking, configured):
        stripe_client, _ = stub_client()
        with patch("payments.gateway._client", return_value=stripe_client):
            response = client.post(
                reverse("api:payment_intent"), {"reference": booking.reference},
                content_type="application/json",
            )
        assert response.status_code == 200
        assert response.json()["client_secret"] == "pi_test_123_secret_abc"
        assert response.json()["amount"] == "145.10"

    def test_request_body_cannot_change_the_amount(self, client, booking, configured):
        stripe_client, _ = stub_client()
        with patch("payments.gateway._client", return_value=stripe_client):
            client.post(
                reverse("api:payment_intent"),
                {"reference": booking.reference, "amount": "1.00", "total": "1.00"},
                content_type="application/json",
            )
        params = stripe_client.payment_intents.create.call_args.kwargs["params"]
        assert params["amount"] == 14510

    def test_unknown_reference_is_404(self, client, configured):
        response = client.post(reverse("api:payment_intent"), {"reference": "NOPE1234"},
                               content_type="application/json")
        assert response.status_code == 404

    def test_cancelled_booking_cannot_be_paid(self, client, booking, configured):
        booking.status = Booking.Status.CANCELLED
        booking.save()
        response = client.post(reverse("api:payment_intent"),
                               {"reference": booking.reference},
                               content_type="application/json")
        assert response.status_code == 409

    def test_already_paid_booking_is_refused(self, client, booking, configured):
        Payment.objects.create(booking=booking, amount=booking.total,
                               status=Payment.Status.SUCCEEDED)
        response = client.post(reverse("api:payment_intent"),
                               {"reference": booking.reference},
                               content_type="application/json")
        assert response.status_code == 409

    def test_another_customers_booking_is_404(self, client, booking, configured):
        owner = User.objects.create_user(email="owner@example.com")
        booking.customer = owner
        booking.save()
        User.objects.create_user(email="other@example.com", password="PayLocal!2026")
        client.login(username="other@example.com", password="PayLocal!2026")

        response = client.post(reverse("api:payment_intent"),
                               {"reference": booking.reference},
                               content_type="application/json")
        assert response.status_code == 404

    def test_misconfiguration_does_not_leak_details_to_the_customer(
        self, client, booking, configured,
    ):
        configured.is_enabled = False
        configured.save()
        response = client.post(reverse("api:payment_intent"),
                               {"reference": booking.reference},
                               content_type="application/json")
        assert response.status_code == 503
        assert "Stripe" not in response.json()["detail"]
        assert "secret" not in response.json()["detail"].lower()

    def test_config_endpoint_exposes_only_the_publishable_key(self, client, configured):
        body = client.get(reverse("api:payment_config")).json()
        assert body["publishable_key"] == TEST_PUBLISHABLE
        assert TEST_SECRET not in str(body)
        assert WEBHOOK_SECRET not in str(body)


@pytest.mark.django_db
class TestWebhookSecurity:
    def post_webhook(self, client, event, signature="t=1,v1=deadbeef"):
        with patch("payments.gateway.stripe.Webhook.construct_event", return_value=event):
            return client.post(
                reverse("api:payment_webhook"), data=b"{}",
                content_type="application/json", HTTP_STRIPE_SIGNATURE=signature,
            )

    def test_unsigned_request_is_rejected(self, client, booking, configured):
        response = client.post(reverse("api:payment_webhook"), data=b"{}",
                               content_type="application/json")
        assert response.status_code == 400
        assert not WebhookEvent.objects.exists()

    def test_bad_signature_is_rejected(self, client, booking, configured):
        with patch("payments.gateway.stripe.Webhook.construct_event",
                   side_effect=stripe.SignatureVerificationError("bad", "sig")):
            response = client.post(
                reverse("api:payment_webhook"), data=b"{}",
                content_type="application/json", HTTP_STRIPE_SIGNATURE="t=1,v1=forged",
            )
        assert response.status_code == 400

    def test_a_forged_success_cannot_confirm_a_booking(self, client, booking, configured):
        """
        Without signature verification, anyone knowing the URL could post
        `payment_intent.succeeded` and get a free ride.
        """
        with patch("payments.gateway.stripe.Webhook.construct_event",
                   side_effect=stripe.SignatureVerificationError("bad", "sig")):
            client.post(
                reverse("api:payment_webhook"),
                data=b'{"type":"payment_intent.succeeded"}',
                content_type="application/json", HTTP_STRIPE_SIGNATURE="forged",
            )
        booking.refresh_from_db()
        assert booking.status == Booking.Status.PENDING

    def test_missing_webhook_secret_returns_503_so_stripe_retries(
        self, client, booking, configured,
    ):
        configured._webhook_secret = ""
        configured.save()
        response = client.post(
            reverse("api:payment_webhook"), data=b"{}",
            content_type="application/json", HTTP_STRIPE_SIGNATURE="t=1,v1=x",
        )
        assert response.status_code == 503


@pytest.mark.django_db
class TestWebhookProcessing:
    def event(self, booking, event_type="payment_intent.succeeded", **intent_overrides):
        intent = fake_intent(
            status="succeeded",
            metadata={"booking_reference": booking.reference},
            **intent_overrides,
        )
        return {"id": "evt_test_1", "type": event_type, "data": {"object": intent}}

    def post(self, client, event):
        with patch("payments.gateway.stripe.Webhook.construct_event", return_value=event):
            return client.post(
                reverse("api:payment_webhook"), data=b"{}",
                content_type="application/json", HTTP_STRIPE_SIGNATURE="t=1,v1=ok",
            )

    def test_success_confirms_the_booking(self, client, booking, configured):
        Payment.objects.create(booking=booking, payment_intent_id="pi_test_123",
                               amount=booking.total)
        assert self.post(client, self.event(booking)).status_code == 200

        booking.refresh_from_db()
        assert booking.status == Booking.Status.CONFIRMED
        assert booking.payments.get().status == Payment.Status.SUCCEEDED

    def test_confirmation_is_audited(self, client, booking, configured):
        Payment.objects.create(booking=booking, payment_intent_id="pi_test_123",
                               amount=booking.total)
        self.post(client, self.event(booking))
        change = booking.status_changes.get()
        assert change.to_status == Booking.Status.CONFIRMED
        assert "Stripe" in change.note

    def test_replayed_event_is_ignored(self, client, booking, configured):
        Payment.objects.create(booking=booking, payment_intent_id="pi_test_123",
                               amount=booking.total)
        event = self.event(booking)
        assert self.post(client, event).status_code == 200
        second = self.post(client, event)

        assert second.json()["status"] == "duplicate ignored"
        assert booking.status_changes.count() == 1
        assert WebhookEvent.objects.count() == 1

    def test_failure_is_recorded_without_confirming(self, client, booking, configured):
        Payment.objects.create(booking=booking, payment_intent_id="pi_test_123",
                               amount=booking.total)
        event = self.event(booking, event_type="payment_intent.payment_failed")
        event["data"]["object"]["status"] = "requires_payment_method"
        event["data"]["object"]["last_payment_error"] = {"message": "Card declined"}

        self.post(client, event)
        booking.refresh_from_db()
        assert booking.status == Booking.Status.PENDING
        assert "declined" in booking.payments.get().error_message

    def test_only_last4_is_stored_from_the_charge(self, client, booking, configured):
        """Stripe never sends a full number, but the field could not hold one anyway."""
        Payment.objects.create(booking=booking, payment_intent_id="pi_test_123",
                               amount=booking.total)
        event = self.event(booking, charges={"data": [{
            "id": "ch_1",
            "receipt_url": "https://stripe.example/receipt",
            "payment_method_details": {"card": {"brand": "visa", "last4": "4242"}},
        }]})
        self.post(client, event)

        payment = booking.payments.get()
        assert payment.card_last4 == "4242"
        assert payment.card_brand == "visa"
        assert payment.masked_card == "Visa •••• 4242"

    def test_unhandled_event_types_are_acknowledged_not_retried(
        self, client, booking, configured,
    ):
        event = self.event(booking, event_type="customer.created")
        response = self.post(client, event)
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    def test_webhook_for_an_unknown_booking_does_not_crash(self, client, configured):
        intent = fake_intent(status="succeeded", metadata={"booking_reference": "GONE1234"})
        event = {"id": "evt_x", "type": "payment_intent.succeeded",
                 "data": {"object": intent}}
        assert self.post(client, event).status_code == 200


@pytest.mark.django_db
class TestRefunds:
    @pytest.fixture
    def paid(self, booking, configured):
        return Payment.objects.create(
            booking=booking, payment_intent_id="pi_test_123",
            amount=Decimal("145.10"), status=Payment.Status.SUCCEEDED,
        )

    def stub_refund(self, refund_id="re_test_1"):
        client = MagicMock()
        client.refunds.create.return_value = MagicMock(id=refund_id)
        return client

    def test_cash_refund_needs_no_stripe(self, booking, db):
        """
        A cash payment never touched Stripe: refunding it records a manual
        refund with no gateway call and no configuration -- deliberately no
        `configured` fixture here.
        """
        paid_cash = Payment.objects.create(
            booking=booking, provider=Payment.Provider.CASH,
            amount=Decimal("145.10"), status=Payment.Status.SUCCEEDED,
        )
        with patch("payments.gateway._client") as stub:
            refund = gateway.refund(paid_cash, amount=Decimal("45.10"),
                                    reason="cancelled")
            stub.assert_not_called()
        assert refund.amount == Decimal("45.10")
        assert refund.stripe_refund_id == ""

    def test_cash_refund_still_validates_the_remaining_amount(self, booking, db):
        paid_cash = Payment.objects.create(
            booking=booking, provider=Payment.Provider.CASH,
            amount=Decimal("145.10"), status=Payment.Status.SUCCEEDED,
        )
        gateway.refund(paid_cash, amount=Decimal("100.00"))
        with pytest.raises(gateway.PaymentGatewayError):
            gateway.refund(paid_cash, amount=Decimal("100.00"))

    def test_full_refund(self, paid, configured):
        with patch("payments.gateway._client", return_value=self.stub_refund()):
            refund = gateway.refund(paid, reason="cancelled")
        assert refund.amount == Decimal("145.10")

    def test_partial_refund(self, paid, configured):
        with patch("payments.gateway._client", return_value=self.stub_refund()):
            refund = gateway.refund(paid, amount=Decimal("45.10"))
        assert refund.amount == Decimal("45.10")

    def test_cannot_refund_more_than_remains(self, paid, configured):
        with patch("payments.gateway._client", return_value=self.stub_refund()):
            gateway.refund(paid, amount=Decimal("100.00"))
            with pytest.raises(gateway.PaymentGatewayError, match="remains available"):
                gateway.refund(paid, amount=Decimal("100.00"))

    def test_cannot_refund_an_unsuccessful_payment(self, booking, configured):
        pending = Payment.objects.create(booking=booking, amount=Decimal("10"),
                                         status=Payment.Status.PROCESSING)
        with pytest.raises(gateway.PaymentGatewayError, match="successful payment"):
            gateway.refund(pending)

    def test_zero_refund_is_refused(self, paid, configured):
        with pytest.raises(gateway.PaymentGatewayError, match="greater than zero"):
            gateway.refund(paid, amount=Decimal("0"))

    def test_refund_from_the_dashboard_is_attributed(self, client, paid, configured, db):
        sync_roles()
        manager = User.objects.create_user(
            email="manager@example.com", password="PayLocal!2026", is_staff=True,
        )
        manager.groups.add(Group.objects.get(name=MANAGER))
        client.login(username="manager@example.com", password="PayLocal!2026")

        with patch("payments.gateway._client", return_value=self.stub_refund()):
            response = client.post(
                reverse("dashboard:issue_refund", args=[paid.booking.reference]),
                {"amount": "20.00", "reason": "late cancellation"}, follow=True,
            )
        assert response.status_code == 200
        refund = Refund.objects.get()
        assert refund.amount == Decimal("20.00")
        assert refund.created_by == manager

    def test_dispatcher_cannot_refund(self, client, paid, configured, db):
        sync_roles()
        user = User.objects.create_user(
            email="dispatcher@example.com", password="PayLocal!2026", is_staff=True,
        )
        user.groups.add(Group.objects.get(name=DISPATCHER))
        client.login(username="dispatcher@example.com", password="PayLocal!2026")

        response = client.post(
            reverse("dashboard:issue_refund", args=[paid.booking.reference]),
            {"amount": "20.00"},
        )
        assert response.status_code == 403
        assert not Refund.objects.exists()

    def test_external_refund_is_recorded_once(self, paid, configured):
        charge = {
            "id": "ch_1", "payment_intent": "pi_test_123",
            "refunds": {"data": [
                {"id": "re_ext_1", "amount": 5000, "reason": "requested_by_customer"},
            ]},
        }
        gateway.record_refund_from_charge(charge)
        gateway.record_refund_from_charge(charge)
        assert Refund.objects.count() == 1
        assert Refund.objects.get().amount == Decimal("50.00")


@pytest.mark.django_db
class TestCardsOnFile:
    """Saving a card via a SetupIntent -- no charge, just a card kept for later."""

    @pytest.fixture
    def customer(self, db):
        return User.objects.create_user(
            email="saver@example.com", password="PayLocal!2026",
            first_name="Sa", last_name="Ver",
        )

    def test_setup_intent_creates_a_customer_and_returns_the_secret(self, customer, configured):
        client = MagicMock()
        client.customers.create.return_value = MagicMock(id="cus_new")
        client.setup_intents.create.return_value = MagicMock(client_secret="seti_secret")
        with patch("payments.gateway._client", return_value=client):
            secret = gateway.create_setup_intent(customer)
        assert secret == "seti_secret"
        customer.refresh_from_db()
        assert customer.stripe_customer_id == "cus_new"
        _, kwargs = client.setup_intents.create.call_args
        # Off-session usage so staff can bill the card later -- same as checkout.
        assert kwargs["params"]["usage"] == "off_session"
        assert kwargs["params"]["customer"] == "cus_new"

    def test_save_card_rejects_a_foreign_payment_method(self, customer, configured):
        customer.stripe_customer_id = "cus_mine"
        customer.save(update_fields=["stripe_customer_id"])
        client = MagicMock()
        client.payment_methods.retrieve.return_value = MagicMock(
            customer="cus_someone_else", card=MagicMock(),
        )
        with patch("payments.gateway._client", return_value=client):
            with pytest.raises(gateway.PaymentGatewayError, match="could not be verified"):
                gateway.save_card_from_setup(customer, "pm_theirs")
        assert customer.saved_cards.count() == 0

    def test_save_card_persists_display_bits_only(self, customer, configured):
        customer.stripe_customer_id = "cus_mine"
        customer.save(update_fields=["stripe_customer_id"])
        client = MagicMock()
        client.payment_methods.retrieve.return_value = MagicMock(
            customer="cus_mine",
            card=MagicMock(brand="visa", last4="4242", exp_month=4, exp_year=2031),
        )
        with patch("payments.gateway._client", return_value=client):
            card = gateway.save_card_from_setup(customer, "pm_mine")
        assert card.last4 == "4242"
        assert card.brand == "visa"
        assert card.is_default is True

    def test_set_default_moves_the_flag(self, customer):
        from payments.models import SavedCard
        a = SavedCard.objects.create(customer=customer, stripe_payment_method_id="pm_a",
                                     last4="1111", is_default=True)
        b = SavedCard.objects.create(customer=customer, stripe_payment_method_id="pm_b",
                                     last4="2222", is_default=False)
        gateway.set_default_card(b)
        a.refresh_from_db(); b.refresh_from_db()
        assert b.is_default is True
        assert a.is_default is False
