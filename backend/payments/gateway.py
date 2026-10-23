"""
Stripe gateway.

Card details never pass through here. The browser sends them straight to Stripe
Elements; we handle a PaymentIntent and, afterwards, a brand and a last-4 that
Stripe gives back for display. That is what takes this application out of PCI
scope, and it is why the legacy failure -- 3,416 card numbers in the database --
cannot recur regardless of what anyone writes later.

Credentials come from `PaymentSettings`, managed in the dashboard and encrypted
at rest. They are read per call rather than cached at import, so changing them
in the settings page takes effect immediately.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import stripe
from django.utils import timezone

from bookings.models import Booking, BookingStatusChange

from .models import Payment, PaymentSettings, Refund

logger = logging.getLogger(__name__)

CENTS = Decimal("100")

# Stripe status -> our status. Anything unmapped is recorded verbatim so an
# unexpected value is visible rather than silently coerced to "succeeded".
STATUS_MAP = {
    "requires_payment_method": Payment.Status.REQUIRES_PAYMENT_METHOD,
    "requires_confirmation": Payment.Status.REQUIRES_PAYMENT_METHOD,
    "requires_action": Payment.Status.REQUIRES_ACTION,
    "processing": Payment.Status.PROCESSING,
    "succeeded": Payment.Status.SUCCEEDED,
    "canceled": Payment.Status.CANCELLED,
}


class PaymentConfigurationError(Exception):
    """Stripe is not configured, or is misconfigured."""


class PaymentGatewayError(Exception):
    """Stripe rejected the request or could not be reached."""


def _is_missing_customer(exc) -> bool:
    """True when Stripe rejected a request because the `customer` id is unknown.

    Happens when a cached `stripe_customer_id` is stale -- e.g. after switching
    the account's keys from test to live, or restoring a database against a
    different Stripe account. The id is valid-looking but doesn't exist here.
    """
    return getattr(exc, "code", None) == "resource_missing" \
        and getattr(exc, "param", None) == "customer"


def _settings() -> PaymentSettings:
    config = PaymentSettings.load()

    if not config.is_enabled:
        raise PaymentConfigurationError(
            "Card payments are switched off. A manager can enable them in "
            "Dashboard → Settings."
        )
    secret = config.secret_key
    if not secret:
        raise PaymentConfigurationError(
            "No Stripe secret key is configured. Add one in Dashboard → Settings."
        )
    if not config.key_mode_matches:
        # Live mode with test keys takes no money while reporting success.
        raise PaymentConfigurationError(
            f"The stored Stripe key does not match {config.get_mode_display()}. "
            "Correct it in Dashboard → Settings before taking payments."
        )
    return config


def _client(config: PaymentSettings) -> stripe.StripeClient:
    return stripe.StripeClient(api_key=config.secret_key)


def to_cents(amount: Decimal) -> int:
    """Stripe works in the smallest currency unit."""
    return int((Decimal(amount) * CENTS).quantize(Decimal("1")))


def publishable_key() -> str:
    """The key the browser needs. Safe to expose -- that is its purpose."""
    config = PaymentSettings.load()
    return config.publishable_key if config.is_enabled else ""


def create_payment_intent(booking, *, idempotency_suffix: str = "", save_card: bool = False) -> Payment:
    """
    Create (or reuse) a PaymentIntent for a booking.

    The amount comes from `booking.total`, which the pricing engine computed
    server-side. Nothing a client sent is used here.

    When `save_card` is set and the booking belongs to a signed-in customer, the
    intent is attached to their Stripe Customer with `setup_future_usage`, so the
    card can be reused for later bookings and charged off-session by staff. The
    card is persisted (see `save_card_for_user`) once payment succeeds.
    """
    config = _settings()

    if booking.total <= 0:
        raise PaymentGatewayError("This booking has no amount to charge.")

    # Attach to the customer so the card can be kept on file.
    customer_id = ""
    if save_card and booking.customer_id:
        customer_id = get_or_create_customer(booking.customer)

    # Reuse a live intent rather than stacking up abandoned ones on retries.
    existing = booking.payments.filter(
        provider=Payment.Provider.STRIPE,
        status__in=[
            Payment.Status.REQUIRES_PAYMENT_METHOD,
            Payment.Status.REQUIRES_ACTION,
            Payment.Status.PROCESSING,
        ],
    ).first()
    if existing and existing.amount == booking.total:
        return existing

    client = _client(config)
    # A stable key means a retried request returns the same intent instead of
    # charging twice.
    idempotency_key = f"booking-{booking.reference}-{booking.total}-{int(save_card)}{idempotency_suffix}"

    params = {
        "amount": to_cents(booking.total),
        "currency": booking.currency.lower(),
        "automatic_payment_methods": {"enabled": True},
        "description": f"Booking {booking.reference}",
        "statement_descriptor_suffix": config.statement_descriptor or None,
        "metadata": {
            "booking_reference": booking.reference,
            "booking_id": str(booking.pk),
            "pickup_at": booking.pickup_at.isoformat(),
        },
    }
    if customer_id:
        params["customer"] = customer_id
        # Lets the card be reused and charged off-session later; also captures
        # the mandate the customer agrees to when saving it.
        params["setup_future_usage"] = "off_session"

    try:
        intent = client.payment_intents.create(
            params=params,
            options={"idempotency_key": idempotency_key},
        )
    except stripe.StripeError as exc:
        # A stale cached customer id shouldn't wedge checkout. Drop it, make a
        # fresh customer and retry once (new idempotency key -- the body changed).
        if customer_id and _is_missing_customer(exc):
            logger.warning("Stale Stripe customer %s for user %s -- recreating.",
                           customer_id, booking.customer_id)
            booking.customer.stripe_customer_id = ""
            booking.customer.save(update_fields=["stripe_customer_id"])
            customer_id = get_or_create_customer(booking.customer)
            params["customer"] = customer_id
            try:
                intent = client.payment_intents.create(
                    params=params,
                    options={"idempotency_key": f"{idempotency_key}-recustomer"},
                )
            except stripe.StripeError as retry_exc:
                logger.error("Stripe intent creation failed for %s after customer reset: %s",
                             booking.reference, retry_exc)
                raise PaymentGatewayError(
                    getattr(retry_exc, "user_message", None) or "The payment could not be started."
                ) from retry_exc
        else:
            logger.error("Stripe intent creation failed for %s: %s", booking.reference, exc)
            raise PaymentGatewayError(
                getattr(exc, "user_message", None) or "The payment could not be started."
            ) from exc

    payment, _ = Payment.objects.update_or_create(
        payment_intent_id=intent.id,
        defaults={
            "booking": booking,
            "provider": Payment.Provider.STRIPE,
            "amount": booking.total,
            "currency": booking.currency,
            "status": STATUS_MAP.get(intent.status, Payment.Status.UNKNOWN),
        },
    )
    return payment


def client_secret_for(payment: Payment) -> str:
    """
    Fetch the intent's client secret.

    Deliberately not stored: it is a short-lived credential for one checkout,
    and a database column holding it is a database column that can leak it.
    """
    config = _settings()
    try:
        intent = _client(config).payment_intents.retrieve(payment.payment_intent_id)
    except stripe.StripeError as exc:
        raise PaymentGatewayError("The payment could not be started.") from exc
    return intent.client_secret


# -- customers & cards on file ----------------------------------------------

def get_or_create_customer(user) -> str:
    """The user's Stripe Customer id, created on first use and cached on the row."""
    if user.stripe_customer_id:
        return user.stripe_customer_id
    client = _client(_settings())
    try:
        customer = client.customers.create(params={
            "email": user.email,
            "name": f"{user.first_name} {user.last_name}".strip() or user.email,
            "metadata": {"user_id": str(user.pk)},
        })
    except stripe.StripeError as exc:
        raise PaymentGatewayError("Could not create a customer record.") from exc
    user.stripe_customer_id = customer.id
    user.save(update_fields=["stripe_customer_id"])
    return customer.id


