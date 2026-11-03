"""
API contract and authorisation.

The two properties worth most here are the ones legacy got wrong:
the client cannot dictate a price, and a customer cannot read another
customer's booking.
"""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking
from content.models import Page, SiteSettings
from fleet.models import DistanceBand, Vehicle
from pricing.distance import DistanceLookupError, Journey
from pricing.models import PricingSettings, TimeSurcharge

User = get_user_model()


@pytest.fixture
def vehicle(db):
    v = Vehicle.objects.create(
        name="Business Class", slug="bc", hourly_rate=Decimal("85.00"),
        minimum_fare=Decimal("95.00"), is_active=True,
    )
    for start, end, rate in [(0, 6, "15.00"), (6, 50, "2.90"),
                             (50, 100, "2.20"), (100, None, "1.50")]:
        DistanceBand.objects.create(vehicle=v, from_miles=start, to_miles=end,
                                    rate_per_mile=Decimal(rate))
    PricingSettings.load()
    return v


@pytest.fixture
def future():
    return (timezone.now() + timedelta(days=3)).replace(microsecond=0)


STUB_JOURNEY = Journey(
    distance_miles=Decimal("25"),
    duration_minutes=32,
    resolved_origin="Austin-Bergstrom International Airport, TX",
    resolved_destination="Downtown, Austin, TX",
)


@pytest.fixture(autouse=True)
def stub_distance():
    """
    The distance is measured server-side. Tests stub the lookup rather than
    calling Google -- 25 miles keeps the expected fares identical to the
    hand-checked figures in the pricing tests.
    """
    with patch("api.views.measure_journey", return_value=STUB_JOURNEY) as stub:
        yield stub


def get_quote(client, future, **overrides):
    payload = {
        "pickup_address": "Austin-Bergstrom International Airport",
        "dropoff_address": "Downtown Austin",
        "pickup_at": future.isoformat(),
    }
    payload.update(overrides)
    return client.post(reverse("api:quotes"), payload, content_type="application/json")


@pytest.mark.django_db
class TestPublicContent:
    def test_page_detail(self, client):
        Page.objects.create(slug="fleet", title="Our fleet", body="<p>Cars</p>")
        response = client.get(reverse("api:page_detail", args=["fleet"]))
        assert response.status_code == 200
        assert response.json()["title"] == "Our fleet"

    def test_unpublished_page_is_not_exposed(self, client):
        Page.objects.create(slug="draft", title="Draft", is_published=False)
        assert client.get(reverse("api:page_detail", args=["draft"])).status_code == 404

    def test_vehicle_list_hides_inactive(self, client, vehicle):
        active = Vehicle.objects.create(
            name="Shown Shuttle", slug="shown-shuttle", is_active=True,
        )
        inactive = Vehicle.objects.create(
            name="Retired", slug="retired", is_active=False,
        )
        names = [v["name"] for v in client.get(reverse("api:vehicles")).json()]
        assert active.name in names
        assert inactive.name not in names

    def test_vehicle_list_is_public(self, client, vehicle):
        assert client.get(reverse("api:vehicles")).status_code == 200


