"""
Public API consumed by the Next.js frontend.

Two rules run through everything here:

  1. The server computes prices. No endpoint accepts a money value.
  2. A customer sees their own bookings and nobody else's. Legacy exposed
     `direct-payment.php?orderID=` with no authentication at all, which is how
     the orders table became readable by anyone.
"""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from config.session import scoped_ensure_csrf_cookie
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, ScopedRateThrottle

from accounts.forms import MigrationPasswordResetForm
from accounts.models import LoginCode
from bookings.models import Booking, BookingStatusChange
from content.models import Page, SiteSettings
from enquiries.models import ContactMessage
from fleet.models import Vehicle
from notifications import mailer
from notifications.pdf import render_booking_pdf
from payments import gateway as payments_gateway
from payments.models import SavedCard
from pricing.distance import DistanceLookupError
from pricing.distance import lookup as measure_journey
from pricing.engine import QuoteError, priced_city_to_city, quote_all
from pricing.models import BlackoutDate, TimeSurcharge

from . import quotes
from .serializers import (
    AvailabilitySerializer,
    BookingAmendSerializer,
    BookingCreateSerializer,
    BookingSerializer,
    BookingStatusSerializer,
    CancelBookingSerializer,
    DetailSerializer,
    EnquirySerializer,
    LoginRequestSerializer,
    PageSerializer,
    PasswordResetRequestSerializer,
    QuoteRequestSerializer,
    QuoteResponseSerializer,
    RegisterRequestSerializer,
    SavedCardSerializer,
    SendCodeRequestSerializer,
    SiteSettingsSerializer,
    UserSerializer,
    VehicleSerializer,
    VerifyCodeRequestSerializer,
)

User = get_user_model()


def money(value) -> str:
    """
    Render a monetary amount as a fixed-precision string.

    JSON has no decimal type, so a Decimal rendered by the default encoder
    becomes a float -- 145.10 arrives as 145.1, and anything a client computes
    from it inherits binary rounding error. Money crosses this boundary as a
    string, always.
    """
    return f"{Decimal(value):.2f}"


class QuoteThrottle(ScopedRateThrottle):
    scope = "quote"


class EnquiryThrottle(ScopedRateThrottle):
    scope = "enquiry"


class LoginCodeSendThrottle(ScopedRateThrottle):
    scope = "login_code_send"


class LoginCodeVerifyThrottle(ScopedRateThrottle):
    scope = "login_code_verify"


# -- content ---------------------------------------------------------------