def save_card_for_user(user, payment_method_id: str):
    """
    Record a PaymentMethod as a reusable card for the user.

    The PaymentMethod is already attached to the customer (Stripe does that when
    an intent runs with `setup_future_usage`). Brand/last4/expiry are read back
    from Stripe -- never trusted from the client.
    """
    from .models import SavedCard

    client = _client(_settings())
    try:
        pm = client.payment_methods.retrieve(payment_method_id)
    except stripe.StripeError as exc:
        raise PaymentGatewayError("Could not read the card details.") from exc

    card = getattr(pm, "card", None)
    saved, _ = SavedCard.objects.update_or_create(
        stripe_payment_method_id=payment_method_id,
        defaults={
            "customer": user,
            "brand": getattr(card, "brand", "") or "",
            "last4": getattr(card, "last4", "") or "",
            "exp_month": getattr(card, "exp_month", None),
            "exp_year": getattr(card, "exp_year", None),
        },
    )
    if not user.saved_cards.filter(is_default=True).exclude(pk=saved.pk).exists():
        saved.is_default = True
        saved.save(update_fields=["is_default"])
    return saved


def charge_saved_card(saved_card, amount: Decimal, description: str, *, booking=None) -> Payment:
    """
    Charge a card on file off-session -- e.g. staff billing a trip extension.

    Off-session relies on the mandate captured when the card was saved. Records
    a Payment against the booking if given, otherwise standalone.
    """
    config = _settings()
    amount = Decimal(amount)
    if amount <= 0:
        raise PaymentGatewayError("Enter an amount greater than zero.")

    user = saved_card.customer
    if not user.stripe_customer_id:
        raise PaymentGatewayError("This customer has no Stripe record to charge.")

    client = _client(config)
    try:
        intent = client.payment_intents.create(params={
            "amount": to_cents(amount),
            "currency": "usd",
            "customer": user.stripe_customer_id,
            "payment_method": saved_card.stripe_payment_method_id,
            "off_session": True,
            "confirm": True,
            "description": description or "Trip extension",
            "statement_descriptor_suffix": config.statement_descriptor or None,
            "metadata": {
                "saved_card_id": str(saved_card.pk),
                "user_id": str(user.pk),
                "booking_reference": booking.reference if booking else "",
                "kind": "staff_offsession_charge",
            },
        })
    except stripe.CardError as exc:
        raise PaymentGatewayError(
            getattr(exc, "user_message", None) or "The card was declined."
        ) from exc
    except stripe.StripeError as exc:
        logger.error("Off-session charge failed: %s", exc)
        raise PaymentGatewayError("The charge could not be completed.") from exc

    return Payment.objects.create(
        booking=booking,
        provider=Payment.Provider.STRIPE,
        payment_intent_id=intent.id,
        amount=amount,
        currency="USD",
        status=STATUS_MAP.get(intent.status, Payment.Status.UNKNOWN),
        card_brand=saved_card.brand,
        card_last4=saved_card.last4,
    )


