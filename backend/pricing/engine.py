"""
The fare engine.

A pure function: no request, no session, no database writes. That is what makes
it testable against nine years of historical bookings, which is the only way to
know a rewrite prices identically to the system it replaces.

Legacy equivalent (for reference during the replay):
  * bands        -- includes/functionClassFront.php :: calculate_price_about_distance()
  * surcharges   -- pickup_details.php:329-340
  * fee & floor  -- car_selection.php:216-260

Order of operations, which legacy establishes by statement sequence rather than
by design:

    1. base fare        cumulative distance bands, or hours x hourly rate
    2. surcharge        (blackout% + late-night%) applied ONCE to the base
    3. meet & greet     flat fee, added after the surcharge
    4. minimum fare     floor, applied last

Step 2 is the one that is easy to get wrong. Legacy sums the percentages and
applies the total once:

    $increase_amount = $busy_dates + $special_time;
    $fare = $fare + ($increase_amount / 100 * $fare);

Applying them sequentially would compound: a 40% event date at 22:00 is +60%,
not +68%.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone as dj_timezone

from bookings.models import BookingPriceLine
from fleet.models import Vehicle
from pricing.models import BlackoutDate, PricingSettings, TimeSurcharge

CENTS = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """Round to cents, half-up. PHP's number_format rounds the same way."""
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Line:
    kind: str
    label: str
    amount: Decimal


@dataclass
class Quote:
    vehicle_id: int
    vehicle_name: str
    lines: list[Line] = field(default_factory=list)
    subtotal: Decimal = Decimal("0.00")
    surcharge_total: Decimal = Decimal("0.00")
    tax: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    currency: str = "USD"
    surcharge_percentage: Decimal = Decimal("0.00")

    def as_price_lines(self, booking) -> list[BookingPriceLine]:
        return [
            BookingPriceLine(
                booking=booking, kind=line.kind, label=line.label,
                amount=line.amount, ordering=index,
            )
            for index, line in enumerate(self.lines)
        ]


class QuoteError(ValueError):
    """The vehicle cannot be priced for the requested journey."""


def surcharge_percentage_for(
    pickup_at: datetime,
    *,
    surcharges: list[TimeSurcharge] | None = None,
    blackouts: dict | None = None,
) -> tuple[Decimal, list[str]]:
    """
    Total uplift percentage for a pickup time, plus the reasons.

    Percentages are summed, matching legacy. `pickup_at` must be aware; the
    time-of-day comparison uses local time because that is what a customer and
    a dispatcher mean by "9pm".
    """
    local = dj_timezone.localtime(pickup_at) if dj_timezone.is_aware(pickup_at) else pickup_at

    total = Decimal("0.00")
    reasons: list[str] = []

    if blackouts is None:
        blackout = BlackoutDate.objects.filter(date=local.date(), is_active=True).first()
    else:
        blackout = blackouts.get(local.date())

    if blackout and blackout.percentage > 0:
        total += blackout.percentage
        reasons.append(f"{blackout.name} +{blackout.percentage:g}%")

    rules = surcharges if surcharges is not None else TimeSurcharge.objects.filter(
        is_active=True
    )
    for rule in rules:
        if rule.applies_at(local.time()):
            total += rule.percentage
            reasons.append(f"{rule.name} +{rule.percentage:g}%")

    return total, reasons


def _city_to_city_bands(
    vehicle: Vehicle,
    distance: Decimal,
    *,
    bands: list | None = None,
    intercity_bands: list | None = None,
) -> list:
    """
    The rate card a free-form city-to-city trip is priced on.

    The vehicle's INTERCITY card (`intercity_bands`) is used when the vehicle
    offers intercity pricing (`city_to_city_min_miles` is set, not NULL), it has
    an intercity card, and the trip is at least that minimum distance. A minimum
    of 0 means "no minimum" -- intercity applies at any distance, matching the
    `Vehicle.city_to_city_min_miles` field semantics.

    Every other case -- the trip is shorter than the minimum, intercity pricing
    is not offered (minimum is NULL), or the vehicle has no intercity card --
    SILENTLY falls back to the normal transfer card (`bands`). No error.
    """
    ic_bands = (
        intercity_bands if intercity_bands is not None
        else list(vehicle.intercity_bands.all())
    )
    min_miles = vehicle.city_to_city_min_miles
    if ic_bands and min_miles is not None and distance >= min_miles:
        return ic_bands
    return bands if bands is not None else list(vehicle.bands.all())


