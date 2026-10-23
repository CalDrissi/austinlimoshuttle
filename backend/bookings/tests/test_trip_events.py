"""DriverTripEvent: the single creation entry point + its decoupling signal."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from bookings.models import Booking, Driver, DriverTripEvent
from bookings.signals import driver_trip_event_recorded
from fleet.models import Vehicle


@pytest.fixture
def booking(db):
    vehicle = Vehicle.objects.create(name="Business Class", slug="bc", hourly_rate=85)
    return Booking.objects.create(
        vehicle=vehicle,
        pickup_address="Austin-Bergstrom International Airport",
        pickup_at=timezone.now() + timedelta(days=1),
        status=Booking.Status.CONFIRMED,
    )


@pytest.mark.django_db
class TestRecord:
    def test_record_creates_a_row_with_all_fields(self, booking):
        driver = Driver.objects.create(full_name="Alex Ruiz")
        event = DriverTripEvent.record(
            booking, DriverTripEvent.EventType.ARRIVED,
            lat=Decimal("30.194500"), lng=Decimal("-97.669800"),
            accuracy=Decimal("12.50"), driver=driver,
        )
        assert event.pk is not None
        assert DriverTripEvent.objects.count() == 1
        assert event.booking == booking
        assert event.event_type == DriverTripEvent.EventType.ARRIVED
        assert event.latitude == Decimal("30.194500")
        assert event.longitude == Decimal("-97.669800")
        assert event.location_accuracy == Decimal("12.50")
        assert event.driver == driver
        assert event.created_at is not None
        # Reachable from the booking via the published related_name.
        assert list(booking.trip_events.all()) == [event]

    def test_record_allows_null_gps_and_driver(self, booking):
        """GPS unavailable / driver not resolvable -- the ping still records."""
        event = DriverTripEvent.record(booking, DriverTripEvent.EventType.ON_WAY)
        assert event.latitude is None
        assert event.longitude is None
        assert event.location_accuracy is None
        assert event.driver is None

    def test_record_fires_the_signal_with_the_instance(self, booking):
        received = []

        def receiver(sender, instance, **kwargs):
            received.append((sender, instance))

        driver_trip_event_recorded.connect(receiver, sender=DriverTripEvent)
        try:
            event = DriverTripEvent.record(booking, DriverTripEvent.EventType.ON_BOARD)
        finally:
            driver_trip_event_recorded.disconnect(receiver, sender=DriverTripEvent)

        assert received == [(DriverTripEvent, event)]


@pytest.mark.django_db
class TestStatusProgression:
    def test_completed_event_advances_booking_to_completed(self, booking):
        assert booking.status == Booking.Status.CONFIRMED
        DriverTripEvent.record(booking, DriverTripEvent.EventType.COMPLETED)
        booking.refresh_from_db()
        assert booking.status == Booking.Status.COMPLETED

    def test_in_progress_events_do_not_change_status(self, booking):
        for et in (DriverTripEvent.EventType.ON_WAY,
                   DriverTripEvent.EventType.ARRIVED,
                   DriverTripEvent.EventType.ON_BOARD):
            DriverTripEvent.record(booking, et)
            booking.refresh_from_db()
            assert booking.status == Booking.Status.CONFIRMED

    def test_completed_never_clobbers_a_cancelled_booking(self, booking):
        booking.status = Booking.Status.CANCELLED
        booking.save()
        DriverTripEvent.record(booking, DriverTripEvent.EventType.COMPLETED)
        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED
