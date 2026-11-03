"""
The staff manual-booking path persists the city-to-city marker.

The dashboard New Booking screen prices with the SAME engine as the website, so
the Booking it creates must record whether the INTERCITY card actually priced the
trip -- not merely the "City to City" radio the dispatcher picked. A city-to-city
trip below the vehicle's minimum distance is charged on the normal transfer card
and must persist is_city_to_city=False, so a later Booking.reprice() reproduces
the same fare. See CONTRACTS.md -> "city-to-city marker on Booking".
"""

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse

from bookings.models import Booking
from dashboard.permissions import DISPATCHER, sync_roles
from fleet.models import DistanceBand, IntercityBand, Vehicle
from pricing.distance import Journey
from pricing.models import PricingSettings

User = get_user_model()
AUSTIN = ZoneInfo("America/Chicago")

# Noon in summer: no night/event surcharge window, so the fare is pure mileage
# and it is unambiguous which rate card priced the trip.
NOON = datetime(2026, 6, 1, 12, 0, tzinfo=AUSTIN)


@pytest.fixture
def roles(db):
    sync_roles()


@pytest.fixture
def staff(client, roles):
    user = User.objects.create_user(
        email="dispatcher@example.com", password="DashLocal!2026", is_staff=True,
    )
    user.groups.add(Group.objects.get(name=DISPATCHER))
    client.force_login(user)
    return user


@pytest.fixture
def vehicle(db):
    """Normal $3.00/mi, intercity $1.50/mi applying from 50 mi.

    Distinct flat rates make it obvious from the total which card priced a trip.
    """
    v = Vehicle.objects.create(
        name="Intercity Class", slug="ic", hourly_rate=Decimal("85.00"),
        minimum_fare=Decimal("0.00"), city_to_city_min_miles=Decimal("50.00"),
        is_active=True,
    )
    DistanceBand.objects.create(
        vehicle=v, from_miles=0, to_miles=None, rate_per_mile=Decimal("3.00"),
    )
    IntercityBand.objects.create(
        vehicle=v, from_miles=0, to_miles=None, rate_per_mile=Decimal("1.50"),
    )
    obj = PricingSettings.load()
    obj.tax_rate = Decimal("0.00")
    obj.save()
    return v


def _journey(miles):
    return Journey(
        distance_miles=Decimal(miles), duration_minutes=40,
        resolved_origin="Austin, TX", resolved_destination="San Antonio, TX",
    )


def _post_booking(client, vehicle, *, trip_mode, miles):
    """Submit the New Booking form with a stubbed measured distance (cash)."""
    with patch("dashboard.views.measure_journey", return_value=_journey(miles)):
        return client.post(reverse("dashboard:booking_create"), {
            "trip_mode": trip_mode,
            "vehicle": vehicle.pk,
            "pickup_at": NOON.strftime("%Y-%m-%dT%H:%M"),
            "pickup_address": "Austin, TX",
            "dropoff_address": "San Antonio, TX",
            "pickup_sign": "Jane Doe",
            "guest_phone": "+15125550000",
            "passenger_count": 2,
            "luggage_count": 0,
            "status": Booking.Status.PENDING,
        })


@pytest.mark.django_db
class TestManualBookingPersistsCityToCityMarker:
    def test_true_city_to_city_persists_true(self, client, staff, vehicle):
        """60 mi >= 50 mi minimum -> intercity card -> marker True; reprice matches."""
        resp = _post_booking(client, vehicle, trip_mode="city", miles="60")
        assert resp.status_code == 302  # redirects to the new booking's detail page
        booking = Booking.objects.latest("created_at")
        assert booking.is_city_to_city is True
        assert booking.total == Decimal("90.00")  # 60 x $1.50 intercity
        assert booking.reprice().total == booking.total

    def test_normal_transfer_persists_false(self, client, staff, vehicle):
        """A plain transfer is never city-to-city; reprice stays on normal bands."""
        resp = _post_booking(client, vehicle, trip_mode="transfer", miles="60")
        assert resp.status_code == 302
        booking = Booking.objects.latest("created_at")
        assert booking.is_city_to_city is False
        assert booking.total == Decimal("180.00")  # 60 x $3.00 normal
        assert booking.reprice().total == booking.total

    def test_below_minimum_c2c_silent_fallback_persists_false(self, client, staff, vehicle):
        """40 mi < 50 mi minimum: charged on the normal card, so the marker is
        False -- reprice() must NOT jump to the intercity rate."""
        resp = _post_booking(client, vehicle, trip_mode="city", miles="40")
        assert resp.status_code == 302
        booking = Booking.objects.latest("created_at")
        assert booking.is_city_to_city is False
        assert booking.total == Decimal("120.00")  # 40 x $3.00 normal, not intercity
        assert booking.reprice().total == booking.total
