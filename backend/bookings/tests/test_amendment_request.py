"""
BookingAmendmentRequest model behaviour.

The API tests cover the endpoints; these pin the model's own guarantees: the
booking is untouched while pending, approve() applies + re-prices, the
transitions are idempotent, and the OLD->NEW diff resolves correctly.
"""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from bookings.models import Booking, BookingAmendmentRequest, BookingPriceLine
from fleet.models import DistanceBand, Vehicle
from pricing.models import PricingSettings, TimeSurcharge

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


def _request(booking, **changes):
    return BookingAmendmentRequest.objects.create(
        booking=booking, requested_by=booking.customer,
        requested_changes=changes, old_total=booking.total,
        new_subtotal=booking.subtotal, new_total=booking.total, currency="USD",
    )


@pytest.mark.django_db
class TestApprove:
    def test_applies_fields_and_marks_approved(self, booking):
        staff = User.objects.create_user(email="staff@x.com", is_staff=True)
        req = _request(booking, passenger_count=3, notes="car seat")
        req.approve(reviewed_by=staff)

        booking.refresh_from_db()
        assert booking.passenger_count == 3
        assert booking.notes == "car seat"
        assert req.status == BookingAmendmentRequest.Status.APPROVED
        assert booking.pending_amendment is None

    def test_phone_lands_on_the_account(self, booking):
        staff = User.objects.create_user(email="staff2@x.com", is_staff=True)
        _request(booking, phone="+15125559999").approve(reviewed_by=staff)
        booking.customer.refresh_from_db()
        assert booking.customer.phone == "+15125559999"

    def test_pickup_change_reprices(self, booking):
        TimeSurcharge.objects.create(
            name="Night", start_time=time(21, 0), end_time=time(6, 0),
            percentage=Decimal("20.00"), is_active=True,
        )
        staff = User.objects.create_user(email="staff3@x.com", is_staff=True)
        night = timezone.localtime(booking.pickup_at).replace(hour=23, minute=0)
        req = _request(booking, pickup_at=night.isoformat())
        req.approve(reviewed_by=staff)

        booking.refresh_from_db()
        assert booking.total > Decimal("145.10")
        assert req.new_total == booking.total

    def test_is_idempotent(self, booking):
        staff = User.objects.create_user(email="staff4@x.com", is_staff=True)
        req = _request(booking, passenger_count=3)
        req.approve(reviewed_by=staff)
        booking.refresh_from_db()
        req.approve(reviewed_by=staff)  # no-op second time
        assert booking.passenger_count == 3
        assert req.status == BookingAmendmentRequest.Status.APPROVED


@pytest.mark.django_db
class TestDecline:
    def test_records_reason_and_leaves_booking(self, booking):
        staff = User.objects.create_user(email="staff5@x.com", is_staff=True)
        req = _request(booking, passenger_count=3)
        req.decline(reviewed_by=staff, reason="no availability")
        booking.refresh_from_db()
        assert booking.passenger_count == 2
        assert req.status == BookingAmendmentRequest.Status.DECLINED
        assert req.decline_reason == "no availability"

    def test_is_idempotent(self, booking):
        staff = User.objects.create_user(email="staff6@x.com", is_staff=True)
        req = _request(booking, passenger_count=3)
        req.decline(reviewed_by=staff, reason="first")
        req.decline(reviewed_by=staff, reason="second")
        assert req.decline_reason == "first"


@pytest.mark.django_db
class TestDiff:
    def test_changed_fields_resolve_old_and_new(self, booking):
        req = _request(booking, passenger_count=3)
        rows = {r["field"]: r for r in req.changed_fields()}
        assert rows["passenger_count"]["old"] == 2
        assert rows["passenger_count"]["new"] == 3
        assert rows["passenger_count"]["label"] == "Passengers"

    def test_price_delta(self, booking):
        req = _request(booking, passenger_count=3)
        req.new_total = Decimal("160.00")
        assert req.price_delta == Decimal("14.90")
