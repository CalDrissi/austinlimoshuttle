"""
Staff dashboard.

Django templates, served by Django. These are the screens that go beyond model
CRUD -- the work a dispatcher actually does during a shift. Everything else
stays in Django's generated admin.
"""

from __future__ import annotations

import calendar
import csv
import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME, get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.deletion import ProtectedError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from bookings.models import (
    Booking,
    BookingPriceLine,
    BookingStatusChange,
    Driver,
    DriverTripEvent,
)
from django.conf import settings
from django.http import JsonResponse
from django.utils.dateparse import parse_datetime
from content.models import SiteSettings
from fleet.models import Vehicle
from pricing.distance import DistanceLookupError
from pricing.distance import lookup as measure_journey
from pricing.engine import QuoteError, quote
from enquiries.models import ContactMessage
from notifications import mailer, sms
from notifications.models import EmailLog, EmailSettings, SmsLog, SmsSettings
from payments import gateway, paypal
from payments.models import Payment, PaymentSettings, PayPalSettings, SavedCard
from pricing.models import CityRoute, PricingSettings

from . import crud, managed
from .forms import (
    BookingEditForm,
    ChargeCardForm,
    EmailSettingsForm,
    ManualBookingForm,
    PaymentSettingsForm,
    PayPalSettingsForm,
    PricingSettingsForm,
    SiteSettingsForm,
    SmsSettingsForm,
)
from .permissions import is_manager, role_names

logger = logging.getLogger(__name__)

BOOKINGS_PER_PAGE = 50
ENQUIRIES_PER_PAGE = 50
TRIP_EVENTS_PER_PAGE = 50


def admin_login_redirect(request):
    """
    Send Django's admin login to the branded gate.

    The admin ships its own login view at /admin/login/, so re-pointing
    LOGIN_URL only moved the dashboard's gate and left a second, unstyled one
    for anyone who went to /admin/ directly. Two sign-in screens for one set of
    credentials is confusing on its own, and one of them looks like a different
    product.

    The ?next= is carried across but validated first: reflecting it unchecked
    would turn this into an open redirect, which is a phishing primitive.
    """
    target = request.GET.get(REDIRECT_FIELD_NAME) or "/admin/"
    if not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        target = "/admin/"
    return redirect(f"{reverse('dashboard:login')}?{urlencode({REDIRECT_FIELD_NAME: target})}")


def staff_required(view):
    """Dashboard access requires a staff account, not merely a login."""
    return login_required(
        permission_required("bookings.view_booking", raise_exception=True)(view),
        login_url="dashboard:login",
    )


@staff_required
def home(request):
    """Overview: what needs attention today."""
    now = timezone.now()
    today_end = now.replace(hour=23, minute=59, second=59)
    week_ago = now - timedelta(days=7)

    upcoming = Booking.objects.for_dispatch().upcoming()

    context = {
        "today_count": upcoming.filter(pickup_at__lte=today_end).count(),
        "week_count": upcoming.filter(pickup_at__lte=now + timedelta(days=7)).count(),
        "unassigned": upcoming.filter(driver__isnull=True).count(),
        "pending": Booking.objects.filter(status=Booking.Status.PENDING).count(),
        "unread_enquiries": ContactMessage.objects.filter(is_read=False).count(),
        "recent_revenue": Booking.objects.filter(
            created_at__gte=week_ago,
            status__in=[Booking.Status.CONFIRMED, Booking.Status.COMPLETED],
        ).aggregate(total=Sum("total"))["total"],
        "next_pickups": upcoming.order_by("pickup_at")[:8],
        "roles": role_names(request.user),
        "is_manager": is_manager(request.user),
    }
    return render(request, "dashboard/home.html", context)


@staff_required
def dispatch(request):
    """
    The dispatch board: today and tomorrow, in pickup order.

    This is the screen staff live in, so it answers one question at a glance --
    what is happening next, and does it have a driver.
    """
    now = timezone.now()
    horizon = now + timedelta(days=2)

    bookings = (
        Booking.objects.for_dispatch()
        .filter(pickup_at__gte=now - timedelta(hours=4), pickup_at__lte=horizon)
        .exclude(status=Booking.Status.CANCELLED)
        .order_by("pickup_at")
    )

    context = {
        "bookings": bookings,
        "drivers": Driver.objects.filter(is_active=True),
        "statuses": Booking.Status.choices,
        "now": now,
        "roles": role_names(request.user),
    }
    return render(request, "dashboard/dispatch.html", context)


@staff_required
def booking_list(request):
    """Searchable, filterable booking list."""
    bookings = Booking.objects.for_dispatch().order_by("-pickup_at")

    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    date_from = request.GET.get("from", "").strip()
    date_to = request.GET.get("to", "").strip()

    if query:
        bookings = bookings.filter(
            Q(reference__icontains=query)
            | Q(pickup_address__icontains=query)
            | Q(dropoff_address__icontains=query)
            | Q(pickup_sign__icontains=query)
            | Q(flight_number__icontains=query)
            | Q(customer__email__icontains=query)
            | Q(customer__first_name__icontains=query)
            | Q(customer__last_name__icontains=query)
        )
    if status:
        bookings = bookings.filter(status=status)
    if date_from:
        bookings = bookings.filter(pickup_at__date__gte=date_from)
    if date_to:
        bookings = bookings.filter(pickup_at__date__lte=date_to)

    # The export deliberately ignores paging: it is the whole filtered set.
    if request.GET.get("export") == "csv":
        return _export_csv(bookings)

    paginator = Paginator(bookings, BOOKINGS_PER_PAGE)
    page = paginator.get_page(request.GET.get("page"))

    # Quick date filters. Computed server-side in the site's timezone, because
    # "today" from the browser is whatever timezone the dispatcher's laptop is
    # set to, which is not necessarily Austin's.
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    quick_ranges = {
        "today": (today, today),
        "tomorrow": (tomorrow, tomorrow),
        "week": (today, today + timedelta(days=7)),
    }
    active_quick = next(
        (
            name for name, (start, end) in quick_ranges.items()
            if date_from == start.isoformat() and date_to == end.isoformat()
        ),
        None,
    )

    # Filters have to survive a page change, so they are rebuilt into every
    # pagination link. `page` itself is dropped or it would accumulate.
    params = request.GET.copy()
    params.pop("page", None)
    querystring = params.urlencode()

    context = {
        "bookings": page.object_list,
        "page": page,
        "paginator": paginator,
        "page_range": paginator.get_elided_page_range(
            page.number, on_each_side=2, on_ends=1,
        ),
        "total": paginator.count,
        "showing": len(page.object_list),
        "querystring": f"&{querystring}" if querystring else "",
        "statuses": Booking.Status.choices,
        "filters": {"q": query, "status": status, "from": date_from, "to": date_to},
        "quick_ranges": {
            name: {"from": start.isoformat(), "to": end.isoformat()}
            for name, (start, end) in quick_ranges.items()
        },
        "active_quick": active_quick,
        "roles": role_names(request.user),
    }
    return render(request, "dashboard/booking_list.html", context)


