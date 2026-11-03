"""
Distance band arithmetic.

Bands are cumulative, which is the part that goes wrong silently: charging the
whole journey at the band the total distance lands in, rather than charging each
band only for the miles inside it, inflates long trips dramatically.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from fleet.models import DistanceBand, IntercityBand, Vehicle


@pytest.fixture
def vehicle(db):
    v = Vehicle.objects.create(
        name="Business Class", slug="business-class",
        hourly_rate=Decimal("85.00"), minimum_fare=Decimal("95.00"),
    )
    # The real Business Class rate card.
    DistanceBand.objects.create(vehicle=v, from_miles=0, to_miles=6, rate_per_mile=Decimal("15.00"))
    DistanceBand.objects.create(vehicle=v, from_miles=6, to_miles=50, rate_per_mile=Decimal("2.90"))
    DistanceBand.objects.create(vehicle=v, from_miles=50, to_miles=100, rate_per_mile=Decimal("2.20"))
    DistanceBand.objects.create(vehicle=v, from_miles=100, to_miles=None, rate_per_mile=Decimal("1.50"))
    return v


@pytest.mark.django_db
class TestMilesWithin:
    def test_distance_inside_first_band(self, vehicle):
        first = vehicle.bands.first()
        assert first.miles_within(Decimal("4")) == Decimal("4")

    def test_distance_beyond_band_is_capped_at_band_width(self, vehicle):
        first = vehicle.bands.first()
        assert first.miles_within(Decimal("30")) == Decimal("6")

    def test_distance_below_band_start_contributes_nothing(self, vehicle):
        second = vehicle.bands.all()[1]
        assert second.miles_within(Decimal("4")) == Decimal("0")

    def test_partial_fill_of_middle_band(self, vehicle):
        second = vehicle.bands.all()[1]  # 6-50
        assert second.miles_within(Decimal("30")) == Decimal("24")

    def test_unbounded_band_takes_everything_above_its_start(self, vehicle):
        last = vehicle.bands.last()  # 100+
        assert last.miles_within(Decimal("250")) == Decimal("150")

    def test_exact_boundary_belongs_to_the_lower_band(self, vehicle):
        first, second = vehicle.bands.all()[0], vehicle.bands.all()[1]
        assert first.miles_within(Decimal("6")) == Decimal("6")
        assert second.miles_within(Decimal("6")) == Decimal("0")

    def test_bands_sum_to_the_total_distance(self, vehicle):
        """No miles may be lost or double-counted across the rate card."""
        for total in [Decimal("0.5"), Decimal("6"), Decimal("49.9"),
                      Decimal("100"), Decimal("137.4"), Decimal("500")]:
            covered = sum(b.miles_within(total) for b in vehicle.bands.all())
            assert covered == total, f"{total} miles -> {covered} covered"


@pytest.mark.django_db
class TestBandContains:
    def test_contains_is_lower_inclusive_upper_exclusive(self, vehicle):
        first = vehicle.bands.first()
        assert first.contains(Decimal("0"))
        assert first.contains(Decimal("5.99"))
        assert not first.contains(Decimal("6"))

    def test_unbounded_band_contains_any_large_value(self, vehicle):
        assert vehicle.bands.last().contains(Decimal("99999"))


@pytest.mark.django_db
class TestBandValidation:
    def test_upper_bound_must_exceed_lower(self, vehicle):
        band = DistanceBand(vehicle=vehicle, from_miles=50, to_miles=20, rate_per_mile=1)
        with pytest.raises(ValidationError):
            band.clean()

    def test_band_start_is_unique_per_vehicle(self, vehicle):
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            DistanceBand.objects.create(
                vehicle=vehicle, from_miles=0, to_miles=3, rate_per_mile=1,
            )


@pytest.mark.django_db
class TestVehicle:
    def test_rate_for_mile_picks_the_right_band(self, vehicle):
        assert vehicle.rate_for_mile(Decimal("3")) == Decimal("15.00")
        assert vehicle.rate_for_mile(Decimal("20")) == Decimal("2.90")
        assert vehicle.rate_for_mile(Decimal("75")) == Decimal("2.20")
        assert vehicle.rate_for_mile(Decimal("500")) == Decimal("1.50")

    def test_vehicle_without_bands_returns_zero_rate(self, db):
        bare = Vehicle.objects.create(name="Bare", slug="bare")
        assert bare.rate_for_mile(Decimal("10")) == Decimal("0.00")


# --- City-to-city intercity rate card -------------------------------------
#
# IntercityBand mirrors DistanceBand: same cumulative-band arithmetic and
# validation, but a separate card (related_name="intercity_bands") used for
# free-form origin->destination trips. These tests pin that the two cards stay
# interchangeable and that the per-vehicle min-distance field behaves as the
# published contract says.


@pytest.fixture
def intercity_vehicle(db):
    v = Vehicle.objects.create(
        name="Sedan", slug="sedan",
        hourly_rate=Decimal("75.00"), minimum_fare=Decimal("85.00"),
        city_to_city_min_miles=Decimal("50.00"),
    )
    # A plausible long-haul intercity card: flatter per-mile than the normal one.
    IntercityBand.objects.create(vehicle=v, from_miles=0, to_miles=50, rate_per_mile=Decimal("3.00"))
    IntercityBand.objects.create(vehicle=v, from_miles=50, to_miles=150, rate_per_mile=Decimal("2.00"))
    IntercityBand.objects.create(vehicle=v, from_miles=150, to_miles=None, rate_per_mile=Decimal("1.25"))
    return v


@pytest.mark.django_db
class TestIntercityBandIsSeparateCard:
    def test_related_name_is_intercity_bands(self, intercity_vehicle):
        assert intercity_vehicle.intercity_bands.count() == 3

    def test_intercity_bands_are_independent_of_normal_bands(self, intercity_vehicle):
        # Adding a normal band must not leak into the intercity card and vice versa.
        DistanceBand.objects.create(
            vehicle=intercity_vehicle, from_miles=0, to_miles=10, rate_per_mile=Decimal("9.00"),
        )
        assert intercity_vehicle.bands.count() == 1
        assert intercity_vehicle.intercity_bands.count() == 3


@pytest.mark.django_db
class TestIntercityMilesWithin:
    """Same cumulative semantics as DistanceBand."""

    def test_distance_beyond_band_is_capped_at_band_width(self, intercity_vehicle):
        first = intercity_vehicle.intercity_bands.first()  # 0-50
        assert first.miles_within(Decimal("80")) == Decimal("50")

    def test_partial_fill_of_middle_band(self, intercity_vehicle):
        second = intercity_vehicle.intercity_bands.all()[1]  # 50-150
        assert second.miles_within(Decimal("100")) == Decimal("50")

    def test_unbounded_band_takes_everything_above_its_start(self, intercity_vehicle):
        last = intercity_vehicle.intercity_bands.last()  # 150+
        assert last.miles_within(Decimal("400")) == Decimal("250")

    def test_bands_sum_to_the_total_distance(self, intercity_vehicle):
        for total in [Decimal("0.5"), Decimal("50"), Decimal("149.9"),
                      Decimal("150"), Decimal("275.4"), Decimal("900")]:
            covered = sum(b.miles_within(total) for b in intercity_vehicle.intercity_bands.all())
            assert covered == total, f"{total} miles -> {covered} covered"


@pytest.mark.django_db
class TestIntercityBandContains:
    def test_contains_is_lower_inclusive_upper_exclusive(self, intercity_vehicle):
        first = intercity_vehicle.intercity_bands.first()  # 0-50
        assert first.contains(Decimal("0"))
        assert first.contains(Decimal("49.99"))
        assert not first.contains(Decimal("50"))

    def test_unbounded_band_contains_any_large_value(self, intercity_vehicle):
        assert intercity_vehicle.intercity_bands.last().contains(Decimal("99999"))


@pytest.mark.django_db
class TestIntercityBandValidation:
    def test_upper_bound_must_exceed_lower(self, intercity_vehicle):
        band = IntercityBand(
            vehicle=intercity_vehicle, from_miles=150, to_miles=80, rate_per_mile=1,
        )
        with pytest.raises(ValidationError):
            band.clean()

    def test_band_start_is_unique_per_vehicle(self, intercity_vehicle):
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            IntercityBand.objects.create(
                vehicle=intercity_vehicle, from_miles=0, to_miles=5, rate_per_mile=1,
            )

    def test_same_start_is_allowed_across_the_two_cards(self, intercity_vehicle):
        # from_miles=0 already exists on the intercity card; the same start on the
        # NORMAL card must be fine -- the two uniqueness constraints are separate.
        DistanceBand.objects.create(
            vehicle=intercity_vehicle, from_miles=0, to_miles=6, rate_per_mile=Decimal("10.00"),
        )
        assert intercity_vehicle.bands.filter(from_miles=0).exists()
        assert intercity_vehicle.intercity_bands.filter(from_miles=0).exists()


@pytest.mark.django_db
class TestCityToCityMinMiles:
    def test_defaults_to_null_meaning_not_offered(self, db):
        v = Vehicle.objects.create(name="No C2C", slug="no-c2c")
        assert v.city_to_city_min_miles is None

    def test_stores_a_threshold(self, intercity_vehicle):
        intercity_vehicle.refresh_from_db()
        assert intercity_vehicle.city_to_city_min_miles == Decimal("50.00")

    def test_zero_is_a_valid_no_minimum_sentinel(self, db):
        v = Vehicle.objects.create(
            name="Always C2C", slug="always-c2c", city_to_city_min_miles=Decimal("0.00"),
        )
        v.refresh_from_db()
        assert v.city_to_city_min_miles == Decimal("0.00")
