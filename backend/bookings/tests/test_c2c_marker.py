"""
City-to-city marker on Booking.

A booking made as a free-form city-to-city (intercity) trip persists an
`is_city_to_city` flag. The flag is what keeps intercity pricing on an
amend/re-quote: `Booking.reprice()` forwards it to the pricing engine as
`city_to_city=True`, so an amended intercity trip stays on the vehicle's
intercity rate card instead of silently dropping to the normal distance bands.

See CONTRACTS.md -> "city-to-city marker on Booking".
"""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from bookings.models import Booking
from fleet.models import DistanceBand, IntercityBand, Vehicle
from pricing.models import PricingSettings

AUSTIN = ZoneInfo("America/Chicago")

# Noon in summer: no night/event surcharge window, so the fare is pure mileage
# and it is unambiguous which rate card priced the trip.
NOON = datetime(2026, 6, 1, 12, 0, tzinfo=AUSTIN)


@pytest.fixture
def settings_obj(db):
    obj = PricingSettings.load()
    obj.tax_rate = Decimal("0.00")
    obj.save()
    return obj


@pytest.fixture
def intercity_vehicle(db):
    """A vehicle with BOTH cards: normal $3.00/mi, intercity $1.50/mi >= 50 mi.

    Distinct flat rates make it obvious from the total which card priced a trip.
    """
    v = Vehicle.objects.create(
        name="Intercity Class", slug="ic",
        hourly_rate=Decimal("85.00"),
        minimum_fare=Decimal("0.00"),
        city_to_city_min_miles=Decimal("50.00"),
    )
    DistanceBand.objects.create(
        vehicle=v, from_miles=0, to_miles=None, rate_per_mile=Decimal("3.00"),
    )
    IntercityBand.objects.create(
        vehicle=v, from_miles=0, to_miles=None, rate_per_mile=Decimal("1.50"),
    )
    return v


def _c2c_booking(vehicle, *, is_city_to_city):
    return Booking.objects.create(
        vehicle=vehicle,
        trip_type=Booking.TripType.TRANSFER,
        is_city_to_city=is_city_to_city,
        pickup_address="Austin, TX",
        dropoff_address="San Antonio, TX",
        pickup_at=NOON,
        distance_miles=Decimal("60.000"),
    )


@pytest.mark.django_db
class TestMarkerPersistence:
    def test_defaults_false(self, intercity_vehicle):
        """Existing/normal bookings are not city-to-city -- backwards-compatible."""
        b = _c2c_booking(intercity_vehicle, is_city_to_city=False)
        assert Booking.objects.get(pk=b.pk).is_city_to_city is False

    def test_persists_true(self, intercity_vehicle):
        b = _c2c_booking(intercity_vehicle, is_city_to_city=True)
        assert Booking.objects.get(pk=b.pk).is_city_to_city is True


@pytest.mark.django_db
class TestRepriceKeepsIntercityCard:
    def test_amend_reprices_on_intercity_card(self, intercity_vehicle, settings_obj):
        """A c2c booking re-prices with city_to_city=True -> intercity card."""
        b = _c2c_booking(intercity_vehicle, is_city_to_city=True)
        q = b.reprice()
        # 60 mi x $1.50 intercity, NOT x $3.00 normal.
        assert q.total == Decimal("90.00")

    def test_non_c2c_booking_reprices_on_normal_card(
        self, intercity_vehicle, settings_obj
    ):
        """Without the marker the same trip falls on the normal distance bands."""
        b = _c2c_booking(intercity_vehicle, is_city_to_city=False)
        q = b.reprice()
        # 60 mi x $3.00 normal.
        assert q.total == Decimal("180.00")

    def test_reprice_forwards_marker_to_engine(self, intercity_vehicle):
        """reprice() passes the persisted marker through as the engine's flag."""
        from unittest.mock import patch

        b = _c2c_booking(intercity_vehicle, is_city_to_city=True)
        with patch("pricing.engine.quote") as spy:
            b.reprice()
        assert spy.call_args.kwargs["city_to_city"] is True

    def test_reprice_accepts_a_proposed_new_time(self, intercity_vehicle, settings_obj):
        """A new pickup time can be priced without mutating the booking."""
        b = _c2c_booking(intercity_vehicle, is_city_to_city=True)
        later = NOON.replace(hour=14)
        q = b.reprice(pickup_at=later)
        assert q.total == Decimal("90.00")
        assert b.pickup_at == NOON  # unchanged -- reprice does not persist