@staff_required
def calendar_view(request):
    """
    Bookings as a month grid.

    The dispatch board answers "what is happening next"; this answers "how busy
    is the 14th", which is the question asked when someone rings up wanting a
    car on a date three weeks out.
    """
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        first_of_month = date(year, month, 1)
    except (TypeError, ValueError):
        first_of_month = today.replace(day=1)
        year, month = first_of_month.year, first_of_month.month

    last_day = calendar.monthrange(year, month)[1]
    month_end = date(year, month, last_day)

    # The grid shows leading and trailing days from the neighbouring months, so
    # the query has to cover them or those cells look empty when they are not.
    grid = calendar.Calendar(firstweekday=6).monthdatescalendar(year, month)
    span_start, span_end = grid[0][0], grid[-1][-1]

    bookings = (
        Booking.objects.select_related("vehicle", "driver")
        .filter(
            pickup_at__date__gte=span_start,
            pickup_at__date__lte=span_end,
        )
        .exclude(status=Booking.Status.CANCELLED)
        .order_by("pickup_at")
    )

    by_day: dict[date, list[Booking]] = defaultdict(list)
    for booking in bookings:
        by_day[timezone.localtime(booking.pickup_at).date()].append(booking)

    weeks = [
        [
            {
                "date": day,
                "bookings": by_day.get(day, []),
                "in_month": day.month == month,
                "is_today": day == today,
            }
            for day in week
        ]
        for week in grid
    ]

    previous_month = first_of_month - timedelta(days=1)
    next_month = month_end + timedelta(days=1)

    return render(request, "dashboard/calendar.html", {
        "weeks": weeks,
        "month_label": first_of_month.strftime("%B %Y"),
        "weekday_names": ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        "prev": {"year": previous_month.year, "month": previous_month.month},
        "next": {"year": next_month.year, "month": next_month.month},
        "today": today,
        "month_total": sum(
            len(v) for k, v in by_day.items() if k.month == month and k.year == year
        ),
        "roles": role_names(request.user),
    })


@staff_required
def booking_detail(request, reference):
    booking = get_object_or_404(
        Booking.objects.select_related("vehicle", "driver", "customer")
        .prefetch_related(
            "price_lines", "payments", "status_changes__changed_by",
            "trip_events__driver",
        ),
        reference=reference,
    )
    # The booking's own driver timeline (oldest-first reads like a journey).
    trip_events = list(booking.trip_events.all())
    context = {
        "booking": booking,
        "drivers": Driver.objects.filter(is_active=True),
        "statuses": Booking.Status.choices,
        "trip_events": trip_events,
        "map_points": _trip_event_map_points(trip_events),
        "roles": role_names(request.user),
        "is_manager": is_manager(request.user),
    }
    return render(request, "dashboard/booking_detail.html", context)


def _trip_event_map_points(events):
    """
    Turn trip events into JSON-safe pins for the Leaflet map.

    Only events that carry a GPS fix become pins; events with a null latitude
    or longitude are skipped here (the list still shows them as "location
    unknown"). Decimals are cast to float so the value survives json_script.
    """
    points = []
    for event in events:
        if event.latitude is None or event.longitude is None:
            continue
        points.append({
            "lat": float(event.latitude),
            "lng": float(event.longitude),
            "label": event.get_event_type_display(),
            "ref": event.booking.reference,
            "driver": event.driver.full_name if event.driver else "",
            "time": timezone.localtime(event.created_at).strftime("%-d %b %Y, %H:%M"),
        })
    return points


@staff_required
def trip_events(request):
    """
    Recent driver trip-events across every booking — a live feed of the status
    pings drivers send from the road, newest first, with a map of the ones that
    carried a GPS fix. Staff-gated like the rest of the dashboard.
    """
    events = (
        DriverTripEvent.objects.select_related("booking", "driver")
        .order_by("-created_at", "-id")
    )

    paginator = Paginator(events, TRIP_EVENTS_PER_PAGE)
    page = paginator.get_page(request.GET.get("page"))
    page_events = list(page.object_list)

    params = request.GET.copy()
    params.pop("page", None)
    querystring = params.urlencode()

    context = {
        "trip_events": page_events,
        "map_points": _trip_event_map_points(page_events),
        "page": page,
        "paginator": paginator,
        "page_range": paginator.get_elided_page_range(
            page.number, on_each_side=2, on_ends=1,
        ),
        "querystring": f"&{querystring}" if querystring else "",
        "roles": role_names(request.user),
        "is_manager": is_manager(request.user),
    }
    return render(request, "dashboard/trip_events.html", context)


