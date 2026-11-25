"""
HTML email bodies must escape user-originated values.

The email base template used to render inside {% autoescape off %}, so a
booking note (or placard name, or address) containing markup went into the
HTML part verbatim — a stored-XSS payload delivered to whoever opens the
message in an HTML mail client. These tests pin the fix: hostile input renders
entity-escaped in every HTML part, while the text/plain part (where entities
would be wrong) still carries the raw text.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from bookings.models import Booking, Driver
from fleet.models import Vehicle
from notifications import mailer
from notifications.models import EmailSettings

User = get_user_model()

XSS = '<img src=x onerror=alert(1)>'
XSS_ESCAPED = "&lt;img src=x onerror=alert(1)&gt;"


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
    config.is_enabled = True
    config.save()
    return config


@pytest.fixture
def hostile_booking(db):
    vehicle = Vehicle.objects.create(name="Business Class", slug="bc", hourly_rate=85)
    customer = User.objects.create_user(
        email="rider@example.com", first_name="Sam", last_name="Ray",
    )
    driver = Driver.objects.create(
        full_name="Alex Ruiz", phone="512-555-0134", email="alex@example.com",
    )
    return Booking.objects.create(
        customer=customer, vehicle=vehicle, driver=driver,
        pickup_address="Austin-Bergstrom International Airport",
        dropoff_address="Downtown Austin",
        pickup_at=timezone.now() + timedelta(days=1),
        total=Decimal("145.10"), subtotal=Decimal("145.10"),
        passenger_count=2, status=Booking.Status.CONFIRMED,
        notes=XSS,
        pickup_sign=XSS,
    )


def _html_part(message) -> str:
    assert message.alternatives, "every email must carry an HTML part"
    return message.alternatives[0][0]


@pytest.mark.django_db
class TestHtmlPartsEscapeUserInput:
    def test_driver_job_sheet_escapes_notes_and_placard(
        self, hostile_booking, configured,
    ):
        assert mailer.send_driver_job_notification(hostile_booking)

        html = _html_part(mail.outbox[0])
        assert XSS not in html
        assert XSS_ESCAPED in html
        # The text/plain part is not HTML: the raw text is correct there.
        assert XSS in mail.outbox[0].body

    def test_booking_confirmation_escapes_the_placard(
        self, hostile_booking, configured,
    ):
        assert mailer.send_booking_confirmation(hostile_booking)

        html = _html_part(mail.outbox[0])
        assert XSS not in html
        assert XSS_ESCAPED in html

    def test_branding_and_us_format(self, hostile_booking, configured):
        """The rebrand rides along: brand name, $X.XX total, no 'USD' suffix."""
        assert mailer.send_booking_confirmation(hostile_booking)

        html = _html_part(mail.outbox[0])
        assert "M&amp;M Austin Limousine" in html
        assert "$145.10" in html
        assert "USD" not in html
        # US-style datetime, e.g. "Saturday, November 28, 2026, 1:30 PM"
        local = timezone.localtime(hostile_booking.pickup_at)
        assert local.strftime("%A, %B") in html
        assert local.strftime("%p") in html
