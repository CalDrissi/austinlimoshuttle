"""
Client cancellation-request -> staff approval workflow (API side).

A customer no longer cancels a paid booking directly: a cancel request files a
pending row that staff approve (cancel + staff-set refund) or decline. The
properties pinned here:

  * the booking is NOT cancelled while a request is pending,
  * the cancellation window is enforced,
  * a request notifies staff + the admin address,
  * only the owner may request,
  * the pending/last request is surfaced on the booking.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, BookingCancellationRequest, BookingPriceLine
from content.models import SiteSettings
from fleet.models import DistanceBand, Vehicle
from notifications.models import EmailLog, EmailSettings
from payments.models import Payment
from pricing.models import PricingSettings

User = get_user_model()
PASSWORD = "CancelLocal!2026"


@pytest.fixture(autouse=True)
def empty_outbox():
    mail.outbox.clear()
    yield
    mail.outbox.clear()


@pytest.fixture
def email_on(db):
    config = EmailSettings.load()
    config.host = "mail.austinlimoshuttle.com"
    config.from_email = "bookings@austinlimoshuttle.com"
    config.from_name = "Austin Limo Shuttle"
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


def make_owner(email="rider@example.com"):
    return User.objects.create_user(
        email=email, password=PASSWORD, first_name="Sam", last_name="Ray",
        phone="+15125550100",
    )


def make_booking(owner, vehicle, *, days_ahead=5, paid=Decimal("145.10")):
    booking = Booking.objects.create(
        customer=owner, vehicle=vehicle,
        pickup_address="Austin-Bergstrom International Airport",
        dropoff_address="Downtown Austin",
        pickup_at=timezone.now() + timedelta(days=days_ahead),
        distance_miles=Decimal("25"),
        subtotal=Decimal("145.10"), total=Decimal("145.10"),
        passenger_count=2, luggage_count=1,
        status=Booking.Status.CONFIRMED, currency="USD",
    )
    BookingPriceLine.objects.create(
        booking=booking, kind=BookingPriceLine.Kind.BAND,
        label="25 mi", amount=Decimal("145.10"),
    )
    if paid is not None:
        Payment.objects.create(
            booking=booking, payment_intent_id="pi_cancel_1",
            amount=paid, status=Payment.Status.SUCCEEDED, currency="USD",
        )
    return booking


def cancel_url(booking):
    return reverse("api:cancel_request", args=[booking.reference])


@pytest.mark.django_db
class TestCancelRequestCreation:
    def test_owner_request_creates_pending_without_cancelling(self, client, vehicle):
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        client.login(username=owner.email, password=PASSWORD)

        response = client.post(cancel_url(booking))
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "approved"
        # paid_amount snapshotted from the succeeded payment; refund not yet set.
        assert body["paid_amount"] == "145.10"
        assert body["refund_amount"] == "0.00"

        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED
        req = BookingCancellationRequest.objects.get(booking=booking)
        assert req.status == BookingCancellationRequest.Status.APPROVED
        assert req.paid_amount == Decimal("145.10")

    def test_paid_amount_is_zero_without_a_successful_payment(self, client, vehicle):
        owner = make_owner()
        booking = make_booking(owner, vehicle, paid=None)
        client.login(username=owner.email, password=PASSWORD)
        response = client.post(cancel_url(booking))
        assert response.status_code == 201
        assert response.json()["paid_amount"] == "0.00"

    def test_within_the_cancellation_window_is_rejected(self, client, vehicle):
        settings = PricingSettings.load()
        settings.cancellation_window_hours = 24
        settings.save()
        owner = make_owner()
        booking = make_booking(owner, vehicle, days_ahead=0)  # inside 24h
        client.login(username=owner.email, password=PASSWORD)

        response = client.post(cancel_url(booking))
        assert response.status_code == 400
        assert "within 24 hours" in response.json()["detail"]
        assert not BookingCancellationRequest.objects.exists()

    def test_terminal_booking_is_rejected(self, client, vehicle):
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status"])
        client.login(username=owner.email, password=PASSWORD)
        response = client.post(cancel_url(booking))
        assert response.status_code == 400
        assert not BookingCancellationRequest.objects.exists()

    def test_second_pending_request_is_rejected(self, client, vehicle):
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        client.login(username=owner.email, password=PASSWORD)
        first = client.post(cancel_url(booking))
        assert first.status_code == 201
        second = client.post(cancel_url(booking))
        assert second.status_code == 400
        assert BookingCancellationRequest.objects.count() == 1


@pytest.mark.django_db
class TestCancelRequestPermissions:
    def test_anonymous_is_rejected(self, client, vehicle):
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        response = client.post(cancel_url(booking))
        assert response.status_code in (401, 403)

    def test_another_customer_gets_404(self, client, vehicle):
        owner = make_owner("owner@example.com")
        booking = make_booking(owner, vehicle)
        User.objects.create_user(email="other@example.com", password=PASSWORD)
        client.login(username="other@example.com", password=PASSWORD)
        response = client.post(cancel_url(booking))
        assert response.status_code == 404
        assert not BookingCancellationRequest.objects.exists()


@pytest.mark.django_db
class TestCancelRequestNotifies:
    def test_request_emails_staff_and_the_admin_address(self, client, vehicle, email_on):
        User.objects.create_user(
            email="dispatch@austinlimoshuttle.com", password=PASSWORD, is_staff=True,
        )
        User.objects.create_user(
            email="manager@austinlimoshuttle.com", password=PASSWORD, is_staff=True,
        )
        site = SiteSettings.load()
        site.ops_notification_email = "ops@austinlimoshuttle.com"
        site.save()

        owner = make_owner()
        booking = make_booking(owner, vehicle)
        client.login(username=owner.email, password=PASSWORD)
        response = client.post(cancel_url(booking))
        assert response.status_code == 201

        # Two messages: the staff alert, then the customer's acknowledgement.
        assert len(mail.outbox) == 2
        recipients = set(mail.outbox[0].to)
        assert "dispatch@austinlimoshuttle.com" in recipients
        assert "manager@austinlimoshuttle.com" in recipients
        assert "ops@austinlimoshuttle.com" in recipients
        assert mail.outbox[1].to == [owner.email]
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.CANCELLATION_REQUESTED, succeeded=True,
        ).exists()
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.CANCELLATION_RECEIVED, succeeded=True,
        ).exists()


@pytest.mark.django_db
class TestBookingSurfacesRequest:
    def test_pending_cancellation_is_exposed(self, client, vehicle):
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        BookingCancellationRequest.objects.create(
            booking=booking, requested_by=owner,
            paid_amount=Decimal("145.10"), currency="USD",
        )
        client.login(username=owner.email, password=PASSWORD)
        response = client.get(reverse("api:my_booking_detail", args=[booking.reference]))
        assert response.status_code == 200
        pending = response.json()["pending_cancellation"]
        assert pending is not None
        assert pending["status"] == "pending"

    @pytest.mark.parametrize("review_status", ["approved", "declined"])
    def test_last_cancellation_is_exposed(self, client, vehicle, review_status):
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        req = BookingCancellationRequest.objects.create(
            booking=booking, requested_by=owner,
            paid_amount=Decimal("145.10"), currency="USD",
        )
        req.status = review_status
        req.refund_amount = Decimal("45.10") if review_status == "approved" else None
        req.decline_reason = "non-refundable" if review_status == "declined" else ""
        req.reviewed_at = timezone.now()
        req.save()
        client.login(username=owner.email, password=PASSWORD)
        response = client.get(reverse("api:my_booking_detail", args=[booking.reference]))
        assert response.status_code == 200
        body = response.json()
        assert body["pending_cancellation"] is None
        assert body["last_cancellation"]["status"] == review_status


@pytest.mark.django_db
def test_auto_refund_calls_gateway_before_cancellation(client, vehicle, monkeypatch):
    settings = PricingSettings.load()
    settings.auto_refund = True
    settings.save()
    owner = make_owner()
    booking = make_booking(owner, vehicle)
    client.login(username=owner.email, password=PASSWORD)
    calls = []
    def refund(payment, **kwargs):
        payment.booking.refresh_from_db()
        assert payment.booking.status == Booking.Status.CONFIRMED
        calls.append(kwargs["amount"])
    monkeypatch.setattr("api.views.payments_gateway.refund", refund)
    response = client.post(cancel_url(booking))
    assert response.status_code == 201
    assert calls == [Decimal("145.10")]
    assert response.json()["refund_amount"] == "145.10"
