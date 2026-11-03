"""
Fare engine.

Every number here is checked by hand against the legacy behaviour it replaces.
The band arithmetic, the additive surcharge and the ordering of the
meet-and-greet fee against the minimum-fare floor are the three places a rewrite
silently reprices a business.
"""

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from bookings.models import BookingPriceLine
from fleet.models import DistanceBand, IntercityBand, Vehicle
from pricing.engine import QuoteError, quote, quote_all, surcharge_percentage_for
from pricing.models import BlackoutDate, PricingSettings, TimeSurcharge

AUSTIN = ZoneInfo("America/Chicago")


def austin(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=AUSTIN)


@pytest.fixture
def settings_obj(db):
    obj = PricingSettings.load()
    obj.tax_rate = Decimal("0.00")  # legacy charged no tax
    obj.save()
    return obj


@pytest.fixture
def business_class(db):
    """The real Business Class rate card."""
    v = Vehicle.objects.create(
        name="Business Class", slug="bc",
        hourly_rate=Decimal("85.00"),
        minimum_fare=Decimal("95.00"),
        meet_greet_fee=Decimal("0.00"),
    )
    for start, end, rate in [
        (0, 6, "15.00"), (6, 50, "2.90"), (50, 100, "2.20"), (100, None, "1.50"),
    ]:
        DistanceBand.objects.create(
            vehicle=v, from_miles=start, to_miles=end, rate_per_mile=Decimal(rate),
        )
    return v


@pytest.fixture
def late_night(db):
    return TimeSurcharge.objects.create(
        name="Late night", start_time=time(21, 0), end_time=time(6, 0),
        percentage=Decimal("20.00"),
    )


@pytest.mark.django_db
class TestDistanceBands:
    def test_short_trip_uses_only_the_first_band(self, business_class, settings_obj):
        # 4 mi x $15 = $60, below the $95 minimum -> floored
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 12),
                       distance_miles=Decimal("4"))
        assert result.subtotal == Decimal("60.00")
        assert result.total == Decimal("95.00")

    def test_bands_are_cumulative_not_flat(self, business_class, settings_obj):
        """
        25 miles = (6 x 15.00) + (19 x 2.90) = 90.00 + 55.10 = 145.10

        Charging all 25 miles at the band the total lands in would give
        25 x 2.90 = 72.50 -- roughly half. This is the mistake worth guarding.
        """
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 12),
                       distance_miles=Decimal("25"))
        assert result.subtotal == Decimal("145.10")
        assert result.total == Decimal("145.10")

    def test_crossing_three_bands(self, business_class, settings_obj):
        # 70 mi = (6 x 15) + (44 x 2.90) + (20 x 2.20) = 90 + 127.60 + 44 = 261.60
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 12),
                       distance_miles=Decimal("70"))
        assert result.subtotal == Decimal("261.60")

    def test_crossing_all_four_bands(self, business_class, settings_obj):
        # 150 mi = 90 + 127.60 + 110 + (50 x 1.50 = 75) = 402.60
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 12),
                       distance_miles=Decimal("150"))
        assert result.subtotal == Decimal("402.60")

    def test_exact_band_boundary(self, business_class, settings_obj):
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 12),
                       distance_miles=Decimal("6"))
        assert result.subtotal == Decimal("90.00")

    def test_each_band_produces_a_line(self, business_class, settings_obj):
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 12),
                       distance_miles=Decimal("70"))
        kinds = [line.kind for line in result.lines]
        assert kinds.count(BookingPriceLine.Kind.BAND) == 3


