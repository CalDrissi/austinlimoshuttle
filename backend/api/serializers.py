"""API serializers."""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from bookings.models import Booking
from content.models import Page, SiteSettings
from payments.models import SavedCard
from enquiries.models import ContactMessage
from fleet.models import Vehicle

MAX_PASSENGERS = 20
MAX_HOURS = Decimal("24")
MAX_DISTANCE_MILES = Decimal("1000")


class PageSerializer(serializers.ModelSerializer):
    url = serializers.CharField(source="url_path", read_only=True)

    class Meta:
        model = Page
        fields = [
            "slug", "url", "title", "page_type", "body",
            "meta_title", "meta_description", "meta_keywords",
        ]


class SiteSettingsSerializer(serializers.ModelSerializer):
    """
    Site-wide contact details and social links, for the header and footer.

    `ops_notification_email` is deliberately absent. It is where new-booking
    alerts land, it sits on the same model as the public address purely because
    legacy kept both on the admin user row, and publishing it would hand every
    scraper the one mailbox the business cannot afford to have flooded.
    """

    class Meta:
        model = SiteSettings
        fields = [
            "contact_email", "contact_phone",
            "facebook", "instagram", "twitter", "linkedin",
            "google_maps_api_key",
        ]
        read_only_fields = fields


class VehicleSerializer(serializers.ModelSerializer):
    photo = serializers.SerializerMethodField()

    class Meta:
        model = Vehicle
        fields = [
            "id", "name", "slug", "description", "features",
            "passenger_capacity", "luggage_capacity", "minimum_fare", "photo",
        ]

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_photo(self, obj):
        """Absolute URL of the uploaded photo, or null to fall back to a placeholder.

        The host comes from the incoming request (build_absolute_uri). The
        storefront fetches /api/vehicles/ from the BROWSER (all vehicle fetches
        are in "use client" components), so that host is the public site and the
        URL is correct. If a vehicle list were ever fetched server-side from
        Next (e.g. SSR against an internal container host), this would need a
        configured absolute MEDIA base instead.
        """
        if not obj.photo:
            return None
        url = obj.photo.url
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request else url


class QuoteRequestSerializer(serializers.Serializer):
    """
    A request for fares.

    Deliberately accepts NO distance and NO price. A transfer is described by
    its two addresses and the server measures it (pricing/distance.py); an
    hourly hire is described by its duration. A client-supplied distance is a
    client-supplied fare with extra steps.
    """

    pickup_address = serializers.CharField(max_length=255)
    dropoff_address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    pickup_at = serializers.DateTimeField()
    hours = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True,
        min_value=Decimal("0.5"), max_value=MAX_HOURS,
        help_text="Hourly hire only. Omit for a point-to-point transfer.",
    )
    meet_and_greet = serializers.BooleanField(default=False)
    # City-to-city is a free-form origin->destination trip, exactly like a
    # transfer: the server measures the distance from the two addresses. The flag
    # only selects the vehicle's intercity rate card (the engine falls back to the
    # normal transfer card when intercity pricing is not offered or the trip is
    # shorter than the vehicle's minimum). It is NOT a fixed route lookup.
    city_to_city = serializers.BooleanField(default=False)

    def validate_pickup_at(self, value):
        if value < timezone.now():
            raise serializers.ValidationError("Pickup time must be in the future.")
        from pricing.models import booking_lead_error
        lead = booking_lead_error(value)
        if lead:
            raise serializers.ValidationError(lead)
        return value

    def validate(self, attrs):
        hours = attrs.get("hours")
        dropoff = (attrs.get("dropoff_address") or "").strip()

        if attrs.get("city_to_city"):
            if hours is not None:
                raise serializers.ValidationError(
                    "City-to-city is a point-to-point trip, not hourly hire."
                )
            if not dropoff:
                raise serializers.ValidationError(
                    "Provide both a pickup and a drop-off address."
                )
            attrs["dropoff_address"] = dropoff
            return attrs

        if hours is None and not dropoff:
            raise serializers.ValidationError(
                "Provide a destination address for a transfer, or hours for hourly hire."
            )
        if hours is not None and dropoff:
            raise serializers.ValidationError(
                "A journey is either a transfer (two addresses) or hourly hire "
                "(a duration), not both."
            )
        attrs["dropoff_address"] = dropoff
        return attrs