def priced_city_to_city(
    vehicle: Vehicle,
    *,
    distance_miles: Decimal | None,
    city_to_city: bool,
    intercity_bands: list | None = None,
) -> bool:
    """
    Whether a journey is ACTUALLY priced on the vehicle's intercity card.

    Booking-creation paths persist this on `Booking.is_city_to_city`, so the
    stored marker reflects the rate card the fare was charged on -- not the mode
    the customer or dispatcher picked. A city-to-city request below the vehicle's
    minimum distance (or for a vehicle that offers no intercity pricing) SILENTLY
    falls back to the normal transfer card in `quote()`; this returns False for
    exactly those cases, so a later `Booking.reprice()` reproduces the same fare
    instead of jumping to the intercity rate. The condition mirrors the rate-card
    selection in `_city_to_city_bands`.
    """
    if not city_to_city or distance_miles is None:
        return False
    ic_bands = (
        intercity_bands if intercity_bands is not None
        else list(vehicle.intercity_bands.all())
    )
    min_miles = vehicle.city_to_city_min_miles
    return bool(ic_bands) and min_miles is not None and Decimal(distance_miles) >= min_miles


def quote(
    vehicle: Vehicle,
    *,
    pickup_at: datetime,
    distance_miles: Decimal | None = None,
    hours: Decimal | None = None,
    meet_and_greet: bool = False,
    city_to_city: bool = False,
    settings: PricingSettings | None = None,
    surcharges: list[TimeSurcharge] | None = None,
    blackouts: dict | None = None,
    bands: list | None = None,
    intercity_bands: list | None = None,
) -> Quote:
    """
    Price one vehicle for one journey.

    Supply `distance_miles` for a transfer or `hours` for hourly hire. The
    optional `surcharges`/`blackouts`/`bands`/`intercity_bands` arguments let
    callers preload reference data once when pricing many journeys (the
    historical replay does this); omitted, they are read from the database.

    City-to-city is a free-form origin->destination trip, not a fixed route.
    The caller measures the trip distance the same way as a transfer (the
    Google Distance Matrix path in `distance.py`) and passes it as
    `distance_miles` with `city_to_city=True`. The vehicle is then priced on
    its INTERCITY rate card (`intercity_bands`) when it offers intercity pricing
    and the trip is long enough -- otherwise the trip silently falls back to the
    vehicle's NORMAL transfer rate card (`bands`). See `_city_to_city_bands`.
    Surcharge, meet&greet, minimum fare and tax then apply exactly as for a
    transfer; the only difference a city-to-city trip makes is which rate card
    computes the base fare.
    """
    if city_to_city and distance_miles is None:
        raise QuoteError("City-to-city pricing requires a measured trip distance.")
    if distance_miles is None and hours is None:
        raise QuoteError("Either distance_miles or hours is required.")
    if distance_miles is not None and hours is not None:
        raise QuoteError("A journey is either distance-based or hourly, not both.")

    settings = settings or PricingSettings.load()
    lines: list[Line] = []

    # 1. base fare -------------------------------------------------------
    if hours is not None:
        if hours <= 0:
            raise QuoteError("Hourly hire needs a positive number of hours.")
        if vehicle.hourly_rate <= 0:
            raise QuoteError(f"{vehicle.name} has no hourly rate.")
        base = money(Decimal(hours) * vehicle.hourly_rate)
        lines.append(Line(
            BookingPriceLine.Kind.BASE,
            f"{Decimal(hours):g} h × ${vehicle.hourly_rate:.2f}/h",
            base,
        ))
    else:
        distance = Decimal(distance_miles)
        if distance < 0:
            raise QuoteError("Distance cannot be negative.")

        if city_to_city:
            vehicle_bands = _city_to_city_bands(
                vehicle, distance, bands=bands, intercity_bands=intercity_bands,
            )
        else:
            vehicle_bands = bands if bands is not None else list(vehicle.bands.all())
        if not vehicle_bands:
            raise QuoteError(f"{vehicle.name} has no distance bands and cannot be quoted.")

        for band in sorted(vehicle_bands, key=lambda b: b.from_miles):
            miles = band.miles_within(distance)
            if miles <= 0:
                continue
            amount = money(miles * band.rate_per_mile)
            lines.append(Line(
                BookingPriceLine.Kind.BAND,
                f"{miles:g} mi in {band.label} × ${band.rate_per_mile:.2f}",
                amount,
            ))

    subtotal = money(sum((line.amount for line in lines), Decimal("0.00")))

    # 2. surcharge -- summed, then applied once --------------------------
    percentage, reasons = surcharge_percentage_for(
        pickup_at, surcharges=surcharges, blackouts=blackouts,
    )
    surcharge_total = Decimal("0.00")
    if percentage > 0 and subtotal > 0:
        surcharge_total = money(subtotal * percentage / Decimal("100"))
        lines.append(Line(
            BookingPriceLine.Kind.SURCHARGE,
            " + ".join(reasons) if reasons else f"Surcharge +{percentage:g}%",
            surcharge_total,
        ))

    running = money(subtotal + surcharge_total)

    # 3. meet and greet ---------------------------------------------------
    if meet_and_greet and vehicle.meet_greet_fee > 0:
        fee = money(vehicle.meet_greet_fee)
        lines.append(Line(BookingPriceLine.Kind.MEET_GREET, "Meet & greet", fee))
        running = money(running + fee)

    # 4. minimum fare floor, applied last ---------------------------------
    if vehicle.minimum_fare > 0 and running < vehicle.minimum_fare:
        adjustment = money(vehicle.minimum_fare - running)
        lines.append(Line(
            BookingPriceLine.Kind.MINIMUM,
            f"Minimum fare ${vehicle.minimum_fare:.2f}",
            adjustment,
        ))
        running = money(vehicle.minimum_fare)

    # 5. tax ---------------------------------------------------------------
    tax = Decimal("0.00")
    if settings.tax_rate > 0:
        tax = money(running * settings.tax_rate / Decimal("100"))
        lines.append(Line(
            BookingPriceLine.Kind.TAX, f"Tax {settings.tax_rate:g}%", tax,
        ))
        running = money(running + tax)

    return Quote(
        vehicle_id=vehicle.pk,
        vehicle_name=vehicle.name,
        lines=lines,
        subtotal=subtotal,
        surcharge_total=surcharge_total,
        surcharge_percentage=percentage,
        tax=tax,
        total=running,
        currency=settings.currency,
    )