@pytest.mark.django_db
class TestSurcharges:
    def test_late_night_uplift(self, business_class, settings_obj, late_night):
        # 25 mi = 145.10, +20% = 174.12
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 23),
                       distance_miles=Decimal("25"))
        assert result.subtotal == Decimal("145.10")
        assert result.surcharge_total == Decimal("29.02")
        assert result.total == Decimal("174.12")

    def test_no_uplift_during_the_day(self, business_class, settings_obj, late_night):
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 14),
                       distance_miles=Decimal("25"))
        assert result.surcharge_total == Decimal("0.00")
        assert result.total == Decimal("145.10")

    def test_blackout_and_late_night_are_added_not_compounded(
        self, business_class, settings_obj, late_night,
    ):
        """
        Legacy sums the percentages and applies the total once:
            increase = blackout% + late_night%
            fare = fare + (increase / 100 * fare)

        40 + 20 = 60%, so 145.10 -> 232.16.
        Compounding (1.40 x 1.20 = 1.68) would give 243.77 -- a 5% overcharge.
        """
        BlackoutDate.objects.create(
            name="SXSW", date=date(2026, 3, 13), percentage=Decimal("40.00"),
        )
        result = quote(business_class, pickup_at=austin(2026, 3, 13, 22),
                       distance_miles=Decimal("25"))

        assert result.surcharge_percentage == Decimal("60.00")
        assert result.total == Decimal("232.16")
        assert result.total != Decimal("243.77")  # the compounding mistake

    def test_blackout_alone(self, business_class, settings_obj, late_night):
        BlackoutDate.objects.create(
            name="F1", date=date(2026, 10, 18), percentage=Decimal("80.00"),
        )
        result = quote(business_class, pickup_at=austin(2026, 10, 18, 12),
                       distance_miles=Decimal("25"))
        assert result.surcharge_percentage == Decimal("80.00")
        assert result.total == Decimal("261.18")

    def test_inactive_blackout_is_ignored(self, business_class, settings_obj):
        BlackoutDate.objects.create(
            name="Old", date=date(2026, 5, 5), percentage=Decimal("50.00"),
            is_active=False,
        )
        percentage, _ = surcharge_percentage_for(austin(2026, 5, 5, 12))
        assert percentage == Decimal("0.00")

    def test_surcharge_uses_local_time_not_utc(self, business_class, settings_obj, late_night):
        """
        22:00 in Austin is 03:00 UTC the next day. Comparing in UTC would apply
        the wrong rule and shift every booking near the boundary.
        """
        local_late = austin(2026, 6, 1, 22)
        assert local_late.astimezone(ZoneInfo("UTC")).hour == 3
        percentage, _ = surcharge_percentage_for(local_late)
        assert percentage == Decimal("20.00")

        local_afternoon = austin(2026, 6, 1, 15)
        percentage, _ = surcharge_percentage_for(local_afternoon)
        assert percentage == Decimal("0.00")


@pytest.mark.django_db
class TestHourlyHire:
    def test_hourly_rate_applies(self, business_class, settings_obj):
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 12),
                       hours=Decimal("3"))
        assert result.subtotal == Decimal("255.00")  # 3 x 85

    def test_hourly_respects_the_minimum_fare(self, business_class, settings_obj):
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 12),
                       hours=Decimal("1"))
        assert result.total == Decimal("95.00")  # 85 floored to 95

    def test_hourly_gets_surcharges_too(self, business_class, settings_obj, late_night):
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 23),
                       hours=Decimal("3"))
        assert result.total == Decimal("306.00")  # 255 x 1.20

    def test_vehicle_without_an_hourly_rate_cannot_be_quoted(self, settings_obj, db):
        v = Vehicle.objects.create(name="No rate", slug="nr", hourly_rate=0)
        with pytest.raises(QuoteError, match="no hourly rate"):
            quote(v, pickup_at=austin(2026, 6, 1, 12), hours=Decimal("2"))


@pytest.mark.django_db
class TestOrderOfOperations:
    def test_meet_and_greet_is_added_after_the_surcharge(self, settings_obj, late_night, db):
        """
        The fee is flat: surcharging it would inflate a fixed cost.
        60.00 base -> +20% = 72.00 -> +25.00 fee = 97.00.
        Surcharging the fee first would give (60+25) x 1.2 = 102.00.
        """
        v = Vehicle.objects.create(
            name="MG", slug="mg", meet_greet_fee=Decimal("25.00"), minimum_fare=0,
        )
        DistanceBand.objects.create(vehicle=v, from_miles=0, to_miles=None,
                                    rate_per_mile=Decimal("15.00"))
        result = quote(v, pickup_at=austin(2026, 6, 1, 23),
                       distance_miles=Decimal("4"), meet_and_greet=True)
        assert result.total == Decimal("97.00")

    def test_minimum_fare_is_applied_last(self, settings_obj, db):
        """The floor is a floor on the final amount, not on the base fare."""
        v = Vehicle.objects.create(
            name="Floor", slug="floor", minimum_fare=Decimal("100.00"),
            meet_greet_fee=Decimal("10.00"),
        )
        DistanceBand.objects.create(vehicle=v, from_miles=0, to_miles=None,
                                    rate_per_mile=Decimal("5.00"))
        # 4 mi x 5 = 20, + 10 fee = 30 -> floored to 100
        result = quote(v, pickup_at=austin(2026, 6, 1, 12),
                       distance_miles=Decimal("4"), meet_and_greet=True)
        assert result.total == Decimal("100.00")
        assert any(line.kind == BookingPriceLine.Kind.MINIMUM for line in result.lines)

    def test_no_minimum_adjustment_when_fare_exceeds_it(self, business_class, settings_obj):
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 12),
                       distance_miles=Decimal("25"))
        assert not any(
            line.kind == BookingPriceLine.Kind.MINIMUM for line in result.lines
        )


