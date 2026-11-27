"""
Bookings -- the core business record.

Replaces `limousin_order` (2,217 rows) and `limousin_orderdetails` (2,488).

Deliberate differences from the legacy schema:
  * No card columns. Legacy held the PAN, expiry, cardholder name and CVV in
    plaintext across both tables. Nothing here can store them.
  * `pickup_at` is a real timezone-aware datetime. Legacy stored a formatted
    English string ("Fri, 21 Sep 2018, 2:30 PM") which cannot be sorted or
    ranged in SQL.
  * Status is a readable word, not an opaque letter (P/N/D/C/DL, one of which
    was never used).
  * Driver is a foreign key, not free text typed onto every booking.
  * The fare breakdown is persisted as price lines, so a disputed charge can be
    explained years later. Legacy stored only the final number.
"""

from __future__ import annotations

import secrets
from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models, transaction
from django.utils import timezone

from .signals import driver_trip_event_recorded

REFERENCE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1
REFERENCE_LENGTH = 8


def generate_reference() -> str:
    return "".join(secrets.choice(REFERENCE_ALPHABET) for _ in range(REFERENCE_LENGTH))


class Driver(models.Model):
    """A chauffeur available for assignment."""

    full_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=32, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, help_text="Internal only.")

    # Login for the mobile driver app. Null until an account is provisioned:
    # most of a driver's life (assignment, payout) is staff-managed and needs no
    # login. SET_NULL so deleting the account never erases the driver record the
    # booking history points at.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="driver_profile",
        help_text="Login account for the driver app. Blank = no app access yet.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return self.full_name


class BookingQuerySet(models.QuerySet):
    def upcoming(self):
        return self.filter(pickup_at__gte=timezone.now()).exclude(
            status=Booking.Status.CANCELLED
        )

    def for_dispatch(self):
        return self.select_related("vehicle", "driver", "customer")


