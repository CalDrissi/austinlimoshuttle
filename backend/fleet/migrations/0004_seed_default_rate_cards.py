"""Seed default per-mile rate cards for the four band-less fleet vehicles.

At launch only the Cadillac Escalade carried distance bands, so the pricing
engine could quote only that one vehicle and the storefront hid the other four
(a vehicle with no bands raises QuoteError -- see pricing/engine.py). This
migration gives each of the remaining four a sensible DEFAULT rate card so all
five show and price. Staff tune the numbers from the back office afterwards.

Method (data-driven, not hardcoded):
  * TRANSFER (DistanceBand) -- READ the Escalade's existing bands and mirror
    their mile breakpoints exactly as the template. Each vehicle's per-mile
    rates are the template rates scaled to its tier: the scale factor is the
    average of its hourly_rate and minimum_fare relative to the Escalade's, so
    the E-Class (cheapest) lands below the Escalade and the Sprinter / Chrysler
    (priciest) land above it.
  * CITY-TO-CITY (IntercityBand) -- a matching per-mile card at the same scaled
    rates, but with its FINAL band left UNBOUNDED. Intercity trips are by
    definition at or above city_to_city_min_miles (seeded to 50), i.e. longer
    than the Escalade template's 40-mile top breakpoint; an unbounded final
    band means those long runs are actually charged across their whole
    distance instead of capping at 40 miles.

Idempotent: a vehicle that already has a transfer card is left untouched, and
likewise for its intercity card, so a re-run (or an operator who has already
set rates) is a no-op. The Escalade is never touched -- it is not a target.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations

CENTS = Decimal("0.01")

TEMPLATE_SLUG = "cadillac-escalade"

# Fallback template, matching the Escalade's launch bands, used only if the
# Escalade somehow carries no bands at migrate time (keeps the migration
# deterministic across environments). (from_miles, to_miles, rate_per_mile)
FALLBACK_TEMPLATE = [
    (Decimal("0.00"), Decimal("20.00"), Decimal("50.00")),
    (Decimal("20.00"), Decimal("40.00"), Decimal("45.00")),
]
FALLBACK_REF = {"hourly_rate": Decimal("95.00"), "minimum_fare": Decimal("150.00")}

# The four vehicles that launched without rate cards.
TARGET_SLUGS = [
    "chevrolet-suburban",
    "mercedes-e-class",
    "mercedes-sprinter",
    "chrysler-300-limo",
]

DEFAULT_CITY_TO_CITY_MIN_MILES = Decimal("50.00")


def _money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(CENTS, rounding=ROUND_HALF_UP)


def _scale_factor(vehicle, ref_hourly: Decimal, ref_min_fare: Decimal) -> Decimal:
    """Tier signal: average of hourly_rate and minimum_fare vs the reference."""
    ratios = []
    if ref_hourly and ref_hourly > 0:
        ratios.append(Decimal(vehicle.hourly_rate) / ref_hourly)
    if ref_min_fare and ref_min_fare > 0:
        ratios.append(Decimal(vehicle.minimum_fare) / ref_min_fare)
    if not ratios:
        return Decimal("1")
    return sum(ratios) / Decimal(len(ratios))


def seed_rate_cards(apps, schema_editor):
    Vehicle = apps.get_model("fleet", "Vehicle")
    DistanceBand = apps.get_model("fleet", "DistanceBand")
    IntercityBand = apps.get_model("fleet", "IntercityBand")

    # Read the Escalade's bands as the breakpoint template.
    template = list(FALLBACK_TEMPLATE)
    ref_hourly = FALLBACK_REF["hourly_rate"]
    ref_min_fare = FALLBACK_REF["minimum_fare"]
    escalade = Vehicle.objects.filter(slug=TEMPLATE_SLUG).first()
    if escalade is not None:
        esc_bands = list(escalade.bands.order_by("from_miles"))
        if esc_bands:
            template = [(b.from_miles, b.to_miles, b.rate_per_mile) for b in esc_bands]
        ref_hourly = Decimal(escalade.hourly_rate)
        ref_min_fare = Decimal(escalade.minimum_fare)

    for vehicle in Vehicle.objects.filter(slug__in=TARGET_SLUGS):
        scale = _scale_factor(vehicle, ref_hourly, ref_min_fare)

        # TRANSFER card -- mirror the template breakpoints exactly. Skip if the
        # vehicle already has any transfer bands.
        if not vehicle.bands.exists():
            for from_miles, to_miles, rate in template:
                DistanceBand.objects.create(
                    vehicle=vehicle,
                    from_miles=from_miles,
                    to_miles=to_miles,
                    rate_per_mile=_money(rate * scale),
                )

        # CITY-TO-CITY card -- same scaled rates, final band left unbounded so
        # long intercity runs price across their whole distance. Skip if the
        # vehicle already has an intercity card.
        if not vehicle.intercity_bands.exists():
            last = len(template) - 1
            for index, (from_miles, to_miles, rate) in enumerate(template):
                IntercityBand.objects.create(
                    vehicle=vehicle,
                    from_miles=from_miles,
                    to_miles=None if index == last else to_miles,
                    rate_per_mile=_money(rate * scale),
                )
            if vehicle.city_to_city_min_miles is None:
                vehicle.city_to_city_min_miles = DEFAULT_CITY_TO_CITY_MIN_MILES
                vehicle.save(update_fields=["city_to_city_min_miles"])


def unseed_rate_cards(apps, schema_editor):
    Vehicle = apps.get_model("fleet", "Vehicle")
    DistanceBand = apps.get_model("fleet", "DistanceBand")
    IntercityBand = apps.get_model("fleet", "IntercityBand")

    targets = Vehicle.objects.filter(slug__in=TARGET_SLUGS)
    DistanceBand.objects.filter(vehicle__in=targets).delete()
    IntercityBand.objects.filter(vehicle__in=targets).delete()
    targets.update(city_to_city_min_miles=None)


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0003_seed_fleet_vehicles"),
    ]

    operations = [
        migrations.RunPython(seed_rate_cards, unseed_rate_cards),
    ]
