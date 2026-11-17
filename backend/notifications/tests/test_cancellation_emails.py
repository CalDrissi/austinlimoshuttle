"""
Cancellation notification emails.

The staff "requested" alert reuses the amendment recipient rule (every active
staff account plus one configured admin/contact address). The client-facing
"declined" email carries the staff reason; the approved case reuses the existing
booking-cancelled email with the staff-set refund amount.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from bookings.models import Booking, BookingCancellationRequest, BookingPriceLine
from content.models import SiteSettings
from fleet.models import Vehicle
from notifications import mailer
from notifications.models import EmailLog, EmailSettings

User = get_user_model()


@pytest.fixture(autouse=True)
def empty_outbox():
    mail.outbox.clear()
    yield
    mail.outbox.clear()


@pytest.fixture
def email_on(db):
    config = EmailSettings.load()
    config.host = "mail.austinlimoshuttle.com"
    config.from_email = "bookings@austinlimoshuttle.com"
    config.is_enabled = True
    config.save()
    return config


@pytest.fixture
def cancellation(db):
    vehicle = Vehicle.objects.create(name="Business Class", slug="bc", hourly_rate=85)
    owner = User.objects.create_user(
        email="rider@example.com", first_name="Sam", last_name="Ray",
    )
    booking = Booking.objects.create(
        customer=owner, vehicle=vehicle, pickup_address="ABIA",
        dropoff_address="Downtown",
        pickup_at=timezone.now() + timedelta(days=3),
        total=Decimal("145.10"), subtotal=Decimal("145.10"),
        passenger_count=2, status=Booking.Status.CONFIRMED,
    )
    BookingPriceLine.objects.create(
        booking=booking, kind=BookingPriceLine.Kind.BAND, label="25 mi",
        amount=Decimal("145.10"),
    )
    return BookingCancellationRequest.objects.create(
        booking=booking, requested_by=owner,
        paid_amount=Decimal("145.10"), currency="USD",
    )


@pytest.mark.django_db
class TestEmails:
    def test_requested_email_reaches_staff_and_admin(self, cancellation, email_on):
        User.objects.create_user(email="staff@x.com", is_staff=True)
        site = SiteSettings.load()
        site.ops_notification_email = "ops@x.com"
        site.save()

        assert mailer.send_cancellation_requested(cancellation)
        recipients = set(mail.outbox[0].to)
        assert "staff@x.com" in recipients
        assert "ops@x.com" in recipients
        body = mail.outbox[0].body
        assert cancellation.booking.reference in body
        assert "145.10" in body  # the amount paid / default refund
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.CANCELLATION_REQUESTED
        ).exists()

    def test_declined_email_carries_the_reason(self, cancellation, email_on):
        cancellation.decline_reason = "This fare is non-refundable."
        cancellation.save(update_fields=["decline_reason"])
        assert mailer.send_cancellation_declined(cancellation)
        assert mail.outbox[0].to == [cancellation.booking.contact_email]
        assert "non-refundable" in mail.outbox[0].body
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.CANCELLATION_DECLINED
        ).exists()

    def test_approved_reuses_booking_cancelled_with_refund_amount(
        self, cancellation, email_on
    ):
        """The approve path emails the client via the booking-cancelled email."""
        assert mailer.send_booking_cancelled(
            cancellation.booking, refund_amount=Decimal("45.10")
        )
        assert mail.outbox[0].to == [cancellation.booking.contact_email]
        assert "45.10" in mail.outbox[0].body
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.BOOKING_CANCELLED
        ).exists()