class Booking(models.Model):
    """A single journey."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending payment"
        CONFIRMED = "confirmed", "Confirmed"
        COMPLETED = "completed", "Completed"
        NO_SHOW = "no_show", "No-show"
        CANCELLED = "cancelled", "Cancelled"

    class TripType(models.TextChoices):
        TRANSFER = "transfer", "Point-to-point transfer"
        HOURLY = "hourly", "Hourly hire"

    reference = models.CharField(
        max_length=16, unique=True, default=generate_reference, db_index=True,
        help_text="Customer-facing booking code.",
    )

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="bookings",
        help_text="Null for guest bookings. Deleting an account must not erase "
                  "booking history.",
    )
    vehicle = models.ForeignKey(
        "fleet.Vehicle", on_delete=models.PROTECT, related_name="bookings",
        help_text="PROTECT: a vehicle with bookings can be deactivated, not deleted.",
    )
    driver = models.ForeignKey(
        Driver, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="bookings",
    )

    trip_type = models.CharField(
        max_length=10, choices=TripType.choices, default=TripType.TRANSFER,
    )
    # Persisted marker: this journey was booked as a free-form city-to-city
    # (intercity) trip. A plain boolean rather than a `TripType` value because,
    # for pricing, a city-to-city trip *is* a distance-based transfer -- it
    # differs only in which rate card applies. The engine needs this at
    # amend/re-quote time (`city_to_city=True`) so an amended intercity booking
    # keeps its intercity card instead of silently dropping to the normal
    # distance bands. Defaults False: every existing booking is a normal
    # transfer or hourly hire, so the column is backwards-compatible.
    is_city_to_city = models.BooleanField(
        default=False,
        help_text="True when the trip was booked as a free-form city-to-city "
                  "(intercity) journey; keeps intercity pricing on re-quote.",
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True,
    )

    # -- itinerary --------------------------------------------------------
    pickup_address = models.CharField(max_length=255)
    pickup_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    pickup_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    dropoff_address = models.CharField(max_length=255, blank=True)
    dropoff_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    dropoff_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    pickup_at = models.DateTimeField(db_index=True)

    distance_miles = models.DecimalField(
        max_digits=8, decimal_places=3, null=True, blank=True,
        help_text="From the Distance Matrix API. Null for hourly hire.",
    )
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    hours = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Booked hours, for hourly hire.",
    )

    passenger_count = models.PositiveSmallIntegerField(default=1)
    luggage_count = models.PositiveSmallIntegerField(default=0)

    flight_number = models.CharField(max_length=32, blank=True)
    pickup_sign = models.CharField(
        max_length=120, blank=True, help_text="Name shown on the placard.",
    )
    meet_and_greet = models.BooleanField(default=False)
    notes = models.TextField(blank=True, help_text="Customer instructions.")

    guest_email = models.EmailField(
        blank=True,
        help_text="Contact address for a booking made without an account. "
                  "Without it a guest can never receive their own confirmation.",
    )
    guest_name = models.CharField(
        max_length=150, blank=True,
        help_text="Contact name for a booking made without an account. Distinct "
                  "from pickup_sign, which is what the driver's placard shows.",
    )
    guest_phone = models.CharField(max_length=32, blank=True)

    # -- money -------------------------------------------------------------
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    surcharge_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    tax = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="USD")

    vehicle_name_snapshot = models.CharField(
        max_length=120, blank=True,
        help_text="Vehicle name as sold. Deliberate denormalisation: renaming "
                  "the fleet must not rewrite history.",
    )

    # -- cancellation ------------------------------------------------------
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    cancellation_fee = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
    )

    legacy_order_id = models.IntegerField(
        null=True, blank=True, unique=True, db_index=True,
        help_text="`limousin_order.id`.",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        ordering = ["-pickup_at"]
        indexes = [
            models.Index(fields=["status", "pickup_at"]),
            models.Index(fields=["pickup_at", "status"], name="booking_dispatch_idx"),
        ]

    def __str__(self):
        return f"{self.reference} — {self.pickup_at:%d %b %Y %H:%M}"

    def save(self, *args, **kwargs):
        if not self.vehicle_name_snapshot and self.vehicle_id:
            self.vehicle_name_snapshot = self.vehicle.name
        super().save(*args, **kwargs)

    @property
    def is_cancellable(self) -> bool:
        if self.status in {self.Status.CANCELLED, self.Status.COMPLETED}:
            return False
        return self.pickup_at > timezone.now()

    @property
    def amendment_deadline(self):
        """
        Latest moment a customer may change this booking's details online.

        The window (hours before pickup) is set by the office in pricing
        settings, so "3 days before" vs "6 hours before" is a config change.
        """
        from datetime import timedelta

        from pricing.models import PricingSettings

        hours = PricingSettings.load().amendment_window_hours
        return self.pickup_at - timedelta(hours=hours)

    @property
    def is_amendable(self) -> bool:
        """Whether the customer can still edit non-price details online."""
        if self.status in {self.Status.CANCELLED, self.Status.COMPLETED}:
            return False
        return timezone.now() < self.amendment_deadline

    @property
    def pending_amendment(self):
        """
        The customer's outstanding change request awaiting staff review, if any.

        At most one is allowed open at a time (the amend-request endpoint rejects
        a second), so the newest pending row is the one the client is waiting on.
        """
        return self.amendment_requests.filter(
            status=BookingAmendmentRequest.Status.PENDING
        ).first()

    @property
    def cancellation_deadline(self):
        """
        Latest moment a customer may ask to cancel this booking online.

        Mirrors `amendment_deadline`: the window (hours before pickup) is office-
        set in pricing settings, so "free cancellation up to 1 hour before" vs
        "24 hours" is a config change, not a code change.
        """
        from datetime import timedelta

        from pricing.models import PricingSettings

        hours = PricingSettings.load().cancellation_window_hours
        return self.pickup_at - timedelta(hours=hours)

    @property
    def pending_cancellation(self):
        """
        The customer's outstanding cancellation request awaiting staff review.

        Like `pending_amendment`, at most one may be open at a time (the cancel-
        request endpoint rejects a second), so the newest pending row is the one
        the client is waiting on. The booking is NOT cancelled while this is set.
        """
        return self.cancellation_requests.filter(
            status=BookingCancellationRequest.Status.PENDING
        ).first()

    @property
    def contact_email(self) -> str:
        """Where correspondence for this booking goes."""
        if self.customer and self.customer.email:
            return self.customer.email
        return self.guest_email

    @property
    def contact_phone(self) -> str:
        """The booker's phone -- account phone for customers, guest phone otherwise."""
        if self.customer and self.customer.phone:
            return self.customer.phone
        return self.guest_phone

    @property
    def customer_name(self) -> str:
        """
        The booker's name, never the placard: `pickup_sign` is what the driver
        holds up and is often the passenger, not the customer who booked.
        """
        if self.customer:
            return self.customer.get_full_name() or self.customer.email
        return self.guest_name or "Guest"

    def reprice(self, *, pickup_at=None):
        """
        Re-run this booking through the pricing engine and return the fresh Quote.

        The single re-quote entry point for an existing booking (amend / office
        re-price). The booking's own attributes decide which rate card applies --
        crucially `is_city_to_city`, forwarded as the engine's `city_to_city`
        flag so an amended intercity trip keeps the intercity card instead of
        silently falling back to the normal distance bands. Pass `pickup_at` to
        price a proposed new time (time-based surcharges differ); it defaults to
        the stored one.

        Does NOT persist -- the caller writes the returned figures only if it
        decides to (an amend may just be previewing a new time). Mirror of the
        website amend path; see CONTRACTS.md -> "city-to-city marker on Booking".
        """
        from pricing.engine import quote

        return quote(
            self.vehicle,
            pickup_at=pickup_at or self.pickup_at,
            distance_miles=(
                self.distance_miles if self.trip_type == self.TripType.TRANSFER else None
            ),
            hours=self.hours if self.trip_type == self.TripType.HOURLY else None,
            meet_and_greet=self.meet_and_greet,
            city_to_city=self.is_city_to_city,
        )