def charge_booking_with_payment_method(booking, payment_method_id: str, *, save_for=None):
    """
    Charge a booking's total with a card collected at the counter (on-session).

    Confirms immediately with the given PaymentMethod. Returns (Payment, status).
    A plain test card (4242…) succeeds outright; a card that needs 3-D Secure
    comes back "requires_action" and the caller surfaces that.

    When `save_for` is a customer user, the card is attached to their Stripe
    Customer and saved on file (`SavedCard`) on success, so the next booking is
    one tap -- this is why a counter card charge requires a customer.
    """
    config = _settings()
    if booking.total <= 0:
        raise PaymentGatewayError("This booking has no amount to charge.")

    client = _client(config)

    def _create():
        params = {
            "amount": to_cents(booking.total),
            "currency": booking.currency.lower(),
            "payment_method": payment_method_id,
            "confirm": True,
            # Card only -- we confirm server-side, so no redirect-based methods.
            "automatic_payment_methods": {"enabled": True, "allow_redirects": "never"},
            "description": f"Booking {booking.reference} (counter)",
            "statement_descriptor_suffix": config.statement_descriptor or None,
            "metadata": {
                "booking_reference": booking.reference,
                "booking_id": str(booking.pk),
                "kind": "backoffice_card",
            },
        }
        if save_for is not None:
            params["customer"] = get_or_create_customer(save_for)
            params["setup_future_usage"] = "off_session"
        return client.payment_intents.create(params=params)

    try:
        intent = _create()
    except stripe.CardError as exc:
        raise PaymentGatewayError(
            getattr(exc, "user_message", None) or "The card was declined."
        ) from exc
    except stripe.StripeError as exc:
        # A stale cached Stripe customer id -> clear it and try once more.
        if save_for is not None and _is_missing_customer(exc):
            save_for.stripe_customer_id = ""
            save_for.save(update_fields=["stripe_customer_id"])
            try:
                intent = _create()
            except stripe.StripeError as exc2:
                logger.error("Counter charge retry failed for %s: %s", booking.reference, exc2)
                raise PaymentGatewayError("The charge could not be completed.") from exc2
        else:
            logger.error("Counter charge failed for %s: %s", booking.reference, exc)
            raise PaymentGatewayError("The charge could not be completed.") from exc

    payment = Payment.objects.create(
        booking=booking,
        provider=Payment.Provider.STRIPE,
        payment_intent_id=intent.id,
        amount=booking.total,
        currency=booking.currency,
        status=STATUS_MAP.get(intent.status, Payment.Status.UNKNOWN),
    )
    # Brand/last4 for the receipt -- read back from Stripe, never the client.
    try:
        card = getattr(client.payment_methods.retrieve(payment_method_id), "card", None)
        payment.card_brand = (getattr(card, "brand", "") or "")[:20]
        payment.card_last4 = (getattr(card, "last4", "") or "")[:4]
        payment.save(update_fields=["card_brand", "card_last4"])
    except stripe.StripeError:
        pass

    # Persist the card on file for next time (PM is attached by setup_future_usage).
    if save_for is not None and intent.status == "succeeded":
        try:
            save_card_for_user(save_for, payment_method_id)
        except stripe.StripeError:
            logger.warning("Charged but couldn't save card for %s", booking.reference)

    return payment, intent.status


