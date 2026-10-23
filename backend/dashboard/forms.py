"""Dashboard forms."""

from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password

from bookings.models import Booking, Driver
from content.models import Banner, GalleryImage, Page, SiteSettings, Testimonial
from fleet.models import DistanceBand, Vehicle
from notifications.models import EmailSettings, SmsSettings
from payments.models import PaymentSettings, PayPalSettings
from pricing.models import BlackoutDate, CityRoute, CityRoutePrice, PricingSettings, TimeSurcharge

User = get_user_model()


class BootstrapFormMixin:
    """
    Apply Bootstrap's form classes to every widget.

    Done here rather than in the templates so a new field is styled the moment
    it is added, and so the markup stays declarative -- a template that has to
    remember `class="form-control"` on each field will eventually forget one.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            existing = widget.attrs.get("class", "")
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, forms.Select):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs["class"] = f"{existing} {css}".strip()


TRIP_MODE_CHOICES = [
    ("transfer", "Transfer"),
    ("hourly", "By the hour"),
    ("city", "City to City"),
]


def _apply_capacity_errors(form, cleaned):
    """Reject passenger/luggage counts above the vehicle's limits (0 = no limit)."""
    vehicle = cleaned.get("vehicle")
    if not vehicle:
        return
    pax = cleaned.get("passenger_count")
    lug = cleaned.get("luggage_count")
    if vehicle.passenger_capacity and pax is not None and pax > vehicle.passenger_capacity:
        form.add_error("passenger_count", f"{vehicle.name} seats up to {vehicle.passenger_capacity}.")
    if vehicle.luggage_capacity and lug is not None and lug > vehicle.luggage_capacity:
        form.add_error("luggage_count", f"{vehicle.name} holds up to {vehicle.luggage_capacity} bags.")


