"""
Guest bookings are claimed by the matching account on sign-in.

The confirmation page tells a guest "create an account to track this ride";
these tests pin that promise: registering or logging in with the address the
guest booking was made under attaches it to the account (customer=user), so it
shows up in /account and becomes amendable/cancellable. Someone else's email,
or an already-claimed booking, is never touched.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from bookings.models import Booking
from fleet.models import Vehicle

User = get_user_model()

PASSWORD = "S3cure-enough-pass!"


@pytest.fixture
def vehicle(db):
    return Vehicle.objects.create(
        name="Business Class", slug="bc", hourly_rate=Decimal("85.00"),
        minimum_fare=Decimal("95.00"), is_active=True,
    )


def _guest_booking(vehicle, email="guest@example.com"):
    return Booking.objects.create(
        vehicle=vehicle, guest_email=email, guest_name="Pat Guest",
        pickup_address="ABIA", dropoff_address="Downtown",
        pickup_at=timezone.now() + timedelta(days=5),
        total=Decimal("145.10"), status=Booking.Status.CONFIRMED,
    )


@pytest.mark.django_db
def test_register_claims_guest_bookings(vehicle):
    booking = _guest_booking(vehicle)
    client = APIClient()
    r = client.post("/api/auth/register/", {
        "email": "Guest@Example.com",  # case-insensitive match
        "password": PASSWORD, "first_name": "Pat",
    }, format="json")
    assert r.status_code == 201

    booking.refresh_from_db()
    user = User.objects.get(email="guest@example.com")
    assert booking.customer == user
    # ...and it now shows in the account's booking list.
    mine = client.get("/api/account/bookings/")
    assert [b["reference"] for b in mine.json()] == [booking.reference]


@pytest.mark.django_db
def test_login_claims_guest_bookings(vehicle):
    user = User.objects.create_user(email="guest@example.com", password=PASSWORD)
    booking = _guest_booking(vehicle)  # booked as a guest after registering
    client = APIClient()
    r = client.post("/api/auth/login/", {
        "email": "guest@example.com", "password": PASSWORD,
    }, format="json")
    assert r.status_code == 200

    booking.refresh_from_db()
    assert booking.customer == user


@pytest.mark.django_db
def test_other_accounts_never_claim(vehicle):
    booking = _guest_booking(vehicle, email="guest@example.com")
    User.objects.create_user(email="other@example.com", password=PASSWORD)
    client = APIClient()
    client.post("/api/auth/login/", {
        "email": "other@example.com", "password": PASSWORD,
    }, format="json")

    booking.refresh_from_db()
    assert booking.customer is None


@pytest.mark.django_db
def test_already_claimed_bookings_stay_put(vehicle):
    owner = User.objects.create_user(email="owner@example.com", password=PASSWORD)
    booking = _guest_booking(vehicle, email="guest@example.com")
    booking.customer = owner
    booking.save(update_fields=["customer"])
    User.objects.create_user(email="guest@example.com", password=PASSWORD)
    client = APIClient()
    client.post("/api/auth/login/", {
        "email": "guest@example.com", "password": PASSWORD,
    }, format="json")

    booking.refresh_from_db()
    assert booking.customer == owner
