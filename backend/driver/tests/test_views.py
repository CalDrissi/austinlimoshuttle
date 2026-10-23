"""Driver portal views — the Day view and the new All-upcoming list view."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, BookingStatusChange, Driver, DriverTripEvent
from fleet.models import Vehicle

User = get_user_model()


@pytest.fixture
def vehicle(db):
    return Vehicle.objects.create(name="Business Class", slug="bc", hourly_rate=85)


@pytest.fixture
def driver_user(db):
    u = User.objects.create_user(email="dan@example.com", password="DanPass!2026")
    Driver.objects.create(full_name="Dan Driver", user=u, is_active=True)
    return u


def _run(driver, vehicle, when, ref, status=Booking.Status.CONFIRMED):
    return Booking.objects.create(
        reference=ref, vehicle=vehicle, driver=driver,
        pickup_address="Austin-Bergstrom Airport", dropoff_address="Downtown Austin",
        pickup_at=when, status=status,
    )


@pytest.mark.django_db
def test_upcoming_lists_runs_beyond_tomorrow(client, driver_user, vehicle):
    driver = driver_user.driver_profile
    noon = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)
    _run(driver, vehicle, noon, "TODAYAAA")
    _run(driver, vehicle, noon + timedelta(days=1), "TMRWBBBB")
    _run(driver, vehicle, noon + timedelta(days=5), "FUTRCCCC")

    client.force_login(driver_user)
    resp = client.get(reverse("driver:upcoming"))
    assert resp.status_code == 200
    body = resp.content.decode()
    # The whole point: runs past tomorrow show up in one list.
    assert "TODAYAAA" in body
    assert "TMRWBBBB" in body
    assert "FUTRCCCC" in body
    # Grouped by day.
    assert "Today" in body and "Tomorrow" in body


@pytest.mark.django_db
def test_upcoming_excludes_past_and_cancelled(client, driver_user, vehicle):
    driver = driver_user.driver_profile
    noon = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)
    _run(driver, vehicle, noon - timedelta(days=1), "PASTAAAA")
    _run(driver, vehicle, noon + timedelta(days=2), "CANCBBBB",
         status=Booking.Status.CANCELLED)
    _run(driver, vehicle, noon + timedelta(days=2), "GOODCCCC")

    client.force_login(driver_user)
    body = client.get(reverse("driver:upcoming")).content.decode()
    assert "GOODCCCC" in body
    assert "PASTAAAA" not in body   # yesterday
    assert "CANCBBBB" not in body   # cancelled


@pytest.mark.django_db
def test_upcoming_only_shows_the_signed_in_drivers_runs(client, driver_user, vehicle):
    driver = driver_user.driver_profile
    other = User.objects.create_user(email="eve@example.com", password="x")
    other_driver = Driver.objects.create(full_name="Eve", user=other, is_active=True)
    noon = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)
    _run(driver, vehicle, noon, "MINEAAAA")
    _run(other_driver, vehicle, noon, "EVESRUNN")

    client.force_login(driver_user)
    body = client.get(reverse("driver:upcoming")).content.decode()
    assert "MINEAAAA" in body
    assert "EVESRUNN" not in body


# --- Live trip-status buttons (DriverTripEvent pings) -----------------------

@pytest.fixture
def my_run(db, driver_user, vehicle):
    noon = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0)
    return _run(driver_user.driver_profile, vehicle, noon, "MYRUNAAA")


@pytest.mark.django_db
def test_trip_detail_shows_all_four_status_buttons(client, driver_user, my_run):
    client.force_login(driver_user)
    body = client.get(reverse("driver:trip_detail", args=[my_run.reference])).content.decode()
    for label in ("On My Way", "Arrived", "Client On Board", "Completed"):
        assert label in body
    # Self-hosted, CSP-safe JS -- no inline handler, no external host.
    assert "driver/trip_events.js" in body
    assert "onclick" not in body


@pytest.mark.django_db
@pytest.mark.parametrize("event_type", ["on_way", "arrived", "on_board", "completed"])
def test_each_button_records_its_event_with_gps(client, driver_user, my_run, event_type):
    client.force_login(driver_user)
    resp = client.post(
        reverse("driver:trip_action", args=[my_run.reference]),
        {"event_type": event_type, "latitude": "30.267153",
         "longitude": "-97.743057", "accuracy": "12.5"},
    )
    assert resp.status_code == 302  # back to the trip page

    event = DriverTripEvent.objects.get(booking=my_run)
    assert event.event_type == event_type
    assert float(event.latitude) == pytest.approx(30.267153)
    assert float(event.longitude) == pytest.approx(-97.743057)
    assert float(event.location_accuracy) == pytest.approx(12.5)
    # The acting driver is attributed to the ping.
    assert event.driver == driver_user.driver_profile


@pytest.mark.django_db
def test_event_records_without_gps(client, driver_user, my_run):
    """Device denied/lacked location -> no coords posted, but the ping still records."""
    client.force_login(driver_user)
    resp = client.post(
        reverse("driver:trip_action", args=[my_run.reference]),
        {"event_type": "arrived"},  # no latitude/longitude/accuracy at all
    )
    assert resp.status_code == 302

    event = DriverTripEvent.objects.get(booking=my_run)
    assert event.event_type == "arrived"
    assert event.latitude is None
    assert event.longitude is None
    assert event.location_accuracy is None


@pytest.mark.django_db
def test_blank_gps_fields_record_as_null(client, driver_user, my_run):
    """Empty hidden fields (form submitted with no fix) are treated as null."""
    client.force_login(driver_user)
    client.post(
        reverse("driver:trip_action", args=[my_run.reference]),
        {"event_type": "on_way", "latitude": "", "longitude": "", "accuracy": ""},
    )
    event = DriverTripEvent.objects.get(booking=my_run)
    assert event.latitude is None and event.longitude is None


@pytest.mark.django_db
def test_completed_event_advances_booking_status(client, driver_user, my_run):
    client.force_login(driver_user)
    client.post(
        reverse("driver:trip_action", args=[my_run.reference]),
        {"event_type": "completed"},
    )
    my_run.refresh_from_db()
    assert my_run.status == Booking.Status.COMPLETED


@pytest.mark.django_db
def test_unknown_event_type_records_nothing(client, driver_user, my_run):
    client.force_login(driver_user)
    resp = client.post(
        reverse("driver:trip_action", args=[my_run.reference]),
        {"event_type": "teleported"},
    )
    assert resp.status_code == 302
    assert not DriverTripEvent.objects.filter(booking=my_run).exists()


@pytest.mark.django_db
def test_non_owner_driver_cannot_post_events(client, db, vehicle, my_run):
    """A driver may only ping their own bookings; someone else's run 404s and records nothing."""
    other = User.objects.create_user(email="mallory@example.com", password="x")
    Driver.objects.create(full_name="Mallory", user=other, is_active=True)

    client.force_login(other)
    resp = client.post(
        reverse("driver:trip_action", args=[my_run.reference]),
        {"event_type": "on_way"},
    )
    assert resp.status_code == 404
    assert not DriverTripEvent.objects.filter(booking=my_run).exists()


@pytest.mark.django_db
def test_legacy_completed_action_still_works(client, driver_user, my_run):
    """The original action=completed outcome path is untouched: status + audit row."""
    client.force_login(driver_user)
    resp = client.post(
        reverse("driver:trip_action", args=[my_run.reference]),
        {"action": "completed"},
    )
    assert resp.status_code == 302
    my_run.refresh_from_db()
    assert my_run.status == Booking.Status.COMPLETED
    assert BookingStatusChange.objects.filter(
        booking=my_run, to_status=Booking.Status.COMPLETED
    ).exists()
    # The legacy path does not create a telemetry ping.
    assert not DriverTripEvent.objects.filter(booking=my_run).exists()
