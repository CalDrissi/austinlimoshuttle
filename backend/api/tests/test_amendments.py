"""
Client booking-edit -> staff approval workflow.

A customer no longer edits a booking directly: an edit files a pending request
that staff approve or decline. The properties that matter here:

  * the booking is NOT touched while a request is pending,
  * the amendment window is enforced the same as a direct amend,
  * approval applies the change, re-prices and emails the customer,
  * decline leaves the booking alone and emails the reason,
  * only the owner may request, only staff may review.
"""

from datetime import time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, BookingAmendmentRequest, BookingPriceLine
from content.models import SiteSettings
from fleet.models import DistanceBand, Vehicle
from notifications.models import EmailLog, EmailSettings
from pricing.models import PricingSettings, TimeSurcharge

User = get_user_model()
PASSWORD = "AmendLocal!2026"


@pytest.fixture(autouse=True)
def empty_outbox():
    mail.outbox.clear()
    yield
    mail.outbox.clear()


@pytest.fixture
def email_on(db):
    """Enabled SMTP settings so the mailer actually sends (and logs)."""
    config = EmailSettings.load()
    config.host = "mail.austinlimoshuttle.com"
    config.from_email = "bookings@austinlimoshuttle.com"
    config.from_name = "Austin Limo Shuttle"
    config.is_enabled = True
    config.save()
    return config


@pytest.fixture
def vehicle(db):
    v = Vehicle.objects.create(
        name="Business Class", slug="bc", hourly_rate=Decimal("85.00"),
        minimum_fare=Decimal("95.00"), is_active=True,
        passenger_capacity=4, luggage_capacity=4,
    )
    for start, end, rate in [(0, 6, "15.00"), (6, 50, "2.90"),
                             (50, 100, "2.20"), (100, None, "1.50")]:
        DistanceBand.objects.create(vehicle=v, from_miles=start, to_miles=end,
                                    rate_per_mile=Decimal(rate))
    PricingSettings.load()
    return v


def make_owner(email="rider@example.com"):
    return User.objects.create_user(
        email=email, password=PASSWORD, first_name="Sam", last_name="Ray",
        phone="+15125550100",
    )


def make_booking(owner, vehicle, *, days_ahead=5):
    booking = Booking.objects.create(
        customer=owner, vehicle=vehicle,
        pickup_address="Austin-Bergstrom International Airport",
        dropoff_address="Downtown Austin",
        pickup_at=timezone.now() + timedelta(days=days_ahead),
        distance_miles=Decimal("25"),
        subtotal=Decimal("145.10"), total=Decimal("145.10"),
        passenger_count=2, luggage_count=1,
        status=Booking.Status.CONFIRMED, currency="USD",
    )
    BookingPriceLine.objects.create(
        booking=booking, kind=BookingPriceLine.Kind.BAND,
        label="25 mi", amount=Decimal("145.10"),
    )
    return booking


def amend_url(booking):
    return reverse("api:amend_request", args=[booking.reference])