def _quote_manual(mode, vehicle, *, pickup_at, pickup_address, dropoff_address,
                  hours, city_route, meet_and_greet):
    """
    Price a manual booking with the SAME engine as the website.

    `mode` is "transfer" | "hourly" | "city". Returns (quote, distance_miles,
    route); raises ValueError with a staff-facing message on any problem, so the
    caller can surface it in the form or as JSON.
    """
    if vehicle is None:
        raise ValueError("Choose a vehicle first.")
    if pickup_at is None:
        raise ValueError("Set the pickup date & time first.")

    distance = None
    route = None
    if mode == "city":
        route = city_route
        if route is None:
            raise ValueError("Choose a city-to-city route.")
    elif mode == "hourly":
        if not hours or hours <= 0:
            raise ValueError("Enter how many hours for the hourly hire.")
    else:  # transfer
        if not (dropoff_address or "").strip():
            raise ValueError("Enter a drop-off address for the transfer.")
        try:
            journey = measure_journey(pickup_address, dropoff_address)
        except DistanceLookupError as exc:
            raise ValueError(str(exc)) from exc
        distance = journey.distance_miles

    try:
        q = quote(
            vehicle,
            pickup_at=pickup_at,
            distance_miles=distance,
            hours=hours if mode == "hourly" else None,
            meet_and_greet=meet_and_greet,
            route=route,
        )
    except QuoteError as exc:
        raise ValueError(str(exc)) from exc
    return q, distance, route


def _resolve_customer(cd):
    """
    Attach a customer to a manual booking:
      - an explicitly-picked existing account (customer_id from the search), or
      - find-or-create by the entered email (accounts are email-based), or
      - None (guest booking) when no email is given.
    Returns (user_or_None, created_new).
    """
    User = get_user_model()
    cid = cd.get("customer_id")
    if cid:
        user = User.objects.filter(pk=cid, is_staff=False).first()
        if user:
            return user, False
    email = (cd.get("guest_email") or "").strip().lower()
    if not email:
        return None, False
    user = User.objects.filter(email__iexact=email).first()
    if user:
        return user, False
    first, _, last = (cd.get("pickup_sign") or "").strip().partition(" ")
    user = User.objects.create_user(
        email=email, password=None,
        first_name=first, last_name=last, phone=(cd.get("guest_phone") or ""),
    )
    return user, True


@login_required(login_url="dashboard:login")
@permission_required("bookings.add_booking", raise_exception=True)
def booking_customer_lookup(request):
    """Find existing customers by phone/email/name for the New Booking search."""
    q = (request.GET.get("q") or "").strip()
    results = []
    if len(q) >= 3:
        User = get_user_model()
        matches = (
            User.objects.filter(is_staff=False)
            .filter(Q(email__icontains=q) | Q(phone__icontains=q)
                    | Q(first_name__icontains=q) | Q(last_name__icontains=q))
            .order_by("last_name", "first_name")[:8]
        )
        for u in matches:
            cards = [
                {"id": c.id, "brand": c.brand, "last4": c.last4}
                for c in SavedCard.objects.filter(customer=u)
            ]
            results.append({
                "id": u.id,
                "name": u.get_full_name() or u.email,
                "email": u.email,
                "phone": u.phone,
                "has_card": bool(cards),
                "cards": cards,
            })
    return JsonResponse({"results": results})


@login_required(login_url="dashboard:login")
@permission_required("bookings.change_booking", raise_exception=True)
@require_POST
def booking_mark_cash_collected(request, reference):
    """Mark a cash booking's awaiting-collection payment as collected."""
    booking = get_object_or_404(Booking, reference=reference)
    payment = booking.payments.filter(
        provider=Payment.Provider.CASH,
    ).exclude(status=Payment.Status.SUCCEEDED).first()
    if payment is None:
        messages.info(request, "No cash payment is awaiting collection.")
    else:
        payment.status = Payment.Status.SUCCEEDED
        payment.save(update_fields=["status"])
        BookingStatusChange.objects.create(
            booking=booking, from_status=booking.status, to_status=booking.status,
            changed_by=request.user, note=f"Cash collected (${payment.amount:.2f}).",
        )
        messages.success(request, f"Cash of ${payment.amount:.2f} marked collected.")
    return redirect("dashboard:booking_detail", reference=reference)


@login_required(login_url="dashboard:login")
@permission_required("bookings.add_booking", raise_exception=True)
@require_POST
def booking_quote(request):
    """Live fare preview for the New Booking form -- same engine as the website."""
    post = request.POST
    vehicle = Vehicle.objects.filter(pk=post.get("vehicle") or 0, is_active=True).first()
    route = CityRoute.objects.filter(pk=post.get("city_route") or 0, is_active=True).first()
    pickup_at = parse_datetime(post.get("pickup_at") or "")
    if pickup_at and timezone.is_naive(pickup_at):
        pickup_at = timezone.make_aware(pickup_at)
    try:
        hours = Decimal(post["hours"]) if post.get("hours") else None
    except (InvalidOperation, KeyError):
        hours = None
    try:
        q, distance, _ = _quote_manual(
            post.get("trip_mode", "transfer"), vehicle,
            pickup_at=pickup_at or timezone.now(),
            pickup_address=post.get("pickup_address", ""),
            dropoff_address=post.get("dropoff_address", ""),
            hours=hours, city_route=route,
            meet_and_greet=post.get("meet_and_greet") in ("on", "true", "True", "1"),
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)})
    return JsonResponse({
        "ok": True,
        "total": f"{q.total:.2f}",
        "currency": q.currency,
        "distance_miles": f"{distance:.1f}" if distance is not None else None,
        "lines": [{"label": line.label, "amount": f"{line.amount:.2f}"} for line in q.lines],
    })


