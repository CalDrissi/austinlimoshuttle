"""Booking model behaviour and referential guarantees."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import ProtectedError
from django.utils import timezone

from bookings.models import Booking, BookingPriceLine, Driver, generate_reference
from fleet.models import Vehicle
from payments.models import Payment

User = get_user_model()


@pytest.fixture
def vehicle(db):
    return Vehicle.objects.create(name="Business Class", slug="bc", hourly_rate=85)


@pytest.fixture
def customer(db):
    return User.objects.create_user(email="rider@example.com", first_name="Sam", last_name="Ray")


@pytest.fixture
def booking(db, vehicle, customer):
    return Booking.objects.create(
        customer=customer, vehicle=vehicle,
        pickup_address="Austin-Bergstrom International Airport",
        dropoff_address="Downtown Austin",
        pickup_at=timezone.now() + timedelta(days=2),
        distance_miles=Decimal("12.500"), total=Decimal("95.00"),
    )


@pytest.mark.django_db
class TestReference:
    def test_generated_reference_is_unambiguous(self):
        """No I/O/0/1 -- references are read aloud over the phone."""
        for _ in range(50):
            ref = generate_reference()
            assert len(ref) == 8
            assert not set(ref) & set("IO01")

    def test_reference_is_unique(self, vehicle):
        from django.db import IntegrityError

        Booking.objects.create(
            reference="FIXED123", vehicle=vehicle, pickup_address="a",
            pickup_at=timezone.now(),
        )
        with pytest.raises(IntegrityError):
            Booking.objects.create(
                reference="FIXED123", vehicle=vehicle, pickup_address="b",
                pickup_at=timezone.now(),
            )


@pytest.mark.django_db
class TestReferentialIntegrity:
    def test_vehicle_with_bookings_cannot_be_deleted(self, booking, vehicle):
        """PROTECT: renaming or retiring a vehicle must not erase history."""
        with pytest.raises(ProtectedError):
            vehicle.delete()

    def test_deleting_a_customer_keeps_the_booking(self, booking, customer):
        customer.delete()
        booking.refresh_from_db()
        assert booking.customer is None
        assert Booking.objects.filter(pk=booking.pk).exists()

    def test_deleting_a_driver_keeps_the_booking(self, booking):
        driver = Driver.objects.create(full_name="Alex Ruiz")
        booking.driver = driver
        booking.save()
        driver.delete()
        booking.refresh_from_db()
        assert booking.driver is None

    def test_price_lines_are_removed_with_the_booking(self, booking):
        BookingPriceLine.objects.create(
            booking=booking, kind=BookingPriceLine.Kind.BASE, label="Base", amount=50,
        )
        booking.delete()
        assert BookingPriceLine.objects.count() == 0

    def test_booking_with_payments_cannot_be_deleted(self, booking):
        """Financial records are never cascade-deleted."""
        Payment.objects.create(booking=booking, amount=Decimal("95.00"))
        with pytest.raises(ProtectedError):
            booking.delete()


@pytest.mark.django_db
class TestVehicleSnapshot:
    def test_snapshot_is_captured_on_save(self, booking):
        assert booking.vehicle_name_snapshot == "Business Class"

    def test_renaming_the_vehicle_does_not_rewrite_history(self, booking, vehicle):
        vehicle.name = "Executive Sedan"
        vehicle.save()
        booking.refresh_from_db()
        assert booking.vehicle_name_snapshot == "Business Class"


@pytest.mark.django_db
class TestCancellation:
    def test_future_booking_is_cancellable(self, booking):
        assert booking.is_cancellable

    def test_past_booking_is_not(self, booking):
        booking.pickup_at = timezone.now() - timedelta(hours=1)
        booking.save()
        assert not booking.is_cancellable

    def test_already_cancelled_is_not(self, booking):
        booking.status = Booking.Status.CANCELLED
        booking.save()
        assert not booking.is_cancellable

    def test_completed_is_not(self, booking):
        booking.status = Booking.Status.COMPLETED
        booking.save()
        assert not booking.is_cancellable


@pytest.mark.django_db
class TestCustomerName:
    def test_uses_the_account_name(self, booking):
        assert booking.customer_name == "Sam Ray"

    def test_guest_booking_uses_the_contact_name_not_the_placard(self, vehicle):
        guest = Booking.objects.create(
            vehicle=vehicle, pickup_address="a", pickup_at=timezone.now(),
            guest_name="J. Okafor", pickup_sign="Mr Placard",
        )
        assert guest.customer_name == "J. Okafor"

    def test_guest_booking_without_a_name_is_just_guest(self, vehicle):
        """The placard is the passenger's sign, not the booker -- never shown
        as the customer."""
        guest = Booking.objects.create(
            vehicle=vehicle, pickup_address="a", pickup_at=timezone.now(),
            pickup_sign="Mr Placard",
        )
        assert guest.customer_name == "Guest"


@pytest.mark.django_db
class TestPaymentModel:
    def test_card_last4_rejects_a_full_number(self, booking):
        """
        A database-level guarantee, not just validation. The whole point of this
        schema is that a card number has nowhere to go.

        Either error is a pass: the 4-character column rejects the length
        (DataError) before the CHECK constraint on the digit pattern
        (IntegrityError) gets a chance. Both are the database refusing.
        """
        from django.db import DatabaseError

        with pytest.raises(DatabaseError):
            Payment.objects.create(
                booking=booking, amount=10, card_last4="4111111111111111",
            )

    def test_card_last4_accepts_four_digits(self, booking):
        payment = Payment.objects.create(
            booking=booking, amount=10, card_last4="4242", card_brand="visa",
        )
        assert payment.masked_card == "Visa •••• 4242"

    def test_no_field_can_hold_a_card_number(self):
        """Guards against a future migration reintroducing the legacy columns."""
        forbidden = {"card_number", "pan", "expiration_date", "expiry",
                     "securitycode", "cvv", "cvc"}
        fields = {f.name for f in Payment._meta.get_fields()}
        assert not (fields & forbidden)

    def test_last4_field_is_too_short_for_a_pan(self):
        field = Payment._meta.get_field("card_last4")
        assert isinstance(field, models.CharField)
        assert field.max_length == 4


@pytest.mark.django_db
class TestQuerySet:
    def test_upcoming_excludes_past_and_cancelled(self, vehicle, booking):
        Booking.objects.create(
            vehicle=vehicle, pickup_address="past", pickup_at=timezone.now() - timedelta(days=1),
        )
        cancelled = Booking.objects.create(
            vehicle=vehicle, pickup_address="cancelled",
            pickup_at=timezone.now() + timedelta(days=3),
            status=Booking.Status.CANCELLED,
        )
        upcoming = list(Booking.objects.upcoming())
        assert booking in upcoming
        assert cancelled not in upcoming
        assert len(upcoming) == 1