class ManualBookingForm(BootstrapFormMixin, forms.ModelForm):
    """
    Staff-entered booking for phone and walk-in customers.

    The fare is computed by the same pricing engine as the website, from the
    trip type and its inputs (distance for a transfer, hours for hourly, or a
    flat city-to-city route). Staff may override the total for a negotiated or
    corporate price; the override is recorded on the audit trail. The view does
    the pricing -- this form only collects the inputs.
    """

    trip_mode = forms.ChoiceField(
        choices=TRIP_MODE_CHOICES, initial="transfer",
        widget=forms.RadioSelect, label="Trip type",
    )
    city_route = forms.ModelChoiceField(
        queryset=CityRoute.objects.filter(is_active=True),
        required=False, empty_label="— choose a route —", label="Route",
    )
    override_total = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=10, decimal_places=2,
        label="Override total ($)",
        help_text="Leave blank to use the system price.",
    )
    # Set by the "Find customer" search when staff pick an existing account.
    customer_id = forms.IntegerField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Booking
        fields = [
            "pickup_sign", "guest_phone", "guest_email",
            "vehicle", "pickup_at", "pickup_address", "dropoff_address",
            "hours", "passenger_count", "luggage_count", "flight_number",
            "meet_and_greet", "driver", "status", "notes",
        ]
        labels = {
            "pickup_sign": "Customer name",
            "guest_phone": "Customer phone",
            "guest_email": "Customer email",
            "pickup_at": "Pickup date & time",
            "driver": "Assign driver (optional)",
            "notes": "Notes for the driver",
        }
        help_texts = {
            "pickup_sign": "Who the ride is for -- shown to the driver.",
            "dropoff_address": "Transfer: the drop-off. City-to-city: optional.",
            "hours": "By-the-hour only.",
            "guest_email": "Optional -- the receipt is emailed here if given.",
        }
        widgets = {
            "pickup_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M",
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = (
            Vehicle.objects.filter(is_active=True).order_by("display_order", "name")
        )
        self.fields["pickup_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]
        self.fields["pickup_sign"].required = True
        self.fields["guest_phone"].required = True
        self.fields["hours"].required = False
        self.fields["dropoff_address"].required = False
        self.fields["driver"].required = False
        self.fields["driver"].queryset = Driver.objects.filter(is_active=True).order_by("full_name")
        # A manual booking is one staff just took; only these statuses make sense.
        self.fields["status"].choices = [
            (Booking.Status.CONFIRMED, Booking.Status.CONFIRMED.label),
            (Booking.Status.PENDING, Booking.Status.PENDING.label),
        ]
        self.initial.setdefault("status", Booking.Status.CONFIRMED)
        self.initial.setdefault("passenger_count", 1)

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("trip_mode")
        if mode == "transfer":
            if not (cleaned.get("dropoff_address") or "").strip():
                self.add_error("dropoff_address",
                               "A drop-off address is required for a transfer.")
        elif mode == "hourly":
            if not cleaned.get("hours") or cleaned["hours"] <= 0:
                self.add_error("hours", "Enter how many hours for an hourly hire.")
        elif mode == "city":
            if not cleaned.get("city_route"):
                self.add_error("city_route", "Choose a city-to-city route.")
        _apply_capacity_errors(self, cleaned)
        return cleaned


class BookingEditForm(BootstrapFormMixin, forms.ModelForm):
    """
    Edit an existing booking's trip details, contact and fare.

    Independent of the create form: here the total is edited directly (changing
    it replaces the stored breakdown with a single adjusted line, in the view).
    Status/driver stay with the dedicated control on the detail page.
    """

    class Meta:
        model = Booking
        fields = [
            "pickup_sign", "guest_phone", "guest_email",
            "vehicle", "pickup_at", "pickup_address", "dropoff_address",
            "passenger_count", "luggage_count", "flight_number",
            "meet_and_greet", "total", "notes",
        ]
        labels = {
            "pickup_sign": "Customer name",
            "guest_phone": "Customer phone",
            "guest_email": "Customer email",
            "pickup_at": "Pickup date & time",
            "total": "Total fare ($)",
            "notes": "Notes for the driver",
        }
        widgets = {
            "pickup_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M",
            ),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = (
            Vehicle.objects.filter(is_active=True).order_by("display_order", "name")
        )
        self.fields["pickup_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"]
        self.fields["pickup_sign"].required = False
        self.fields["guest_phone"].required = False

    def clean_total(self):
        total = self.cleaned_data.get("total")
        if total is None or total < 0:
            raise forms.ValidationError("Enter the agreed fare as a positive amount.")
        return total

    def clean(self):
        cleaned = super().clean()
        _apply_capacity_errors(self, cleaned)
        return cleaned


class PaymentSettingsForm(BootstrapFormMixin, forms.ModelForm):
    """
    Stripe credentials.

    The two secret fields are write-only: they render empty every time and an
    empty submission means "leave the stored value alone". A form that echoed
    the secret back would put a live charge-and-refund credential into the HTML
    of a page, into the browser cache, and into anyone's screen recording.
    """

    secret_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"autocomplete": "off", "placeholder": "sk_live_… or sk_test_…"},
        ),
        help_text="Leave blank to keep the current key. Encrypted at rest.",
    )
    webhook_secret = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"autocomplete": "off", "placeholder": "whsec_…"},
        ),
        help_text="From the Stripe webhook endpoint. Leave blank to keep the current value.",
    )

    class Meta:
        model = PaymentSettings
        fields = ["mode", "is_enabled", "publishable_key", "statement_descriptor"]
        widgets = {
            "publishable_key": forms.TextInput(
                attrs={"placeholder": "pk_live_… or pk_test_…", "size": 50},
            ),
            "statement_descriptor": forms.TextInput(
                attrs={"placeholder": "AUSTIN LIMO", "maxlength": 22},
            ),
        }

    def clean_publishable_key(self):
        value = (self.cleaned_data.get("publishable_key") or "").strip()
        if value and not value.startswith(("pk_test_", "pk_live_")):
            raise forms.ValidationError(
                "A publishable key starts with pk_test_ or pk_live_. "
                "If this starts with sk_, it is a secret key and must not go here."
            )
        return value

    def clean_secret_key(self):
        value = (self.cleaned_data.get("secret_key") or "").strip()
        if value and not value.startswith(("sk_test_", "sk_live_", "rk_test_", "rk_live_")):
            raise forms.ValidationError(
                "A secret key starts with sk_ (or rk_ for a restricted key)."
            )
        return value

    def clean_webhook_secret(self):
        value = (self.cleaned_data.get("webhook_secret") or "").strip()
        if value and not value.startswith("whsec_"):
            raise forms.ValidationError("A webhook signing secret starts with whsec_.")
        return value

    def clean(self):
        """
        Cross-check the keys against the selected mode.

        Live mode with test keys is a silent failure: the checkout appears to
        work and no money moves. Test keys in live mode is the reverse and
        charges real cards during testing.
        """
        cleaned = super().clean()
        mode = cleaned.get("mode")
        enabled = cleaned.get("is_enabled")

        secret = cleaned.get("secret_key") or (self.instance.secret_key or "")
        publishable = cleaned.get("publishable_key") or ""

        if mode == PaymentSettings.Mode.LIVE:
            if secret and not secret.startswith(("sk_live_", "rk_live_")):
                self.add_error(
                    "mode",
                    "Live mode is selected but the secret key is a test key. "
                    "Payments would silently never reach a real card.",
                )
            if publishable and not publishable.startswith("pk_live_"):
                self.add_error("publishable_key", "Live mode needs a pk_live_ key.")
        elif mode == PaymentSettings.Mode.TEST:
            if secret and secret.startswith(("sk_live_", "rk_live_")):
                self.add_error(
                    "mode",
                    "Test mode is selected but the secret key is a LIVE key. "
                    "Testing would charge real cards.",
                )
            if publishable and publishable.startswith("pk_live_"):
                self.add_error("publishable_key", "Test mode needs a pk_test_ key.")

        if enabled:
            if not publishable:
                self.add_error(
                    "is_enabled", "A publishable key is required before enabling payments.",
                )
            if not secret:
                self.add_error(
                    "is_enabled", "A secret key is required before enabling payments.",
                )

        return cleaned

    def save(self, commit=True):
        """Only overwrite a secret when a replacement was actually supplied."""
        instance = super().save(commit=False)

        if secret := self.cleaned_data.get("secret_key"):
            instance.secret_key = secret
        if webhook := self.cleaned_data.get("webhook_secret"):
            instance.webhook_secret = webhook

        if commit:
            instance.save()
        return instance