def detach_card(saved_card) -> None:
    """Remove a card on file: detach the PaymentMethod at Stripe, delete locally."""
    try:
        _client(_settings()).payment_methods.detach(saved_card.stripe_payment_method_id)
    except (stripe.StripeError, PaymentConfigurationError) as exc:
        # Already gone at Stripe, or Stripe isn't configured -- still remove our
        # local record so the customer can clear a stale card.
        logger.warning("Could not detach %s: %s", saved_card.stripe_payment_method_id, exc)
    was_default, user = saved_card.is_default, saved_card.customer
    saved_card.delete()
    if was_default:
        nxt = user.saved_cards.first()
        if nxt:
            nxt.is_default = True
            nxt.save(update_fields=["is_default"])


def verify_webhook(payload: bytes, signature: str):
    """
    Verify a webhook signature and return the event.

    Unsigned or badly-signed payloads are rejected. Without this, anyone who
    knows the URL could post `payment_intent.succeeded` and confirm bookings
    without paying.
    """
    config = PaymentSettings.load()
    secret = config.webhook_secret
    if not secret:
        raise PaymentConfigurationError(
            "No webhook signing secret is configured; incoming events cannot be "
            "verified and are refused."
        )
    if not signature:
        raise PaymentGatewayError("Missing Stripe signature header.")

    try:
        return stripe.Webhook.construct_event(payload, signature, secret)
    except ValueError as exc:
        raise PaymentGatewayError("Malformed webhook payload.") from exc
    except stripe.SignatureVerificationError as exc:
        logger.warning("Rejected a webhook with an invalid signature.")
        raise PaymentGatewayError("Invalid webhook signature.") from exc


def refund(payment: Payment, *, amount: Decimal | None = None, reason: str = "",
           created_by=None):
    """
    Refund a payment, in full or in part.

    Partial refunds cover a cancellation net of its fee.
    """
    config = _settings()

    if payment.status != Payment.Status.SUCCEEDED:
        raise PaymentGatewayError("Only a successful payment can be refunded.")

    already = sum((r.amount for r in payment.refunds.all()), Decimal("0.00"))
    remaining = payment.amount - already
    amount = Decimal(amount) if amount is not None else remaining

    if amount <= 0:
        raise PaymentGatewayError("A refund must be greater than zero.")
    if amount > remaining:
        raise PaymentGatewayError(
            f"Only {remaining} {payment.currency} remains available to refund."
        )

    try:
        stripe_refund = _client(config).refunds.create(params={
            "payment_intent": payment.payment_intent_id,
            "amount": to_cents(amount),
            "metadata": {"booking_reference": payment.booking.reference},
        })
    except stripe.StripeError as exc:
        logger.error("Stripe refund failed for %s: %s", payment.booking.reference, exc)
        raise PaymentGatewayError(
            getattr(exc, "user_message", None) or "The refund could not be processed."
        ) from exc

    return Refund.objects.create(
        payment=payment,
        stripe_refund_id=stripe_refund.id,
        amount=amount,
        reason=reason,
        created_by=created_by,
    )


