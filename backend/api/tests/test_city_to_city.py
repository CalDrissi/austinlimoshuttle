"""
City-to-city is now a FREE-FORM origin->destination trip, priced on distance.

The request carries two addresses plus `city_to_city=true` (no fixed route id).
The server measures the trip exactly like a transfer and the engine prices each
vehicle on its intercity rate card when the vehicle offers intercity pricing and
the trip is at least the vehicle's minimum distance -- otherwise it silently
falls back to the normal transfer card. The old /api/city-routes/ options
endpoint is gone and the API no longer references CityRoute.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from fleet.models import DistanceBand, IntercityBand, Vehicle
from pricing.distance import Journey
from pricing.models import PricingSettings


@pytest.fixture
def vehicle(db):
    """A vehicle that offers intercity pricing above a 20-mile threshold.

    Normal transfer card and intercity card use deliberately different rates so a
    test can tell from the total which card priced the fare.
    """
    v = Vehicle.objects.create(
        name="Business Class", slug="bc", minimum_fare=Decimal("0.00"),
        city_to_city_min_miles=Decimal("20"), is_active=True,
    )
    for start, end, rate in [(0, 6, "15.00"), (6, 50, "2.90"), (50, None, "2.00")]:
        DistanceBand.objects.create(vehicle=v, from_miles=start, to_miles=end,
                                    rate_per_mile=Decimal(rate))
    IntercityBand.objects.create(vehicle=v, from_miles=0, to_miles=None,
                                 rate_per_mile=Decimal("10.00"))
    PricingSettings.load()
    return v


@pytest.fixture
def future():
    return (timezone.now() + timedelta(days=3)).replace(microsecond=0)


def _journey(miles):
    return Journey(
        distance_miles=Decimal(miles), duration_minutes=40,
        resolved_origin="Austin, TX", resolved_destination="Houston, TX",
    )


def _c2c_quote(client, future, miles):
    """Post a free-form city-to-city quote with a stubbed measured distance."""
    with patch("api.views.measure_journey", return_value=_journey(miles)):
        return client.post(
            reverse("api:quotes"),
            {"pickup_address": "Austin, TX", "dropoff_address": "Houston, TX",
             "pickup_at": future.isoformat(), "city_to_city": True},
            content_type="application/json",
        )


@pytest.mark.django_db
class TestFreeFormCityToCity:
    def test_above_minimum_prices_on_the_intercity_card(self, client, vehicle, future):
        """25 mi >= 20 mi minimum -> intercity rate (25 x $10 = $250.00)."""
        resp = _c2c_quote(client, future, "25")
        assert resp.status_code == 200
        body = resp.json()
        # Measured like a transfer: the journey IS returned (no longer a fixed route).
        assert body["journey"] is not None
        assert body["journey"]["distance_miles"] == "25"
        assert body["quotes"][0]["total"] == "250.00"

    def test_below_minimum_silently_falls_back_to_the_normal_card(
        self, client, vehicle, future,
    ):
        """10 mi < 20 mi minimum -> normal bands, no error.

        (6 x $15) + (4 x $2.90) = $90 + $11.60 = $101.60, not the $100 the
        intercity card would charge.
        """
        resp = _c2c_quote(client, future, "10")
        assert resp.status_code == 200
        assert resp.json()["quotes"][0]["total"] == "101.60"

    def test_booking_recomputes_on_the_intercity_card(self, client, vehicle, future):
        """The city_to_city flag rides the signed token, so redeem reprices on
        the intercity card -- the booked total matches the quoted intercity fare."""
        token = _c2c_quote(client, future, "25").json()["quotes"][0]["quote_token"]
        resp = client.post(
            reverse("api:create_booking"),
            {"quote_token": token, "guest_email": "c@example.com",
             "guest_phone": "+15125550000", "passenger_count": 2},
            content_type="application/json",
        )
        assert resp.status_code == 201
        assert resp.json()["total"] == "250.00"

    def test_city_to_city_still_rejects_hourly(self, client, vehicle, future):
        resp = client.post(
            reverse("api:quotes"),
            {"pickup_address": "Austin, TX", "dropoff_address": "Houston, TX",
             "pickup_at": future.isoformat(), "city_to_city": True, "hours": "3"},
            content_type="application/json",
        )
        assert resp.status_code == 400


@pytest.mark.django_db
def test_city_routes_options_endpoint_is_gone():
    """The fixed-route options endpoint no longer exists."""
    with pytest.raises(NoReverseMatch):
        reverse("api:city_routes")
