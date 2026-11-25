"""
Confirmation fan-out semantics.

booking_confirmed must never make the confirming request wait on SMTP/PDF/SMS:
in production it runs on a background thread started at commit. The test suite
runs with NOTIFICATIONS_SYNC=True so sends stay inline and assertable; these
tests pin both modes, plus that EmailLog still records every send.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core import mail
from django.utils import timezone

from bookings.models import Booking
from fleet.models import Vehicle
from notifications import events
from notifications.models import EmailLog, EmailSettings


@pytest.fixture(autouse=True)
def empty_outbox():
    mail.outbox.clear()
    yield
    mail.outbox.clear()


@pytest.fixture
def configured(db):
    config = EmailSettings.load()
    config.host = "mail.austinlimoshuttle.com"
    config.port = 587
    config.security = EmailSettings.Security.TLS
    config.username = "bookings@austinlimoshuttle.com"
    config.password = "MailboxLocal!2026"
    config.from_email = "bookings@austinlimoshuttle.com"
    config.from_name = "Austin Limo Shuttle"
    config.ops_notification_email = "ops@austinlimoshuttle.com"
    config.is_enabled = True
    config.save()
    return config


@pytest.fixture
def booking(db):
    vehicle = Vehicle.objects.create(name="Business Class", slug="bc", hourly_rate=85)
    return Booking.objects.create(
        vehicle=vehicle, pickup_address="ABIA", dropoff_address="Downtown",
        pickup_at=timezone.now() + timedelta(days=3),
        status=Booking.Status.CONFIRMED,
        total=Decimal("145.10"), subtotal=Decimal("145.10"), currency="USD",
        guest_email="guest@example.com", guest_phone="+15125550000",
    )


@pytest.mark.django_db
class TestBookingConfirmed:
    def test_sync_mode_sends_inline_and_logs(self, configured, booking):
        events.booking_confirmed(booking)

        recipients = {tuple(m.to) for m in mail.outbox}
        assert ("guest@example.com",) in recipients
        assert ("ops@austinlimoshuttle.com",) in recipients
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.BOOKING_CONFIRMATION, succeeded=True
        ).exists()

    def test_notify_ops_false_skips_the_office_alert(self, configured, booking):
        events.booking_confirmed(booking, notify_ops=False)
        assert all(m.to != ["ops@austinlimoshuttle.com"] for m in mail.outbox)

    def test_async_mode_returns_before_sending(self, settings, configured, booking,
                                               django_capture_on_commit_callbacks):
        """With sync off, the call itself sends nothing — a daemon thread is
        started at commit and the sends (and their EmailLog rows) happen there."""
        settings.NOTIFICATIONS_SYNC = False

        with patch.object(events.threading, "Thread") as thread:
            with django_capture_on_commit_callbacks(execute=True):
                events.booking_confirmed(booking)
                assert not thread.return_value.start.called  # waits for commit
            assert thread.return_value.start.called

        assert mail.outbox == []  # the (mocked) thread owns the sending

        # The thread body itself still sends and logs.
        fns, target_booking = thread.call_args.kwargs["args"]
        events._dispatch(fns, target_booking, close_connection=False)
        assert {tuple(m.to) for m in mail.outbox} >= {("guest@example.com",)}
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.BOOKING_CONFIRMATION, succeeded=True
        ).exists()
