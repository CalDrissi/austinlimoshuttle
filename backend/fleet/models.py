"""
Fleet and rate cards.

Replaces `limousin_car_list`, where the four mileage tiers were fixed columns
(`product_price_mile`, `product_price_mile_above`, `product_price_fifty_hundred`,
`product_price_above_hundred`) and their boundaries lived in PHP constants
(ADJUST_DISTANCE = 6, ADJUST_DISTANCE_SIX_TO_FIFTY = 50,
ADJUST_DISTANCE_FIFTY_TO_HUNDRED = 100). Changing a pricing tier therefore meant
editing code and redeploying.

Here the tiers are DistanceBand rows, so staff can reshape them from the admin.

A vehicle carries TWO independent band rate cards with identical cumulative
semantics (see RateBand):
  * `bands`           -- the normal per-mile rate card (DistanceBand).
  * `intercity_bands` -- the city-to-city rate card (IntercityBand), used for
                         free-form origin->destination trips at or above the
                         vehicle's `city_to_city_min_miles` threshold.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class Vehicle(models.Model):
    """A bookable vehicle class -- not an individual car."""

    name = models.CharField(max_length=120, help_text='e.g. "Business Class".')
    slug = models.SlugField(max_length=140, unique=True)

    description = models.TextField(blank=True)
    features = models.TextField(
        blank=True,
        help_text='Marketing copy, e.g. "Free cancellation up until 1 hour before pickup".',
    )
    photo = models.ImageField(upload_to="fleet/", blank=True, null=True)

    passenger_capacity = models.PositiveSmallIntegerField(default=0)
    luggage_capacity = models.PositiveSmallIntegerField(default=0)

    hourly_rate = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Rate per hour for hourly hire.",
    )
    meet_greet_fee = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Airport meet-and-greet supplement.",
    )
    minimum_fare = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Fare floor. Applied after every other adjustment.",
    )

    city_to_city_min_miles = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text=(
            "Trip distance (miles) at or above which the city-to-city "
            "`intercity_bands` rate card is used instead of the normal `bands`. "
            "NULL = intercity pricing not offered for this vehicle (always use "
            "`bands`). 0 = no minimum (intercity applies at any distance). "
            "Only takes effect when the vehicle has intercity_bands."
        ),
    )

    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(
        default=True,
        help_text="Deactivate rather than delete: bookings reference this row.",
    )

    legacy_car_id = models.IntegerField(
        null=True, blank=True, unique=True, db_index=True,
        help_text="`limousin_car_list.id`, for idempotent imports.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name

    def rate_for_mile(self, mile_offset: Decimal) -> Decimal:
        """Rate applying at a given distance into the journey."""
        for band in self.bands.all():
            if band.contains(mile_offset):
                return band.rate_per_mile
        return Decimal("0.00")


class RateBand(models.Model):
    """
    One tier of a vehicle's per-mile rate card.

    Bands are cumulative: a 70-mile trip is charged the 0-6 band for its first
    6 miles, the 6-50 band for the next 44, and the 50-100 band for the last 20.

    Abstract so the normal card (DistanceBand) and the city-to-city card
    (IntercityBand) share identical band arithmetic and validation. The
    `vehicle` FK and Meta (ordering + unique-start constraint) live on the
    concrete subclasses so each card keeps its own `related_name` and
    constraint name.
    """

    from_miles = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Lower bound, inclusive.",
    )
    to_miles = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Upper bound, exclusive. Leave empty for the final, unbounded band.",
    )
    rate_per_mile = models.DecimalField(
        max_digits=8, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )

    class Meta:
        abstract = True

    def __str__(self):
        upper = f"{self.to_miles:g}" if self.to_miles is not None else "∞"
        return f"{self.vehicle.name}: {self.from_miles:g}–{upper} mi @ {self.rate_per_mile}"

    @property
    def label(self) -> str:
        upper = f"{self.to_miles:g}" if self.to_miles is not None else "and above"
        if self.to_miles is None:
            return f"{self.from_miles:g} mi {upper}"
        return f"{self.from_miles:g}–{upper} mi"

    def contains(self, miles: Decimal) -> bool:
        if miles < self.from_miles:
            return False
        return self.to_miles is None or miles < self.to_miles

    def miles_within(self, total_distance: Decimal) -> Decimal:
        """How many of `total_distance` miles fall inside this band."""
        if total_distance <= self.from_miles:
            return Decimal("0.00")
        upper = total_distance if self.to_miles is None else min(total_distance, self.to_miles)
        return max(Decimal("0.00"), upper - self.from_miles)

    def clean(self):
        if self.to_miles is not None and self.to_miles <= self.from_miles:
            raise ValidationError(
                {"to_miles": "Upper bound must be greater than the lower bound."}
            )


class DistanceBand(RateBand):
    """One tier of a vehicle's NORMAL per-mile rate card. See RateBand."""

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name="bands")

    class Meta:
        ordering = ["vehicle", "from_miles"]
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle", "from_miles"], name="unique_band_start_per_vehicle",
            ),
        ]


class IntercityBand(RateBand):
    """
    One tier of a vehicle's CITY-TO-CITY per-mile rate card. See RateBand.

    Identical cumulative-band semantics and validation as DistanceBand, but a
    separate card: used for free-form origin->destination intercity trips when
    the trip distance meets the vehicle's `city_to_city_min_miles` threshold.
    Fetch a vehicle's intercity card with `vehicle.intercity_bands.all()`.
    """

    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name="intercity_bands",
    )

    class Meta:
        ordering = ["vehicle", "from_miles"]
        constraints = [
            models.UniqueConstraint(
                fields=["vehicle", "from_miles"],
                name="unique_intercity_band_start_per_vehicle",
            ),
        ]
