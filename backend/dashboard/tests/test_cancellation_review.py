"""
Back-office review of customer cancellation requests.

The dashboard screen is the human side of BookingCancellationRequest: staff see
the pending queue and approve (cancel + staff-set refund, issued through the
existing Stripe refund path) or decline (reason + email). These pin that the
screen is staff-gated, that approval refunds the STAFF-SET amount (full, partial
and zero), that the booking is cancelled on approval but untouched on decline,
that resolved requests are not re-processed, and that the sidebar badge counts
what is waiting.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, BookingCancellationRequest, BookingPriceLine
from dashboard.permissions import DISPATCHER, MANAGER, sync_roles
from fleet.models import DistanceBand, Vehicle
from notifications.models import EmailLog
from payments.models import Payment, PaymentSettings, Refund
from pricing.models import PricingSettings

User = get_user_model()
PASSWORD = "DashLocal!2026"


@pytest.fixture
def roles(db):
    sync_roles()


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
def vehicle(db):
    v = Vehicle.objects.create(
        name="Business Class", slug="bc", hourly_rate=Decimal("85.00"),
        minimum_fare=Decimal("95.00"), is_active=True,
        passenger_capacity=4, luggage_capacity=4,
    )
    for start, end, rate in [(0, 6, "15.00"), (6, 50, "2.90")]:
        DistanceBand.objects.create(vehicle=v, from_miles=start, to_miles=end,
                                    rate_per_mile=Decimal(rate))
    PricingSettings.load()
    return v


@pytest.fixture
def booking(db, vehicle):
    owner = User.objects.create_user(
        email="rider@example.com", first_name="Sam", last_name="Ray",
        phone="+15125550100",
    )
    b = Booking.objects.create(
        customer=owner, vehicle=vehicle,
        pickup_address="ABIA", dropoff_address="Downtown",
        pickup_at=timezone.now() + timedelta(days=5),
        distance_miles=Decimal("25"),
        subtotal=Decimal("145.10"), total=Decimal("145.10"),
        passenger_count=2, luggage_count=1,
        status=Booking.Status.CONFIRMED, currency="USD",
    )
    BookingPriceLine.objects.create(
        booking=b, kind=BookingPriceLine.Kind.BAND, label="25 mi",
        amount=Decimal("145.10"),
    )
    Payment.objects.create(
        booking=b, payment_intent_id="pi_cancel_review",
        amount=Decimal("145.10"), status=Payment.Status.SUCCEEDED, currency="USD",
    )
    return b


def _request(booking, paid=Decimal("145.10")):
    return BookingCancellationRequest.objects.create(
        booking=booking, requested_by=booking.customer,
        paid_amount=paid, currency="USD",
    )


def staff_in(role):
    user = User.objects.create_user(
        email=f"{role.lower()}@example.com", password=PASSWORD, is_staff=True,
    )
    user.groups.add(Group.objects.get(name=role))
    return user


def _stub_client(refund_id="re_test_1"):
    client = MagicMock()
    client.refunds.create.return_value = MagicMock(id=refund_id)
    return client


@pytest.mark.django_db
class TestAccess:
    def test_anonymous_is_redirected_to_login(self, client):
        response = client.get(reverse("dashboard:cancellations"))
        assert response.status_code == 302
        assert "/dashboard/login/" in response["Location"]

    def test_dispatcher_can_reach_the_queue(self, client, roles):
        staff_in(DISPATCHER)
        client.login(username="dispatcher@example.com", password=PASSWORD)
        assert client.get(reverse("dashboard:cancellations")).status_code == 200


@pytest.mark.django_db
class TestApprove:
    def test_manager_approve_full_refund_cancels_and_refunds(
        self, client, roles, configured, booking
    ):
        staff_in(MANAGER)
        client.login(username="manager@example.com", password=PASSWORD)
        req = _request(booking)

        with patch("payments.gateway._client", return_value=_stub_client()):
            response = client.post(
                reverse("dashboard:cancellation_detail", args=[req.pk]),
                {"action": "approve", "refund_amount": "145.10"},
            )
        assert response.status_code == 302

        req.refresh_from_db()
        booking.refresh_from_db()
        assert req.status == BookingCancellationRequest.Status.APPROVED
        assert req.refund_amount == Decimal("145.10")
        assert req.reviewed_by.email == "manager@example.com"
        assert booking.status == Booking.Status.CANCELLED
        # The staff-set amount was refunded through the real refund path.
        refund = Refund.objects.get()
        assert refund.amount == Decimal("145.10")
        assert refund.created_by.email == "manager@example.com"
        # Customer emailed that it is cancelled (with the refund).
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.BOOKING_CANCELLED, booking=booking,
        ).exists()

    def test_manager_approve_partial_refund(self, client, roles, configured, booking):
        staff_in(MANAGER)
        client.login(username="manager@example.com", password=PASSWORD)
        req = _request(booking)

        with patch("payments.gateway._client", return_value=_stub_client()):
            response = client.post(
                reverse("dashboard:cancellation_detail", args=[req.pk]),
                {"action": "approve", "refund_amount": "45.10"},
            )
        assert response.status_code == 302
        req.refresh_from_db()
        booking.refresh_from_db()
        assert req.refund_amount == Decimal("45.10")
        assert booking.status == Booking.Status.CANCELLED
        refund = Refund.objects.get()
        assert refund.amount == Decimal("45.10")

    def test_zero_refund_cancels_without_touching_stripe(
        self, client, roles, configured, booking
    ):
        staff_in(MANAGER)
        client.login(username="manager@example.com", password=PASSWORD)
        req = _request(booking)

        with patch("payments.gateway._client") as stub:
            response = client.post(
                reverse("dashboard:cancellation_detail", args=[req.pk]),
                {"action": "approve", "refund_amount": "0"},
            )
            stub.assert_not_called()  # no gateway call for a zero refund
        assert response.status_code == 302
        req.refresh_from_db()
        booking.refresh_from_db()
        assert req.refund_amount == Decimal("0.00")
        assert booking.status == Booking.Status.CANCELLED
        assert not Refund.objects.exists()

    def test_refund_above_paid_amount_is_rejected(
        self, client, roles, configured, booking
    ):
        staff_in(MANAGER)
        client.login(username="manager@example.com", password=PASSWORD)
        req = _request(booking)
        response = client.post(
            reverse("dashboard:cancellation_detail", args=[req.pk]),
            {"action": "approve", "refund_amount": "999.00"},
        )
        assert response.status_code == 302
        req.refresh_from_db()
        booking.refresh_from_db()
        assert req.status == BookingCancellationRequest.Status.PENDING  # not processed
        assert booking.status == Booking.Status.CONFIRMED

    def test_dispatcher_cannot_approve(self, client, roles, configured, booking):
        """Approving issues a refund -> needs refund rights (Manager only)."""
        staff_in(DISPATCHER)
        client.login(username="dispatcher@example.com", password=PASSWORD)
        req = _request(booking)
        response = client.post(
            reverse("dashboard:cancellation_detail", args=[req.pk]),
            {"action": "approve", "refund_amount": "145.10"},
        )
        assert response.status_code == 403
        req.refresh_from_db()
        booking.refresh_from_db()
        assert req.status == BookingCancellationRequest.Status.PENDING
        assert booking.status == Booking.Status.CONFIRMED

    def test_already_resolved_is_not_reprocessed(
        self, client, roles, configured, booking
    ):
        manager = staff_in(MANAGER)
        client.login(username="manager@example.com", password=PASSWORD)
        req = _request(booking)
        req.decline(reviewed_by=manager, reason="first call")

        response = client.post(
            reverse("dashboard:cancellation_detail", args=[req.pk]),
            {"action": "approve", "refund_amount": "145.10"},
        )
        assert response.status_code == 302
        req.refresh_from_db()
        booking.refresh_from_db()
        assert req.status == BookingCancellationRequest.Status.DECLINED
        assert booking.status == Booking.Status.CONFIRMED
        assert not Refund.objects.exists()


@pytest.mark.django_db
class TestApproveCash:
    """
    A cash fare never touched Stripe, so approving its cancellation must not
    call (or even require) the Stripe gateway -- deliberately no `configured`
    fixture here. The refund is recorded as a manual (hand-back) refund.
    """

    @pytest.fixture
    def cash_booking(self, booking):
        payment = booking.payments.get()
        payment.provider = Payment.Provider.CASH
        payment.payment_intent_id = ""
        payment.save(update_fields=["provider", "payment_intent_id"])
        return booking

    def test_partial_cash_refund_approves_without_stripe(
        self, client, roles, cash_booking
    ):
        staff_in(MANAGER)
        client.login(username="manager@example.com", password=PASSWORD)
        req = _request(cash_booking)

        with patch("payments.gateway._client") as stub:
            response = client.post(
                reverse("dashboard:cancellation_detail", args=[req.pk]),
                {"action": "approve", "refund_amount": "45.10"},
            )
            stub.assert_not_called()
        assert response.status_code == 302

        req.refresh_from_db()
        cash_booking.refresh_from_db()
        assert req.status == BookingCancellationRequest.Status.APPROVED
        assert req.refund_amount == Decimal("45.10")
        assert cash_booking.status == Booking.Status.CANCELLED
        # Recorded as a manual refund: real amount, no Stripe reference.
        refund = Refund.objects.get()
        assert refund.amount == Decimal("45.10")
        assert refund.stripe_refund_id == ""
        assert refund.created_by.email == "manager@example.com"
        # The history explains how the money goes back.
        note = cash_booking.status_changes.first().note
        assert "cash refund $45.10 to be returned to customer" in note
        # Customer still gets the cancellation email with the refund amount.
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.BOOKING_CANCELLED, booking=cash_booking,
        ).exists()

    def test_full_cash_refund_approves_without_stripe(
        self, client, roles, cash_booking
    ):
        staff_in(MANAGER)
        client.login(username="manager@example.com", password=PASSWORD)
        req = _request(cash_booking)

        response = client.post(
            reverse("dashboard:cancellation_detail", args=[req.pk]),
            {"action": "approve", "refund_amount": "145.10"},
        )
        assert response.status_code == 302
        req.refresh_from_db()
        cash_booking.refresh_from_db()
        assert req.status == BookingCancellationRequest.Status.APPROVED
        assert cash_booking.status == Booking.Status.CANCELLED
        assert Refund.objects.get().amount == Decimal("145.10")

    def test_card_history_note_keeps_stripe_wording(
        self, client, roles, configured, booking
    ):
        """The card path is untouched: refunded via Stripe, noted as refunded."""
        staff_in(MANAGER)
        client.login(username="manager@example.com", password=PASSWORD)
        req = _request(booking)

        with patch("payments.gateway._client", return_value=_stub_client()):
            client.post(
                reverse("dashboard:cancellation_detail", args=[req.pk]),
                {"action": "approve", "refund_amount": "45.10"},
            )
        booking.refresh_from_db()
        note = booking.status_changes.first().note
        assert "refunded 45.10 USD" in note
        assert "cash" not in note.lower()


@pytest.mark.django_db
class TestDecline:
    def test_decline_records_reason_and_leaves_booking(self, client, roles, booking):
        staff_in(DISPATCHER)
        client.login(username="dispatcher@example.com", password=PASSWORD)
        req = _request(booking)

        response = client.post(
            reverse("dashboard:cancellation_detail", args=[req.pk]),
            {"action": "decline", "reason": "This fare is non-refundable."},
        )
        assert response.status_code == 302
        req.refresh_from_db()
        booking.refresh_from_db()
        assert req.status == BookingCancellationRequest.Status.DECLINED
        assert req.decline_reason == "This fare is non-refundable."
        assert booking.status == Booking.Status.CONFIRMED  # untouched
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.CANCELLATION_DECLINED, booking=booking,
        ).exists()

    def test_decline_requires_a_reason(self, client, roles, booking):
        staff_in(DISPATCHER)
        client.login(username="dispatcher@example.com", password=PASSWORD)
        req = _request(booking)
        client.post(
            reverse("dashboard:cancellation_detail", args=[req.pk]),
            {"action": "decline", "reason": "   "},
        )
        req.refresh_from_db()
        assert req.status == BookingCancellationRequest.Status.PENDING


@pytest.mark.django_db
class TestBadge:
    def test_pending_count_shown_in_sidebar(self, client, roles, booking):
        staff_in(DISPATCHER)
        client.login(username="dispatcher@example.com", password=PASSWORD)
        _request(booking)

        response = client.get(reverse("dashboard:home"))
        assert response.context["nav_pending_cancellations"] == 1
        assert b"Cancellations" in response.content
