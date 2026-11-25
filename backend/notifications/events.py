"""
One place that fires every notification for a booking event, so email and SMS
stay in lock-step no matter which path confirmed the booking (Stripe webhook,
cash, or a manual back-office booking).

Each channel is independent and self-contained: a failure in one never raises
and never stops the others -- a notification outage must not break a booking.

Confirmation fan-out runs in a background thread: SMTP + PDF render + SMS can
take tens of seconds, and the customer's confirm request must not wait on any
of it. The thread starts on transaction commit (so it can never read a booking
the request later rolls back), each send still records its EmailLog row, and
`settings.NOTIFICATIONS_SYNC = True` (tests) keeps everything inline and
deterministic.
"""

import logging
import threading

from django.conf import settings
from django.db import connection, transaction

logger = logging.getLogger(__name__)


def _safe(fn, booking):
    try:
        fn(booking)
    except Exception:
        logger.exception("Notification %s failed for %s",
                         getattr(fn, "__name__", fn), booking.reference)


def _dispatch(fns, booking, *, close_connection: bool) -> None:
    try:
        for fn in fns:
            _safe(fn, booking)
    finally:
        # A thread gets its own DB connection (EmailLog writes, related
        # queries); close it or it leaks. Never close the request's own.
        if close_connection:
            connection.close()


def booking_confirmed(booking, *, notify_ops: bool = True) -> None:
    """
    Customer confirmation by email AND SMS, plus the office alert -- sent in
    the background so the confirming request returns immediately.

    `notify_ops=False` for manual back-office bookings -- the staff member who
    just created it doesn't need a "new booking" alert about their own entry.
    """
    from . import mailer, sms

    fns = [mailer.send_booking_confirmation, sms.send_booking_confirmation]
    if notify_ops:
        fns.append(mailer.send_ops_new_booking)

    if getattr(settings, "NOTIFICATIONS_SYNC", False):
        _dispatch(fns, booking, close_connection=False)
        return

    def start() -> None:
        threading.Thread(
            target=_dispatch,
            args=(fns, booking),
            kwargs={"close_connection": True},
            name=f"notify-{booking.reference}",
            daemon=True,
        ).start()

    # Runs immediately when no transaction is open; otherwise waits for commit
    # so the thread can never race (or outlive) an uncommitted booking.
    transaction.on_commit(start)
