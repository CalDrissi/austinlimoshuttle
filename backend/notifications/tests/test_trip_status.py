"""
Trip-status emails driven by the driver's live pings.

These assert the routing contract: "on the way" / "arrived" reach the office
*and* the customer, while "on board" / "completed" are office-only. They also
pin the two ways this must never break a driver's ping -- a customer with no
email, and a ping with no GPS fix.

Every test goes through `DriverTripEvent.record()` (the real creation entry
point), so it exercises the whole path: record -> signal -> receiver -> mailer.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from bookings.models import Booking, DriverTripEvent, Driver
from fleet.models import Vehicle
from notifications.models import EmailLog, EmailSettings

User = get_user_model()

OPS = "ops@austinlimoshuttle.com"
CLIENT = "rider@example.com"


@pytest.fixture(autouse=True)
def empty_outbox():
    mail.outbox.clear()
    yield
    mail.outbox.clear()


@pytest.fixture
def configured(db):
    config = EmailSettings.load()
    config.host = "mail.austinlimoshuttle.com"
    config.from_email = "bookings@austinlimoshuttle.com"
    config.from_name = "Austin Limo Shuttle"
    config.ops_notification_email = OPS
    config.is_enabled = True
    config.save()
    return config


@pytest.fixture
def driver(db):
    return Driver.objects.create(full_name="Alex Ruiz", phone="512-555-0134")


@pytest.fixture
def booking(db, driver):
    vehicle = Vehicle.objects.create(name="Business Class", slug="bc", hourly_rate=85)
    customer = User.objects.create_user(
        email=CLIENT, first_name="Sam", last_name="Ray",
    )
    return Booking.objects.create(
        customer=customer, vehicle=vehicle, driver=driver,
        pickup_address="Austin-Bergstrom International Airport",
        dropoff_address="Downtown Austin",
        pickup_at=timezone.now() + timedelta(days=1),
        total=Decimal("145.10"), subtotal=Decimal("145.10"),
        status=Booking.Status.CONFIRMED,
    )


@pytest.mark.django_db
class TestRouting:
    @pytest.mark.parametrize("event_type", ["on_way", "arrived"])
    def test_client_events_reach_admin_and_client(self, booking, driver, configured, event_type):
        DriverTripEvent.record(booking, event_type, driver=driver)

        assert len(mail.outbox) == 1
        assert set(mail.outbox[0].to) == {OPS, CLIENT}

    @pytest.mark.parametrize("event_type", ["on_board", "completed"])
    def test_operational_events_reach_admin_only(self, booking, driver, configured, event_type):
        DriverTripEvent.record(booking, event_type, driver=driver)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [OPS]

    def test_body_carries_reference_driver_and_time(self, booking, driver, configured):
        DriverTripEvent.record(booking, "on_way", driver=driver)

        body = mail.outbox[0].body
        assert booking.reference in body
        assert "Alex Ruiz" in body
        year = timezone.localtime(booking.trip_events.get().created_at).strftime("%Y")
        assert year in body

    def test_is_logged_as_trip_status(self, booking, driver, configured):
        DriverTripEvent.record(booking, "arrived", driver=driver)

        log = EmailLog.objects.get()
        assert log.kind == EmailLog.Kind.TRIP_STATUS
        assert log.succeeded
        assert log.booking == booking


@pytest.mark.django_db
class TestLocation:
    def test_gps_fix_adds_a_map_link(self, booking, driver, configured):
        DriverTripEvent.record(
            booking, "on_way", lat=Decimal("30.194500"), lng=Decimal("-97.669800"),
            accuracy=Decimal("12.00"), driver=driver,
        )

        body = mail.outbox[0].body
        assert "30.194500" in body and "-97.669800" in body
        assert "maps" in body

    def test_null_gps_still_sends_without_a_map_link(self, booking, driver, configured):
        DriverTripEvent.record(booking, "on_way", lat=None, lng=None, driver=driver)

        assert len(mail.outbox) == 1
        assert "maps?q=" not in mail.outbox[0].body
        # The rest of the message is intact.
        assert booking.reference in mail.outbox[0].body


@pytest.mark.django_db
class TestMissingRecipients:
    def _guest_booking(self, *, email=""):
        vehicle = Vehicle.objects.create(name="V", slug="v", hourly_rate=50)
        return Booking.objects.create(
            vehicle=vehicle, pickup_address="a",
            pickup_at=timezone.now() + timedelta(days=1),
            total=Decimal("50.00"), guest_email=email,
        )

    def test_missing_client_email_still_emails_admin(self, configured):
        booking = self._guest_booking(email="")  # no customer, no guest email
        DriverTripEvent.record(booking, "on_way")

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [OPS]

    def test_missing_admin_and_client_sends_nothing_but_does_not_crash(self, configured):
        configured.ops_notification_email = ""
        configured.save()
        booking = self._guest_booking(email="")

        # Must not raise even though there is nobody to notify.
        event = DriverTripEvent.record(booking, "on_board")

        assert event is not None
        assert len(mail.outbox) == 0

    def test_operational_event_ignores_a_present_client_address(self, booking, configured):
        # on_board is office-only even when the booking has a customer email.
        DriverTripEvent.record(booking, "on_board")

        assert mail.outbox[0].to == [OPS]
        assert CLIENT not in mail.outbox[0].to


@pytest.mark.django_db
class TestSignalWiring:
    def test_record_triggers_exactly_one_email_via_the_signal(self, booking, configured):
        # No direct mailer call here -- the email only happens if the receiver
        # is actually connected in AppConfig.ready().
        DriverTripEvent.record(booking, "arrived")
        assert len(mail.outbox) == 1
