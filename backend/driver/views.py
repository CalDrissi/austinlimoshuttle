"""
The driver app: a mobile-first portal where a chauffeur sees their own runs and
reports progress.

Deliberately server-rendered and JavaScript-free: it reuses Django's auth and
session, and the dashboard's Bootstrap, so there is no API or SPA to maintain.
A driver only ever sees bookings assigned to their own Driver record.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from bookings.models import Booking, BookingStatusChange

# The driver can see runs this far back when paging through days -- enough to
# fix up yesterday's status, not so much it becomes a history browser (v2).
PAST_DAYS_LIMIT = 7


def driver_for(user):
    """The active Driver behind a user, or None. The whole access rule lives here."""
    if not user.is_authenticated:
        return None
    profile = getattr(user, "driver_profile", None)
    return profile if (profile and profile.is_active) else None


def driver_required(view):
    """Gate a page to drivers. Never logs anyone out -- staff share the cookie."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=reverse("driver:login"))
        if driver_for(request.user) is None:
            return render(request, "driver/no_access.html", status=403)
        return view(request, *args, **kwargs)
    return wrapped


def _day_bounds(d):
    """Aware [start, end) for a local calendar day in the business timezone."""
    start = timezone.make_aware(datetime.combine(d, time.min))
    return start, start + timedelta(days=1)


def driver_login(request):
    """Email + password sign-in, scoped to accounts that are a driver."""
    if driver_for(request.user):
        return redirect("driver:runs")

    error = ""
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=email, password=password)
        if user is not None and driver_for(user):
            login(request, user)
            return redirect("driver:runs")
        error = "Wrong email or password, or this account has no driver access."
    return render(request, "driver/login.html", {"error": error})


@driver_required
def runs(request):
    """The driver's assigned trips for one day, with Today/Tomorrow + day paging."""
    profile = driver_for(request.user)
    today = timezone.localdate()

    selected = parse_date(request.GET.get("date", "")) or today
    # Clamp how far back they can page; forward is open (future schedule).
    if selected < today - timedelta(days=PAST_DAYS_LIMIT):
        selected = today - timedelta(days=PAST_DAYS_LIMIT)

    start, end = _day_bounds(selected)
    bookings = (
        profile.bookings
        .select_related("vehicle")
        .filter(pickup_at__gte=start, pickup_at__lt=end)
        .exclude(status=Booking.Status.CANCELLED)
        .order_by("pickup_at")
    )

    prev_date = selected - timedelta(days=1)
    return render(request, "driver/runs.html", {
        "driver": profile,
        "view": "day",
        "bookings": bookings,
        "selected": selected,
        "today": today,
        "tomorrow": today + timedelta(days=1),
        "is_today": selected == today,
        "is_tomorrow": selected == today + timedelta(days=1),
        "prev_date": prev_date if prev_date >= today - timedelta(days=PAST_DAYS_LIMIT) else None,
        "next_date": selected + timedelta(days=1),
    })


@driver_required
def upcoming(request):
    """Every upcoming run in one scroll, grouped by day -- the list view, for a
    driver who wants to see further ahead than Today/Tomorrow."""
    profile = driver_for(request.user)
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    start, _ = _day_bounds(today)

    bookings = (
        profile.bookings
        .select_related("vehicle")
        .filter(pickup_at__gte=start)
        .exclude(status=Booking.Status.CANCELLED)
        .order_by("pickup_at")
    )

    # Group by the LOCAL calendar day (pickup_at is stored tz-aware).
    groups = []
    for b in bookings:
        day = timezone.localtime(b.pickup_at).date()
        if not groups or groups[-1]["date"] != day:
            groups.append({
                "date": day,
                "is_today": day == today,
                "is_tomorrow": day == tomorrow,
                "items": [],
            })
        groups[-1]["items"].append(b)

    return render(request, "driver/upcoming.html", {
        "driver": profile,
        "view": "upcoming",
        "groups": groups,
        "total": len(bookings),
    })


def _own_booking(request, reference):
    profile = driver_for(request.user)
    return get_object_or_404(
        Booking.objects.select_related("vehicle", "customer"),
        reference=reference, driver=profile,
    )


@driver_required
def trip_detail(request, reference):
    """Everything the driver needs on the road for one trip."""
    booking = _own_booking(request, reference)
    return render(request, "driver/trip_detail.html", {
        "booking": booking,
        "driver": driver_for(request.user),
    })


# What a driver is allowed to set, and the human note recorded on the audit row.
DRIVER_ACTIONS = {
    "completed": (Booking.Status.COMPLETED, "Driver marked the trip completed"),
    "no_show": (Booking.Status.NO_SHOW, "Driver marked the passenger a no-show"),
}


@driver_required
@require_POST
def trip_action(request, reference):
    """Report the outcome of a trip: completed or no-show."""
    booking = _own_booking(request, reference)
    action = request.POST.get("action", "")

    if action not in DRIVER_ACTIONS:
        messages.error(request, "Unknown action.")
        return redirect("driver:trip_detail", reference=reference)

    new_status, note = DRIVER_ACTIONS[action]
    if booking.status == new_status:
        messages.info(request, "That was already recorded.")
        return redirect("driver:trip_detail", reference=reference)
    if booking.status == Booking.Status.CANCELLED:
        messages.error(request, "This trip was cancelled — contact dispatch.")
        return redirect("driver:trip_detail", reference=reference)

    BookingStatusChange.objects.create(
        booking=booking,
        from_status=booking.status,
        to_status=new_status,
        changed_by=request.user,
        note=note,
    )
    booking.status = new_status
    booking.save(update_fields=["status", "updated_at"])
    messages.success(request, "Thanks — dispatch has been updated.")
    return redirect("driver:trip_detail", reference=reference)