@pytest.mark.django_db
class TestAmendRequestCreation:
    def test_owner_request_creates_pending_without_mutating_the_booking(
        self, client, vehicle
    ):
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        client.login(username=owner.email, password=PASSWORD)

        response = client.post(
            amend_url(booking),
            {"passenger_count": 3, "notes": "Two car seats please"},
            content_type="application/json",
        )
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"

        booking.refresh_from_db()
        assert booking.passenger_count == 2  # unchanged
        assert booking.notes == ""  # unchanged
        req = BookingAmendmentRequest.objects.get(booking=booking)
        assert req.status == BookingAmendmentRequest.Status.PENDING
        assert req.requested_changes["passenger_count"] == 3

    def test_pickup_time_change_is_repriced_on_the_request(self, client, vehicle):
        # A night surcharge so moving the pickup into it changes the fare.
        TimeSurcharge.objects.create(
            name="Night", start_time=time(21, 0), end_time=time(6, 0),
            percentage=Decimal("20.00"), is_active=True,
        )
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        client.login(username=owner.email, password=PASSWORD)

        night = timezone.localtime(timezone.now() + timedelta(days=5)).replace(
            hour=23, minute=0, second=0, microsecond=0
        )
        response = client.post(
            amend_url(booking),
            {"pickup_at": night.isoformat()},
            content_type="application/json",
        )
        assert response.status_code == 201
        req = BookingAmendmentRequest.objects.get(booking=booking)
        assert req.new_total > req.old_total  # surcharge applied
        booking.refresh_from_db()
        assert booking.total == Decimal("145.10")  # booking still untouched

    def test_no_op_request_is_rejected(self, client, vehicle):
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        client.login(username=owner.email, password=PASSWORD)
        response = client.post(
            amend_url(booking),
            {"passenger_count": booking.passenger_count},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_within_the_amendment_window_is_rejected(self, client, vehicle):
        settings = PricingSettings.load()
        settings.amendment_window_hours = 48
        settings.save()
        owner = make_owner()
        booking = make_booking(owner, vehicle, days_ahead=1)  # inside 48h
        client.login(username=owner.email, password=PASSWORD)

        response = client.post(
            amend_url(booking),
            {"passenger_count": 3},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "within 48 hours" in response.json()["detail"]
        assert not BookingAmendmentRequest.objects.exists()

    def test_second_pending_request_is_rejected(self, client, vehicle):
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        client.login(username=owner.email, password=PASSWORD)
        first = client.post(
            amend_url(booking), {"passenger_count": 3},
            content_type="application/json",
        )
        assert first.status_code == 201
        second = client.post(
            amend_url(booking), {"passenger_count": 4},
            content_type="application/json",
        )
        assert second.status_code == 400
        assert BookingAmendmentRequest.objects.count() == 1

    def test_over_capacity_request_is_rejected(self, client, vehicle):
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        client.login(username=owner.email, password=PASSWORD)
        response = client.post(
            amend_url(booking), {"passenger_count": 99},
            content_type="application/json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestAmendRequestPermissions:
    def test_anonymous_is_rejected(self, client, vehicle):
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        response = client.post(
            amend_url(booking), {"passenger_count": 3},
            content_type="application/json",
        )
        assert response.status_code in (401, 403)

    def test_another_customer_gets_404(self, client, vehicle):
        owner = make_owner("owner@example.com")
        booking = make_booking(owner, vehicle)
        User.objects.create_user(email="other@example.com", password=PASSWORD)
        client.login(username="other@example.com", password=PASSWORD)
        response = client.post(
            amend_url(booking), {"passenger_count": 3},
            content_type="application/json",
        )
        assert response.status_code == 404
        assert not BookingAmendmentRequest.objects.exists()


@pytest.mark.django_db
class TestAmendRequestNotifies:
    def test_request_emails_staff_and_the_admin_address(
        self, client, vehicle, email_on
    ):
        # Two staff accounts and a configured admin/contact address.
        User.objects.create_user(
            email="dispatch@austinlimoshuttle.com", password=PASSWORD,
            is_staff=True,
        )
        User.objects.create_user(
            email="manager@austinlimoshuttle.com", password=PASSWORD,
            is_staff=True,
        )
        site = SiteSettings.load()
        site.ops_notification_email = "ops@austinlimoshuttle.com"
        site.save()

        owner = make_owner()
        booking = make_booking(owner, vehicle)
        client.login(username=owner.email, password=PASSWORD)
        response = client.post(
            amend_url(booking), {"passenger_count": 3},
            content_type="application/json",
        )
        assert response.status_code == 201

        assert len(mail.outbox) == 1
        recipients = set(mail.outbox[0].to)
        assert "dispatch@austinlimoshuttle.com" in recipients
        assert "manager@austinlimoshuttle.com" in recipients
        assert "ops@austinlimoshuttle.com" in recipients
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.AMENDMENT_REQUESTED, succeeded=True
        ).exists()

    def test_admin_falls_back_to_superuser_when_unset(
        self, client, vehicle, email_on
    ):
        boss = User.objects.create_superuser(
            email="boss@austinlimoshuttle.com", password=PASSWORD,
        )
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        client.login(username=owner.email, password=PASSWORD)
        client.post(
            amend_url(booking), {"passenger_count": 3},
            content_type="application/json",
        )
        assert boss.email in set(mail.outbox[0].to)


@pytest.mark.django_db
class TestStaffReview:
    def _staff(self):
        return User.objects.create_user(
            email="staff@austinlimoshuttle.com", password=PASSWORD, is_staff=True,
        )

    def _pending(self, owner, vehicle, **changes):
        booking = make_booking(owner, vehicle)
        return BookingAmendmentRequest.objects.create(
            booking=booking, requested_by=owner,
            requested_changes=changes or {"passenger_count": 3},
            old_total=booking.total, new_subtotal=booking.subtotal,
            new_tax=booking.tax, new_total=booking.total, currency="USD",
        )

    def test_approve_applies_change_and_emails_the_client(
        self, client, vehicle, email_on
    ):
        owner = make_owner()
        req = self._pending(owner, vehicle, passenger_count=3,
                            notes="Two car seats please")
        staff = self._staff()
        client.login(username=staff.email, password=PASSWORD)

        response = client.post(
            reverse("api:staff_amendment_approve", args=[req.pk])
        )
        assert response.status_code == 200
        assert response.json()["status"] == "approved"

        req.refresh_from_db()
        assert req.status == BookingAmendmentRequest.Status.APPROVED
        assert req.reviewed_by == staff
        assert req.reviewed_at is not None

        booking = req.booking
        booking.refresh_from_db()
        assert booking.passenger_count == 3
        assert booking.notes == "Two car seats please"

        # Customer notified that the change is confirmed.
        assert any(
            m.to == [owner.email] and "confirmed" in m.subject.lower()
            for m in mail.outbox
        )
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.AMENDMENT_APPROVED, succeeded=True
        ).exists()

    def test_approve_reprices_when_the_pickup_time_moves(
        self, client, vehicle, email_on
    ):
        TimeSurcharge.objects.create(
            name="Night", start_time=time(21, 0), end_time=time(6, 0),
            percentage=Decimal("20.00"), is_active=True,
        )
        owner = make_owner()
        booking = make_booking(owner, vehicle)
        night = timezone.localtime(timezone.now() + timedelta(days=5)).replace(
            hour=23, minute=0, second=0, microsecond=0
        )
        req = BookingAmendmentRequest.objects.create(
            booking=booking, requested_by=owner,
            requested_changes={"pickup_at": night.isoformat()},
            old_total=booking.total, new_total=booking.total, currency="USD",
        )
        staff = self._staff()
        client.login(username=staff.email, password=PASSWORD)
        client.post(reverse("api:staff_amendment_approve", args=[req.pk]))

        booking.refresh_from_db()
        assert timezone.localtime(booking.pickup_at).hour == 23
        assert booking.total > Decimal("145.10")  # surcharge applied
        # Price lines regenerated for the new fare.
        assert booking.price_lines.filter(
            kind=BookingPriceLine.Kind.SURCHARGE
        ).exists()

    def test_approve_is_idempotent(self, client, vehicle, email_on):
        owner = make_owner()
        req = self._pending(owner, vehicle)
        staff = self._staff()
        client.login(username=staff.email, password=PASSWORD)
        first = client.post(reverse("api:staff_amendment_approve", args=[req.pk]))
        assert first.status_code == 200
        mail.outbox.clear()
        second = client.post(reverse("api:staff_amendment_approve", args=[req.pk]))
        assert second.status_code == 409
        assert mail.outbox == []

    def test_decline_emails_the_reason_and_leaves_the_booking(
        self, client, vehicle, email_on
    ):
        owner = make_owner()
        req = self._pending(owner, vehicle, passenger_count=3)
        staff = self._staff()
        client.login(username=staff.email, password=PASSWORD)

        response = client.post(
            reverse("api:staff_amendment_decline", args=[req.pk]),
            {"reason": "That vehicle is fully booked at the new time."},
            content_type="application/json",
        )
        assert response.status_code == 200
        req.refresh_from_db()
        assert req.status == BookingAmendmentRequest.Status.DECLINED
        assert req.decline_reason

        req.booking.refresh_from_db()
        assert req.booking.passenger_count == 2  # unchanged

        client_mail = [m for m in mail.outbox if m.to == [owner.email]]
        assert client_mail
        assert "fully booked" in client_mail[0].body
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.AMENDMENT_DECLINED, succeeded=True
        ).exists()

    def test_decline_is_idempotent(self, client, vehicle):
        owner = make_owner()
        req = self._pending(owner, vehicle)
        staff = self._staff()
        client.login(username=staff.email, password=PASSWORD)
        client.post(reverse("api:staff_amendment_decline", args=[req.pk]),
                    {"reason": "x"}, content_type="application/json")
        second = client.post(
            reverse("api:staff_amendment_decline", args=[req.pk]),
            {"reason": "y"}, content_type="application/json",
        )
        assert second.status_code == 409

    def test_non_staff_cannot_approve(self, client, vehicle):
        owner = make_owner()
        req = self._pending(owner, vehicle)
        client.login(username=owner.email, password=PASSWORD)  # not staff
        response = client.post(
            reverse("api:staff_amendment_approve", args=[req.pk])
        )
        assert response.status_code in (401, 403)
        req.refresh_from_db()
        assert req.status == BookingAmendmentRequest.Status.PENDING

    def test_staff_list_returns_the_pending_queue(self, client, vehicle):
        owner = make_owner()
        self._pending(owner, vehicle)
        staff = self._staff()
        client.login(username=staff.email, password=PASSWORD)
        response = client.get(reverse("api:staff_amendment_requests"))
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_booking_detail_exposes_the_pending_request(self, client, vehicle):
        owner = make_owner()
        req = self._pending(owner, vehicle)
        client.login(username=owner.email, password=PASSWORD)
        response = client.get(
            reverse("api:my_booking_detail", args=[req.booking.reference])
        )
        assert response.status_code == 200
        pending = response.json()["pending_amendment"]
        assert pending is not None
        assert pending["status"] == "pending"


    @pytest.mark.parametrize("review_status", ["approved", "declined"])
    def test_booking_exposes_last_reviewed_request(self, client, vehicle, review_status):
        owner = make_owner()
        req = self._pending(owner, vehicle)
        req.status = review_status
        req.decline_reason = "Please contact the office" if review_status == "declined" else ""
        req.reviewed_at = timezone.now()
        req.save()
        client.login(username=owner.email, password=PASSWORD)
        for url in [reverse("api:my_booking_detail", args=[req.booking.reference]),
                    reverse("api:my_bookings")]:
            response = client.get(url)
            assert response.status_code == 200
            booking = response.json()[0] if isinstance(response.json(), list) else response.json()
            assert booking["pending_amendment"] is None
            assert booking["last_amendment"]["status"] == review_status
            assert booking["last_amendment"]["decline_reason"] == req.decline_reason
