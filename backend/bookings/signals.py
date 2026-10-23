"""
Cross-lane signals emitted by the bookings core.

Keeping the signal definitions here lets other apps subscribe without the
bookings app ever importing them. A receiver connects to the signal; bookings
only ever *sends*. That one-way dependency is what keeps the lanes decoupled
(e.g. notifications can react to a driver's trip events without bookings
knowing notifications exists).
"""

from __future__ import annotations

import django.dispatch

# Fired by DriverTripEvent.record() after a new event row is committed.
#   sender   -> the DriverTripEvent model class
#   instance -> the freshly created DriverTripEvent
# Connect with: driver_trip_event_recorded.connect(receiver, sender=DriverTripEvent)
driver_trip_event_recorded = django.dispatch.Signal()
