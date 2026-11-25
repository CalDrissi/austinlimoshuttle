"""
Voiding abandoned pending bookings.

The storefront creates a booking before payment; when the customer then changes
their trip or identity, the replaced draft is voided so it never reaches the
office as pending work. The endpoint must ONLY touch unpaid pendings — anything
confirmed or with money in motion belongs to the cancellation-request flow.
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


def authorize(client, booking):
    session = client.session
    session["voidable_booking_refs"] = [booking.reference]
    session.save()
    client.cookies["mm_store_sessionid"] = session.session_key


def void(client, booking):
    return client.post(reverse("api:void_pending", args=[booking.reference]))


@pytest.mark.django_db
class TestVoidPending:
    @pytest.fixture(autouse=True)
    def authorize_creator(self, client, booking):
        authorize(client, booking)

    def test_reference_alone_cannot_void(self, client, booking):
        client.cookies.clear()
        assert void(client, booking).status_code == 404

    def test_voids_unpaid_pending(self, client, booking):
        response = void(client, booking)
        assert response.status_code == 200
        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED
        change = booking.status_changes.latest("id")
        assert change.to_status == Booking.Status.CANCELLED
        assert "Voided" in change.note

    def test_idempotent_on_already_cancelled(self, client, booking):
        assert void(client, booking).status_code == 200
        assert void(client, booking).status_code == 200

    def test_refuses_confirmed_booking(self, client, booking):
        booking.status = Booking.Status.CONFIRMED
        booking.save(update_fields=["status"])
        assert void(client, booking).status_code == 409
        booking.refresh_from_db()
        assert booking.status == Booking.Status.CONFIRMED

    def test_refuses_awaiting_cash_collection(self, client, booking):
        Payment.objects.create(
            booking=booking, provider=Payment.Provider.CASH,
            amount=booking.total, currency=booking.currency,
            status=Payment.Status.PROCESSING,
        )
        assert void(client, booking).status_code == 409

    def test_refuses_paid_booking(self, client, booking):
        Payment.objects.create(
            booking=booking, provider=Payment.Provider.STRIPE,
            amount=booking.total, currency=booking.currency,
            status=Payment.Status.SUCCEEDED,
        )
        assert void(client, booking).status_code == 409

    def test_failed_payment_does_not_block_void(self, client, booking):
        Payment.objects.create(
            booking=booking, provider=Payment.Provider.STRIPE,
            amount=booking.total, currency=booking.currency,
            status=Payment.Status.FAILED,
        )
        assert void(client, booking).status_code == 200

    def test_unknown_reference_404(self, client, db):
        response = client.post(reverse("api:void_pending", args=["NOPE1234"]))
        assert response.status_code == 404

    def test_other_customers_booking_hidden(self, client, booking, django_user_model):
        password = "longenough-pass-123"
        owner = django_user_model.objects.create_user(
            email="owner@example.com", password=password)
        booking.customer = owner
        booking.save(update_fields=["customer"])
        django_user_model.objects.create_user(
            email="other@example.com", password=password)
        # ScopedClient.login also authenticates the scoped /api/ cookie.
        assert client.login(username="other@example.com", password=password)
        assert void(client, booking).status_code == 404


@pytest.mark.django_db
def test_serializer_exposes_is_city_to_city(client, booking):
    """The account/booking payload carries the c2c marker for display."""
    from api.serializers import BookingSerializer
    booking.is_city_to_city = True
    booking.save(update_fields=["is_city_to_city"])
    assert BookingSerializer(booking).data["is_city_to_city"] is True