class EmailSettingsForm(BootstrapFormMixin, forms.ModelForm):
    """
    SMTP credentials.

    The password is write-only, for the same reason as the Stripe secret: a
    mailbox password sends mail as the business, and a leaked one is a phishing
    platform with the client's own domain behind it.
    """

    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"autocomplete": "new-password", "placeholder": "mailbox password"},
        ),
        help_text="Leave blank to keep the current password. Encrypted at rest.",
    )

    class Meta:
        model = EmailSettings
        fields = [
            "is_enabled", "host", "port", "security", "username",
            "from_name", "from_email", "reply_to", "ops_notification_email",
            "timeout_seconds",
        ]
        widgets = {
            "host": forms.TextInput(attrs={"placeholder": "mail.austinlimoshuttle.com",
                                           "size": 40}),
            "from_email": forms.EmailInput(
                attrs={"placeholder": "bookings@austinlimoshuttle.com", "size": 40}),
            "reply_to": forms.EmailInput(attrs={"size": 40}),
            "ops_notification_email": forms.EmailInput(attrs={"size": 40}),
        }

    def clean(self):
        cleaned = super().clean()
        security = cleaned.get("security")
        port = cleaned.get("port")

        # Not fatal -- hosts vary -- but the mismatch is worth surfacing, because
        # the symptom is a connection that hangs rather than an error.
        if security == EmailSettings.Security.SSL and port == 587:  # noqa: PLR2004
            self.add_error(
                "port",
                "Port 587 is normally STARTTLS, not SSL/TLS. SSL usually uses 465.",
            )
        if security == EmailSettings.Security.TLS and port == 465:  # noqa: PLR2004
            self.add_error(
                "port",
                "Port 465 is normally SSL/TLS, not STARTTLS. STARTTLS usually uses 587.",
            )

        if cleaned.get("is_enabled"):
            if not cleaned.get("host"):
                self.add_error("is_enabled", "A host is required before enabling email.")
            if not cleaned.get("from_email"):
                self.add_error(
                    "is_enabled", "A from address is required before enabling email.",
                )

        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if password := self.cleaned_data.get("password"):
            instance.password = password
        if commit:
            instance.save()
        return instance


