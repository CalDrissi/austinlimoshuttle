"""
BookingCancellationRequest model behaviour.

The API/dashboard tests cover the endpoints; these pin the model's own
guarantees: the booking is untouched while pending, approve() cancels and records
the staff-set refund (including a partial or zero amount), decline() leaves the
booking alone, and both transitions are idempotent.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from bookings.models import Booking, BookingCancellationRequest, BookingPriceLine
from fleet.models import DistanceBand, Vehicle
from pricing.models import PricingSettings

User = get_user_model()


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
    return b


def _request(booking, paid=Decimal("145.10")):
    return BookingCancellationRequest.objects.create(
        booking=booking, requested_by=booking.customer,
        paid_amount=paid, currency="USD",
    )


@pytest.mark.django_db
class TestPending:
    def test_booking_stays_confirmed_while_pending(self, booking):
        req = _request(booking)
        booking.refresh_from_db()
        assert booking.status == Booking.Status.CONFIRMED
        assert req.status == BookingCancellationRequest.Status.PENDING
        assert booking.pending_cancellation == req


@pytest.mark.django_db
class TestApprove:
    def test_cancels_and_records_full_refund(self, booking):
        staff = User.objects.create_user(email="staff@x.com", is_staff=True)
        req = _request(booking)
        req.approve(reviewed_by=staff, refund_amount=Decimal("145.10"))

        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED
        assert booking.cancelled_at is not None
        assert req.status == BookingCancellationRequest.Status.APPROVED
        assert req.refund_amount == Decimal("145.10")
        assert req.reviewed_by == staff
        assert booking.pending_cancellation is None

    def test_records_a_partial_refund(self, booking):
        staff = User.objects.create_user(email="staff2@x.com", is_staff=True)
        req = _request(booking)
        req.approve(reviewed_by=staff, refund_amount=Decimal("45.10"))

        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED
        assert req.refund_amount == Decimal("45.10")

    def test_records_a_zero_refund(self, booking):
        staff = User.objects.create_user(email="staff3@x.com", is_staff=True)
        req = _request(booking)
        req.approve(reviewed_by=staff, refund_amount=Decimal("0.00"))

        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED
        assert req.refund_amount == Decimal("0.00")

    def test_writes_a_status_change_audit_row(self, booking):
        staff = User.objects.create_user(email="staff4@x.com", is_staff=True)
        req = _request(booking)
        req.approve(reviewed_by=staff, refund_amount=Decimal("45.10"))
        change = booking.status_changes.first()
        assert change.to_status == Booking.Status.CANCELLED
        assert change.changed_by == staff

    def test_is_idempotent(self, booking):
        staff = User.objects.create_user(email="staff5@x.com", is_staff=True)
        req = _request(booking)
        req.approve(reviewed_by=staff, refund_amount=Decimal("100.00"))
        req.approve(reviewed_by=staff, refund_amount=Decimal("0.00"))  # no-op
        assert req.refund_amount == Decimal("100.00")
        assert req.status == BookingCancellationRequest.Status.APPROVED


@pytest.mark.django_db
class TestDecline:
    def test_records_reason_and_leaves_booking(self, booking):
        staff = User.objects.create_user(email="staff6@x.com", is_staff=True)
        req = _request(booking)
        req.decline(reviewed_by=staff, reason="non-refundable fare")
        booking.refresh_from_db()
        assert booking.status == Booking.Status.CONFIRMED
        assert req.status == BookingCancellationRequest.Status.DECLINED
        assert req.decline_reason == "non-refundable fare"

    def test_is_idempotent(self, booking):
        staff = User.objects.create_user(email="staff7@x.com", is_staff=True)
        req = _request(booking)
        req.decline(reviewed_by=staff, reason="first")
        req.decline(reviewed_by=staff, reason="second")
        assert req.decline_reason == "first"