@login_required(login_url="dashboard:login")
@permission_required("bookings.add_booking", raise_exception=True)
def booking_create(request):
    """
    Manual booking entry for phone / walk-in customers.

    The fare is computed by the pricing engine (same as the website) from the
    trip type and its inputs; staff may override the total for a negotiated
    price, which is recorded on the audit trail. Stored like a web booking --
    reference, real fare breakdown, audit row -- so the detail view and receipt
    read the same.
    """
    maps_key = SiteSettings.load().google_maps_api_key or getattr(settings, "GOOGLE_MAPS_API_KEY", "")
    stripe_pk = gateway.publishable_key()

    if request.method == "POST":
        form = ManualBookingForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            mode = cd["trip_mode"]
            override = cd.get("override_total")
            try:
                priced, distance, route = _quote_manual(
                    mode, cd["vehicle"],
                    pickup_at=cd["pickup_at"],
                    pickup_address=cd.get("pickup_address", ""),
                    dropoff_address=cd.get("dropoff_address", ""),
                    hours=cd.get("hours"),
                    city_route=cd.get("city_route"),
                    meet_and_greet=cd.get("meet_and_greet", False),
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                pay_method = request.POST.get("payment_method", "cash")
                pm_id = (request.POST.get("stripe_payment_method_id") or "").strip()
                charged = False
                new_customer = False
                try:
                    with transaction.atomic():
                        booking = form.save(commit=False)
                        # Attach the customer: an existing account (picked in the
                        # search or matched by email) or a new one created here.
                        customer, new_customer = _resolve_customer(cd)
                        booking.customer = customer
                        booking.trip_type = (
                            Booking.TripType.HOURLY if mode == "hourly"
                            else Booking.TripType.TRANSFER
                        )
                        booking.city_route = route
                        booking.distance_miles = distance
                        booking.hours = cd.get("hours") if mode == "hourly" else None
                        booking.currency = priced.currency
                        if override is not None:
                            booking.subtotal = override
                            booking.surcharge_total = Decimal("0.00")
                            booking.tax = Decimal("0.00")
                            booking.total = override
                        else:
                            booking.subtotal = priced.subtotal
                            booking.surcharge_total = priced.surcharge_total
                            booking.tax = priced.tax
                            booking.total = priced.total
                        booking.save()

                        if override is not None:
                            BookingPriceLine.objects.create(
                                booking=booking, kind=BookingPriceLine.Kind.BASE,
                                label="Fare (agreed by staff)", amount=override, ordering=0,
                            )
                        else:
                            for line in priced.as_price_lines(booking):
                                line.save()

                        note = "Created manually in the back office"
                        if override is not None:
                            note += f" (fare set to ${override:.2f})"
                        BookingStatusChange.objects.create(
                            booking=booking, from_status="", to_status=booking.status,
                            changed_by=request.user, note=note,
                        )
                        if pay_method == "card":
                            if booking.customer is None:
                                raise gateway.PaymentGatewayError(
                                    "Charging a card needs a customer — search for one "
                                    "above, or add an email so the card can be saved."
                                )
                            if not pm_id:
                                raise gateway.PaymentGatewayError("No card was entered.")
                            payment, pstatus = gateway.charge_booking_with_payment_method(
                                booking, pm_id, save_for=booking.customer,
                            )
                            if pstatus == "succeeded":
                                BookingStatusChange.objects.create(
                                    booking=booking, from_status=booking.status,
                                    to_status=Booking.Status.CONFIRMED, changed_by=request.user,
                                    note=f"Card charged ${booking.total:.2f} ({payment.masked_card}) — saved on file",
                                )
                                booking.status = Booking.Status.CONFIRMED
                                booking.save(update_fields=["status", "updated_at"])
                                charged = True
                            else:
                                raise gateway.PaymentGatewayError(
                                    f"the card needs extra authentication ({pstatus}); "
                                    "use a different card or take cash"
                                )
                        elif pay_method == "saved":
                            if booking.customer is None:
                                raise gateway.PaymentGatewayError("A saved card belongs to a customer — link one first.")
                            card = SavedCard.objects.filter(
                                customer=booking.customer, pk=request.POST.get("saved_card_id") or 0
                            ).first()
                            if card is None:
                                raise gateway.PaymentGatewayError("Choose a saved card to charge.")
                            payment = gateway.charge_saved_card(
                                card, booking.total, f"Booking {booking.reference} (counter)", booking=booking,
                            )
                            if payment.status == Payment.Status.SUCCEEDED:
                                BookingStatusChange.objects.create(
                                    booking=booking, from_status=booking.status,
                                    to_status=Booking.Status.CONFIRMED, changed_by=request.user,
                                    note=f"Charged saved card {card.brand} ••{card.last4} ${booking.total:.2f}",
                                )
                                booking.status = Booking.Status.CONFIRMED
                                booking.save(update_fields=["status", "updated_at"])
                                charged = True
                            else:
                                raise gateway.PaymentGatewayError(
                                    f"the saved card charge did not complete ({payment.status})."
                                )
                        else:  # cash -- record an awaiting-collection payment so it reconciles
                            Payment.objects.create(
                                booking=booking,
                                provider=Payment.Provider.CASH,
                                amount=booking.total,
                                currency=booking.currency,
                                status=Payment.Status.PROCESSING,
                            )
                except (gateway.PaymentConfigurationError, gateway.PaymentGatewayError) as exc:
                    messages.error(request, f"Card payment failed: {exc}. The booking was not created.")
                else:
                    if booking.status == Booking.Status.CONFIRMED:
                        from notifications.events import booking_confirmed
                        booking_confirmed(booking, notify_ops=False)
                    if charged:
                        messages.success(
                            request,
                            f"Booking {booking.reference} created and card charged ${booking.total:.2f}.",
                        )
                    else:
                        messages.success(request, f"Booking {booking.reference} created.")
                    if new_customer:
                        messages.info(
                            request,
                            f"New customer account created for {booking.customer.email}.",
                        )
                    return redirect("dashboard:booking_detail", reference=booking.reference)
    else:
        form = ManualBookingForm()

    return render(request, "dashboard/booking_form.html", {
        "form": form, "maps_key": maps_key, "stripe_pk": stripe_pk,
    })


@login_required(login_url="dashboard:login")
@permission_required("bookings.change_booking", raise_exception=True)
def booking_edit(request, reference):
    """
    Edit an existing booking's trip details, contact and fare.

    Status and driver stay with the control on the detail page (it records a
    proper transition). If the fare is changed, the stored breakdown is replaced
    with a single "adjusted" line so the total always matches its lines. Every
    edit writes an audit row naming the fields that changed and the acting user.
    """
    booking = get_object_or_404(Booking, reference=reference)
    if request.method == "POST":
        form = BookingEditForm(request.POST, instance=booking)
        if form.is_valid():
            if not form.changed_data:
                messages.info(request, "Nothing changed.")
                return redirect("dashboard:booking_detail", reference=reference)
            with transaction.atomic():
                total_changed = "total" in form.changed_data
                booking = form.save(commit=False)
                # Cascade: the vehicle name is snapshotted at creation and the
                # model only fills it when blank, so a vehicle change here would
                # otherwise leave the old name on the detail view and receipt.
                if "vehicle" in form.changed_data and booking.vehicle_id:
                    booking.vehicle_name_snapshot = booking.vehicle.name
                # Cascade: keep the fare breakdown consistent with a new total.
                if total_changed:
                    booking.subtotal = booking.total
                    booking.surcharge_total = Decimal("0.00")
                    booking.tax = Decimal("0.00")
                booking.save()
                if total_changed:
                    booking.price_lines.all().delete()
                    BookingPriceLine.objects.create(
                        booking=booking,
                        kind=BookingPriceLine.Kind.BASE,
                        label="Fare (adjusted by staff)",
                        amount=booking.total,
                        ordering=0,
                    )
                BookingStatusChange.objects.create(
                    booking=booking,
                    from_status=booking.status,
                    to_status=booking.status,
                    changed_by=request.user,
                    note="Details edited: " + ", ".join(form.changed_data),
                )
            messages.success(request, f"{booking.reference} updated.")
            return redirect("dashboard:booking_detail", reference=reference)
    else:
        form = BookingEditForm(instance=booking)
    maps_key = SiteSettings.load().google_maps_api_key or getattr(settings, "GOOGLE_MAPS_API_KEY", "")
    return render(request, "dashboard/booking_form.html",
                  {"form": form, "booking": booking, "maps_key": maps_key})


@staff_required
@require_POST
def booking_update(request, reference):
    """
    Change status and/or driver.

    Every status transition writes an audit row naming the acting user -- the
    thing a single shared admin login made impossible.
    """
    booking = get_object_or_404(Booking, reference=reference)
    changed: list[str] = []
    status_changed = False
    driver_changed = False

    new_status = request.POST.get("status", "").strip()
    if new_status and new_status != booking.status:
        valid = {value for value, _ in Booking.Status.choices}
        if new_status not in valid:
            messages.error(request, f"Unknown status {new_status!r}.")
            return redirect("dashboard:booking_detail", reference=reference)

        BookingStatusChange.objects.create(
            booking=booking,
            from_status=booking.status,
            to_status=new_status,
            changed_by=request.user,
            note=request.POST.get("note", "").strip(),
        )
        previous = booking.get_status_display()
        booking.status = new_status
        if new_status == Booking.Status.CANCELLED and not booking.cancelled_at:
            booking.cancelled_at = timezone.now()
            booking.cancellation_reason = request.POST.get("note", "").strip()
        changed.append(f"status {previous} → {booking.get_status_display()}")
        status_changed = True

    driver_id = request.POST.get("driver", "").strip()
    if driver_id != str(booking.driver_id or ""):
        booking.driver = Driver.objects.filter(pk=driver_id).first() if driver_id else None
        changed.append(
            f"driver → {booking.driver.full_name}" if booking.driver else "driver cleared"
        )
        driver_changed = True

    if changed:
        booking.save()

        if driver_changed and booking.driver:
            mailer.send_driver_assigned(booking)
        if booking.status == Booking.Status.CANCELLED and status_changed:
            mailer.send_booking_cancelled(booking)

        messages.success(request, f"{booking.reference}: " + "; ".join(changed))
    else:
        messages.info(request, "Nothing changed.")

    return redirect(request.POST.get("next") or "dashboard:booking_detail",
                    reference=reference)


@staff_required
def charge_card(request):
    """
    Charge a customer's card on file off-session -- e.g. billing a trip
    extension agreed after pickup. Manager-only: it takes money off a card.
    """
    if not is_manager(request.user):
        raise PermissionDenied("Only managers can charge a card on file.")

    if request.method == "POST":
        form = ChargeCardForm(request.POST)
        if form.is_valid():
            customer = form.cleaned_data["customer"]
            card = (
                customer.saved_cards.filter(is_default=True).first()
                or customer.saved_cards.first()
            )
            if card is None:
                messages.error(request, "That customer has no card on file.")
            else:
                try:
                    payment = gateway.charge_saved_card(
                        card, form.cleaned_data["amount"], form.cleaned_data["description"],
                    )
                    messages.success(
                        request,
                        f"Charged {card.label} ${form.cleaned_data['amount']:.2f} — "
                        f"{payment.get_status_display()}.",
                    )
                    return redirect("dashboard:charge_card")
                except gateway.PaymentConfigurationError as exc:
                    messages.error(request, f"Card payments aren’t set up: {exc}")
                except gateway.PaymentGatewayError as exc:
                    messages.error(request, f"Charge failed: {exc}")
    else:
        form = ChargeCardForm()

    has_any_cards = SavedCard.objects.exists()
    return render(request, "dashboard/charge_card.html",
                  {"form": form, "has_any_cards": has_any_cards})


@staff_required
def enquiry_inbox(request):
    enquiries = ContactMessage.objects.all()

    state = request.GET.get("state", "unread")
    if state == "unread":
        enquiries = enquiries.filter(is_read=False)
    elif state == "unanswered":
        enquiries = enquiries.filter(replied_at__isnull=True)

    nature = request.GET.get("nature", "").strip()
    if nature:
        enquiries = enquiries.filter(nature=nature)

    paginator = Paginator(enquiries, ENQUIRIES_PER_PAGE)
    page = paginator.get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)
    querystring = params.urlencode()

    context = {
        "enquiries": page.object_list,
        "page": page,
        "paginator": paginator,
        "page_range": paginator.get_elided_page_range(
            page.number, on_each_side=2, on_ends=1,
        ),
        "total": paginator.count,
        "querystring": f"&{querystring}" if querystring else "",
        "counts": ContactMessage.objects.aggregate(
            all=Count("id"),
            unread=Count("id", filter=Q(is_read=False)),
            unanswered=Count("id", filter=Q(replied_at__isnull=True)),
        ),
        "natures": ContactMessage.Nature.choices,
        "state": state,
        "nature": nature,
        "roles": role_names(request.user),
    }
    return render(request, "dashboard/enquiries.html", context)