class PayPalSettingsForm(BootstrapFormMixin, forms.ModelForm):
    """
    PayPal REST credentials.

    The client secret is write-only, as with the Stripe key and the SMTP
    password: a form that echoes a secret back puts it into page HTML, the
    browser cache, and any screen recording.

    Unlike Stripe, PayPal credentials carry no sandbox/live prefix, so the mode
    cannot be cross-checked against the strings. The "Test connection" action on
    the page covers that instead.
    """

    client_secret = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"autocomplete": "off", "placeholder": "PayPal client secret"},
        ),
        help_text="Leave blank to keep the current secret. Encrypted at rest.",
    )

    class Meta:
        model = PayPalSettings
        fields = ["mode", "is_enabled", "client_id", "webhook_id", "brand_name"]
        widgets = {
            "client_id": forms.TextInput(attrs={"placeholder": "AY…", "size": 50}),
            "webhook_id": forms.TextInput(attrs={"placeholder": "8SW…"}),
            "brand_name": forms.TextInput(attrs={"placeholder": "Austin Limo Shuttle"}),
        }

    def clean_client_id(self):
        value = (self.cleaned_data.get("client_id") or "").strip()
        if value and value.startswith(("sk_", "pk_", "whsec_")):
            raise forms.ValidationError(
                "That looks like a Stripe key. PayPal credentials belong on this "
                "page; Stripe keys belong on the Payments page."
            )
        return value

    def clean_client_secret(self):
        return (self.cleaned_data.get("client_secret") or "").strip()

    def clean(self):
        cleaned = super().clean()
        secret = cleaned.get("client_secret") or (self.instance.client_secret or "")

        if cleaned.get("is_enabled"):
            if not cleaned.get("client_id"):
                self.add_error(
                    "is_enabled", "A client ID is required before enabling PayPal.",
                )
            if not secret:
                self.add_error(
                    "is_enabled", "A client secret is required before enabling PayPal.",
                )
            if not cleaned.get("webhook_id"):
                # Not fatal: a webhook id is only needed once payments are taken,
                # and enabling without one is a legitimate intermediate state.
                self.add_error(
                    "webhook_id",
                    "A webhook ID is needed to verify PayPal events. Add it before "
                    "taking live payments.",
                )

        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if secret := self.cleaned_data.get("client_secret"):
            instance.client_secret = secret
        if commit:
            instance.save()
        return instance


# ---------------------------------------------------------------------------
# Managed records
#
# These back the screens that replace Django's admin. Validation that protects
# money or search rankings lives here rather than in the template, so it holds
# whichever screen the edit arrives from.
# ---------------------------------------------------------------------------


class DriverForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Driver
        fields = ["full_name", "phone", "email", "is_active", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}
        help_texts = {
            "is_active": "Deactivate rather than delete — past bookings name this driver.",
        }


class VehicleForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = [
            "name", "slug", "description", "features", "photo",
            "passenger_capacity", "luggage_capacity",
            "hourly_rate", "meet_greet_fee", "minimum_fare",
            "display_order", "is_active",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "features": forms.Textarea(attrs={"rows": 3}),
        }


class DistanceBandForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = DistanceBand
        fields = ["from_miles", "to_miles", "rate_per_mile"]


class BaseDistanceBandFormSet(forms.BaseInlineFormSet):
    """
    A vehicle's rate card, validated as a set.

    Bands are cumulative, so the individual rows can each be valid while the
    card as a whole is wrong: a gap between 6 and 10 miles silently prices those
    four miles at zero, and an overlap charges them twice. Neither is visible
    when checking one row at a time, and both misprice every future quote for
    that vehicle.
    """

    def clean(self):
        super().clean()
        if any(self.errors):
            return

        bands = sorted(
            (
                form.cleaned_data for form in self.forms
                if form.cleaned_data and not form.cleaned_data.get("DELETE")
            ),
            key=lambda row: row["from_miles"],
        )
        if not bands:
            return

        if bands[0]["from_miles"] != 0:
            raise forms.ValidationError(
                "The first band must start at 0 miles, or the opening miles of "
                "every journey are unpriced."
            )

        unbounded = [b for b in bands if b.get("to_miles") is None]
        if len(unbounded) > 1:
            raise forms.ValidationError(
                "Only the final band may be left open-ended."
            )
        if unbounded and unbounded[0] is not bands[-1]:
            raise forms.ValidationError(
                "Only the final band may be left open-ended."
            )

        for lower, higher in zip(bands, bands[1:], strict=False):
            if lower.get("to_miles") is None:
                continue
            if lower["to_miles"] < higher["from_miles"]:
                raise forms.ValidationError(
                    f"Nothing prices the miles between {lower['to_miles']:g} and "
                    f"{higher['from_miles']:g}. Bands must be continuous."
                )
            if lower["to_miles"] > higher["from_miles"]:
                raise forms.ValidationError(
                    f"Bands overlap between {higher['from_miles']:g} and "
                    f"{lower['to_miles']:g}. Those miles would be charged twice."
                )