def quote_all(
    pickup_at: datetime,
    *,
    distance_miles: Decimal | None = None,
    hours: Decimal | None = None,
    meet_and_greet: bool = False,
    city_to_city: bool = False,
) -> list[Quote]:
    """
    Price every bookable vehicle. Vehicles that cannot be priced are omitted.

    Pass `city_to_city=True` for a free-form intercity trip: each vehicle is
    priced on its intercity card when it offers intercity pricing and the trip
    is long enough, else it silently falls back to its normal transfer card
    (see `quote`).
    """
    settings = PricingSettings.load()
    surcharges = list(TimeSurcharge.objects.filter(is_active=True))
    blackouts = {b.date: b for b in BlackoutDate.objects.filter(is_active=True)}

    vehicles = Vehicle.objects.filter(is_active=True).prefetch_related("bands")
    if city_to_city:
        vehicles = vehicles.prefetch_related("intercity_bands")

    quotes = []
    for vehicle in vehicles:
        try:
            quotes.append(quote(
                vehicle,
                pickup_at=pickup_at,
                distance_miles=distance_miles,
                hours=hours,
                meet_and_greet=meet_and_greet,
                city_to_city=city_to_city,
                settings=settings,
                surcharges=surcharges,
                blackouts=blackouts,
                bands=list(vehicle.bands.all()),
                intercity_bands=(
                    list(vehicle.intercity_bands.all()) if city_to_city else None
                ),
            ))
        except QuoteError:
            continue
    return quotes