@staff_required
def enquiry_detail(request, pk):
    enquiry = get_object_or_404(ContactMessage, pk=pk)

    if request.method == "POST":
        reply = request.POST.get("reply", "").strip()
        if reply:
            enquiry.reply_body = reply
            enquiry.replied_at = timezone.now()
            enquiry.replied_by = request.user
            enquiry.is_read = True
            enquiry.save()
            messages.success(request, "Reply recorded.")
            return redirect("dashboard:enquiries")
        messages.error(request, "Write a reply first.")

    if not enquiry.is_read:
        enquiry.is_read = True
        enquiry.save(update_fields=["is_read"])

    return render(request, "dashboard/enquiry_detail.html",
                  {"enquiry": enquiry, "roles": role_names(request.user)})


def _export_csv(bookings) -> HttpResponse:
    response = HttpResponse(content_type="text/csv")
    stamp = timezone.now().strftime("%Y%m%d-%H%M")
    response["Content-Disposition"] = f'attachment; filename="bookings-{stamp}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        "Reference", "Pickup (local)", "Status", "Customer", "Email", "Phone",
        "Vehicle", "Driver", "Pickup address", "Dropoff address",
        "Distance (mi)", "Hours", "Total", "Currency",
    ])
    for booking in bookings.iterator(chunk_size=500):
        writer.writerow([
            booking.reference,
            timezone.localtime(booking.pickup_at).strftime("%Y-%m-%d %H:%M"),
            booking.get_status_display(),
            booking.customer_name,
            booking.customer.email if booking.customer else "",
            booking.customer.phone if booking.customer else "",
            booking.vehicle_name_snapshot,
            booking.driver.full_name if booking.driver else "",
            booking.pickup_address,
            booking.dropoff_address,
            booking.distance_miles or "",
            booking.hours or "",
            booking.total,
            booking.currency,
        ])
    return response


