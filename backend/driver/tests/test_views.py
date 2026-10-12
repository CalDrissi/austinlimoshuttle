"""Driver portal views — the Day view and the new All-upcoming list view."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, Driver
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
