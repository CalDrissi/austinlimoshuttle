"""
What staff can manage from the dashboard.

One entry per model that previously required Django's admin. The order here is
the order they appear in the sidebar.
"""

from __future__ import annotations

from bookings.models import Driver
from fleet.models import Vehicle
from pricing.models import BlackoutDate, TimeSurcharge

from . import forms
from .crud import Column, Inline, Managed, register

QUOTE_PREVIEW_CHARS = 70

User = Driver._meta.apps.get_model("accounts", "User")


def _truncate(text: str | None) -> str:
    text = text or ""
    return text[:QUOTE_PREVIEW_CHARS] + ("…" if len(text) > QUOTE_PREVIEW_CHARS else "")


def _money(attr, prefix="$"):
    def render(instance):
        value = getattr(instance, attr)
        return f"{prefix}{value:,.2f}" if value is not None else "—"
    return render


# -- operations -------------------------------------------------------------

register(Managed(
    slug="drivers",
    model=Driver,
    form_class=forms.DriverForm,
    label="Driver",
    label_plural="Drivers",
    permission="bookings.change_driver",
    icon="bi-person-badge",
    lede="Chauffeurs available for assignment on the dispatch board.",
    search_fields=["full_name", "phone", "email"],
    ordering=["full_name"],
    columns=[
        Column("Name", "full_name", sub="email"),
        Column("Phone", "phone"),
        Column("Active", "is_active", boolean=True),
    ],
))

# -- fleet and pricing ------------------------------------------------------

register(Managed(
    slug="vehicles",
    model=Vehicle,
    form_class=forms.VehicleForm,
    label="Vehicle",
    label_plural="Vehicles & rates",
    permission="fleet.change_vehicle",
    icon="bi-car-front",
    lede="Vehicle classes and their per-mile rate cards.",
    form_note=(
        "The rate card is cumulative: a 70-mile journey is charged the first "
        "band for its opening miles, the next band for the miles after that, "
        "and so on. Bands must be continuous and start at zero — a gap prices "
        "those miles at nothing, and an overlap charges them twice."
    ),
    search_fields=["name", "slug"],
    ordering=["display_order", "name"],
    prefetch_related=["bands", "intercity_bands"],
    inlines=[
        Inline(
            forms.DistanceBandFormSet,
            label="Rate card",
            note="From/to are miles. Leave the final band's upper bound empty.",
        ),
        Inline(
            forms.IntercityBandFormSet,
            label="City-to-city",
            note=(
                "Per-mile card for free-form city-to-city trips. Fill in the "
                "minimum distance above to switch it on: empty = never, "
                "0 = any distance. Same from/to rules as the rate card."
            ),
            icon="bi-signpost-split",
        ),
    ],
    columns=[
        Column("Vehicle", "name", sub="slug"),
        Column("Seats", "passenger_capacity"),
        Column("Luggage", "luggage_capacity"),
        Column("Hourly", _money("hourly_rate"), align_end=True),
        Column("Minimum fare", _money("minimum_fare"), align_end=True),
        Column("Bands", lambda v: v.bands.count()),
        Column("Active", "is_active", boolean=True),
    ],
))

# "City routes" (CityRoute + CityRoutePrice) was removed from the dashboard on
# 2026-11-03 as part of the city-to-city rework: intercity pricing is now the
# free-form, per-mile IntercityBand card edited on the Vehicle screen above, so
# the fixed-route page no longer has anything to manage. The CityRoute model is
# untouched here (owned by @pricing-rates); the dashboard simply stops
# registering it, so /dashboard/manage/city-routes/ no longer exists.

register(Managed(
    slug="surcharges",
    model=TimeSurcharge,
    form_class=forms.TimeSurchargeForm,
    label="Time surcharge",
    label_plural="Time surcharges",
    permission="pricing.change_timesurcharge",
    icon="bi-clock-history",
    lede="Windows that cost more — late night, early morning.",
    search_fields=["name"],
    ordering=["start_time"],
    columns=[
        Column("Name", "name"),
        Column("From", lambda s: s.start_time.strftime("%H:%M")),
        Column("To", lambda s: s.end_time.strftime("%H:%M")),
        Column("Uplift", lambda s: f"+{s.percentage:g}%", align_end=True),
        Column("Active", "is_active", boolean=True),
    ],
))

register(Managed(
    slug="blackout-dates",
    model=BlackoutDate,
    form_class=forms.BlackoutDateForm,
    label="Event date",
    label_plural="Event dates",
    permission="pricing.change_blackoutdate",
    icon="bi-calendar-event",
    lede="Dates that carry an uplift — SXSW, ACL, New Year's Eve.",
    search_fields=["name", "description"],
    ordering=["date"],
    columns=[
        Column("Date", lambda b: b.date.strftime("%d %b %Y")),
        Column("Name", "name", sub="description"),
        Column("Uplift", lambda b: f"+{b.percentage:g}%", align_end=True),
        Column("Active", "is_active", boolean=True),
    ],
))

# -- website content --------------------------------------------------------
# Pages, Testimonials, Banners and Gallery were removed from the dashboard on
# 2026-10-06. The storefront renders that content hardcoded and consumes none of
# it: Testimonials/Banners/Gallery have no public API, and /api/pages/ exists but
# nothing on the frontend calls it. Editing these changed nothing on the live
# site. The models, data and admin are untouched -- re-register them here once
# the storefront is wired to that content (tracked in the project todos).

# -- people -----------------------------------------------------------------

register(Managed(
    slug="staff",
    model=User,
    form_class=forms.StaffUserForm,
    label="Staff account",
    label_plural="Staff accounts",
    permission="accounts.change_user",
    icon="bi-people",
    lede=(
        "One account per person. Every booking change is recorded against "
        "whoever made it, which only works if logins are not shared."
    ),
    search_fields=["email", "first_name", "last_name"],
    ordering=["email"],
    prefetch_related=["groups"],
    can_delete=False,  # deactivate instead; the audit trail points at these rows
    columns=[
        Column("Name", lambda u: u.get_full_name() or "—", sub="email"),
        Column("Role", lambda u: ", ".join(g.name for g in u.groups.all()) or "—"),
        Column("Superuser", "is_superuser", boolean=True),
        Column("Active", "is_active", boolean=True),
    ],
))

register(Managed(
    slug="customers",
    model=User,
    form_class=forms.CustomerForm,
    label="Customer",
    label_plural="Customers",
    permission="accounts.change_user",
    icon="bi-person-lines-fill",
    lede=(
        "Imported customers have no password until they use the reset link — "
        "passwords were deliberately not carried over from the old system."
    ),
    search_fields=["email", "first_name", "last_name", "phone"],
    ordering=["-date_joined"],
    can_delete=False,
    columns=[
        Column("Name", lambda u: u.get_full_name() or "—", sub="email"),
        Column("Phone", "phone"),
        Column("Bookings", lambda u: u.bookings.count(), align_end=True),
        Column("Joined", lambda u: u.date_joined.strftime("%d %b %Y")),
        Column("Active", "is_active", boolean=True),
    ],
))


def staff_queryset_filter(slug, queryset):
    """
    Staff and customers share one table, so each screen must exclude the other
    or the customer list shows dispatchers and the staff list shows 1,252
    customers.
    """
    if slug == "staff":
        return queryset.filter(is_staff=True)
    if slug == "customers":
        return queryset.filter(is_staff=False)
    return queryset
