"""
Cash / pay-on-arrival semantics.

A cash fare is money we have NOT received yet: confirming the booking must
record an awaiting-collection payment, not a succeeded one. Succeeded is only
set when staff mark the cash collected in the back office. These pin that,
plus the knock-on that matters most: paid-to-date (the refund ceiling on a
cancellation request) reflects money actually in hand.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking
from fleet.models import Vehicle
from payments.models import Payment
from pricing.models import PricingSettings

User = get_user_model()


@pytest.fixture
def vehicle(db):
    PricingSettings.load()
    return Vehicle.objects.create(
        name="Business Class", slug="bc", hourly_rate=Decimal("85.00"),
        minimum_fare=Decimal("95.00"), is_active=True,
    )


@pytest.fixture
def booking(db, vehicle):
    return Booking.objects.create(
        vehicle=vehicle, pickup_address="ABIA", dropoff_address="Downtown",
        pickup_at=timezone.now() + timedelta(days=3),
        status=Booking.Status.PENDING,
        total=Decimal("145.10"), subtotal=Decimal("145.10"), currency="USD",
        guest_email="guest@example.com", guest_phone="+15125550000",
    )


def pay_cash(client, booking):
    return client.post(reverse("api:pay_cash", args=[booking.reference]))


@pytest.mark.django_db
class TestPayCash:
    def test_records_awaiting_collection_not_paid(self, client, booking):
        response = pay_cash(client, booking)
        assert response.status_code == 200

        booking.refresh_from_db()
        assert booking.status == Booking.Status.CONFIRMED
        payment = booking.payments.get()
        assert payment.provider == Payment.Provider.CASH
        assert payment.status == Payment.Status.PROCESSING  # NOT succeeded
        assert payment.amount == Decimal("145.10")

    def test_repeat_confirm_does_not_double_record(self, client, booking):
        pay_cash(client, booking)
        response = pay_cash(client, booking)
        assert response.status_code == 200  # idempotent, not an error
        assert booking.payments.count() == 1

    def test_already_paid_booking_is_409(self, client, booking):
        Payment.objects.create(
            booking=booking, provider=Payment.Provider.CASH,
            amount=booking.total, currency="USD",
            status=Payment.Status.SUCCEEDED,
        )
        assert pay_cash(client, booking).status_code == 409

    def test_cancelled_booking_is_409(self, client, booking):
        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status"])
        assert pay_cash(client, booking).status_code == 409


@pytest.mark.django_db
class TestPaidToDate:
    """The cancellation-request snapshot is the refund ceiling -- it must only
    count money actually collected."""

    def _owned_booking(self, vehicle, owner):
        b = Booking.objects.create(
            customer=owner, vehicle=vehicle,
            pickup_address="ABIA", dropoff_address="Downtown",
            pickup_at=timezone.now() + timedelta(days=5),
            status=Booking.Status.CONFIRMED,
            total=Decimal("145.10"), subtotal=Decimal("145.10"), currency="USD",
        )
        Payment.objects.create(
            booking=b, provider=Payment.Provider.CASH,
            amount=Decimal("145.10"), currency="USD",
            status=Payment.Status.PROCESSING,
        )
        return b

    def test_uncollected_cash_counts_as_nothing_paid(self, client, vehicle):
        owner = User.objects.create_user(
            email="rider@example.com", password="CashRider!2026",
        )
        booking = self._owned_booking(vehicle, owner)
        # ScopedClient.login also sets the scoped /api/ session cookie.
        assert client.login(username="rider@example.com", password="CashRider!2026")

        response = client.post(reverse("api:cancel_request", args=[booking.reference]))
        assert response.status_code == 201
        assert Decimal(response.json()["paid_amount"]) == Decimal("0.00")

    def test_collected_cash_counts_in_full(self, client, vehicle):
        owner = User.objects.create_user(
            email="rider2@example.com", password="CashRider!2026",
        )
        booking = self._owned_booking(vehicle, owner)
        payment = booking.payments.get()
        payment.status = Payment.Status.SUCCEEDED  # staff marked it collected
        payment.save(update_fields=["status"])
        assert client.login(username="rider2@example.com", password="CashRider!2026")

        response = client.post(reverse("api:cancel_request", args=[booking.reference]))
        assert response.status_code == 201
        assert Decimal(response.json()["paid_amount"]) == Decimal("145.10")