def apply_intent_to_payment(intent) -> Payment | None:
    """
    Bring a Payment (and its Booking) into line with a Stripe intent.

    Called from the webhook, which is the authoritative source: the browser's
    return from checkout is a hint, not proof. The legacy system trusted the
    browser.
    """
    payment = Payment.objects.filter(payment_intent_id=intent["id"]).first()
    if payment is None:
        reference = (intent.get("metadata") or {}).get("booking_reference")
        booking = Booking.objects.filter(reference=reference).first() if reference else None
        if booking is None:
            logger.warning("Webhook for unknown intent %s", intent["id"])
            return None
        payment = Payment.objects.create(
            booking=booking,
            provider=Payment.Provider.STRIPE,
            payment_intent_id=intent["id"],
            amount=Decimal(intent["amount"]) / CENTS,
            currency=(intent.get("currency") or "usd").upper(),
        )

    payment.status = STATUS_MAP.get(intent.get("status"), Payment.Status.UNKNOWN)

    charges = (intent.get("charges") or {}).get("data") or []
    if charges:
        charge = charges[0]
        payment.charge_id = charge.get("id", "")
        payment.receipt_url = charge.get("receipt_url") or ""
        details = (charge.get("payment_method_details") or {}).get("card") or {}
        payment.card_brand = (details.get("brand") or "")[:20]
        # Last four only. There is no field here that could hold more.
        payment.card_last4 = (details.get("last4") or "")[:4]

    if error := intent.get("last_payment_error"):
        payment.error_message = error.get("message", "")[:500]

    payment.save()

    # If the customer chose to keep the card on file, persist it once the money
    # has actually moved. Never fatal to the payment path.
    if (
        payment.status == Payment.Status.SUCCEEDED
        and intent.get("setup_future_usage")
        and intent.get("payment_method")
        and intent.get("customer")
        and payment.booking
        and payment.booking.customer_id
    ):
        try:
            save_card_for_user(payment.booking.customer, intent["payment_method"])
        except Exception:
            logger.exception("Could not save card from intent %s", intent.get("id"))

    booking = payment.booking
    if (
        booking
        and payment.status == Payment.Status.SUCCEEDED
        and booking.status == Booking.Status.PENDING
    ):
        BookingStatusChange.objects.create(
            booking=booking,
            from_status=booking.status,
            to_status=Booking.Status.CONFIRMED,
            note=f"Payment confirmed by Stripe ({payment.payment_intent_id})",
        )
        booking.status = Booking.Status.CONFIRMED
        booking.save(update_fields=["status", "updated_at"])
        logger.info("Booking %s confirmed by payment %s", booking.reference,
                    payment.payment_intent_id)

        # Notifications must never break the confirmation: the money has already
        # moved, and losing the booking to save an email is the wrong trade.
        # mailer never raises, but the import is local so a broken notifications
        # app cannot take the payment path down with it.
        from notifications.events import booking_confirmed

        booking_confirmed(booking)  # email + SMS + ops alert; each is self-safe

    return payment


def record_refund_from_charge(charge) -> None:
    """
    Record a refund issued outside this application.

    Staff can refund directly in the Stripe dashboard; without this the two
    systems would disagree about what a customer was charged.
    """
    payment = Payment.objects.filter(charge_id=charge.get("id")).first()
    if payment is None:
        intent_id = charge.get("payment_intent")
        payment = Payment.objects.filter(payment_intent_id=intent_id).first()
    if payment is None:
        return

    for entry in (charge.get("refunds") or {}).get("data", []):
        if Refund.objects.filter(stripe_refund_id=entry["id"]).exists():
            continue
        Refund.objects.create(
            payment=payment,
            stripe_refund_id=entry["id"],
            amount=Decimal(entry["amount"]) / CENTS,
            reason=entry.get("reason") or "Refunded in Stripe",
            created_by=None,
        )
        logger.info("Recorded external refund %s for %s", entry["id"],
                    payment.booking.reference)


def mark_settings_verified(config: PaymentSettings) -> None:
    config.updated_at = timezone.now()
    config.save(update_fields=["updated_at"])
