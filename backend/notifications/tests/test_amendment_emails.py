"""
Amendment notification emails and recipient resolution.

The recipient rule is the fiddly part: every active staff account plus one
configured admin/contact address, with a superuser fallback, deduplicated.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.utils import timezone

from bookings.models import Booking, BookingAmendmentRequest, BookingPriceLine
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
def amendment(db):
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
    return BookingAmendmentRequest.objects.create(
        booking=booking, requested_by=owner,
        requested_changes={"passenger_count": 3},
        old_total=Decimal("145.10"), new_total=Decimal("160.00"),
        new_subtotal=Decimal("160.00"), currency="USD",
    )


@pytest.mark.django_db
class TestRecipients:
    def test_staff_plus_site_admin_deduped(self):
        User.objects.create_user(email="a@x.com", is_staff=True)
        User.objects.create_user(email="b@x.com", is_staff=True)
        User.objects.create_user(email="customer@x.com", is_staff=False)
        site = SiteSettings.load()
        site.ops_notification_email = "a@x.com"  # also a staff address
        site.save()

        recipients = mailer._amendment_recipients()
        assert "a@x.com" in recipients
        assert "b@x.com" in recipients
        assert "customer@x.com" not in recipients
        assert len(recipients) == len(set(r.lower() for r in recipients))

    def test_contact_email_used_when_no_ops_address(self):
        User.objects.create_user(email="a@x.com", is_staff=True)
        site = SiteSettings.load()
        site.contact_email = "hello@x.com"
        site.save()
        assert "hello@x.com" in mailer._amendment_recipients()

    def test_superuser_fallback(self):
        User.objects.create_user(email="a@x.com", is_staff=True)
        User.objects.create_superuser(email="boss@x.com", password="X!pass2026")
        SiteSettings.load()  # no admin address configured
        assert "boss@x.com" in mailer._amendment_recipients()


@pytest.mark.django_db
class TestEmails:
    def test_requested_email_shows_diff_and_delta(self, amendment, email_on):
        User.objects.create_user(email="staff@x.com", is_staff=True)
        assert mailer.send_amendment_requested(amendment)
        body = mail.outbox[0].body
        assert amendment.booking.reference in body
        assert "Passengers" in body
        assert "160.00" in body

    def test_approved_email_goes_to_the_customer(self, amendment, email_on):
        assert mailer.send_amendment_approved(amendment)
        assert mail.outbox[0].to == [amendment.booking.contact_email]
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.AMENDMENT_APPROVED
        ).exists()

    def test_declined_email_carries_the_reason(self, amendment, email_on):
        amendment.decline_reason = "No vehicle at that time."
        amendment.save(update_fields=["decline_reason"])
        assert mailer.send_amendment_declined(amendment)
        assert "No vehicle at that time." in mail.outbox[0].body
