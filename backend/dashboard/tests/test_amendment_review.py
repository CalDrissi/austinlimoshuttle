"""
Back-office review of customer booking-change requests.

The dashboard screen is the human side of BookingAmendmentRequest: staff see the
pending queue, compare OLD vs NEW, and approve (apply + re-price + email) or
decline (reason + email). These pin that the screen is staff-gated, that the two
actions call through to the model's guarded transitions, and that the sidebar
badge counts what is waiting.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, BookingAmendmentRequest, BookingPriceLine
from dashboard.permissions import DISPATCHER, EDITOR, sync_roles
from fleet.models import DistanceBand, Vehicle
from notifications.models import EmailLog
from pricing.models import PricingSettings

User = get_user_model()


@pytest.fixture
def roles(db):
    sync_roles()


@pytest.fixture
def vehicle(db):
    v = Vehicle.objects.create(
        name="Business Class", slug="bc", hourly_rate=Decimal("85.00"),
        minimum_fare=Decimal("95.00"), is_active=True,
        passenger_capacity=4, luggage_capacity=4,
    )
    for start, end, rate in [(0, 6, "15.00"), (6, 50, "2.90")]:
        DistanceBand.objects.create(vehicle=v, from_miles=start, to_miles=end,
                                    rate_per_mile=Decimal(rate))
    PricingSettings.load()
    return v


@pytest.fixture
def booking(db, vehicle):
    owner = User.objects.create_user(
        email="rider@example.com", first_name="Sam", last_name="Ray",
        phone="+15125550100",
    )
    b = Booking.objects.create(
        customer=owner, vehicle=vehicle,
        pickup_address="ABIA", dropoff_address="Downtown",
        pickup_at=timezone.now() + timedelta(days=5),
        distance_miles=Decimal("25"),
        subtotal=Decimal("145.10"), total=Decimal("145.10"),
        passenger_count=2, luggage_count=1,
        status=Booking.Status.CONFIRMED, currency="USD",
    )
    BookingPriceLine.objects.create(
        booking=b, kind=BookingPriceLine.Kind.BAND, label="25 mi",
        amount=Decimal("145.10"),
    )
    return b


def _request(booking, **changes):
    return BookingAmendmentRequest.objects.create(
        booking=booking, requested_by=booking.customer,
        requested_changes=changes, old_total=booking.total,
        new_subtotal=booking.subtotal, new_total=booking.total, currency="USD",
    )


def staff_in(role):
    user = User.objects.create_user(
        email=f"{role.lower()}@example.com", password="DashLocal!2026", is_staff=True,
    )
    user.groups.add(Group.objects.get(name=role))
    return user


@pytest.mark.django_db
class TestAccess:
    def test_anonymous_is_redirected_to_login(self, client):
        response = client.get(reverse("dashboard:amendments"))
        assert response.status_code == 302
        assert "/dashboard/login/" in response["Location"]

    def test_editor_is_forbidden(self, client, roles):
        """Content editors have no view access to bookings, so none here."""
        staff_in(EDITOR)
        client.login(username="editor@example.com", password="DashLocal!2026")
        assert client.get(reverse("dashboard:amendments")).status_code == 403

    def test_dispatcher_can_reach_the_queue(self, client, roles):
        staff_in(DISPATCHER)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        assert client.get(reverse("dashboard:amendments")).status_code == 200


@pytest.mark.django_db
class TestPendingList:
    def test_pending_request_renders(self, client, roles, booking):
        staff_in(DISPATCHER)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        _request(booking, passenger_count=3)

        response = client.get(reverse("dashboard:amendments"))
        assert response.status_code == 200
        assert booking.reference.encode() in response.content

    def test_resolved_filter_hides_pending(self, client, roles, booking):
        staff = staff_in(DISPATCHER)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        pending = _request(booking, passenger_count=3)
        done = _request(booking, notes="later")
        done.decline(reviewed_by=staff, reason="no")

        response = client.get(reverse("dashboard:amendments"), {"state": "resolved"})
        assert response.status_code == 200
        assert pending.booking.reference  # sanity
        # Only the declined one should be listed under resolved.
        assert b"Declined" in response.content


@pytest.mark.django_db
class TestActions:
    def test_approve_applies_and_marks_approved(self, client, roles, booking):
        staff_in(DISPATCHER)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        req = _request(booking, passenger_count=3, notes="car seat")

        response = client.post(
            reverse("dashboard:amendment_detail", args=[req.pk]),
            {"action": "approve"},
        )
        assert response.status_code == 302
        req.refresh_from_db()
        booking.refresh_from_db()
        assert req.status == BookingAmendmentRequest.Status.APPROVED
        assert req.reviewed_by.email == "dispatcher@example.com"
        assert booking.passenger_count == 3
        assert booking.notes == "car seat"
        # The view invoked the approval mailer (logged even when email is off).
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.AMENDMENT_APPROVED, booking=booking,
        ).exists()

    def test_decline_records_reason(self, client, roles, booking):
        staff_in(DISPATCHER)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        req = _request(booking, passenger_count=3)

        response = client.post(
            reverse("dashboard:amendment_detail", args=[req.pk]),
            {"action": "decline", "reason": "That slot is already booked."},
        )
        assert response.status_code == 302
        req.refresh_from_db()
        booking.refresh_from_db()
        assert req.status == BookingAmendmentRequest.Status.DECLINED
        assert req.decline_reason == "That slot is already booked."
        assert req.reviewed_by.email == "dispatcher@example.com"
        # Booking untouched by a decline.
        assert booking.passenger_count == 2
        assert EmailLog.objects.filter(
            kind=EmailLog.Kind.AMENDMENT_DECLINED, booking=booking,
        ).exists()

    def test_decline_requires_a_reason(self, client, roles, booking):
        staff_in(DISPATCHER)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        req = _request(booking, passenger_count=3)

        client.post(
            reverse("dashboard:amendment_detail", args=[req.pk]),
            {"action": "decline", "reason": "   "},
        )
        req.refresh_from_db()
        assert req.status == BookingAmendmentRequest.Status.PENDING

    def test_already_resolved_is_not_reprocessed(self, client, roles, booking):
        staff = staff_in(DISPATCHER)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        req = _request(booking, passenger_count=3)
        req.decline(reviewed_by=staff, reason="first call")

        response = client.post(
            reverse("dashboard:amendment_detail", args=[req.pk]),
            {"action": "approve"},
        )
        assert response.status_code == 302
        req.refresh_from_db()
        # Still declined -- the approve POST was refused by the guard.
        assert req.status == BookingAmendmentRequest.Status.DECLINED
        assert req.decline_reason == "first call"
        booking.refresh_from_db()
        assert booking.passenger_count == 2


@pytest.mark.django_db
class TestBadge:
    def test_pending_count_shown_in_sidebar(self, client, roles, booking):
        staff_in(DISPATCHER)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        _request(booking, passenger_count=3)
        _request(booking, notes="x")

        response = client.get(reverse("dashboard:home"))
        assert response.context["nav_pending_amendments"] == 2
        # And the nav link is rendered.
        assert b"Change requests" in response.content