@staff_required
@permission_required("payments.change_paymentsettings", raise_exception=True)
def payment_settings(request):
    """
    Stripe credentials, editable by a Manager.

    Restricted beyond ordinary dashboard access: these keys authorise charges
    and refunds against the real account, so a Dispatcher must not reach them.
    """
    if not is_manager(request.user):
        raise PermissionDenied("Only managers can change payment settings.")

    instance = PaymentSettings.load()

    if request.method == "POST":
        form = PaymentSettingsForm(request.POST, instance=instance)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.updated_by = request.user
            updated.save()

            changed = [
                form.fields[name].label or name.replace("_", " ")
                for name in form.changed_data
            ]
            logger.info(
                "Payment settings updated by %s (fields: %s)",
                request.user.email, ", ".join(form.changed_data) or "none",
            )
            messages.success(
                request,
                "Payment settings saved." + (f" Changed: {', '.join(changed)}." if changed else ""),
            )
            return redirect("dashboard:payment_settings")
        messages.error(request, "Please correct the errors below.")
    else:
        form = PaymentSettingsForm(instance=instance)

    context = {
        "form": form,
        "settings_obj": instance,
        "roles": role_names(request.user),
        "is_manager": True,
        "webhook_url": request.build_absolute_uri("/api/payments/webhook/"),
    }
    return render(request, "dashboard/payment_settings.html", context)


@staff_required
@require_POST
@permission_required("payments.add_refund", raise_exception=True)
def issue_refund(request, reference):
    """
    Refund a booking's payment, in full or in part.

    Manager only, and always attributed: the legacy single shared admin login
    made it impossible to say who refunded what.
    """
    booking = get_object_or_404(Booking, reference=reference)
    payment = booking.payments.filter(status=Payment.Status.SUCCEEDED).first()

    if payment is None:
        messages.error(request, "There is no successful payment to refund.")
        return redirect("dashboard:booking_detail", reference=reference)

    raw_amount = (request.POST.get("amount") or "").strip()
    reason = (request.POST.get("reason") or "").strip()

    try:
        amount = Decimal(raw_amount) if raw_amount else None
    except InvalidOperation:
        messages.error(request, f"{raw_amount!r} is not a valid amount.")
        return redirect("dashboard:booking_detail", reference=reference)

    try:
        refund = gateway.refund(
            payment, amount=amount, reason=reason, created_by=request.user,
        )
    except (gateway.PaymentConfigurationError, gateway.PaymentGatewayError) as exc:
        messages.error(request, str(exc))
        return redirect("dashboard:booking_detail", reference=reference)

    logger.info(
        "Refund %s of %s on %s issued by %s",
        refund.stripe_refund_id, refund.amount, booking.reference, request.user.email,
    )
    messages.success(
        request, f"Refunded {refund.amount} {payment.currency} on {booking.reference}.",
    )
    return redirect("dashboard:booking_detail", reference=reference)


@staff_required
@permission_required("notifications.change_emailsettings", raise_exception=True)
def email_settings(request):
    """SMTP credentials and a way to prove they work."""
    if not is_manager(request.user):
        raise PermissionDenied("Only managers can change email settings.")

    instance = EmailSettings.load()

    if request.method == "POST" and request.POST.get("action") == "test":
        recipient = (request.POST.get("test_email") or request.user.email).strip()
        ok, error = mailer.send_test_message(recipient)
        if ok:
            messages.success(request, f"Test message sent to {recipient}.")
        else:
            messages.error(request, f"Test message failed: {error}")
        return redirect("dashboard:email_settings")

    if request.method == "POST":
        form = EmailSettingsForm(request.POST, instance=instance)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.updated_by = request.user
            updated.save()
            logger.info(
                "Email settings updated by %s (fields: %s)",
                request.user.email, ", ".join(form.changed_data) or "none",
            )
            messages.success(request, "Email settings saved.")
            return redirect("dashboard:email_settings")
        messages.error(request, "Please correct the errors below.")
    else:
        form = EmailSettingsForm(instance=instance)

    return render(request, "dashboard/email_settings.html", {
        "form": form,
        "settings_obj": instance,
        "recent": EmailLog.objects.all()[:15],
        "failures": EmailLog.objects.filter(succeeded=False).count(),
    })


