"""
Subscribe to cross-app signals we react to.

This module imports from `bookings`, so it must only be imported *after* the app
registry is ready -- `NotificationsConfig.ready()` imports it, never module-level
elsewhere. bookings only ever *sends* `driver_trip_event_recorded`; it never
imports notifications, so wiring the receiver here keeps the dependency one-way
and avoids an import cycle. See CONTRACTS.md -> "DriverTripEvent".
"""

from __future__ import annotations

import logging

from bookings.models import DriverTripEvent
from bookings.signals import driver_trip_event_recorded

from . import mailer

logger = logging.getLogger(__name__)


def on_driver_trip_event(sender, instance, **kwargs):
    """Send the trip-status email for a freshly recorded driver ping.

    The signal fires inside the driver's request; a notification problem must
    never bubble back and fail the ping. `mailer.send_trip_status_update` is
    already contained, but we belt-and-brace here so even an unexpected error
    (e.g. resolving a recipient) can't break signal delivery.
    """
    try:
        mailer.send_trip_status_update(instance)
    except Exception:  # pragma: no cover - defensive; mailer is already contained
        logger.exception("Trip-status email failed for event %s", getattr(instance, "pk", "?"))


def connect():
    """Wire the receiver. Called once from NotificationsConfig.ready()."""
    driver_trip_event_recorded.connect(
        on_driver_trip_event,
        sender=DriverTripEvent,
        dispatch_uid="notifications.on_driver_trip_event",
    )