class PriceLineSerializer(serializers.Serializer):
    kind = serializers.CharField()
    label = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)


class BookingCreateSerializer(serializers.Serializer):
    """
    Create a booking from a signed quote token.

    Deliberately has no `total`, `subtotal` or any other money field: the server
    recomputes the fare from the token. A client-supplied amount is not merely
    ignored here, it is impossible to express.
    """

    quote_token = serializers.CharField()
    passenger_count = serializers.IntegerField(min_value=1, max_value=MAX_PASSENGERS, default=1)
    luggage_count = serializers.IntegerField(min_value=0, max_value=MAX_PASSENGERS, default=0)
    flight_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    pickup_sign = serializers.CharField(max_length=120, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    # Guest checkout
    guest_email = serializers.EmailField(required=False, allow_blank=True)
    guest_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    guest_phone = serializers.CharField(max_length=32, required=False, allow_blank=True)


class BookingSerializer(serializers.ModelSerializer):
    vehicle_name = serializers.CharField(source="vehicle_name_snapshot", read_only=True)
    price_lines = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_amendable = serializers.BooleanField(read_only=True)
    amendment_deadline = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Booking
        fields = [
            "reference", "status", "status_display", "trip_type",
            "pickup_address", "dropoff_address", "pickup_at",
            "distance_miles", "duration_minutes", "hours",
            "passenger_count", "luggage_count", "flight_number", "pickup_sign",
            "meet_and_greet", "notes", "vehicle_name",
            "subtotal", "surcharge_total", "tax", "total", "currency",
            "price_lines", "created_at", "is_amendable", "amendment_deadline",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_price_lines(self, obj):
        """The itemised fare. Amounts are strings -- money is never a float."""
        return [
            {"kind": line.kind, "label": line.label, "amount": f"{line.amount:.2f}"}
            for line in obj.price_lines.all()
        ]


class BookingAmendSerializer(serializers.Serializer):
    """
    Customer-editable booking details within the office-set amendment window.

    All optional (a partial update). Most fields don't touch the fare; changing
    `pickup_at` does (night/event surcharges are time-based), so the server
    re-prices on a date change. The pickup/drop-off addresses and vehicle stay
    office-only — changing them is effectively a new trip. `phone` updates the
    account's contact number.
    """

    passenger_count = serializers.IntegerField(min_value=1, max_value=MAX_PASSENGERS, required=False)
    luggage_count = serializers.IntegerField(min_value=0, max_value=MAX_PASSENGERS, required=False)
    flight_number = serializers.CharField(max_length=32, required=False, allow_blank=True)
    pickup_sign = serializers.CharField(max_length=120, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True)
    pickup_at = serializers.DateTimeField(required=False)

    def validate_pickup_at(self, value):
        if value < timezone.now():
            raise serializers.ValidationError("Pickup time must be in the future.")
        from pricing.models import booking_lead_error
        lead = booking_lead_error(value)
        if lead:
            raise serializers.ValidationError(lead)
        return value


class EnquirySerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactMessage
        fields = ["name", "email", "phone", "nature", "subject", "message", "company_name"]

    def validate_message(self, value):
        if len(value.strip()) < 10:  # noqa: PLR2004
            raise serializers.ValidationError("Please provide a little more detail.")
        return value


# ---------------------------------------------------------------------------
# Response shapes
#
# These exist so the OpenAPI schema describes what the frontend actually
# receives. They are documentation-bearing types, not input validation: nothing
# here is ever used to parse a request.
# ---------------------------------------------------------------------------


class DetailSerializer(serializers.Serializer):
    """A human-readable message. Used for errors and simple acknowledgements."""

    detail = serializers.CharField()


class BookingStatusSerializer(serializers.ModelSerializer):
    """
    The minimum a confirmation page needs.

    Deliberately narrow. This is the one booking endpoint reachable without a
    session, so it carries no addresses, no passenger names and no notes --
    only what someone holding the reference already knows.
    """

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    vehicle_name = serializers.CharField(source="vehicle_name_snapshot", read_only=True)

    class Meta:
        model = Booking
        fields = [
            "reference", "status", "status_display", "pickup_at",
            "vehicle_name", "total", "currency",
        ]
        read_only_fields = fields


class JourneySerializer(serializers.Serializer):
    """The route as measured server-side. Null for hourly hire."""

    distance_miles = serializers.CharField(help_text="Decimal string, e.g. \"25.000\".")
    duration_minutes = serializers.IntegerField()
    pickup_address = serializers.CharField(help_text="As resolved by the mapping service.")
    dropoff_address = serializers.CharField()


class QuoteLineSerializer(serializers.Serializer):
    """One component of a fare."""

    kind = serializers.ChoiceField(
        choices=["base", "band", "surcharge", "meet_greet", "minimum_adjustment", "tax"],
    )
    label = serializers.CharField(help_text='e.g. "19 mi in 6–50 mi × $2.90".')
    amount = serializers.CharField(help_text="Decimal string. Money is never a float.")


class QuoteResultSerializer(serializers.Serializer):
    """A priced option for one vehicle."""

    vehicle_id = serializers.IntegerField()
    vehicle_name = serializers.CharField()
    subtotal = serializers.CharField()
    surcharge_total = serializers.CharField()
    tax = serializers.CharField()
    total = serializers.CharField()
    currency = serializers.CharField()
    lines = QuoteLineSerializer(many=True)
    quote_token = serializers.CharField(
        help_text="Signed and short-lived. Present this to create a booking; "
                  "the server recomputes the fare from it.",
    )


class QuoteResponseSerializer(serializers.Serializer):
    journey = JourneySerializer(allow_null=True)
    quotes = QuoteResultSerializer(many=True)


class BlackoutDateSerializer(serializers.Serializer):
    date = serializers.DateField()
    name = serializers.CharField()
    percentage = serializers.CharField()


class TimeSurchargeSerializer(serializers.Serializer):
    name = serializers.CharField()
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    percentage = serializers.CharField()
    crosses_midnight = serializers.BooleanField()


class AvailabilitySerializer(serializers.Serializer):
    """Everything a date picker needs to warn about surcharged times."""

    blackout_dates = BlackoutDateSerializer(many=True)
    time_surcharges = TimeSurchargeSerializer(many=True)


class PaymentConfigSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    publishable_key = serializers.CharField(
        allow_blank=True, help_text="Safe to embed in the page. Empty when disabled.",
    )
    mode = serializers.CharField(allow_null=True, help_text='"test" or "live".')


class PaymentIntentRequestSerializer(serializers.Serializer):
    reference = serializers.CharField(help_text="Booking reference.")


class PaymentIntentResponseSerializer(serializers.Serializer):
    client_secret = serializers.CharField(help_text="Pass to Stripe Elements.")
    publishable_key = serializers.CharField()
    amount = serializers.CharField()
    currency = serializers.CharField()
    reference = serializers.CharField()


class LoginRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class UserSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    phone = serializers.CharField(allow_blank=True, required=False)


class RegisterRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class CancelBookingSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["cancel"])


class SavedCardSerializer(serializers.ModelSerializer):
    """A customer's card on file. Display bits only -- never anything to charge with."""

    label = serializers.CharField(read_only=True)
    expiry = serializers.CharField(read_only=True)

    class Meta:
        model = SavedCard
        fields = ["id", "brand", "last4", "exp_month", "exp_year",
                  "is_default", "label", "expiry"]
        read_only_fields = fields
