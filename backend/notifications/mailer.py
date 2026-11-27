"""
Transactional email.

Every send goes through `_send()`, which records an `EmailLog` row whether it
succeeded or not, and never raises. A booking must not fail because a mail
server is down -- the payment already went through, and losing the booking to
save the notification is the wrong trade.

Each message renders a plain-text and an HTML part from the same context, so
what a text-only client sees is not an afterthought.
"""

from __future__ import annotations

import logging
import smtplib
import time

from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.utils import timezone

from .models import EmailLog, EmailSettings
from .pdf import render_booking_pdf

logger = logging.getLogger(__name__)

# One retry, short pause, fresh connection. A mail server that dropped the
# connection mid-session (shared hosting recycles them aggressively) usually
# accepts the very next attempt; anything beyond one retry just delays the
# caller for a server that is actually down. TimeoutError is deliberately NOT
# here: every send runs synchronously inside a request, so retrying a timeout
# doubles an already-long block, and a timeout after DATA may mean the server
# actually accepted the message -- resending would deliver it twice.
_TRANSIENT_SMTP_ERRORS = (
    smtplib.SMTPServerDisconnected,
    smtplib.SMTPConnectError,
    ConnectionError,
)
_RETRY_BACKOFF_SECONDS = 2


def _site_settings():
    """
    SiteSettings is the one source of truth for the public contact details
    (phone, email) that templates show in the footer. EmailSettings stays what
    it is: SMTP transport config.
    """
    try:
        from content.models import SiteSettings
        return SiteSettings.load()
    except Exception:  # never let footer decoration break a send
        return None


def _site_url() -> str:
    """Absolute public site base for links in email bodies ('' hides them)."""
    from django.conf import settings as django_settings

    return (getattr(django_settings, "PUBLIC_SITE_URL", "") or "").rstrip("/")


def _us_short(dt) -> str:
    """'Sat Nov 28, 1:30 PM' — subject-line datetime, US style."""
    hour = dt.strftime("%I").lstrip("0") or "12"
    return f"{dt:%a %b} {dt.day}, {hour}:{dt:%M} {dt:%p}"


def _send(
    *,
    kind: str,
    to: list[str],
    subject: str,
    template: str,
    context: dict,
    booking=None,
    attach_pdf: bool = False,
) -> bool:
    """Render, send and log one message. Returns whether it went out."""
    config = EmailSettings.load()
    recipients = [address for address in to if address]

    if not recipients:
        return False

    if not config.is_enabled:
        EmailLog.objects.create(
            kind=kind, to_email=recipients[0], subject=subject, booking=booking,
            succeeded=False, error="Email is switched off in settings.",
        )
        return False

    context = {
        **context,
        "settings": config,
        "site": _site_settings(),
        "site_url": _site_url(),
    }

    text_body = render_to_string(f"notifications/email/{template}.txt", context)
    html_body = render_to_string(f"notifications/email/{template}.html", context)

    message = EmailMultiAlternatives(
        subject=subject.strip(),
        body=text_body,
        from_email=config.sender,
        to=recipients,
        reply_to=[config.reply_to] if config.reply_to else None,
        connection=get_connection(),
    )
    message.attach_alternative(html_body, "text/html")

    attached = False
    if attach_pdf and booking is not None:
        if pdf := render_booking_pdf(booking):
            message.attach(f"booking-{booking.reference}.pdf", pdf, "application/pdf")
            attached = True

    try:
        try:
            message.send(fail_silently=False)
        except _TRANSIENT_SMTP_ERRORS:
            logger.warning(
                "Transient SMTP failure sending %s to %s; retrying once",
                kind, recipients,
            )
            time.sleep(_RETRY_BACKOFF_SECONDS)
            # The old connection is what just died -- retry on a fresh one.
            message.connection = get_connection()
            message.send(fail_silently=False)
    except Exception as exc:
        logger.exception("Failed to send %s to %s", kind, recipients)
        EmailLog.objects.create(
            kind=kind, to_email=recipients[0], subject=subject, booking=booking,
            succeeded=False, error=str(exc)[:1000], has_attachment=attached,
        )
        return False

    EmailLog.objects.create(
        kind=kind, to_email=recipients[0], subject=subject, booking=booking,
        succeeded=True, has_attachment=attached,
    )
    return True


# -- customer-facing ---------------------------------------------------------


def send_booking_confirmation(booking) -> bool:
    """Sent once payment succeeds. Carries the itinerary and the PDF."""
    email = _customer_email(booking)
    if not email:
        return False

    return _send(
        kind=EmailLog.Kind.BOOKING_CONFIRMATION,
        to=[email],
        subject=f"We have received your booking {booking.reference}",
        template="booking_confirmation",
        context={"booking": booking, "lines": booking.price_lines.all()},
        booking=booking,
        attach_pdf=True,
    )