@pytest.mark.django_db
class TestTax:
    def test_tax_applies_last(self, business_class, settings_obj):
        settings_obj.tax_rate = Decimal("10.00")
        settings_obj.save()
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 12),
                       distance_miles=Decimal("25"), settings=settings_obj)
        assert result.tax == Decimal("14.51")
        assert result.total == Decimal("159.61")


@pytest.mark.django_db
class TestInputValidation:
    def test_requires_distance_or_hours(self, business_class, settings_obj):
        with pytest.raises(QuoteError, match="Either distance_miles or hours"):
            quote(business_class, pickup_at=austin(2026, 6, 1, 12))

    def test_rejects_both(self, business_class, settings_obj):
        with pytest.raises(QuoteError, match="not both"):
            quote(business_class, pickup_at=austin(2026, 6, 1, 12),
                  distance_miles=Decimal("10"), hours=Decimal("2"))

    def test_rejects_negative_distance(self, business_class, settings_obj):
        with pytest.raises(QuoteError, match="negative"):
            quote(business_class, pickup_at=austin(2026, 6, 1, 12),
                  distance_miles=Decimal("-5"))

    def test_rejects_zero_hours(self, business_class, settings_obj):
        with pytest.raises(QuoteError, match="positive"):
            quote(business_class, pickup_at=austin(2026, 6, 1, 12), hours=Decimal("0"))

    def test_vehicle_without_bands_cannot_be_quoted(self, settings_obj, db):
        v = Vehicle.objects.create(name="Bare", slug="bare")
        with pytest.raises(QuoteError, match="no distance bands"):
            quote(v, pickup_at=austin(2026, 6, 1, 12), distance_miles=Decimal("10"))


@pytest.mark.django_db
class TestQuoteAll:
    def test_skips_vehicles_that_cannot_be_priced(self, business_class, settings_obj):
        Vehicle.objects.create(name="Unpriceable", slug="up")  # no bands
        results = quote_all(austin(2026, 6, 1, 12), distance_miles=Decimal("25"))
        names = {q.vehicle_name for q in results}
        assert "Business Class" in names
        assert "Unpriceable" not in names

    def test_ignores_inactive_vehicles(self, business_class, settings_obj):
        business_class.is_active = False
        business_class.save()
        assert quote_all(austin(2026, 6, 1, 12), distance_miles=Decimal("25")) == []


@pytest.mark.django_db
class TestPurity:
    def test_quoting_writes_nothing(self, business_class, settings_obj):
        from bookings.models import Booking

        before = (Booking.objects.count(), BookingPriceLine.objects.count())
        quote(business_class, pickup_at=austin(2026, 6, 1, 12),
              distance_miles=Decimal("25"))
        assert (Booking.objects.count(), BookingPriceLine.objects.count()) == before

    def test_same_inputs_give_the_same_answer(self, business_class, settings_obj):
        at = austin(2026, 6, 1, 12)
        a = quote(business_class, pickup_at=at, distance_miles=Decimal("37.4"))
        b = quote(business_class, pickup_at=at, distance_miles=Decimal("37.4"))
        assert a.total == b.total
        assert [x.amount for x in a.lines] == [x.amount for x in b.lines]

    def test_does_not_depend_on_the_current_clock(self, business_class, settings_obj):
        """A fare is a function of the pickup time, never of 'now'."""
        from freezegun import freeze_time

        at = austin(2026, 6, 1, 23)
        with freeze_time("2026-01-01 09:00:00"):
            first = quote(business_class, pickup_at=at, distance_miles=Decimal("25"))
        with freeze_time("2026-12-25 03:00:00"):
            second = quote(business_class, pickup_at=at, distance_miles=Decimal("25"))
        assert first.total == second.total


@pytest.mark.django_db
class TestPriceLinePersistence:
    def test_lines_convert_to_model_instances(self, business_class, settings_obj):
        from bookings.models import Booking

        booking = Booking.objects.create(
            vehicle=business_class, pickup_address="a",
            pickup_at=timezone.now(),
        )
        result = quote(business_class, pickup_at=austin(2026, 6, 1, 23),
                       distance_miles=Decimal("70"))
        lines = result.as_price_lines(booking)
        for line in lines:
            line.save()

        assert booking.price_lines.count() == len(result.lines)
        assert sum(line.amount for line in booking.price_lines.all()) == result.total


