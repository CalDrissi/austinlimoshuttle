"""
Payment endpoints.

The checkout sequence:

  1. POST /api/payments/intent/   -> client secret + publishable key
  2. The browser confirms the card with Stripe Elements. Card details go
     directly from the customer to Stripe; they never touch this server.
  3. Stripe calls /api/payments/webhook/ -> the booking is confirmed.

Step 3 is authoritative. The browser's return from checkout is a hint, not
proof: it can be forged, and it can simply not arrive when a customer closes
the tab. The legacy system confirmed orders on the browser's say-so.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from bookings.models import Booking, BookingStatusChange
from payments import gateway
from payments.models import Payment, PaymentSettings, WebhookEvent

from .serializers import (
    BookingStatusSerializer,
    DetailSerializer,
    PaymentConfigSerializer,
    PaymentIntentRequestSerializer,
    PaymentIntentResponseSerializer,
)

logger = logging.getLogger(__name__)

HANDLED_EVENTS = {
    "payment_intent.succeeded",
    "payment_intent.payment_failed",
    "payment_intent.canceled",
    "payment_intent.processing",
    "charge.refunded",
}


@extend_schema(
    tags=["payments"],
    summary="Publishable key and payment availability",
    description="What the browser needs to render Stripe Elements. Only the "
                "publishable key is ever exposed; it is designed to be public.",
    responses={200: PaymentConfigSerializer},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def payment_config(request):
    """What the browser needs to render Stripe Elements."""
    config = PaymentSettings.load()
    return Response({
        "enabled": config.is_configured,
        "publishable_key": gateway.publishable_key(),
        "mode": config.mode if config.is_enabled else None,
    })


@extend_schema(
    tags=["payments"],
    summary="Start payment for a booking",
    description=(
        "Creates a Stripe PaymentIntent and returns its client secret for "
        "Stripe Elements.\n\n"
        "The amount comes from the booking, which the pricing engine computed. "
        "Nothing in the request body influences it.\n\n"
        "**Confirmation happens by webhook, not here.** A successful card "
        "confirmation in the browser does not mark the booking paid — Stripe "
        "calls `/api/payments/webhook/` and that is what confirms it. Poll "
        "`/api/account/bookings/{reference}/` or show a pending state."
    ),
    request=PaymentIntentRequestSerializer,
    responses={
        200: PaymentIntentResponseSerializer,
        400: DetailSerializer,
        404: DetailSerializer,
        409: OpenApiResponse(DetailSerializer,
                             description="Already paid, or the booking was cancelled."),
        502: DetailSerializer,
        503: OpenApiResponse(DetailSerializer,
                             description="Card payments are not configured."),
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def create_intent(request):
    """
    Start payment for a booking.

    The amount is read from the booking, which the pricing engine computed.
    Nothing in the request body influences it.
    """
    reference = (request.data.get("reference") or "").strip()
    if not reference:
        return Response({"detail": "A booking reference is required."},
                        status=status.HTTP_400_BAD_REQUEST)

    booking = Booking.objects.filter(reference=reference).first()
    if booking is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    # A signed-in customer may only pay for their own booking. Guest bookings
    # have no owner, so the reference itself is the capability -- which is why
    # references are 8 random characters from an unambiguous alphabet.
    if booking.customer_id and request.user.is_authenticated \
            and booking.customer_id != request.user.id:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.status == Booking.Status.CANCELLED:
        return Response({"detail": "This booking was cancelled."},
                        status=status.HTTP_409_CONFLICT)
    if booking.payments.filter(status=Payment.Status.SUCCEEDED).exists():
        return Response({"detail": "This booking is already paid."},
                        status=status.HTTP_409_CONFLICT)
    # A cash confirmation is a settled choice, not an unpaid booking: opening a
    # card intent on top of it would let the fare be collected twice (card now,
    # cash at pickup -- the driver still sees cash due).
    if booking.payments.filter(
        provider=Payment.Provider.CASH, status=Payment.Status.PROCESSING,
    ).exists():
        return Response(
            {"detail": "This booking is set to pay the driver in cash. "
                       "Please contact us to switch to a card payment."},
            status=status.HTTP_409_CONFLICT,
        )

    # A signed-in customer paying for their own booking ALWAYS keeps the card on
    # file -- it is the default for account holders, not an opt-in, so their next
    # booking is one tap and staff can bill agreed extras later. A guest has no
    # account to attach it to, so nothing is saved for them.
    save_card = (
        request.user.is_authenticated
        and booking.customer_id == request.user.id
    )

    try:
        payment = gateway.create_payment_intent(booking, save_card=save_card)
        client_secret = gateway.client_secret_for(payment)
    except gateway.PaymentConfigurationError as exc:
        # An operator problem, not the customer's. Log loudly, stay vague.
        logger.error("Payment configuration problem: %s", exc)
        return Response(
            {"detail": "Card payments are unavailable right now. Please contact us."},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    except gateway.PaymentGatewayError as exc:
        return Response({"detail": str(exc)},
                        status=status.HTTP_502_BAD_GATEWAY)

    return Response({
        "client_secret": client_secret,
        "publishable_key": gateway.publishable_key(),
        "amount": f"{booking.total:.2f}",
        "currency": booking.currency,
        "reference": booking.reference,
    })


@extend_schema(
    tags=["payments"],
    summary="Confirm a booking for cash / pay-on-arrival",
    description=(
        "Confirms a pending booking without an online payment — the fare is "
        "collected by the driver. Records an awaiting-collection cash payment "
        "for the booking's own amount (never a client-supplied one) and moves "
        "the booking to `confirmed`. The payment only becomes `succeeded` when "
        "staff mark the cash collected in the back office, so paid-to-date "
        "reflects money actually received.\n\n"
        "Scoped like the other reference endpoints: a signed-in customer may "
        "only settle their own booking; a guest booking is settled by whoever "
        "holds the reference."
    ),
    request=None,
    responses={
        200: BookingStatusSerializer,
        404: DetailSerializer,
        409: OpenApiResponse(DetailSerializer,
                             description="Already paid, or the booking was cancelled."),
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def pay_cash(request, reference):
    """Confirm a booking as cash / pay-on-arrival."""
    booking = Booking.objects.filter(reference=reference).first()
    if booking is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.customer_id and request.user.is_authenticated \
            and booking.customer_id != request.user.id:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.status == Booking.Status.CANCELLED:
        return Response({"detail": "This booking was cancelled."},
                        status=status.HTTP_409_CONFLICT)
    if booking.payments.filter(status=Payment.Status.SUCCEEDED).exists():
        return Response({"detail": "This booking is already paid."},
                        status=status.HTTP_409_CONFLICT)

    confirmed_now = False
    with transaction.atomic():
        # Serialise concurrent confirms on the booking row: nothing in the
        # schema forbids two awaiting-collection payments, so a double click's
        # two racing requests must queue here rather than both pass the
        # exists() check below.
        booking = Booking.objects.select_for_update().get(pk=booking.pk)

        # Awaiting collection, NOT succeeded: the money changes hands with the
        # driver, so staff mark it collected in the back office. Recording it
        # as paid here would poison paid-to-date (and therefore refunds). A
        # retried confirm finds the existing payment and records nothing new.
        if not booking.payments.filter(
            provider=Payment.Provider.CASH, status=Payment.Status.PROCESSING,
        ).exists():
            Payment.objects.create(
                booking=booking,
                provider=Payment.Provider.CASH,
                amount=booking.total,
                currency=booking.currency,
                status=Payment.Status.PROCESSING,
            )

        # Confirm even when the payment already existed -- a staff-created
        # booking can sit PENDING with an awaiting-collection payment, and
        # this call is the customer's confirmation of it.
        if booking.status == Booking.Status.PENDING:
            BookingStatusChange.objects.create(
                booking=booking,
                from_status=booking.status,
                to_status=Booking.Status.CONFIRMED,
                note="Cash — pay the driver",
            )
            booking.status = Booking.Status.CONFIRMED
            booking.save(update_fields=["status", "updated_at"])
            confirmed_now = True

    if confirmed_now:
        # Same confirmation as the card path: email + SMS + ops alert. Outside
        # the transaction so a slow SMTP conversation never holds the row lock.
        from notifications.events import booking_confirmed
        booking_confirmed(booking)

    return Response(BookingStatusSerializer(booking).data)


@extend_schema(
    tags=["bookings"],
    summary="Void an unpaid pending booking",
    description=(
        "Cancels a booking that is still `pending` and has no settled or "
        "awaiting-collection payment. The storefront calls this when the "
        "customer changes their trip or contact identity after a booking was "
        "created but before paying — the replaced draft would otherwise sit in "
        "the back office as pending work forever.\n\n"
        "Scoped like the other reference endpoints: the reference is the "
        "capability (guest checkout has no session); a signed-in customer may "
        "only void their own. Idempotent: an already-cancelled booking "
        "returns 200. A confirmed or paid booking returns **409** — that is a "
        "cancellation request, not a void."
    ),
    request=None,
    responses={
        200: BookingStatusSerializer,
        404: DetailSerializer,
        409: OpenApiResponse(DetailSerializer,
                             description="Already confirmed or paid."),
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([AnonRateThrottle])
def void_pending(request, reference):
    """Void an unpaid pending booking the customer abandoned mid-flow."""
    booking = Booking.objects.filter(reference=reference).first()
    if booking is None:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.customer_id and request.user.is_authenticated \
            and booking.customer_id != request.user.id:
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.status == Booking.Status.CANCELLED:
        # Idempotent: a retried void finds the work already done.
        return Response(BookingStatusSerializer(booking).data)

    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        # Anything beyond "pending with no money in motion" is out of scope:
        # a paid or confirmed booking goes through the cancellation-request
        # flow, where staff decide refunds.
        if booking.status != Booking.Status.PENDING or booking.payments.filter(
            status__in=[Payment.Status.SUCCEEDED, Payment.Status.PROCESSING],
        ).exists():
            return Response(
                {"detail": "This booking is already confirmed or paid — "
                           "request a cancellation instead."},
                status=status.HTTP_409_CONFLICT,
            )
        BookingStatusChange.objects.create(
            booking=booking,
            from_status=booking.status,
            to_status=Booking.Status.CANCELLED,
            note="Voided — the customer changed their trip before paying",
        )
        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=["status", "updated_at"])

    return Response(BookingStatusSerializer(booking).data)


@extend_schema(
    tags=["payments"],
    summary="Stripe webhook (not for frontend use)",
    description=(
        "Called by Stripe, never by the frontend. Requests are authenticated by "
        "HMAC signature over the raw body; unsigned requests are refused.\n\n"
        "Idempotent: every processed event id is recorded, so Stripe's retries "
        "cannot double-confirm a booking or double-record a refund."
    ),
    request=None,
    responses={200: DetailSerializer, 400: DetailSerializer, 503: DetailSerializer},
)
@csrf_exempt
@api_view(["POST"])
@permission_classes([AllowAny])
def webhook(request):
    """
    Stripe webhook. Signature-verified, idempotent.

    CSRF exemption is correct here and safe: this endpoint authenticates by
    HMAC signature over the raw body, which is stronger than a CSRF token and
    is the only thing it trusts.
    """
    payload = request.body
    signature = request.META.get("HTTP_STRIPE_SIGNATURE", "")

    try:
        event = gateway.verify_webhook(payload, signature)
    except gateway.PaymentConfigurationError as exc:
        logger.error("Webhook received but not verifiable: %s", exc)
        # 503 so Stripe retries once the secret is configured, rather than
        # discarding the event.
        return Response({"detail": "Webhook not configured."},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except gateway.PaymentGatewayError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    event_id = event["id"]
    event_type = event["type"]

    # Replay protection. Stripe retries until it gets a 2xx and may deliver the
    # same event more than once regardless.
    with transaction.atomic():
        _, created = WebhookEvent.objects.get_or_create(
            event_id=event_id,
            defaults={"event_type": event_type,
                      "payload_summary": str(event["data"]["object"].get("id", ""))[:255]},
        )
        if not created:
            logger.info("Ignoring duplicate webhook %s (%s)", event_id, event_type)
            return Response({"status": "duplicate ignored"})

        if event_type not in HANDLED_EVENTS:
            # 200 so Stripe stops retrying an event we deliberately ignore.
            return Response({"status": "ignored"})

        obj = event["data"]["object"]
        try:
            if event_type == "charge.refunded":
                gateway.record_refund_from_charge(obj)
            else:
                gateway.apply_intent_to_payment(obj)
        except Exception:
            # Roll back the dedupe row so Stripe's retry gets a real attempt.
            logger.exception("Failed to process webhook %s (%s)", event_id, event_type)
            raise

    return Response({"status": "ok"})