def send_booking_confirmed_by_staff(booking) -> bool:
    email = _customer_email(booking)
    if not email:
        return False
    return _send(
        kind=EmailLog.Kind.BOOKING_CONFIRMED_BY_STAFF, to=[email],
        subject=f"Your booking is confirmed — {booking.reference}",
        template="booking_confirmed_by_staff", context={"booking": booking},
        booking=booking,
    )


def send_driver_assigned(booking) -> bool:
    """Sent when a dispatcher assigns a driver, so the customer knows who to expect."""
    email = _customer_email(booking)
    if not email or not booking.driver:
        return False

    return _send(
        kind=EmailLog.Kind.DRIVER_ASSIGNED,
        to=[email],
        subject=f"Your driver for {booking.reference}",
        template="driver_assigned",
        context={"booking": booking, "driver": booking.driver},
        booking=booking,
    )


def send_driver_job_notification(booking) -> bool:
    """
    The driver's own copy of an assignment -- the job sheet.

    The customer email above says who is coming; this one tells the chauffeur
    where to be and when, with the passenger's name and phone so they can call
    from the kerb. A driver without an email address on file is skipped quietly:
    plenty of drivers are dispatched by phone, and assignment must not depend on
    this message going out.
    """
    driver = booking.driver
    if not driver or not driver.email:
        return False

    # localtime: the body's |date filter renders site time, and a subject line
    # six hours off is the one a driver plans their day from.
    pickup_local = timezone.localtime(booking.pickup_at)
    return _send(
        kind=EmailLog.Kind.DRIVER_JOB_ASSIGNED,
        to=[driver.email],
        subject=f"New job — {booking.reference}, {_us_short(pickup_local)}",
        template="driver_job_assigned",
        context={"booking": booking, "driver": driver},
        booking=booking,
    )


def send_booking_cancelled(booking, *, refund_amount=None) -> bool:
    email = _customer_email(booking)
    if not email:
        return False

    return _send(
        kind=EmailLog.Kind.BOOKING_CANCELLED,
        to=[email],
        subject=f"Booking {booking.reference} cancelled",
        template="booking_cancelled",
        context={"booking": booking, "refund_amount": refund_amount},
        booking=booking,
    )


def send_pickup_reminder(booking) -> bool:
    email = _customer_email(booking)
    if not email:
        return False

    return _send(
        kind=EmailLog.Kind.PICKUP_REMINDER,
        to=[email],
        subject=f"Your pickup tomorrow — {booking.reference}",
        template="pickup_reminder",
        context={"booking": booking},
        booking=booking,
    )


# -- amendment requests ------------------------------------------------------


