"""
The driver's own job-sheet email, transient-error retry, and the dashboard
failed-email surfacing.

The job sheet is the mirror image of the customer's driver-assigned email: it
goes TO the driver, must carry the passenger's contact details, and must skip
quietly when the driver has no address on file -- assignment can never depend
on the email going out.
"""

import smtplib
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, Driver
from dashboard.permissions import DISPATCHER, sync_roles
from fleet.models import Vehicle
from notifications import mailer
from notifications.models import EmailLog, EmailSettings

User = get_user_model()
PASSWORD = "DriverJobLocal!2026"


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
    config.is_enabled = True
    config.save()
    return config


@pytest.fixture
def driver(db):
    return Driver.objects.create(
        full_name="Alex Ruiz", phone="512-555-0134", email="alex@example.com",
    )


@pytest.fixture
def booking(db, driver):
    vehicle = Vehicle.objects.create(name="Business Class", slug="bc", hourly_rate=85)
    customer = User.objects.create_user(
        email="rider@example.com", first_name="Sam", last_name="Ray",
    )
    return Booking.objects.create(
        customer=customer, vehicle=vehicle, driver=driver,
        pickup_address="Austin-Bergstrom International Airport",
        dropoff_address="Downtown Austin",
        pickup_at=timezone.now() + timedelta(days=1),
        total=Decimal("145.10"), subtotal=Decimal("145.10"),
        passenger_count=2, status=Booking.Status.CONFIRMED,
        notes="Two large suitcases.",
    )


@pytest.mark.django_db
class TestDriverJobEmail:
    def test_goes_to_the_driver_with_the_job_details(self, booking, driver, configured):
        assert mailer.send_driver_job_notification(booking)

        message = mail.outbox[0]
        assert message.to == ["alex@example.com"]
        assert booking.reference in message.body
        assert "Sam Ray" in message.body  # the passenger, so the driver can call
        assert "Two large suitcases." in message.body
        assert booking.pickup_address in message.body

        log = EmailLog.objects.get()
        assert log.kind == EmailLog.Kind.DRIVER_JOB_ASSIGNED
        assert log.succeeded
        assert log.booking == booking

    def test_driver_without_an_email_is_skipped_quietly(self, booking, driver, configured):
        driver.email = ""
        driver.save(update_fields=["email"])
        booking.refresh_from_db()

        assert mailer.send_driver_job_notification(booking) is False
        assert mail.outbox == []
        assert not EmailLog.objects.exists()

    def test_booking_without_a_driver_is_skipped(self, booking, configured):
        booking.driver = None
        booking.save()

        assert mailer.send_driver_job_notification(booking) is False
        assert mail.outbox == []

    def test_dashboard_assignment_emails_customer_and_driver(
        self, client, booking, driver, configured
    ):
        """The booking-update view fires both sides of the assignment."""
        sync_roles()
        user = User.objects.create_user(
            email="dispatcher@example.com", password=PASSWORD, is_staff=True,
        )
        user.groups.add(Group.objects.get(name=DISPATCHER))
        client.login(username="dispatcher@example.com", password=PASSWORD)

        booking.driver = None
        booking.save()
        client.post(
            reverse("dashboard:booking_update", args=[booking.reference]),
            {"status": "", "driver": str(driver.pk), "note": ""},
        )

        recipients = {tuple(m.to) for m in mail.outbox}
        assert ("rider@example.com",) in recipients  # customer: who to expect
        assert ("alex@example.com",) in recipients  # driver: the job sheet
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.DRIVER_JOB_ASSIGNED, succeeded=True,
        ).exists()


@pytest.mark.django_db
class TestTransientRetry:
    def test_disconnected_server_is_retried_once_and_succeeds(
        self, booking, configured, monkeypatch
    ):
        monkeypatch.setattr(mailer, "_RETRY_BACKOFF_SECONDS", 0)
        with patch(
            "notifications.mailer.EmailMultiAlternatives.send",
            side_effect=[smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), 1],
        ) as mocked:
            assert mailer.send_driver_job_notification(booking)

        assert mocked.call_count == 2
        log = EmailLog.objects.get()
        assert log.succeeded

    def test_persistent_disconnect_fails_after_one_retry(
        self, booking, configured, monkeypatch
    ):
        monkeypatch.setattr(mailer, "_RETRY_BACKOFF_SECONDS", 0)
        with patch(
            "notifications.mailer.EmailMultiAlternatives.send",
            side_effect=smtplib.SMTPServerDisconnected("Connection unexpectedly closed"),
        ) as mocked:
            assert mailer.send_driver_job_notification(booking) is False

        assert mocked.call_count == 2  # one retry, not an endless loop
        log = EmailLog.objects.get()
        assert not log.succeeded
        assert "Connection unexpectedly closed" in log.error

    def test_permanent_errors_are_not_retried(self, booking, configured, monkeypatch):
        monkeypatch.setattr(mailer, "_RETRY_BACKOFF_SECONDS", 0)
        with patch(
            "notifications.mailer.EmailMultiAlternatives.send",
            side_effect=smtplib.SMTPRecipientsRefused({"alex@example.com": (550, b"no")}),
        ) as mocked:
            assert mailer.send_driver_job_notification(booking) is False

        assert mocked.call_count == 1  # a refused recipient won't improve on retry
        assert not EmailLog.objects.get().succeeded


@pytest.mark.django_db
class TestDashboardFailureSurfacing:
    def _login(self, client):
        sync_roles()
        user = User.objects.create_user(
            email="dispatcher@example.com", password=PASSWORD, is_staff=True,
        )
        user.groups.add(Group.objects.get(name=DISPATCHER))
        client.login(username="dispatcher@example.com", password=PASSWORD)

    def test_recent_failures_appear_on_the_home_page(self, client, booking, db):
        self._login(client)
        EmailLog.objects.create(
            kind=EmailLog.Kind.BOOKING_CONFIRMATION, to_email="rider@example.com",
            subject="Your booking is confirmed", booking=booking,
            succeeded=False, error="Connection unexpectedly closed",
        )

        response = client.get(reverse("dashboard:home"))
        content = response.content.decode()
        assert "failed to send" in content
        assert "rider@example.com" in content
        assert "Connection unexpectedly closed" in content

    def test_quiet_when_nothing_failed(self, client, db):
        self._login(client)
        EmailLog.objects.create(
            kind=EmailLog.Kind.TEST, to_email="ok@example.com",
            subject="Test", succeeded=True,
        )

        response = client.get(reverse("dashboard:home"))
        assert "failed to send" not in response.content.decode()

    def test_old_failures_do_not_count(self, client, db):
        self._login(client)
        log = EmailLog.objects.create(
            kind=EmailLog.Kind.TEST, to_email="old@example.com",
            subject="Old failure", succeeded=False, error="ancient history",
        )
        # sent_at is auto_now_add; push it outside the 7-day window directly.
        EmailLog.objects.filter(pk=log.pk).update(
            sent_at=timezone.now() - timedelta(days=10)
        )

        response = client.get(reverse("dashboard:home"))
        assert "failed to send" not in response.content.decode()