@staff_required
@permission_required("notifications.change_smssettings", raise_exception=True)
def sms_settings(request):
    """Twilio credentials, toggles, and a way to prove they work."""
    if not is_manager(request.user):
        raise PermissionDenied("Only managers can change SMS settings.")

    instance = SmsSettings.load()

    if request.method == "POST" and request.POST.get("action") == "test":
        recipient = (request.POST.get("test_number") or "").strip()
        if not recipient:
            messages.error(request, "Enter a phone number to send a test to.")
        else:
            ok, error = sms.send_test_message(recipient)
            if ok:
                messages.success(request, f"Test text sent to {recipient}.")
            else:
                messages.error(request, f"Test text failed: {error or 'SMS not configured.'}")
        return redirect("dashboard:sms_settings")

    if request.method == "POST":
        form = SmsSettingsForm(request.POST, instance=instance)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.updated_by = request.user
            updated.save()
            logger.info(
                "SMS settings updated by %s (fields: %s)",
                request.user.email, ", ".join(form.changed_data) or "none",
            )
            messages.success(request, "SMS settings saved.")
            return redirect("dashboard:sms_settings")
        messages.error(request, "Please correct the errors below.")
    else:
        form = SmsSettingsForm(instance=instance)

    return render(request, "dashboard/sms_settings.html", {
        "form": form,
        "settings_obj": instance,
        "recent": SmsLog.objects.all()[:15],
        "failures": SmsLog.objects.filter(succeeded=False).count(),
    })


@staff_required
@permission_required("payments.change_paypalsettings", raise_exception=True)
def paypal_settings(request):
    """
    PayPal credentials, editable by a Manager.

    The checkout flow is not wired up -- Stripe is the working gateway. These
    credentials are stored and verifiable so PayPal can be enabled without a
    deployment when the integration lands.
    """
    if not is_manager(request.user):
        raise PermissionDenied("Only managers can change payment settings.")

    instance = PayPalSettings.load()

    if request.method == "POST" and request.POST.get("action") == "test":
        ok, message = paypal.verify_credentials(instance)
        if ok:
            messages.success(request, message)
        else:
            messages.error(request, message)
        return redirect("dashboard:paypal_settings")

    if request.method == "POST":
        form = PayPalSettingsForm(request.POST, instance=instance)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.updated_by = request.user
            updated.save()
            logger.info(
                "PayPal settings updated by %s (fields: %s)",
                request.user.email, ", ".join(form.changed_data) or "none",
            )
            messages.success(request, "PayPal settings saved.")
            return redirect("dashboard:paypal_settings")
        messages.error(request, "Please correct the errors below.")
    else:
        form = PayPalSettingsForm(instance=instance)

    return render(request, "dashboard/paypal_settings.html", {
        "form": form,
        "settings_obj": instance,
        "webhook_url": request.build_absolute_uri("/api/payments/paypal/webhook/"),
    })


# -- managed records --------------------------------------------------------
#
# The generic screens that replace Django's admin. One set of views drives every
# entry in dashboard.managed, so a new manageable model is a registry entry
# rather than four more views that can drift out of step.


MANAGED_PER_PAGE = 50


def _managed_or_404(slug: str) -> crud.Managed:
    entry = crud.get(slug)
    if entry is None:
        raise Http404(f"Nothing manageable is registered as {slug!r}")
    return entry


@staff_required
def managed_list(request, slug):
    entry = _managed_or_404(slug)
    if not (request.user.has_perm(entry.view_permission)
            or request.user.has_perm(entry.permission)):
        raise PermissionDenied(f"You do not have access to {entry.label_plural}.")

    query = request.GET.get("q", "").strip()
    queryset = managed.staff_queryset_filter(slug, entry.queryset())
    queryset = entry.search(queryset, query)

    paginator = Paginator(queryset, MANAGED_PER_PAGE)
    page = paginator.get_page(request.GET.get("page"))

    params = request.GET.copy()
    params.pop("page", None)
    querystring = params.urlencode()

    rows = [
        {
            "instance": instance,
            "pk": instance.pk,
            "cells": [
                {
                    "value": column.resolve(instance),
                    "sub": column.resolve_sub(instance),
                    "align_end": column.align_end,
                    "boolean": column.boolean,
                }
                for column in entry.columns
            ],
        }
        for instance in page.object_list
    ]

    return render(request, "dashboard/managed_list.html", {
        "entry": entry,
        "rows": rows,
        "page": page,
        "paginator": paginator,
        "page_range": paginator.get_elided_page_range(
            page.number, on_each_side=2, on_ends=1,
        ),
        "total": paginator.count,
        "querystring": f"&{querystring}" if querystring else "",
        "query": query,
        "can_edit": request.user.has_perm(entry.permission),
        "roles": role_names(request.user),
        "is_manager": is_manager(request.user),
    })