class BookingPriceLine(models.Model):
    """
    One component of a booking's fare.

    Persisting the breakdown is what lets staff answer "why was I charged this?"
    long after the rate card has changed.
    """

    class Kind(models.TextChoices):
        BASE = "base", "Base fare"
        BAND = "band", "Distance band"
        SURCHARGE = "surcharge", "Surcharge"
        MEET_GREET = "meet_greet", "Meet and greet"
        MINIMUM = "minimum_adjustment", "Minimum fare adjustment"
        TAX = "tax", "Tax"

    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="price_lines",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    label = models.CharField(max_length=160)
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Signed: adjustments may be negative.",
    )
    ordering = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["booking", "ordering", "id"]

    def __str__(self):
        return f"{self.label}: {self.amount}"


class BookingStatusChange(models.Model):
    """
    Audit trail for status transitions.

    Impossible in the legacy system, which had a single shared admin login -- no
    action could be attributed to a person.
    """

    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="status_changes",
    )
    from_status = models.CharField(max_length=12, blank=True)
    to_status = models.CharField(max_length=12)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="booking_status_changes",
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.booking.reference}: {self.from_status or '—'} → {self.to_status}"


class DriverTripEvent(models.Model):
    """
    A single live status ping sent by the driver while running a trip.

    The storefront/driver app reports where the chauffeur is in the journey
    ("on my way", "arrived", "passenger on board", "completed"), optionally with
    a GPS fix. Each ping is an immutable row so the office can reconstruct the
    timeline and plot the route afterwards.

    This model is the *source of truth* for trip progress. Other lanes build on
    it but never write it directly -- they go through `record()`, which is the
    single creation entry point, and react via the `driver_trip_event_recorded`
    signal. See CONTRACTS.md → "DriverTripEvent".
    """

    class EventType(models.TextChoices):
        ON_WAY = "on_way", "On the way"
        ARRIVED = "arrived", "Arrived at pickup"
        ON_BOARD = "on_board", "Passenger on board"
        COMPLETED = "completed", "Trip completed"

    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="trip_events",
    )
    event_type = models.CharField(max_length=12, choices=EventType.choices)

    # GPS fix at the moment of the ping. Null when the driver's device has no
    # location permission or no signal -- the event is still recorded, it just
    # cannot be plotted. Same precision as the booking's own coordinates.
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
    )
    location_accuracy = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True,
        help_text="Reported GPS accuracy radius in metres, if the device gave one.",
    )

    # Who sent the ping. SET_NULL (and nullable) so deleting a driver account
    # never erases the trip history the booking points at -- mirrors Booking.driver.
    driver = models.ForeignKey(
        Driver, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="trip_events",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["booking", "created_at", "id"]
        indexes = [
            models.Index(fields=["booking", "created_at"]),
        ]

    def __str__(self):
        return f"{self.booking.reference}: {self.get_event_type_display()}"

    @classmethod
    def record(cls, booking, event_type, lat=None, lng=None, accuracy=None, driver=None):
        """
        The single entry point for logging a driver's trip-status ping.

        Creates (and returns) one `DriverTripEvent`, then fires the
        `driver_trip_event_recorded` signal so other lanes (e.g. notifications)
        can react without bookings importing them. This method does NOT send
        emails or any other side effect itself -- it only persists + announces.

        A `completed` event also advances the booking to COMPLETED (see below);
        every other event type leaves `Booking.status` untouched. The status
        bump is guarded so it never clobbers a terminal state and is a no-op if
        the booking is already completed, keeping repeated pings idempotent.
        """
        with transaction.atomic():
            event = cls.objects.create(
                booking=booking,
                event_type=event_type,
                latitude=lat,
                longitude=lng,
                location_accuracy=accuracy,
                driver=driver,
            )
            event._advance_booking_status()

        driver_trip_event_recorded.send(sender=cls, instance=event)
        return event

    def _advance_booking_status(self):
        """
        Minimal, backwards-compatible status progression.

        Only the terminal `completed` ping moves the booking, and only out of a
        non-terminal state (not from CANCELLED or an already-COMPLETED booking).
        The in-progress pings (on_way / arrived / on_board) have no matching
        `Booking.Status` value, so they deliberately leave status alone -- they
        are live telemetry, not lifecycle transitions.
        """
        if self.event_type != self.EventType.COMPLETED:
            return
        booking = self.booking
        terminal = {Booking.Status.CANCELLED, Booking.Status.COMPLETED}
        if booking.status in terminal:
            return
        booking.status = Booking.Status.COMPLETED
        booking.save(update_fields=["status", "updated_at"])


# The booking details a customer may ask to change. `pickup_at` is the only one
# that moves the fare (night/event surcharges are time-based); `phone` lives on
# the account, not the booking, so it is applied there. Addresses and the
# vehicle stay office-only -- changing them is effectively a new trip. This is
# the single source of truth for both the amend serializer and the amendment
# request below.
AMENDABLE_FIELDS = (
    "passenger_count", "luggage_count",
    "pickup_sign", "notes", "phone", "pickup_at", "pickup_address", "dropoff_address",
)

# Human labels for the fields above, used in the staff/customer emails so the
# OLD -> NEW diff reads in plain English rather than ORM attribute names.
AMENDMENT_FIELD_LABELS = {
    "passenger_count": "Passengers",
    "luggage_count": "Luggage",
    "pickup_sign": "Pickup sign",
    "notes": "Notes",
    "phone": "Contact phone",
    "pickup_at": "Pickup time",
    "pickup_address": "Pickup address",
    "dropoff_address": "Dropoff address",
}


class BookingAmendmentRequest(models.Model):
    """
    A customer's proposed change to an upcoming booking, awaiting staff review.

    The booking itself is NOT touched while a request is pending -- the proposed
    values live here as `requested_changes` (field -> new value) alongside the
    re-priced fare the change would produce. Staff `approve()` applies the change
    to the booking and re-prices; `decline()` records a reason. Either way the
    customer is emailed. Both transitions are guarded so an already-resolved
    request can never be approved or declined twice.

    Why a separate model rather than editing the booking in place: a change to a
    confirmed, paid journey has money and dispatch consequences, so the office
    gets to see and accept it first. The audit trail (who requested, who
    reviewed, when) is impossible if the edit just overwrites the booking.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        DECLINED = "declined", "Declined"

    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="amendment_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="booking_amendment_requests",
        help_text="The customer who asked for the change.",
    )

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True,
    )

    # The proposed new values, keyed by Booking field name (plus the virtual
    # `phone`). Only fields that actually differ from the booking are stored, so
    # this doubles as the OLD->NEW diff. `pickup_at` is held as an ISO-8601
    # string (DjangoJSONEncoder serialises datetimes that way); `apply()` parses
    # it back. Addresses/vehicle are never present -- they are office-only.
    requested_changes = models.JSONField(
        default=dict, encoder=DjangoJSONEncoder,
        help_text="Proposed {field: new_value}. Only changed fields appear.",
    )

    # The fare the change would produce, computed from the pricing engine at
    # request time and recomputed authoritatively on approval. `new_*` mirror the
    # booking's own money columns; `old_total` snapshots the fare at request time
    # so the price delta survives even if the booking is later re-priced.
    old_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    new_subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    new_surcharge_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    new_tax = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    new_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default="USD")

    requested_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_amendment_requests",
        help_text="The staff member who approved or declined the request.",
    )
    decline_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["status", "requested_at"]),
        ]

    def __str__(self):
        return f"Amendment {self.pk} for {self.booking.reference} ({self.status})"

    @property
    def is_pending(self) -> bool:
        return self.status == self.Status.PENDING

    @property
    def price_delta(self) -> Decimal:
        """How much the fare moves if approved. Positive = more expensive."""
        return self.new_total - self.old_total

    def changed_fields(self) -> list[dict]:
        """
        The OLD -> NEW diff, resolved to display values, for the emails/serializer.

        While the request is pending the booking still holds the OLD values, so
        they are read straight off it. `phone` is read from the account.
        """
        rows = []
        for field in AMENDABLE_FIELDS:
            if field not in self.requested_changes:
                continue
            new_value = self.requested_changes[field]
            if field == "phone":
                old_value = getattr(self.booking.customer, "phone", "") if self.booking.customer else ""
            elif field == "pickup_at":
                old_value = self._format_pickup(self.booking.pickup_at)
                new_value = self._format_pickup(new_value)
            else:
                old_value = getattr(self.booking, field)
            rows.append({
                "field": field,
                "label": AMENDMENT_FIELD_LABELS.get(field, field),
                "old": old_value,
                "new": new_value,
            })
        return rows

    @staticmethod
    def _format_pickup(value) -> str:
        """Render a pickup time (datetime or ISO string) for display in an email."""
        if not value:
            return ""
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        value = timezone.localtime(value) if timezone.is_aware(value) else value
        return value.strftime("%a %d %b %Y, %H:%M")

    @transaction.atomic
    def approve(self, reviewed_by):
        """
        Apply the requested change to the booking, re-price, and mark approved.

        Idempotent by guard: a request that is not pending is returned untouched,
        so a double-click or a retried request never re-applies the change. The
        booking is mutated only here, never while the request sits pending.
        """
        if not self.is_pending:
            return self

        booking = self.booking
        changes = dict(self.requested_changes)
        applied = []
        recomputed = None
        prior_total = booking.total
        payment_note = ""

        # `phone` lives on the account, not the booking.
        if "phone" in changes and booking.customer_id:
            booking.customer.phone = (changes.pop("phone") or "").strip()
            booking.customer.save(update_fields=["phone"])
            applied.append("phone")

        new_pickup = changes.pop("pickup_at", None)
        for field in ("passenger_count", "luggage_count",
                      "pickup_sign", "notes"):
            if field in changes:
                setattr(booking, field, changes[field])
                applied.append(field)

        address_changed = any(field in changes for field in ("pickup_address", "dropoff_address"))
        if address_changed:
            from pricing.distance import lookup
            journey = lookup(changes.get("pickup_address", booking.pickup_address),
                             changes.get("dropoff_address", booking.dropoff_address))
            for field in ("pickup_address", "dropoff_address"):
                if field in changes:
                    setattr(booking, field, changes[field])
                    applied.append(field)
            if booking.trip_type == Booking.TripType.TRANSFER:
                booking.distance_miles = journey.distance_miles

        if new_pickup is not None:
            pickup_at = (
                datetime.fromisoformat(new_pickup)
                if isinstance(new_pickup, str) else new_pickup
            )
            booking.pickup_at = pickup_at
            applied.append("pickup_at")
        if new_pickup is not None or address_changed:
            # Re-price through the booking's own entry point so an amended
            # intercity trip keeps its intercity card (see Booking.reprice).
            recomputed = booking.reprice(pickup_at=booking.pickup_at)
            booking.subtotal = recomputed.subtotal
            booking.surcharge_total = recomputed.surcharge_total
            booking.tax = recomputed.tax
            booking.total = recomputed.total

        booking.save()
        if recomputed is not None:
            booking.price_lines.all().delete()
            for line in recomputed.as_price_lines(booking):
                line.save()
            # Record the authoritative fare we actually charged.
            self.new_subtotal = booking.subtotal
            self.new_surcharge_total = booking.surcharge_total
            self.new_tax = booking.tax
            self.new_total = booking.total

            # The money owed changed, so what we expect to collect must follow.
            # A cash fare is a pending (awaiting-collection) payment row -- left
            # at the old amount, the driver collects the wrong fare. A card fare
            # was already charged, so the delta cannot be applied silently: it
            # is recorded in the audit note for the office to settle.
            if booking.total != prior_total:
                from payments.models import Payment

                cash_pending = booking.payments.filter(
                    provider=Payment.Provider.CASH,
                ).exclude(status__in=[
                    Payment.Status.SUCCEEDED, Payment.Status.FAILED,
                    Payment.Status.CANCELLED,
                ]).first()
                if cash_pending is not None:
                    cash_pending.amount = booking.total
                    cash_pending.currency = booking.currency
                    cash_pending.save(update_fields=["amount", "currency", "updated_at"])
                    payment_note = (
                        f"; awaiting-collection cash payment updated to "
                        f"${booking.total:.2f}"
                    )

                paid = sum(
                    (p.amount for p in booking.payments.filter(
                        status=Payment.Status.SUCCEEDED)),
                    Decimal("0.00"),
                )
                if paid and paid != booking.total:
                    delta = booking.total - paid
                    payment_note += (
                        f"; fare changed ${prior_total:.2f} -> ${booking.total:.2f}, "
                        f"${paid:.2f} already paid — "
                        + (f"${delta:.2f} outstanding to charge"
                           if delta > 0 else f"${-delta:.2f} to refund")
                    )

        BookingStatusChange.objects.create(
            booking=booking, from_status=booking.status, to_status=booking.status,
            changed_by=reviewed_by,
            note="Amendment approved by staff"
                 + (": " + ", ".join(applied) if applied else "")
                 + payment_note,
        )

        self.status = self.Status.APPROVED
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.save(update_fields=[
            "status", "reviewed_by", "reviewed_at",
            "new_subtotal", "new_surcharge_total", "new_tax", "new_total",
        ])
        return self

    def decline(self, reviewed_by, reason=""):
        """
        Mark the request declined with an optional reason. Leaves the booking
        untouched. Idempotent by guard, like `approve()`.
        """
        if not self.is_pending:
            return self
        self.status = self.Status.DECLINED
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.decline_reason = reason or ""
        self.save(update_fields=[
            "status", "reviewed_by", "reviewed_at", "decline_reason",
        ])
        return self


class BookingCancellationRequest(models.Model):
    """
    A customer's request to cancel an upcoming booking, awaiting staff review.

    Mirrors `BookingAmendmentRequest`: the booking is NOT cancelled while the
    request is pending -- it only becomes cancelled when staff `approve()` it.
    Crucially, approval is **required** and the refund is **not** automatic: the
    amount is set by staff at approval time (defaulting to what was paid, but a
    partial amount or zero is allowed). `approve()` cancels the booking and
    records the staff-set `refund_amount`; the actual Stripe refund is issued by
    the caller through the existing refund path, then this is called to flip the
    state. `decline()` records a reason and leaves the booking untouched. Both
    transitions are guarded so a resolved request can never be processed twice.

    Why a separate model rather than cancelling in place: cancelling a confirmed,
    paid journey has money consequences (a refund), so the office decides whether
    to accept it and how much to return. The audit trail (who asked, who reviewed,
    how much was refunded, when) is impossible if the cancel just flips a flag.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        DECLINED = "declined", "Declined"

    booking = models.ForeignKey(
        Booking, on_delete=models.CASCADE, related_name="cancellation_requests",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="booking_cancellation_requests",
        help_text="The customer who asked to cancel.",
    )

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True,
    )

    # What the customer had paid when they asked to cancel. Snapshotted at request
    # time so it survives later refunds, and used as the default/maximum refund
    # staff may set on approval.
    paid_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00"),
        help_text="Amount paid at request time; the default and ceiling for the refund.",
    )
    # The refund staff chose to issue on approval. Null while pending (a 0 refund
    # is a deliberate choice, distinct from "not decided yet"). Validated into
    # 0..paid_amount by the approving view.
    refund_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Refund set by staff at approval. 0 is allowed; null until reviewed.",
    )
    currency = models.CharField(max_length=3, default="USD")

    requested_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reviewed_cancellation_requests",
        help_text="The staff member who approved or declined the request.",
    )
    decline_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["status", "requested_at"]),
        ]

    def __str__(self):
        return f"Cancellation {self.pk} for {self.booking.reference} ({self.status})"

    @property
    def is_pending(self) -> bool:
        return self.status == self.Status.PENDING

    @transaction.atomic
    def approve(self, reviewed_by, refund_amount, refunded_payment=None):
        """
        Cancel the booking and mark the request approved with the staff-set refund.

        Records the `refund_amount` staff chose (the caller is responsible for
        having issued the actual refund through `gateway.refund` first, so a
        gateway failure never leaves a cancelled-but-unrefunded booking).
        `refunded_payment` is the Payment the caller refunded against -- it
        decides the history wording (cash is handed back, card went through
        Stripe) without this method re-guessing which payment that was.
        Idempotent by guard: a request that is not pending is returned
        untouched, so a double submit never re-cancels or double-counts a refund.
        """
        if not self.is_pending:
            return self

        booking = self.booking
        from_status = booking.status
        booking.status = Booking.Status.CANCELLED
        booking.cancelled_at = timezone.now()
        if not booking.cancellation_reason:
            booking.cancellation_reason = "Cancellation requested by customer"
        booking.save(update_fields=["status", "cancelled_at", "cancellation_reason"])

        # The history line names how the money goes back: a cash fare was never
        # at Stripe, so the refund is returned by hand.
        from payments.models import Payment

        if refunded_payment is None and refund_amount:
            refunded_payment = booking.payments.filter(
                status=Payment.Status.SUCCEEDED,
            ).first()
        if not refund_amount:
            refund_note = "; no refund"
        elif (refunded_payment is not None
              and refunded_payment.provider != Payment.Provider.STRIPE):
            refund_note = (f"; cash refund ${refund_amount} to be returned "
                           "to customer")
        else:
            refund_note = f"; refunded {refund_amount} {self.currency}"

        BookingStatusChange.objects.create(
            booking=booking, from_status=from_status,
            to_status=Booking.Status.CANCELLED, changed_by=reviewed_by,
            note=("Cancellation approved by staff" if reviewed_by else "Cancellation approved automatically") + refund_note,
        )

        self.status = self.Status.APPROVED
        self.refund_amount = refund_amount
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.save(update_fields=[
            "status", "refund_amount", "reviewed_by", "reviewed_at",
        ])
        return self

    def decline(self, reviewed_by, reason=""):
        """
        Mark the request declined with an optional reason. Leaves the booking
        untouched (still confirmed). Idempotent by guard, like `approve()`.
        """
        if not self.is_pending:
            return self
        self.status = self.Status.DECLINED
        self.reviewed_by = reviewed_by
        self.reviewed_at = timezone.now()
        self.decline_reason = reason or ""
        self.save(update_fields=[
            "status", "reviewed_by", "reviewed_at", "decline_reason",
        ])
        return self