DistanceBandFormSet = forms.inlineformset_factory(
    Vehicle, DistanceBand, form=DistanceBandForm, formset=BaseDistanceBandFormSet,
    extra=2, can_delete=True,
)


class CityRouteForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CityRoute
        fields = ["origin", "destination", "bidirectional", "is_active"]
        help_texts = {
            "bidirectional": "Price the reverse direction (B → A) at the same rate.",
        }


class CityRoutePriceForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = CityRoutePrice
        fields = ["vehicle", "price"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only active vehicles can be priced; a retired class shouldn't appear.
        self.fields["vehicle"].queryset = Vehicle.objects.filter(
            is_active=True
        ).order_by("display_order", "name")


class BaseCityRoutePriceFormSet(forms.BaseInlineFormSet):
    """A route's price list. Each vehicle may appear at most once."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        seen = set()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            vehicle = form.cleaned_data.get("vehicle")
            if vehicle in seen:
                raise forms.ValidationError(
                    f"{vehicle} is priced twice — one price per vehicle on a route."
                )
            seen.add(vehicle)


CityRoutePriceFormSet = forms.inlineformset_factory(
    CityRoute, CityRoutePrice, form=CityRoutePriceForm,
    formset=BaseCityRoutePriceFormSet, extra=3, can_delete=True,
)


class TimeSurchargeForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = TimeSurcharge
        fields = ["name", "start_time", "end_time", "percentage", "is_active"]
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }
        help_texts = {
            "percentage": "Added, not compounded. 40% and 20% together make 60%.",
        }


class BlackoutDateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = BlackoutDate
        fields = ["name", "date", "description", "percentage", "is_active"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}


class PricingSettingsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = PricingSettings
        fields = [
            "tax_rate", "currency", "cancellation_window_hours",
            "amendment_window_hours", "min_booking_lead_hours", "quote_ttl_minutes",
        ]
        labels = {
            "amendment_window_hours": "Customer edit window (hours before pickup)",
            "min_booking_lead_hours": "Minimum booking notice (hours before pickup)",
        }
        help_texts = {
            "tax_rate": "Applied to every quote. Changing it changes every future fare.",
            "amendment_window_hours": (
                "How close to pickup a customer can still change their booking "
                "online. 72 = 3 days, 24 = 1 day, 6 = 6 hours."
            ),
            "min_booking_lead_hours": (
                "How far ahead a customer must book online. 0 = no minimum, "
                "2 = at least 2 hours' notice. Staff phone bookings aren't limited."
            ),
        }


class PageForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Page
        fields = [
            "title", "slug", "page_type", "is_published", "body", "hero_image",
            "meta_title", "meta_description", "meta_keywords",
            "parent", "menu_placement", "display_order",
        ]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 14}),
            "meta_description": forms.Textarea(attrs={"rows": 2}),
            "meta_keywords": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {
            "slug": "The page's address. Changing it breaks search rankings and "
                    "every existing link — treat it as permanent.",
        }


class BannerForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Banner
        fields = ["title", "description", "image", "link_url", "page",
                  "display_order", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


class TestimonialForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Testimonial
        fields = ["customer_name", "quote", "rating", "photo",
                  "is_published", "display_order"]
        widgets = {"quote": forms.Textarea(attrs={"rows": 4})}


class GalleryImageForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = GalleryImage
        fields = ["title", "description", "image", "category",
                  "display_order", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}


class SiteSettingsForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = SiteSettings
        fields = [
            "contact_phone", "contact_email", "ops_notification_email",
            "facebook", "instagram", "twitter", "linkedin",
            "google_maps_api_key",
        ]
        labels = {
            "google_maps_api_key": "Google Maps API key",
        }
        help_texts = {
            "contact_phone": "Shown in the header and footer of the public site.",
            "ops_notification_email": "Where new-booking alerts go. Never shown publicly.",
            "google_maps_api_key": (
                "Powers address autocomplete and distance-based pricing. Needs "
                "Maps JavaScript API, Places API (New) and Distance Matrix API "
                "enabled. Leave blank to fall back to the server's configured key."
            ),
        }


class StaffUserForm(BootstrapFormMixin, forms.ModelForm):
    """
    A staff account and its role.

    The password is set through a separate write-only field: rendering the
    stored hash, or echoing a password back, puts a working credential into
    page source. Leaving it blank on an existing account keeps the current one.
    """

    role = forms.ModelChoiceField(
        queryset=Group.objects.all(), required=False,
        help_text="Dispatcher runs the day. Manager adds rates, refunds and "
                  "credentials. Editor is website content only.",
    )
    new_password = forms.CharField(
        required=False, label="Password",
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="Leave blank to keep the existing password.",
    )

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "phone", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["role"].initial = self.instance.groups.first()

    def clean_new_password(self):
        password = self.cleaned_data.get("new_password")
        if password:
            validate_password(password)
        elif not self.instance.pk:
            raise forms.ValidationError("Set a password for the new account.")
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = True  # every account on this screen is a staff account
        if password := self.cleaned_data.get("new_password"):
            user.set_password(password)
        if commit:
            user.save()
            user.groups.set([self.cleaned_data["role"]] if self.cleaned_data.get("role") else [])
        return user


class CustomerForm(BootstrapFormMixin, forms.ModelForm):
    """
    A customer record.

    No password field and no staff flag: this screen exists to correct a name
    or a phone number, not to grant anyone access. A customer who cannot sign
    in uses the reset link, which is the only path that proves they own the
    address.
    """

    class Meta:
        model = User
        fields = ["email", "title", "first_name", "last_name", "phone",
                  "marketing_opt_in", "is_active"]


class ChargeCardForm(BootstrapFormMixin, forms.Form):
    """
    Charge a customer's card on file off-session -- e.g. a trip extension.

    Only customers who have saved a card are selectable; the charge goes to that
    customer's default card. The amount is staff-entered (a negotiated extra),
    unlike a web booking where the server computes it.
    """

    customer = forms.ModelChoiceField(
        queryset=User.objects.none(), label="Customer",
        help_text="Only customers with a card on file are listed.",
    )
    amount = forms.DecimalField(
        min_value=Decimal("0.01"), max_digits=10, decimal_places=2,
        label="Amount to charge ($)",
    )
    description = forms.CharField(
        max_length=160, label="Description",
        help_text='Shown on the receipt, e.g. "Extra hour" or "Airport wait time".',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = (
            User.objects.filter(saved_cards__isnull=False)
            .distinct().order_by("first_name", "last_name", "email")
        )
        self.fields["customer"].label_from_instance = self._label

    @staticmethod
    def _label(user) -> str:
        card = user.saved_cards.first()
        who = user.get_full_name() or user.email
        return f"{who} — {card.label}" if card else who


class SmsSettingsForm(BootstrapFormMixin, forms.ModelForm):
    """Twilio credentials. The auth token is write-only, like the SMTP password."""

    auth_token = forms.CharField(
        required=False,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"autocomplete": "new-password", "placeholder": "Twilio auth token"},
        ),
        help_text="Leave blank to keep the current token. Encrypted at rest.",
    )

    class Meta:
        model = SmsSettings
        fields = [
            "is_enabled", "account_sid", "from_number",
            "confirmation_enabled", "reminder_enabled", "reminder_lead_hours",
        ]
        labels = {
            "is_enabled": "SMS enabled",
            "account_sid": "Twilio Account SID",
            "from_number": "From number (E.164, e.g. +15125550100)",
            "reminder_lead_hours": "Reminder lead time (hours before pickup)",
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        if token := self.cleaned_data.get("auth_token"):
            instance.auth_token = token
        if commit:
            instance.save()
        return instance