def _amendment_recipients() -> list[str]:
    """
    Who reviews a customer's change request: every active staff account plus a
    single configured admin/contact address.

    Staff accounts (`is_staff=True`) are the people who can actually act on the
    request in the back office. The extra admin address is a catch-all for the
    operator's own inbox: the first of SiteSettings.ops_notification_email, the
    public contact address, the SMTP ops address, or -- as a last resort -- the
    superuser's own email, so the alert is never silently addressed to nobody.
    Deduplicated, order preserved; `_send` drops any blanks.
    """
    from django.contrib.auth import get_user_model

    recipients: list[str] = []

    User = get_user_model()
    staff_emails = (
        User.objects.filter(is_staff=True, is_active=True)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    recipients.extend(staff_emails)

    admin_email = ""
    try:
        from content.models import SiteSettings

        site = SiteSettings.load()
        admin_email = site.ops_notification_email or site.contact_email
    except Exception:  # SiteSettings is optional; never block the alert on it
        admin_email = ""
    if not admin_email:
        admin_email = EmailSettings.load().ops_notification_email
    if not admin_email:
        superuser = (
            User.objects.filter(is_superuser=True, is_active=True)
            .exclude(email="")
            .values_list("email", flat=True)
            .first()
        )
        admin_email = superuser or ""
    if admin_email:
        recipients.append(admin_email)

    # Preserve order, drop duplicates (a staff member who is also the admin).
    seen: set[str] = set()
    unique = []
    for address in recipients:
        key = address.lower()
        if address and key not in seen:
            seen.add(key)
            unique.append(address)
    return unique


def _review_url(booking) -> str:
    """Link staff follow to review the request. Absolute in prod, relative in dev."""
    from django.conf import settings as django_settings

    base = getattr(django_settings, "DASHBOARD_BASE_URL", "") or ""
    return f"{base}/dashboard/bookings/{booking.reference}/"


def send_amendment_requested(amendment) -> bool:
    """
    Alert staff + the admin address that a customer wants to change a booking.

    Shows the booking reference, the customer, the OLD -> NEW diff and the price
    delta, plus a link into the back office to approve or decline it. Never
    raises -- a mail failure must not lose the pending request.
    """
    booking = amendment.booking
    return _send(
        kind=EmailLog.Kind.AMENDMENT_REQUESTED,
        to=_amendment_recipients(),
        subject=f"Change requested — {booking.reference}",
        template="amendment_requested",
        context={
            "booking": booking,
            "amendment": amendment,
            "changes": amendment.changed_fields(),
            "price_delta": amendment.price_delta,
            "review_url": _review_url(booking),
        },
        booking=booking,
    )


def send_amendment_received(amendment) -> bool:
    """
    Acknowledge the customer's change request the moment it is filed.

    Staff review can take hours; without this the customer stares at an inbox
    wondering whether the request even went through. Plainly states that nothing
    has changed yet and that a confirmation (or decline) follows.
    """
    booking = amendment.booking
    email = _customer_email(booking)
    if not email:
        return False

    return _send(
        kind=EmailLog.Kind.AMENDMENT_RECEIVED,
        to=[email],
        subject=f"We received your change request — {booking.reference}",
        template="amendment_received",
        context={
            "booking": booking,
            "amendment": amendment,
            "changes": amendment.changed_fields(),
            "price_delta": amendment.price_delta,
        },
        booking=booking,
    )


def send_amendment_approved(amendment) -> bool:
    """Tell the customer their requested change is confirmed, with the new fare."""
    booking = amendment.booking
    email = _customer_email(booking)
    if not email:
        return False

    return _send(
        kind=EmailLog.Kind.AMENDMENT_APPROVED,
        to=[email],
        subject=f"Your change is confirmed — {booking.reference}",
        template="amendment_approved",
        context={
            "booking": booking,
            "amendment": amendment,
            "lines": booking.price_lines.all(),
            "price_delta": amendment.price_delta,
        },
        booking=booking,
    )


def send_amendment_declined(amendment) -> bool:
    """Tell the customer their requested change was declined, with the reason."""
    booking = amendment.booking
    email = _customer_email(booking)
    if not email:
        return False

    return _send(
        kind=EmailLog.Kind.AMENDMENT_DECLINED,
        to=[email],
        subject=f"About your requested change — {booking.reference}",
        template="amendment_declined",
        context={
            "booking": booking,
            "amendment": amendment,
            "changes": amendment.changed_fields(),
            "reason": amendment.decline_reason,
        },
        booking=booking,
    )


def send_cancellation_requested(cancellation) -> bool:
    """
    Alert staff + the admin address that a customer wants to cancel a booking.

    Shows the booking, the customer and what they had paid (the default refund),
    plus a link into the back office to approve (with a staff-set refund) or
    decline. Shares the amendment recipient logic -- every active staff account
    plus the configured admin/contact address. Never raises.
    """
    booking = cancellation.booking
    return _send(
        kind=EmailLog.Kind.CANCELLATION_REQUESTED,
        to=_amendment_recipients(),
        subject=f"Cancellation requested — {booking.reference}",
        template="cancellation_requested",
        context={
            "booking": booking,
            "cancellation": cancellation,
            "review_url": _review_url(booking),
        },
        booking=booking,
    )


def send_cancellation_received(cancellation) -> bool:
    """
    Acknowledge the customer's cancellation request the moment it is filed.

    Explicit that the booking still stands until staff approve -- the worst
    outcome would be a customer who believes they cancelled, skips the pickup,
    and is charged for a no-show.
    """
    booking = cancellation.booking
    email = _customer_email(booking)
    if not email:
        return False

    return _send(
        kind=EmailLog.Kind.CANCELLATION_RECEIVED,
        to=[email],
        subject=f"We received your cancellation request — {booking.reference}",
        template="cancellation_received",
        context={"booking": booking, "cancellation": cancellation},
        booking=booking,
    )


def send_cancellation_declined(cancellation) -> bool:
    """Tell the customer their cancellation request was declined; booking stands."""
    booking = cancellation.booking
    email = _customer_email(booking)
    if not email:
        return False

    return _send(
        kind=EmailLog.Kind.CANCELLATION_DECLINED,
        to=[email],
        subject=f"About your cancellation request — {booking.reference}",
        template="cancellation_declined",
        context={
            "booking": booking,
            "cancellation": cancellation,
            "reason": cancellation.decline_reason,
        },
        booking=booking,
    )


# -- operations --------------------------------------------------------------


def send_ops_new_booking(booking) -> bool:
    """Alert the office. Without this, a booking taken at 3am is a surprise."""
    config = EmailSettings.load()
    if not config.ops_notification_email:
        return False

    pickup_local = timezone.localtime(booking.pickup_at)
    return _send(
        kind=EmailLog.Kind.OPS_NEW_BOOKING,
        to=[config.ops_notification_email],
        subject=f"New booking {booking.reference} — {_us_short(pickup_local)}",
        template="ops_new_booking",
        context={"booking": booking},
        booking=booking,
    )


# -- trip status (driver live events) ----------------------------------------

# Who hears about each live trip ping. "On the way" / "Arrived" are the moments
# a waiting rider cares about, so they reach the customer as well as the office.
# "On board" is an operational checkpoint -- the office tracks it, but the
# customer is already in the car, so we don't buzz their inbox. "Completed"
# reaches the customer too, but as its own thank-you message (with the receipt),
# not a copy of the operational notice.
_TRIP_EVENT_TO_CLIENT = {
    "on_way": True,
    "arrived": True,
    "on_board": False,
    "completed": True,
}

_TRIP_EVENT_SUBJECT = {
    "on_way": "Your driver is on the way — {ref}",
    "arrived": "Your driver has arrived — {ref}",
    "on_board": "Passenger on board — {ref}",
    "completed": "Trip completed — {ref}",
}


def send_trip_status_update(event) -> bool:
    """
    Email a driver's live trip-status ping to the office (and, for the events a
    rider is waiting on, the customer). Driven by `driver_trip_event_recorded`.

    Like every send here it never raises: a flaky mail server must not break a
    driver's status ping. A blank recipient is dropped by `_send`, so an event
    with no customer address still reaches the office; a ping with no GPS fix
    sends without the map line.
    """
    event_type = event.event_type
    if event_type not in _TRIP_EVENT_SUBJECT:
        return False

    booking = event.booking
    config = EmailSettings.load()

    # "Completed" is the one client-facing event where the office and the
    # customer get different messages: an operational notice for dispatch, a
    # thank-you with the receipt for the rider (sent separately below).
    to_client = _TRIP_EVENT_TO_CLIENT.get(event_type, False)
    recipients = [config.ops_notification_email]
    if to_client and event_type != "completed":
        recipients.append(_customer_email(booking))

    driver = event.driver or booking.driver
    has_location = event.latitude is not None and event.longitude is not None

    ok = _send(
        kind=EmailLog.Kind.TRIP_STATUS,
        to=recipients,
        subject=_TRIP_EVENT_SUBJECT[event_type].format(ref=booking.reference),
        template=f"trip_{event_type}",
        context={
            "booking": booking,
            "event": event,
            "driver": driver,
            "driver_name": driver.full_name if driver else "",
            "status_label": event.get_event_type_display(),
            "has_location": has_location,
        },
        booking=booking,
    )

    if to_client and event_type == "completed":
        send_trip_completed_client(booking, driver=driver)

    return ok


def send_trip_completed_client(booking, *, driver=None) -> bool:
    """
    Thank the customer once the driver marks the trip complete.

    Carries the Stripe receipt link when a card payment exists; a cash booking
    simply sends without the receipt line. Deduplicated on EmailLog like the
    pickup reminder: a driver double-tapping "Completed" on a flaky connection
    records two events, and the customer must not get two thank-yous.
    """
    email = _customer_email(booking)
    if not email:
        return False

    if EmailLog.objects.filter(
        kind=EmailLog.Kind.TRIP_COMPLETED_CLIENT, booking=booking, succeeded=True,
    ).exists():
        return False

    from payments.models import Payment

    payment = booking.payments.filter(status=Payment.Status.SUCCEEDED).first()
    receipt_url = payment.receipt_url if payment else ""

    return _send(
        kind=EmailLog.Kind.TRIP_COMPLETED_CLIENT,
        to=[email],
        subject=f"Thanks for riding with us — {booking.reference}",
        template="trip_completed_client",
        context={
            "booking": booking,
            "driver": driver or booking.driver,
            "receipt_url": receipt_url,
        },
        booking=booking,
    )


def send_test_message(to_email: str) -> tuple[bool, str]:
    """
    Send a test message and record the outcome on the settings row.

    Deliverability is invisible until something is actually sent, so this exists
    to prove the credentials work before a real customer depends on them.
    """
    config = EmailSettings.load()
    ok = _send(
        kind=EmailLog.Kind.TEST,
        to=[to_email],
        subject="M&M Austin Limousine — test message",
        template="test_message",
        context={"sent_at": timezone.now()},
    )

    log = EmailLog.objects.filter(kind=EmailLog.Kind.TEST).first()
    error = "" if ok else (log.error if log else "Unknown error")

    config.last_test_at = timezone.now()
    config.last_test_ok = ok
    config.last_test_error = error
    config.save(update_fields=["last_test_at", "last_test_ok", "last_test_error"])

    return ok, error


def _customer_email(booking) -> str:
    """Account address if there is one, otherwise the guest address."""
    return booking.contact_email