@pytest.fixture
def intercity_class(db):
    """A vehicle with BOTH a normal transfer card and a cheaper intercity card.

    Normal: $3.00/mi flat. Intercity: $1.50/mi flat (long-haul discount), used
    for city-to-city trips >= 50 mi. Distinct flat rates make it unambiguous
    which card priced a given trip.
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


@pytest.mark.django_db
class TestCityToCity:
    """Free-form, distance-based city-to-city with a per-vehicle minimum."""

    NOON = austin(2026, 6, 1, 12)  # no surcharge window

    def test_intercity_card_used_when_distance_at_or_above_minimum(
        self, intercity_class, settings_obj
    ):
        q = quote(intercity_class, pickup_at=self.NOON,
                  distance_miles=Decimal("60"), city_to_city=True)
        assert q.total == Decimal("90.00")  # 60 mi × $1.50 intercity, not × $3.00

    def test_minimum_boundary_is_inclusive(self, intercity_class, settings_obj):
        q = quote(intercity_class, pickup_at=self.NOON,
                  distance_miles=Decimal("50"), city_to_city=True)
        assert q.total == Decimal("75.00")  # exactly at min -> intercity (50 × 1.50)

    def test_silent_fallback_to_normal_when_distance_below_minimum(
        self, intercity_class, settings_obj
    ):
        q = quote(intercity_class, pickup_at=self.NOON,
                  distance_miles=Decimal("40"), city_to_city=True)
        assert q.total == Decimal("120.00")  # 40 mi × $3.00 normal, no error

    def test_fallback_when_minimum_is_null(self, intercity_class, settings_obj):
        intercity_class.city_to_city_min_miles = None  # intercity not offered
        intercity_class.save()
        q = quote(intercity_class, pickup_at=self.NOON,
                  distance_miles=Decimal("60"), city_to_city=True)
        assert q.total == Decimal("180.00")  # 60 mi × $3.00 normal despite the IC card

    def test_fallback_when_no_intercity_bands(self, settings_obj, db):
        v = Vehicle.objects.create(
            name="No IC card", slug="noic", minimum_fare=Decimal("0.00"),
            city_to_city_min_miles=Decimal("50.00"),
        )
        DistanceBand.objects.create(
            vehicle=v, from_miles=0, to_miles=None, rate_per_mile=Decimal("3.00"),
        )
        q = quote(v, pickup_at=self.NOON,
                  distance_miles=Decimal("60"), city_to_city=True)
        assert q.total == Decimal("180.00")  # normal card; no intercity card exists

    def test_zero_minimum_applies_intercity_at_any_distance(
        self, intercity_class, settings_obj
    ):
        intercity_class.city_to_city_min_miles = Decimal("0.00")  # no minimum
        intercity_class.save()
        q = quote(intercity_class, pickup_at=self.NOON,
                  distance_miles=Decimal("10"), city_to_city=True)
        assert q.total == Decimal("15.00")  # 10 mi × $1.50 intercity

    def test_city_to_city_requires_a_distance(self, intercity_class, settings_obj):
        with pytest.raises(QuoteError):
            quote(intercity_class, pickup_at=self.NOON, hours=Decimal("3"),
                  city_to_city=True)

    def test_intercity_card_is_cumulative_across_bands(self, settings_obj, db):
        """Intercity bands use the same cumulative math as normal DistanceBands."""
        v = Vehicle.objects.create(
            name="Tiered IC", slug="tic", minimum_fare=Decimal("0.00"),
            city_to_city_min_miles=Decimal("0.00"),
        )
        DistanceBand.objects.create(
            vehicle=v, from_miles=0, to_miles=None, rate_per_mile=Decimal("9.99"),
        )
        for start, end, rate in [(0, 50, "2.00"), (50, None, "1.00")]:
            IntercityBand.objects.create(
                vehicle=v, from_miles=start, to_miles=end, rate_per_mile=Decimal(rate),
            )
        q = quote(v, pickup_at=self.NOON,
                  distance_miles=Decimal("70"), city_to_city=True)
        assert q.total == Decimal("120.00")  # 50×2.00 + 20×1.00, not 70×9.99

    def test_surcharge_still_applies_to_an_intercity_fare(
        self, intercity_class, settings_obj, late_night
    ):
        """City-to-city changes the base card only; the transfer pipeline is intact."""
        q = quote(intercity_class, pickup_at=austin(2026, 6, 1, 23),
                  distance_miles=Decimal("60"), city_to_city=True)
        # 60 × 1.50 = 90.00 base, +20% late-night = 108.00
        assert q.subtotal == Decimal("90.00")
        assert q.total == Decimal("108.00")

    def test_normal_transfer_ignores_the_intercity_card(
        self, intercity_class, settings_obj
    ):
        """A plain transfer (city_to_city=False) never touches intercity bands."""
        q = quote(intercity_class, pickup_at=self.NOON, distance_miles=Decimal("60"))
        assert q.total == Decimal("180.00")  # 60 × $3.00 normal

    def test_quote_all_prices_city_to_city(self, intercity_class, settings_obj):
        results = quote_all(self.NOON, distance_miles=Decimal("60"), city_to_city=True)
        by_name = {q.vehicle_name: q for q in results}
        assert by_name["Intercity Class"].total == Decimal("90.00")