@pytest.mark.django_db
class TestQuoting:
    def test_returns_a_priced_quote_with_a_token(self, client, vehicle, future):
        response = get_quote(client, future)
        assert response.status_code == 200
        quote = response.json()["quotes"][0]
        assert quote["total"] == "145.10"  # (6 x 15) + (19 x 2.90)
        assert quote["quote_token"]

    def test_rejects_a_past_pickup(self, client, vehicle):
        past = timezone.now() - timedelta(days=1)
        response = get_quote(client, past, pickup_at=past.isoformat())
        assert response.status_code == 400

    def test_requires_a_destination_or_hours(self, client, vehicle, future):
        response = client.post(
            reverse("api:quotes"),
            {"pickup_address": "a", "pickup_at": future.isoformat()},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_rejects_a_transfer_and_hourly_hire_together(self, client, vehicle, future):
        """Two addresses plus a duration is contradictory."""
        response = get_quote(client, future, hours="3")
        assert response.status_code == 400

    def test_hourly_hire_needs_no_destination(self, client, vehicle, future):
        response = client.post(
            reverse("api:quotes"),
            {"pickup_address": "Downtown Austin", "pickup_at": future.isoformat(),
             "hours": "3"},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["quotes"][0]["subtotal"] == "255.00"  # 3 x 85

    def test_quote_request_accepts_neither_a_price_nor_a_distance(self):
        """
        Both are server-derived. A serializer that accepts either is a
        serializer a customer can use to set their own fare.
        """
        from api.serializers import QuoteRequestSerializer

        fields = set(QuoteRequestSerializer().fields)
        assert not (fields & {"total", "price", "subtotal", "amount", "fare"})
        assert "distance_miles" not in fields

    def test_a_client_supplied_distance_is_ignored(self, client, vehicle, future):
        """Posting a 1-mile distance must not buy a 25-mile journey cheaply."""
        response = get_quote(client, future, distance_miles="1")
        assert response.status_code == 200
        assert response.json()["quotes"][0]["total"] == "145.10"  # the measured 25 mi

    def test_response_reports_the_measured_journey(self, client, vehicle, future):
        journey = get_quote(client, future).json()["journey"]
        assert journey["distance_miles"] == "25"
        assert journey["duration_minutes"] == 32

    def test_lookup_failure_fails_the_quote(self, client, vehicle, future, stub_distance):
        """No fallback: a failed measurement must not produce a quote."""
        stub_distance.side_effect = DistanceLookupError("No driving route was found.")
        response = get_quote(client, future)
        assert response.status_code == 422
        assert "route" in response.json()["detail"].lower()


@pytest.mark.django_db
class TestQuoteTokenIntegrity:
    def test_booking_uses_the_server_price_not_the_clients(self, client, vehicle, future):
        """
        The client posts a total. It must be ignored -- the schema has no field
        for it, and the stored fare comes from recomputation.
        """
        token = get_quote(client, future).json()["quotes"][0]["quote_token"]
        response = client.post(
            reverse("api:create_booking"),
            {
                "quote_token": token,
                "guest_email": "guest@example.com",
                "guest_phone": "+15125550000",
                "total": "1.00",       # attempted override
                "subtotal": "1.00",
            },
            content_type="application/json",
        )
        assert response.status_code == 201
        assert response.json()["total"] == "145.10"
        assert Booking.objects.get().total == Decimal("145.10")

    def test_tampered_token_is_rejected(self, client, vehicle, future):
        token = get_quote(client, future).json()["quotes"][0]["quote_token"]
        tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
        response = client.post(
            reverse("api:create_booking"),
            {"quote_token": tampered, "guest_email": "g@example.com"},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert not Booking.objects.exists()

    def test_expired_token_is_rejected(self, client, vehicle, future):
        from freezegun import freeze_time

        token = get_quote(client, future).json()["quotes"][0]["quote_token"]
        settings_obj = PricingSettings.load()

        later = timezone.now() + timedelta(minutes=settings_obj.quote_ttl_minutes + 5)
        with freeze_time(later):
            response = client.post(
                reverse("api:create_booking"),
                {"quote_token": token, "guest_email": "g@example.com"},
                content_type="application/json",
            )
        assert response.status_code == 400
        assert "expired" in str(response.json()).lower()

    def test_missing_token_is_rejected(self, client, vehicle):
        response = client.post(
            reverse("api:create_booking"), {"guest_email": "g@example.com"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_booking_over_passenger_capacity_is_rejected(self, client, vehicle, future):
        """A quote token can be replayed with any counts -- the vehicle's seat
        limit is enforced server-side, not just in the browser."""
        vehicle.passenger_capacity = 3
        vehicle.luggage_capacity = 4
        vehicle.save(update_fields=["passenger_capacity", "luggage_capacity"])
        token = get_quote(client, future).json()["quotes"][0]["quote_token"]
        response = client.post(
            reverse("api:create_booking"),
            {"quote_token": token, "guest_email": "g@example.com",
             "guest_phone": "+15125550000", "passenger_count": 6},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert "passenger_count" in response.json()
        assert not Booking.objects.exists()

    def test_booking_at_capacity_is_allowed(self, client, vehicle, future):
        vehicle.passenger_capacity = 3
        vehicle.luggage_capacity = 4
        vehicle.save(update_fields=["passenger_capacity", "luggage_capacity"])
        token = get_quote(client, future).json()["quotes"][0]["quote_token"]
        response = client.post(
            reverse("api:create_booking"),
            {"quote_token": token, "guest_email": "g@example.com",
             "guest_phone": "+15125550000", "passenger_count": 3, "luggage_count": 4},
            content_type="application/json",
        )
        assert response.status_code == 201

    def test_surcharge_is_recomputed_at_booking_time(self, client, vehicle, future):
        """
        A quote issued before a surcharge existed must not lock in the old price
        -- the fare is recomputed from the journey, not replayed from the token.
        """
        # 23:00 in Austin, not in UTC -- the surcharge rule is local-time based.
        austin = ZoneInfo("America/Chicago")
        late_pickup = timezone.localtime(future, austin).replace(
            hour=23, minute=0, second=0, microsecond=0,
        )
        token = get_quote(
            client, late_pickup, pickup_at=late_pickup.isoformat(),
        ).json()["quotes"][0]["quote_token"]

        TimeSurcharge.objects.create(
            name="Late night", start_time="21:00", end_time="06:00",
            percentage=Decimal("20.00"),
        )

        response = client.post(
            reverse("api:create_booking"),
            {"quote_token": token, "guest_email": "g@example.com",
             "guest_phone": "+15125550000"},
            content_type="application/json",
        )
        assert response.status_code == 201
        assert response.json()["total"] == "174.12"  # 145.10 x 1.20


@pytest.mark.django_db
class TestBookingAuthorisation:
    """
    Legacy exposed `direct-payment.php?orderID=` with no authentication, making
    the entire orders table readable. These are the tests that keep that shut.
    """

    def _make_booking(self, owner, vehicle):
        return Booking.objects.create(
            customer=owner, vehicle=vehicle, pickup_address="a",
            pickup_at=timezone.now() + timedelta(days=2), total=Decimal("95.00"),
        )

    def test_anonymous_cannot_read_a_booking(self, client, vehicle):
        owner = User.objects.create_user(email="owner@example.com")
        booking = self._make_booking(owner, vehicle)
        response = client.get(
            reverse("api:my_booking_detail", args=[booking.reference])
        )
        assert response.status_code in (401, 403)

    def test_another_customer_gets_404_not_403(self, client, vehicle):
        """
        404, not 403: a 403 would confirm the reference exists, which is enough
        to enumerate bookings.
        """
        owner = User.objects.create_user(email="owner2@example.com")
        booking = self._make_booking(owner, vehicle)

        User.objects.create_user(email="other@example.com", password="ApiLocal!2026")
        client.login(username="other@example.com", password="ApiLocal!2026")

        response = client.get(
            reverse("api:my_booking_detail", args=[booking.reference])
        )
        assert response.status_code == 404

    def test_owner_can_read_their_own(self, client, vehicle):
        owner = User.objects.create_user(email="owner3@example.com",
                                         password="ApiLocal!2026")
        booking = self._make_booking(owner, vehicle)
        client.login(username="owner3@example.com", password="ApiLocal!2026")

        response = client.get(
            reverse("api:my_booking_detail", args=[booking.reference])
        )
        assert response.status_code == 200
        assert response.json()["reference"] == booking.reference

    def test_my_bookings_lists_only_mine(self, client, vehicle):
        mine = User.objects.create_user(email="mine@example.com", password="ApiLocal!2026")
        theirs = User.objects.create_user(email="theirs@example.com")
        self._make_booking(mine, vehicle)
        self._make_booking(theirs, vehicle)

        client.login(username="mine@example.com", password="ApiLocal!2026")
        results = client.get(reverse("api:my_bookings")).json()
        assert len(results) == 1

    def test_customer_can_cancel_their_own_future_booking(self, client, vehicle):
        owner = User.objects.create_user(email="canceller@example.com",
                                         password="ApiLocal!2026")
        booking = self._make_booking(owner, vehicle)
        client.login(username="canceller@example.com", password="ApiLocal!2026")

        response = client.patch(
            reverse("api:my_booking_detail", args=[booking.reference]),
            {"action": "cancel"}, content_type="application/json",
        )
        assert response.status_code == 200
        booking.refresh_from_db()
        assert booking.status == Booking.Status.CANCELLED
        assert booking.status_changes.filter(changed_by=owner).exists()

    def test_cannot_cancel_a_past_booking(self, client, vehicle):
        owner = User.objects.create_user(email="late@example.com", password="ApiLocal!2026")
        booking = Booking.objects.create(
            customer=owner, vehicle=vehicle, pickup_address="a",
            pickup_at=timezone.now() - timedelta(hours=2), total=Decimal("95"),
        )
        client.login(username="late@example.com", password="ApiLocal!2026")
        response = client.patch(
            reverse("api:my_booking_detail", args=[booking.reference]),
            {"action": "cancel"}, content_type="application/json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestPublicBookingStatus:
    """
    The confirmation page polls this while waiting for Stripe's webhook, and a
    guest has no session to authenticate with. The reference is therefore the
    capability -- so what the endpoint returns has to be safe for anyone who
    holds one, and that is what these tests pin down.
    """

    def _guest_booking(self, vehicle):
        return Booking.objects.create(
            vehicle=vehicle, pickup_address="Austin-Bergstrom, Gate 4",
            dropoff_address="1100 Congress Ave",
            pickup_at=timezone.now() + timedelta(days=2), total=Decimal("95.00"),
            guest_email="guest@example.com", notes="Ring the bell twice",
        )

    def test_guest_can_poll_their_own_reference(self, client, vehicle):
        booking = self._guest_booking(vehicle)
        response = client.get(reverse("api:booking_status", args=[booking.reference]))
        assert response.status_code == 200
        assert response.json()["status"] == booking.status

    def test_response_carries_no_journey_or_passenger_detail(self, client, vehicle):
        booking = self._guest_booking(vehicle)
        body = client.get(reverse("api:booking_status", args=[booking.reference])).json()

        assert set(body) == {
            "reference", "status", "status_display", "pickup_at",
            "vehicle_name", "total", "currency",
        }
        serialised = str(body)
        for leaked in ("Congress", "Gate 4", "guest@example.com", "Ring the bell"):
            assert leaked not in serialised

    def test_unknown_reference_is_404(self, client, vehicle):
        assert client.get(
            reverse("api:booking_status", args=["ZZZZZZZZ"])
        ).status_code == 404

    def test_another_customers_booking_is_404(self, client, vehicle):
        owner = User.objects.create_user(email="statusowner@example.com")
        booking = Booking.objects.create(
            customer=owner, vehicle=vehicle, pickup_address="a",
            pickup_at=timezone.now() + timedelta(days=2), total=Decimal("95.00"),
        )
        User.objects.create_user(email="nosy@example.com", password="ApiLocal!2026")
        client.login(username="nosy@example.com", password="ApiLocal!2026")

        assert client.get(
            reverse("api:booking_status", args=[booking.reference])
        ).status_code == 404

    def test_it_is_read_only(self, client, vehicle):
        booking = self._guest_booking(vehicle)
        response = client.patch(
            reverse("api:booking_status", args=[booking.reference]),
            {"status": "confirmed"}, content_type="application/json",
        )
        assert response.status_code == 405
        booking.refresh_from_db()
        assert booking.status == Booking.Status.PENDING


@pytest.mark.django_db
class TestAuth:
    def test_login_and_me(self, client):
        User.objects.create_user(email="user@example.com", password="ApiLocal!2026",
                                 first_name="Sam")
        response = client.post(
            reverse("api:login"),
            {"email": "user@example.com", "password": "ApiLocal!2026"},
            content_type="application/json",
        )
        assert response.status_code == 200
        assert client.get(reverse("api:me")).json()["first_name"] == "Sam"

    def test_login_is_case_insensitive_on_email(self, client):
        User.objects.create_user(email="mixed@example.com", password="ApiLocal!2026")
        response = client.post(
            reverse("api:login"),
            {"email": "MIXED@Example.COM", "password": "ApiLocal!2026"},
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_wrong_password_and_unknown_email_are_indistinguishable(self, client):
        User.objects.create_user(email="known@example.com", password="ApiLocal!2026")
        wrong = client.post(
            reverse("api:login"),
            {"email": "known@example.com", "password": "nope"},
            content_type="application/json",
        )
        unknown = client.post(
            reverse("api:login"),
            {"email": "nobody@example.com", "password": "nope"},
            content_type="application/json",
        )
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()

    def test_imported_account_cannot_log_in_until_reset(self, client):
        """1,251 imported accounts have an unusable password by design."""
        user = User.objects.create_user(email="legacy@example.com")
        user.set_unusable_password()
        user.save()
        response = client.post(
            reverse("api:login"),
            {"email": "legacy@example.com", "password": ""},
            content_type="application/json",
        )
        assert response.status_code == 401

    def test_registration_enforces_password_strength(self, client):
        response = client.post(
            reverse("api:register"),
            {"email": "new@example.com", "password": "1234"},
            content_type="application/json",
        )
        assert response.status_code == 400
        assert not User.objects.filter(email="new@example.com").exists()

    def test_registration_returns_the_same_user_shape_as_login(self, client):
        """
        The frontend greets people by name from whatever this returns. When it
        answered with the address alone, someone who had just typed their name
        into the form was shown a generic header instead.
        """
        registered = client.post(
            reverse("api:register"),
            {"email": "shape@example.com", "password": "AnotherStrongPass!99",
             "first_name": "Pat", "last_name": "Tester", "phone": "5125550134"},
            content_type="application/json",
        )
        assert registered.status_code == 201

        client.post(
            reverse("api:login"),
            {"email": "shape@example.com", "password": "AnotherStrongPass!99"},
            content_type="application/json",
        )
        me = client.get(reverse("api:me"))

        assert registered.json() == me.json()
        assert registered.json()["first_name"] == "Pat"

    def test_registering_an_existing_address_does_not_disclose_it(self, client):
        User.objects.create_user(email="taken@example.com", password="ApiLocal!2026")
        response = client.post(
            reverse("api:register"),
            {"email": "taken@example.com", "password": "AnotherStrongPass!99"},
            content_type="application/json",
        )
        assert response.status_code == 202
        assert "taken" not in response.json()["detail"].lower()


@pytest.mark.django_db
class TestSiteSettings:
    def test_returns_the_contact_details_the_footer_shows(self, client):
        settings_row = SiteSettings.load()
        settings_row.contact_phone = "+1 (512) 555-0134"
        settings_row.contact_email = "bookings@austinlimoshuttle.com"
        settings_row.facebook = "https://facebook.com/austinlimoshuttle"
        settings_row.save()

        body = client.get(reverse("api:site_settings")).json()

        assert body["contact_phone"] == "+1 (512) 555-0134"
        assert body["contact_email"] == "bookings@austinlimoshuttle.com"
        assert body["facebook"] == "https://facebook.com/austinlimoshuttle"

    def test_does_not_publish_the_ops_notification_address(self, client):
        """
        The address new-booking alerts land on shares a model with the public
        one, for legacy reasons. It must not share the response.
        """
        settings_row = SiteSettings.load()
        settings_row.ops_notification_email = "dispatch-internal@austinlimoshuttle.com"
        settings_row.save()

        body = client.get(reverse("api:site_settings")).json()

        assert "ops_notification_email" not in body
        assert "dispatch-internal" not in str(body)

    def test_works_before_anyone_has_opened_the_admin_page(self, client):
        """A fresh install has no settings row. The header still has to render."""
        SiteSettings.objects.all().delete()

        response = client.get(reverse("api:site_settings"))

        assert response.status_code == 200
        assert response.json()["contact_phone"] == ""


@pytest.mark.django_db
class TestEnquiries:
    def test_creates_an_enquiry(self, client):
        response = client.post(
            reverse("api:enquiries"),
            {"name": "Jo", "email": "jo@example.com",
             "message": "Do you cover Round Rock?"},
            content_type="application/json",
        )
        assert response.status_code == 201

    def test_rejects_a_too_short_message(self, client):
        response = client.post(
            reverse("api:enquiries"),
            {"name": "Jo", "email": "jo@example.com", "message": "hi"},
            content_type="application/json",
        )
        assert response.status_code == 400


@pytest.mark.django_db
class TestMinBookingLeadTime:
    """Admin-set minimum notice before pickup (storefront only)."""

    def test_quote_rejected_when_sooner_than_lead(self, client, vehicle, future):
        s = PricingSettings.load(); s.min_booking_lead_hours = 24; s.save()
        soon = (timezone.now() + timedelta(hours=2)).replace(microsecond=0)
        resp = get_quote(client, future, pickup_at=soon.isoformat())
        assert resp.status_code == 400
        assert "before pickup" in str(resp.json()).lower()

    def test_quote_ok_when_far_enough(self, client, vehicle, future):
        s = PricingSettings.load(); s.min_booking_lead_hours = 2; s.save()
        assert get_quote(client, future).status_code == 200  # 3 days out


@pytest.mark.django_db
class TestAmendRepricesOnDateChange:
    def test_moving_pickup_into_surcharge_window_reprices(self, client, vehicle, future):
        user = User.objects.create_user(
            email="amend@example.com", password="ApiLocal!2026", phone="+15125550000",
        )
        client.login(username="amend@example.com", password="ApiLocal!2026")
        token = get_quote(client, future).json()["quotes"][0]["quote_token"]
        ref = client.post(
            reverse("api:create_booking"), {"quote_token": token},
            content_type="application/json",
        ).json()["reference"]
        booking = Booking.objects.get(reference=ref)
        original_total = booking.total
        assert not booking.price_lines.filter(kind="surcharge").exists()

        TimeSurcharge.objects.create(
            name="Late night", start_time="21:00", end_time="06:00",
            percentage=Decimal("20.00"),
        )
        austin = ZoneInfo("America/Chicago")
        night = timezone.localtime(future, austin).replace(
            hour=23, minute=0, second=0, microsecond=0,
        )
        resp = client.patch(
            reverse("api:my_booking_detail", args=[ref]),
            {"action": "amend", "pickup_at": night.isoformat()},
            content_type="application/json",
        )
        assert resp.status_code == 200
        booking.refresh_from_db()
        assert booking.total > original_total
        assert booking.price_lines.filter(kind="surcharge").exists()
        assert booking.status_changes.filter(note__icontains="pickup_at").exists()