@staff_required
def managed_edit(request, slug, pk=None):
    entry = _managed_or_404(slug)
    if not request.user.has_perm(entry.permission):
        raise PermissionDenied(f"You cannot change {entry.label_plural}.")

    queryset = managed.staff_queryset_filter(slug, entry.model._default_manager.all())
    instance = get_object_or_404(queryset, pk=pk) if pk else None

    formset = None
    if request.method == "POST":
        form = entry.form_class(request.POST, request.FILES, instance=instance)
        if entry.inline_formset:
            formset = entry.inline_formset(
                request.POST, instance=instance or entry.model(),
            )

        if form.is_valid() and (formset is None or formset.is_valid()):
            with transaction.atomic():
                saved = form.save()
                if formset is not None:
                    formset.instance = saved
                    formset.save()

            logger.info(
                "%s %s %s by %s",
                entry.label, saved.pk, "created" if pk is None else "updated",
                request.user.email,
            )
            messages.success(
                request,
                f"{entry.label} “{saved}” {'created' if pk is None else 'saved'}.",
            )
            return redirect("dashboard:managed_list", slug=slug)

        messages.error(request, "Please correct the errors below.")
    else:
        form = entry.form_class(instance=instance)
        if entry.inline_formset:
            formset = entry.inline_formset(instance=instance or entry.model())

    return render(request, "dashboard/managed_form.html", {
        "entry": entry,
        "form": form,
        "formset": formset,
        "instance": instance,
        "roles": role_names(request.user),
        "is_manager": is_manager(request.user),
    })


@staff_required
@require_POST
def managed_delete(request, slug, pk):
    entry = _managed_or_404(slug)
    if not entry.can_delete:
        raise PermissionDenied(
            f"{entry.label_plural} are deactivated rather than deleted."
        )
    if not request.user.has_perm(entry.permission):
        raise PermissionDenied(f"You cannot change {entry.label_plural}.")

    instance = get_object_or_404(entry.model._default_manager.all(), pk=pk)
    label = str(instance)

    try:
        instance.delete()
    except ProtectedError:
        messages.error(
            request,
            f"“{label}” is still referenced by existing records and cannot be "
            f"deleted. Deactivate it instead.",
        )
        return redirect("dashboard:managed_list", slug=slug)

    logger.info("%s %s deleted by %s", entry.label, label, request.user.email)
    messages.success(request, f"{entry.label} “{label}” deleted.")
    return redirect("dashboard:managed_list", slug=slug)


@staff_required
@permission_required("content.change_sitesettings", raise_exception=True)
def site_settings(request):
    """Contact details and social links shown on the public site."""
    instance = SiteSettings.load()

    if request.method == "POST":
        form = SiteSettingsForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            logger.info("Site settings updated by %s", request.user.email)
            messages.success(request, "Site settings saved.")
            return redirect("dashboard:site_settings")
        messages.error(request, "Please correct the errors below.")
    else:
        form = SiteSettingsForm(instance=instance)

    return render(request, "dashboard/site_settings.html", {
        "form": form,
        "settings_obj": instance,
        "roles": role_names(request.user),
        "is_manager": is_manager(request.user),
    })


@staff_required
@permission_required("pricing.change_pricingsettings", raise_exception=True)
def pricing_settings(request):
    """
    Tax, currency and the two windows that govern quotes and cancellations.

    Manager only, and worth the extra care: the tax rate applies to every future
    quote, so a mistyped figure misprices the entire fleet at once.
    """
    if not is_manager(request.user):
        raise PermissionDenied("Only managers can change pricing settings.")

    instance = PricingSettings.load()

    if request.method == "POST":
        form = PricingSettingsForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            logger.info(
                "Pricing settings updated by %s (fields: %s)",
                request.user.email, ", ".join(form.changed_data) or "none",
            )
            messages.success(request, "Pricing settings saved.")
            return redirect("dashboard:pricing_settings")
        messages.error(request, "Please correct the errors below.")
    else:
        form = PricingSettingsForm(instance=instance)

    return render(request, "dashboard/pricing_settings.html", {
        "form": form,
        "settings_obj": instance,
        "roles": role_names(request.user),
        "is_manager": True,
    })


# -- driver app access ------------------------------------------------------

def _driver_access_state(driver):
    """How a driver stands re: the mobile app, for the access screen."""
    if not driver.email:
        return "no_email"
    if not driver.user_id:
        return "not_invited"
    return "active" if driver.user.has_usable_password() else "invited"


@login_required(login_url="dashboard:login")
@permission_required("bookings.change_driver", raise_exception=True)
def driver_access(request):
    """
    Give drivers a login for the mobile driver app.

    Provisioning links the Driver to a (non-staff) User and sends the standard
    password-set link -- the same reset flow migrated customers use, so there is
    no second password mechanism to secure. A driver with no email can't be
    invited until one is added on their record.
    """
    from django.contrib.auth.tokens import default_token_generator

    from accounts.forms import MigrationPasswordResetForm
    from accounts.models import User

    if request.method == "POST":
        driver = get_object_or_404(Driver, pk=request.POST.get("driver_id"))
        if not driver.email:
            messages.error(request, f"Add an email to {driver.full_name} first.")
            return redirect("dashboard:driver_access")

        with transaction.atomic():
            if not driver.user_id:
                email = driver.email.strip().lower()
                user = User.objects.filter(email__iexact=email).first()
                if user is None:
                    parts = driver.full_name.split()
                    user = User(
                        email=email, is_staff=False, is_active=True,
                        first_name=parts[0] if parts else "",
                        last_name=" ".join(parts[1:]),
                        phone=driver.phone or "",
                    )
                    user.set_unusable_password()
                    user.save()
                driver.user = user
                driver.save(update_fields=["user"])

        form = MigrationPasswordResetForm({"email": driver.user.email})
        if form.is_valid():
            form.save(
                request=request,
                use_https=request.is_secure(),
                token_generator=default_token_generator,
                subject_template_name="accounts/email/password_reset_subject.txt",
                email_template_name="accounts/email/password_reset.txt",
                html_email_template_name="accounts/email/password_reset.html",
            )
        messages.success(
            request,
            f"Sent {driver.full_name} a sign-in setup link at {driver.user.email}.",
        )
        return redirect("dashboard:driver_access")

    drivers = Driver.objects.select_related("user").filter(is_active=True)
    rows = [{"driver": d, "state": _driver_access_state(d)} for d in drivers]
    return render(request, "dashboard/driver_access.html", {
        "rows": rows,
        "roles": role_names(request.user),
    })