@extend_schema(
    tags=["content"],
    summary="Fetch one published page",
    description="Content and SEO metadata for a CMS page. Unpublished pages 404.",
    parameters=[OpenApiParameter("slug", str, OpenApiParameter.PATH,
                                 description='URL slug, e.g. "fleet".')],
    responses={200: PageSerializer, 404: DetailSerializer},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def page_detail(request, slug):
    page = Page.objects.filter(slug=slug, is_published=True).first()
    if page is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(PageSerializer(page).data)


@extend_schema(
    tags=["content"],
    summary="List published pages",
    description="Every published page. Use this to build navigation and a sitemap.",
    responses={200: PageSerializer(many=True)},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def page_list(request):
    pages = Page.objects.filter(is_published=True)
    return Response(PageSerializer(pages, many=True).data)


@extend_schema(
    tags=["content"],
    summary="Site-wide contact details and social links",
    description="What the header and footer display. Staff edit these in the "
                "admin, so a changed phone number does not need a deploy.",
    responses={200: SiteSettingsSerializer},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def site_settings(request):
    """
    The singleton settings row.

    `load()` rather than a query: the row may not exist yet on a fresh install,
    and a frontend header that 500s because nobody has opened the admin page is
    a worse failure than empty contact details.
    """
    return Response(SiteSettingsSerializer(SiteSettings.load()).data)


@extend_schema(
    tags=["content"],
    summary="List bookable vehicles",
    description="Active vehicles only. Per-mile rates are not exposed — fares "
                "come from the quote endpoint so they cannot be recomputed "
                "(or disputed) client-side.",
    responses={200: VehicleSerializer(many=True)},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def vehicle_list(request):
    vehicles = Vehicle.objects.filter(is_active=True).prefetch_related("bands")
    return Response(VehicleSerializer(vehicles, many=True, context={"request": request}).data)


@extend_schema(
    tags=["content"],
    summary="Surcharge windows and blackout dates",
    description="For the date picker, so a customer can see before choosing that "
                "a late-night pickup or an event date costs more.",
    responses={200: AvailabilitySerializer},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def availability(request):
    """Blackout dates and surcharge windows, for the date picker."""
    return Response({
        "blackout_dates": [
            {"date": b.date, "name": b.name, "percentage": money(b.percentage)}
            for b in BlackoutDate.objects.filter(is_active=True)
        ],
        "time_surcharges": [
            {
                "name": s.name,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "percentage": money(s.percentage),
                "crosses_midnight": s.crosses_midnight,
            }
            for s in TimeSurcharge.objects.filter(is_active=True)
        ],
    })


# -- quoting ---------------------------------------------------------------


def _enforce_capacity(vehicle, passenger_count, luggage_count):
    """Reject counts above the vehicle's seat/bag limits. Server-side truth.

    A capacity of 0 means "not configured" rather than "seats nobody" -- it's
    the field default -- so it's treated as no limit. An operator who hasn't set
    a limit doesn't accidentally block every booking for that vehicle.
    """
    errors = {}
    if vehicle.passenger_capacity and passenger_count > vehicle.passenger_capacity:
        errors["passenger_count"] = (
            f"{vehicle.name} seats up to {vehicle.passenger_capacity} "
            f"passenger{'' if vehicle.passenger_capacity == 1 else 's'}. "
            "Please choose a larger vehicle."
        )
    if vehicle.luggage_capacity and luggage_count > vehicle.luggage_capacity:
        errors["luggage_count"] = (
            f"{vehicle.name} holds up to {vehicle.luggage_capacity} "
            f"bag{'' if vehicle.luggage_capacity == 1 else 's'}. "
            "Please choose a larger vehicle."
        )
    if errors:
        raise ValidationError(errors)


@extend_schema(
    tags=["quotes"],
    summary="Price a journey across every vehicle",
    description=(
        "Measures the journey server-side from the two addresses and returns a "
        "fare per bookable vehicle.\n\n"
        "**There is no `distance_miles` field and no price field.** A client "
        "cannot declare either. Each result carries a signed `quote_token` — "
        "present it to `POST /api/bookings/` and the fare is recomputed before "
        "anything is stored.\n\n"
        "Supply `dropoff_address` for a transfer, or `hours` for hourly hire, "
        "never both. Throttled to 30/hour."
    ),
    request=QuoteRequestSerializer,
    responses={
        200: QuoteResponseSerializer,
        400: DetailSerializer,
        422: DetailSerializer,
        429: DetailSerializer,
    },
    examples=[
        OpenApiExample(
            "Airport transfer",
            request_only=True,
            value={
                "pickup_address": "Austin-Bergstrom International Airport",
                "dropoff_address": "Downtown Austin, TX",
                "pickup_at": "2026-09-01T14:30:00-05:00",
                "meet_and_greet": True,
            },
        ),
        OpenApiExample(
            "Hourly hire",
            request_only=True,
            value={
                "pickup_address": "Downtown Austin, TX",
                "pickup_at": "2026-09-01T19:00:00-05:00",
                "hours": "3",
            },
        ),
    ],
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([QuoteThrottle])
def create_quote(request):
    """
    Price every bookable vehicle for a journey.

    Each result carries a signed token. Booking requires presenting one back;
    the fare is recomputed at that point, so a stale or edited token cannot buy
    a journey at yesterday's price.
    """
    serializer = QuoteRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    journey = None
    distance_miles = None
    city_to_city = data.get("city_to_city", False)

    if data.get("hours") is None:
        # Both a transfer and a city-to-city trip are free-form origin->destination
        # journeys measured server-side from the two addresses. The distance is
        # never accepted from the client, and there is no fallback if the lookup
        # fails -- a fallback would simply be the vulnerability behind a retry.
        try:
            journey = measure_journey(data["pickup_address"], data["dropoff_address"])
        except DistanceLookupError as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        distance_miles = journey.distance_miles

    # With city_to_city the engine prices each vehicle on its intercity rate card
    # when the vehicle offers intercity pricing and the trip is long enough,
    # otherwise it silently falls back to the normal transfer card.
    results = quote_all(
        data["pickup_at"],
        distance_miles=distance_miles,
        hours=data.get("hours"),
        meet_and_greet=data["meet_and_greet"],
        city_to_city=city_to_city,
    )

    if not results:
        return Response(
            {"detail": "No vehicle can be priced for that journey."},
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    payload = []
    for result in results:
        token = quotes.issue(quotes.QuoteRequest(
            vehicle_id=result.vehicle_id,
            pickup_at=data["pickup_at"],
            distance_miles=distance_miles,
            hours=data.get("hours"),
            meet_and_greet=data["meet_and_greet"],
            pickup_address=data["pickup_address"],
            dropoff_address=data.get("dropoff_address", ""),
            city_to_city=city_to_city,
        ))
        payload.append({
            "vehicle_id": result.vehicle_id,
            "vehicle_name": result.vehicle_name,
            "subtotal": money(result.subtotal),
            "surcharge_total": money(result.surcharge_total),
            "tax": money(result.tax),
            "total": money(result.total),
            "currency": result.currency,
            "lines": [
                {"kind": line.kind, "label": line.label, "amount": money(line.amount)}
                for line in result.lines
            ],
            "quote_token": token,
        })

    return Response({
        "journey": {
            "distance_miles": str(journey.distance_miles),
            "duration_minutes": journey.duration_minutes,
            "pickup_address": journey.resolved_origin,
            "dropoff_address": journey.resolved_destination,
        } if journey else None,
        "quotes": payload,
    })


# -- bookings --------------------------------------------------------------


@extend_schema(
    tags=["bookings"],
    summary="Create a booking from a signed quote",
    description=(
        "Redeems a `quote_token` and creates a booking in `pending` status. The "
        "fare is recomputed from the token; any amount in the request body is "
        "ignored because no such field exists.\n\n"
        "Sign in first, or supply `guest_email` for guest checkout. Take payment "
        "next via `POST /api/payments/intent/`."
    ),
    request=BookingCreateSerializer,
    responses={201: BookingSerializer, 400: DetailSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def create_booking(request):
    """Create a pending booking from a signed quote."""
    serializer = BookingCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    try:
        quote_request, recomputed = quotes.redeem(data["quote_token"])
    except quotes.QuoteTokenError as exc:
        raise ValidationError({"quote_token": str(exc)}) from exc

    customer = request.user if request.user.is_authenticated else None
    if customer is None and not data.get("guest_email"):
        raise ValidationError(
            {"guest_email": "Sign in or provide an email address for the booking."}
        )
    # A contact phone is mandatory. Signed-in bookings take it from the account
    # (set on the Details step); guests must supply one here.
    if customer is None and not data.get("guest_phone"):
        raise ValidationError(
            {"guest_phone": "A contact phone number is required."}
        )

    vehicle = Vehicle.objects.get(pk=quote_request.vehicle_id)

    # The vehicle's seat/bag limits are a hard constraint, not a hint: a quote
    # token can be replayed with any counts, so enforce them here on the server.
    _enforce_capacity(vehicle, data["passenger_count"], data["luggage_count"])

    with transaction.atomic():
        booking = Booking.objects.create(
            customer=customer,
            vehicle=vehicle,
            trip_type=(
                Booking.TripType.HOURLY
                if quote_request.hours is not None
                else Booking.TripType.TRANSFER
            ),
            status=Booking.Status.PENDING,
            pickup_address=quote_request.pickup_address,
            dropoff_address=quote_request.dropoff_address,
            pickup_at=quote_request.pickup_at,
            distance_miles=quote_request.distance_miles,
            hours=quote_request.hours,
            meet_and_greet=quote_request.meet_and_greet,
            # Persist whether the intercity card ACTUALLY priced this trip, not the
            # mode the customer selected: a city-to-city trip below the vehicle's
            # minimum distance was charged on the normal transfer card, so the
            # marker stays False and a later reprice() reproduces the same fare.
            is_city_to_city=priced_city_to_city(
                vehicle,
                distance_miles=quote_request.distance_miles,
                city_to_city=quote_request.city_to_city,
            ),
            passenger_count=data["passenger_count"],
            luggage_count=data["luggage_count"],
            flight_number=data.get("flight_number", ""),
            pickup_sign=data.get("pickup_sign") or data.get("guest_name", ""),
            notes=data.get("notes", ""),
            guest_email=data.get("guest_email", "") if customer is None else "",
            guest_phone=data.get("guest_phone", "") if customer is None else "",
            # Every figure below comes from the server-side recomputation.
            subtotal=recomputed.subtotal,
            surcharge_total=recomputed.surcharge_total,
            tax=recomputed.tax,
            total=recomputed.total,
            currency=recomputed.currency,
        )
        for line in recomputed.as_price_lines(booking):
            line.save()

        BookingStatusChange.objects.create(
            booking=booking, from_status="", to_status=booking.status,
            note="Created via website",
        )

    return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["bookings"],
    summary="Confirmation status for one booking",
    description=(
        "Whether a booking has been confirmed, for the page shown after "
        "payment.\n\n"
        "Card payments are confirmed by Stripe's webhook, not by the browser, "
        "so the confirmation page polls this until the status turns "
        "`confirmed`.\n\n"
        "Reachable without a session because guest checkout has no session: "
        "the reference is the capability, exactly as it is for "
        "`/api/payments/intent/`. The response is therefore limited to what "
        "the holder of the reference already knows — no addresses, no "
        "passenger details. An unknown reference returns 404."
    ),
    parameters=[OpenApiParameter("reference", str, OpenApiParameter.PATH)],
    responses={200: BookingStatusSerializer, 404: DetailSerializer},
)
@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def booking_status(request, reference):
    """
    Public confirmation status, keyed by reference.

    A signed-in customer looking at someone else's reference gets the same 404
    as an unknown one, matching `my_booking_detail`: a 403 would confirm that
    the reference exists.
    """
    booking = Booking.objects.filter(reference=reference).first()
    if booking is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.customer_id and request.user.is_authenticated \
            and booking.customer_id != request.user.id:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    return Response(BookingStatusSerializer(booking).data)


@extend_schema(
    tags=["bookings"],
    summary="Download the booking receipt (PDF)",
    description=(
        "The confirmation as a PDF, rendered from the same template as the "
        "confirmation email. Reachable by reference (guest checkout has no "
        "session); a signed-in customer may only fetch their own."
    ),
    parameters=[OpenApiParameter("reference", str, OpenApiParameter.PATH)],
    responses={200: OpenApiResponse(description="application/pdf"),
               404: DetailSerializer, 503: DetailSerializer},
)
@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def booking_receipt(request, reference):
    """The booking confirmation as a downloadable PDF."""
    booking = Booking.objects.filter(reference=reference).first()
    if booking is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.customer_id and request.user.is_authenticated \
            and booking.customer_id != request.user.id:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    pdf = render_booking_pdf(booking)
    if pdf is None:
        return Response({"detail": "The receipt could not be generated."},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)

    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="booking-{booking.reference}.pdf"'
    )
    return response


@extend_schema(
    tags=["bookings"],
    summary="The signed-in customer's bookings",
    responses={200: BookingSerializer(many=True), 403: DetailSerializer},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_bookings(request):
    bookings = (
        Booking.objects.filter(customer=request.user)
        .prefetch_related("price_lines")
        .order_by("-pickup_at")
    )
    return Response(BookingSerializer(bookings, many=True).data)


@extend_schema(
    tags=["account"],
    summary="The signed-in customer's cards on file",
    responses={200: SavedCardSerializer(many=True), 403: DetailSerializer},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_cards(request):
    cards = request.user.saved_cards.all()
    return Response(SavedCardSerializer(cards, many=True).data)


@extend_schema(
    tags=["account"],
    summary="Remove a card on file",
    responses={204: None, 404: DetailSerializer},
)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def my_card_delete(request, pk):
    card = request.user.saved_cards.filter(pk=pk).first()
    if card is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    payments_gateway.detach_card(card)  # detaches at Stripe and deletes locally
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["bookings"],
    summary="Read or cancel one of your bookings",
    description=(
        "Scoped to the signed-in customer. Another customer's reference returns "
        "**404, not 403** — a 403 would confirm the reference exists and allow "
        "bookings to be enumerated.\n\n"
        "`PATCH {\"action\": \"cancel\"}` cancels, if the pickup is still in "
        "the future."
    ),
    parameters=[OpenApiParameter("reference", str, OpenApiParameter.PATH)],
    request=CancelBookingSerializer,
    responses={200: BookingSerializer, 400: DetailSerializer, 404: DetailSerializer},
)
@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def my_booking_detail(request, reference):
    """
    A customer's own booking.

    Scoped to `customer=request.user`, so an unknown reference and someone
    else's reference are indistinguishable -- both 404. That prevents using the
    endpoint to confirm whether a reference exists.
    """
    booking = (
        Booking.objects.filter(reference=reference, customer=request.user)
        .prefetch_related("price_lines")
        .first()
    )
    if booking is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "PATCH":
        action = request.data.get("action")
        if action == "cancel":
            if not booking.is_cancellable:
                raise ValidationError(
                    {"detail": "This booking can no longer be cancelled online."}
                )
            BookingStatusChange.objects.create(
                booking=booking, from_status=booking.status,
                to_status=Booking.Status.CANCELLED,
                changed_by=request.user, note="Cancelled by customer",
            )
            booking.status = Booking.Status.CANCELLED
            booking.cancelled_at = timezone.now()
            booking.save()
            mailer.send_booking_cancelled(booking)

        elif action == "amend":
            # Details within the office-set edit window. Changing the pickup time
            # re-prices (night/event surcharges are time-based); the other fields
            # don't touch the fare. Addresses/vehicle stay office-only.
            if not booking.is_amendable:
                raise ValidationError({
                    "detail": "Changes to this booking are no longer allowed "
                              "online. Please contact us."
                })
            amend = BookingAmendSerializer(data=request.data)
            amend.is_valid(raise_exception=True)
            data = amend.validated_data

            # Honour the vehicle's seat/bag limits on edits too.
            _enforce_capacity(
                booking.vehicle,
                data.get("passenger_count", booking.passenger_count),
                data.get("luggage_count", booking.luggage_count),
            )

            changed = []
            recomputed = None
            for field in ("passenger_count", "luggage_count", "flight_number",
                          "pickup_sign", "notes"):
                if field in data:
                    setattr(booking, field, data[field])
                    changed.append(field)

            if "pickup_at" in data and data["pickup_at"] != booking.pickup_at:
                booking.pickup_at = data["pickup_at"]
                changed.append("pickup_at")
                # Re-price at the new time via the booking's own re-quote entry
                # point, which reuses the stored distance/hours and forwards the
                # persisted `is_city_to_city` marker -- so an amended intercity
                # trip keeps its intercity rate card instead of silently dropping
                # to the normal distance bands. The fare the client sees stays
                # authoritative.
                try:
                    recomputed = booking.reprice(pickup_at=booking.pickup_at)
                except QuoteError as exc:
                    raise ValidationError({
                        "detail": "We couldn't re-price that time. Please contact us."
                    }) from exc
                booking.subtotal = recomputed.subtotal
                booking.surcharge_total = recomputed.surcharge_total
                booking.tax = recomputed.tax
                booking.total = recomputed.total

            if changed:
                booking.save()
            if recomputed is not None:
                booking.price_lines.all().delete()
                for line in recomputed.as_price_lines(booking):
                    line.save()
            if "phone" in data:  # contact number lives on the account
                request.user.phone = data["phone"].strip()
                request.user.save(update_fields=["phone"])
                changed.append("phone")

            BookingStatusChange.objects.create(
                booking=booking, from_status=booking.status, to_status=booking.status,
                changed_by=request.user,
                note="Details amended by customer"
                     + (": " + ", ".join(changed) if changed else ""),
            )

        else:
            raise ValidationError({"action": "Only 'cancel' or 'amend' is supported."})

    return Response(BookingSerializer(booking).data)


# -- auth -------------------------------------------------------------------


@extend_schema(
    tags=["auth"],
    summary="Sign in",
    description="Sets a session cookie. A wrong password and an unknown address "
                "return the identical response, so this cannot be used to "
                "discover who has an account.",
    request=LoginRequestSerializer,
    responses={200: UserSerializer, 401: DetailSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def auth_login(request):
    email = (request.data.get("email") or "").strip().lower()
    password = request.data.get("password") or ""

    user = authenticate(request, username=email, password=password)
    if user is None:
        # One message for both causes: revealing which is wrong lets an attacker
        # enumerate registered addresses.
        return Response(
            {"detail": "Email or password is incorrect."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    login(request, user)
    return Response({
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
    })


@extend_schema(
    tags=["auth"], summary="Sign out", request=None, responses={204: None},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def auth_logout(request):
    logout(request)
    return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(
    tags=["auth"],
    summary="Create an account",
    description="Password strength is enforced. Registering an address that "
                "already exists returns **202 with a neutral message** rather "
                "than an error, for the same anti-enumeration reason as sign-in.",
    request=RegisterRequestSerializer,
    responses={201: UserSerializer, 202: DetailSerializer, 400: DetailSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def auth_register(request):
    email = (request.data.get("email") or "").strip().lower()
    password = request.data.get("password") or ""

    if not email or "@" not in email:
        raise ValidationError({"email": "A valid email address is required."})

    try:
        validate_password(password)
    except DjangoValidationError as exc:
        raise ValidationError({"password": list(exc.messages)}) from exc

    if User.objects.filter(email=email).exists():
        # Deliberately not "that email is taken" -- same enumeration concern.
        return Response(
            {"detail": "If that address can be registered, you'll receive an email."},
            status=status.HTTP_202_ACCEPTED,
        )

    user = User.objects.create_user(
        email=email,
        password=password,
        first_name=(request.data.get("first_name") or "").strip()[:150],
        last_name=(request.data.get("last_name") or "").strip()[:150],
        phone=(request.data.get("phone") or "").strip()[:32],
    )
    login(request, user)
    # The same shape as /auth/login/ and /auth/me/. Returning only the address
    # here made the frontend show "My account" to someone who had just typed
    # their name in, because the header had nothing else to go on.
    return Response(
        {
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone": user.phone,
        },
        status=status.HTTP_201_CREATED,
    )


@extend_schema(
    tags=["auth"],
    summary="Request a password reset link",
    description=(
        "Always returns 202, whether or not the address is registered.\n\n"
        "The reset is completed on Django-served pages under `/accounts/`, not "
        "in the frontend. Note that customers migrated from the previous system "
        "have no password at all until they use this."
    ),
    request=PasswordResetRequestSerializer,
    responses={202: DetailSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def auth_password_reset(request):
    """
    Trigger a password reset email.

    Delegates to Django's own `PasswordResetForm`, which generates the signed
    one-time token and sends the mail. The reset itself is completed on the
    Django-served pages under /accounts/.

    Always answers 202, whether or not the address is registered: a different
    response for a known address turns this endpoint into a way to enumerate
    customers. Every imported legacy account needs this flow, so the endpoint
    must be safe to hammer.
    """
    form = MigrationPasswordResetForm(data={"email": (request.data.get("email") or "").strip()})
    if form.is_valid():
        form.save(
            request=request,
            use_https=request.is_secure(),
            from_email=settings.DEFAULT_FROM_EMAIL,
            email_template_name="accounts/email/password_reset.txt",
            html_email_template_name="accounts/email/password_reset.html",
            subject_template_name="accounts/email/password_reset_subject.txt",
        )

    return Response(
        {"detail": "If that address has an account, a reset link is on its way."},
        status=status.HTTP_202_ACCEPTED,
    )


# A customer may ask for at most this many codes per address per window before
# further requests are silently dropped. The per-IP ceiling lives in the DRF
# throttle (scope ``login_code_send``); this one stops a single address being
# hammered from a rotating pool of IPs and caps the mail we send per person.
LOGIN_CODE_SEND_WINDOW = 600  # seconds
LOGIN_CODE_SEND_MAX = 3


def _email_login_code(request, user, code: str) -> None:
    """Render and send the one-time code, mirroring the password-reset mail."""
    context = {
        "user": user,
        "code": code,
        "ttl_minutes": int(LoginCode.objects.CODE_TTL.total_seconds() // 60),
        "protocol": "https" if request.is_secure() else "http",
        "domain": request.get_host(),
    }
    subject = render_to_string(
        "accounts/email/login_code_subject.txt", context,
    ).strip()
    text_body = render_to_string("accounts/email/login_code.txt", context)
    html_body = render_to_string("accounts/email/login_code.html", context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(html_body, "text/html")
    # A mail-server hiccup must not turn into a 500 that tells the caller the
    # address exists -- the response is identical either way.
    message.send(fail_silently=True)


@extend_schema(
    tags=["auth"],
    summary="Email a one-time sign-in code",
    description=(
        "Passwordless sign-in, step one. Emails a six-digit code that is valid "
        "for ten minutes, single-use, and rate-limited per address and per IP.\n\n"
        "**Always returns 200** with a neutral message, whether or not the "
        "address is registered -- the response cannot be used to discover who "
        "has an account, exactly like password reset. A registered customer is "
        "sent a code; nothing happens for anyone else."
    ),
    request=SendCodeRequestSerializer,
    responses={200: DetailSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginCodeSendThrottle])
def auth_send_code(request):
    email = (request.data.get("email") or "").strip().lower()
    neutral = Response({
        "detail": "If that address has an account, a sign-in code is on its way.",
    })

    if not email or "@" not in email:
        return neutral

    # Per-address cooldown. Counted for unknown addresses too, so existence
    # cannot be probed by watching for the limit to kick in.
    bucket = f"login-code-send:{email}"
    sent = cache.get(bucket, 0)
    if sent >= LOGIN_CODE_SEND_MAX:
        return neutral
    cache.set(bucket, sent + 1, LOGIN_CODE_SEND_WINDOW)

    user = User.objects.filter(email=email, is_active=True).first()
    if user is not None:
        _code, raw = LoginCode.objects.issue(email)
        _email_login_code(request, user, raw)

    return neutral


@extend_schema(
    tags=["auth"],
    summary="Sign in with a one-time code",
    description=(
        "Passwordless sign-in, step two. Exchanges a valid, unexpired, unused "
        "code for a session -- the response and cookie are identical to "
        "`/auth/login/`. A wrong, expired, used or over-attempted code returns "
        "**400** with a single neutral message. A correct code is consumed on "
        "use and cannot be replayed."
    ),
    request=VerifyCodeRequestSerializer,
    responses={200: UserSerializer, 400: DetailSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginCodeVerifyThrottle])
def auth_verify_code(request):
    email = (request.data.get("email") or "").strip().lower()
    code_input = (request.data.get("code") or "").strip()

    invalid = Response(
        {"detail": "That code is invalid or has expired."},
        status=status.HTTP_400_BAD_REQUEST,
    )

    if not email or not code_input:
        return invalid

    if LoginCode.objects.verify(email, code_input) is None:
        return invalid

    user = User.objects.filter(email=email, is_active=True).first()
    if user is None:
        # A code existed for an address with no active account -- treat as
        # invalid rather than leaking the discrepancy.
        return invalid

    # No password was involved, so there is no authenticate() step; log the
    # user in directly. The session, cookie and payload match /auth/login/.
    login(request, user)
    return Response({
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
    })


@extend_schema(
    tags=["auth"],
    summary="Read or update the signed-in customer",
    description="GET returns the current profile. PATCH updates the editable "
                "fields (first_name, last_name, phone). Email is the login "
                "identifier and is not editable here.",
    request=UserSerializer,
    responses={200: UserSerializer, 403: DetailSerializer},
)
@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def auth_me(request):
    user = request.user
    if request.method == "PATCH":
        data = request.data
        if "first_name" in data:
            user.first_name = (data.get("first_name") or "").strip()[:150]
        if "last_name" in data:
            user.last_name = (data.get("last_name") or "").strip()[:150]
        if "phone" in data:
            user.phone = (data.get("phone") or "").strip()[:32]
        user.save(update_fields=["first_name", "last_name", "phone"])
    return Response({
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
    })


@extend_schema(
    tags=["auth"],
    summary="Prime the CSRF cookie",
    description="Sets the `csrftoken` cookie so the SPA can echo it in an "
                "`X-CSRFToken` header on authenticated writes. Safe to call "
                "anonymously and as often as needed.",
    responses={204: None},
)
@scoped_ensure_csrf_cookie
@api_view(["GET"])
@permission_classes([AllowAny])
def auth_csrf(request):
    return Response(status=status.HTTP_204_NO_CONTENT)


# -- enquiries --------------------------------------------------------------


@extend_schema(
    tags=["enquiries"],
    summary="Submit the contact form",
    description="Throttled to 10/hour per address.",
    request=EnquirySerializer,
    responses={201: DetailSerializer, 400: DetailSerializer, 429: DetailSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([EnquiryThrottle])
def create_enquiry(request):
    serializer = EnquirySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    ContactMessage.objects.create(
        **serializer.validated_data,
        source_ip=_client_ip(request),
        created_at=timezone.now(),
    )
    return Response({"detail": "Thank you — we'll be in touch."},
                    status=status.HTTP_201_CREATED)


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
