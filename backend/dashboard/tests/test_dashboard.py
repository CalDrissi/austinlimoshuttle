"""
Dashboard access control and workflow.

The permission matrix is the point: the legacy system had one shared admin
login, so every staff member could do everything and no action was attributable.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, BookingStatusChange, Driver, DriverTripEvent
from dashboard.permissions import DISPATCHER, EDITOR, MANAGER, sync_roles
from enquiries.models import ContactMessage
from fleet.models import Vehicle

User = get_user_model()

DASHBOARD_URLS = ["dashboard:home", "dashboard:dispatch",
                  "dashboard:bookings", "dashboard:enquiries"]


@pytest.fixture
def roles(db):
    sync_roles()


@pytest.fixture
def vehicle(db):
    return Vehicle.objects.create(name="Business Class", slug="bc", hourly_rate=85)


@pytest.fixture
def booking(db, vehicle):
    return Booking.objects.create(
        vehicle=vehicle, pickup_address="ABIA", dropoff_address="Downtown",
        pickup_at=timezone.now() + timedelta(hours=6),
        total=Decimal("95.00"), status=Booking.Status.CONFIRMED,
    )


def staff_in(role, roles):
    user = User.objects.create_user(
        email=f"{role.lower()}@example.com", password="DashLocal!2026", is_staff=True,
    )
    user.groups.add(__import__("django.contrib.auth.models",
                               fromlist=["Group"]).Group.objects.get(name=role))
    return user


@pytest.mark.django_db
class TestAccessControl:
    @pytest.mark.parametrize("url_name", DASHBOARD_URLS)
    def test_anonymous_is_redirected(self, client, url_name):
        """
        To our own sign-in page, not Django's.

        The gate is the first screen anyone sees. Sending staff to the admin
        login made the product look like Django's admin, which is also the one
        thing the dashboard exists not to be.
        """
        response = client.get(reverse(url_name))
        assert response.status_code == 302
        assert "/dashboard/login/" in response["Location"]
        assert "/admin/login/" not in response["Location"]

    @pytest.mark.parametrize("url_name", DASHBOARD_URLS)
    def test_customer_account_is_forbidden(self, client, roles, url_name):
        User.objects.create_user(email="cust@example.com", password="DashLocal!2026")
        client.login(username="cust@example.com", password="DashLocal!2026")
        assert client.get(reverse(url_name)).status_code in (302, 403)

    @pytest.mark.parametrize("url_name", DASHBOARD_URLS)
    def test_dispatcher_can_reach_every_screen(self, client, roles, url_name):
        staff_in(DISPATCHER, roles)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        assert client.get(reverse(url_name)).status_code == 200

    def test_editor_cannot_reach_bookings(self, client, roles):
        """Content editors have no business seeing customer journeys."""
        staff_in(EDITOR, roles)
        client.login(username="editor@example.com", password="DashLocal!2026")
        assert client.get(reverse("dashboard:bookings")).status_code == 403


@pytest.mark.django_db
class TestDispatchBoard:
    def test_shows_upcoming_bookings(self, client, roles, booking):
        staff_in(DISPATCHER, roles)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        response = client.get(reverse("dashboard:dispatch"))
        assert booking.reference in response.content.decode()

    def test_hides_bookings_beyond_the_horizon(self, client, roles, vehicle):
        far = Booking.objects.create(
            vehicle=vehicle, pickup_address="later",
            pickup_at=timezone.now() + timedelta(days=10), total=Decimal("50"),
        )
        staff_in(DISPATCHER, roles)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        response = client.get(reverse("dashboard:dispatch"))
        assert far.reference not in response.content.decode()


@pytest.mark.django_db
class TestBookingUpdate:
    def _login(self, client, roles):
        staff_in(DISPATCHER, roles)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")

    def test_status_change_is_audited_with_the_acting_user(self, client, roles, booking):
        self._login(client, roles)
        client.post(
            reverse("dashboard:booking_update", args=[booking.reference]),
            {"status": Booking.Status.COMPLETED, "driver": "", "note": "Dropped off"},
        )
        booking.refresh_from_db()
        assert booking.status == Booking.Status.COMPLETED

        change = BookingStatusChange.objects.get(booking=booking)
        assert change.from_status == Booking.Status.CONFIRMED
        assert change.to_status == Booking.Status.COMPLETED
        assert change.changed_by.email == "dispatcher@example.com"
        assert change.note == "Dropped off"

    def test_assigning_a_driver(self, client, roles, booking):
        self._login(client, roles)
        driver = Driver.objects.create(full_name="Alex Ruiz")
        client.post(
            reverse("dashboard:booking_update", args=[booking.reference]),
            {"status": booking.status, "driver": str(driver.pk)},
        )
        booking.refresh_from_db()
        assert booking.driver == driver

    def test_cancelling_stamps_the_time_and_reason(self, client, roles, booking):
        self._login(client, roles)
        client.post(
            reverse("dashboard:booking_update", args=[booking.reference]),
            {"status": Booking.Status.CANCELLED, "driver": "", "note": "Customer called"},
        )
        booking.refresh_from_db()
        assert booking.cancelled_at is not None
        assert booking.cancellation_reason == "Customer called"

    def test_unknown_status_is_rejected(self, client, roles, booking):
        self._login(client, roles)
        client.post(
            reverse("dashboard:booking_update", args=[booking.reference]),
            {"status": "teleported", "driver": ""},
        )
        booking.refresh_from_db()
        assert booking.status == Booking.Status.CONFIRMED
        assert not BookingStatusChange.objects.exists()

    def test_no_change_writes_no_audit_row(self, client, roles, booking):
        self._login(client, roles)
        client.post(
            reverse("dashboard:booking_update", args=[booking.reference]),
            {"status": booking.status, "driver": ""},
        )
        assert not BookingStatusChange.objects.exists()

    def test_get_is_not_allowed(self, client, roles, booking):
        self._login(client, roles)
        response = client.get(
            reverse("dashboard:booking_update", args=[booking.reference])
        )
        assert response.status_code == 405


@pytest.mark.django_db
class TestBookingList:
    def test_search_by_reference(self, client, roles, booking, vehicle):
        other = Booking.objects.create(
            vehicle=vehicle, pickup_address="x",
            pickup_at=timezone.now() + timedelta(days=1), total=Decimal("10"),
        )
        staff_in(DISPATCHER, roles)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        body = client.get(
            reverse("dashboard:bookings"), {"q": booking.reference}
        ).content.decode()
        assert booking.reference in body
        assert other.reference not in body

    def test_csv_export(self, client, roles, booking):
        staff_in(DISPATCHER, roles)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        response = client.get(reverse("dashboard:bookings"), {"export": "csv"})
        assert response["Content-Type"] == "text/csv"
        body = response.content.decode()
        assert "Reference" in body
        assert booking.reference in body

    def test_csv_export_contains_no_card_columns(self, client, roles, booking):
        staff_in(DISPATCHER, roles)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        header = client.get(
            reverse("dashboard:bookings"), {"export": "csv"}
        ).content.decode().splitlines()[0].lower()
        for forbidden in ("card", "cvv", "expiry", "security"):
            assert forbidden not in header


@pytest.mark.django_db
class TestEnquiryInbox:
    def _login(self, client, roles):
        staff_in(MANAGER, roles)
        client.login(username="manager@example.com", password="DashLocal!2026")

    def test_opening_an_enquiry_marks_it_read(self, client, roles):
        enquiry = ContactMessage.objects.create(
            name="Jo", email="jo@example.com", message="hi", created_at=timezone.now(),
        )
        self._login(client, roles)
        client.get(reverse("dashboard:enquiry_detail", args=[enquiry.pk]))
        enquiry.refresh_from_db()
        assert enquiry.is_read

    def test_replying_records_who_and_when(self, client, roles):
        enquiry = ContactMessage.objects.create(
            name="Jo", email="jo@example.com", message="hi", created_at=timezone.now(),
        )
        self._login(client, roles)
        client.post(
            reverse("dashboard:enquiry_detail", args=[enquiry.pk]),
            {"reply": "Yes, we cover ABIA."},
        )
        enquiry.refresh_from_db()
        assert enquiry.is_answered
        assert enquiry.replied_by.email == "manager@example.com"
        assert enquiry.reply_body == "Yes, we cover ABIA."


@pytest.mark.django_db
class TestRoleSync:
    def test_is_idempotent(self, roles):
        from django.contrib.auth.models import Group

        first = {g.name: g.permissions.count() for g in Group.objects.all()}
        sync_roles()
        second = {g.name: g.permissions.count() for g in Group.objects.all()}
        assert first == second

    def test_creates_the_three_roles(self, roles):
        from django.contrib.auth.models import Group

        assert set(Group.objects.values_list("name", flat=True)) == {
            DISPATCHER, MANAGER, EDITOR,
        }

    def test_dispatcher_cannot_change_rates(self, roles):
        user = staff_in(DISPATCHER, roles)
        assert not user.has_perm("fleet.change_vehicle")
        assert user.has_perm("bookings.change_booking")

    def test_manager_can_change_rates(self, roles):
        user = staff_in(MANAGER, roles)
        assert user.has_perm("fleet.change_vehicle")
        assert user.has_perm("payments.add_refund")


@pytest.mark.django_db
class TestNoRawTemplateSyntaxLeaks:
    """
    Guard against unrendered template syntax reaching the browser.

    Django's `{# #}` comment is single-line only. A multi-line one is emitted
    as literal text, which produced a page of raw template source above the
    real content -- and every status check still returned 200, because the page
    "worked". Only a human looking at it, or this test, catches that.
    """

    @pytest.fixture
    def staff_client(self, client, roles):
        staff_in(MANAGER, roles)
        client.login(username="manager@example.com", password="DashLocal!2026")
        return client

    @pytest.mark.parametrize(
        "url_name",
        ["dashboard:home", "dashboard:dispatch", "dashboard:bookings",
         "dashboard:enquiries", "dashboard:payment_settings",
         "dashboard:email_settings", "dashboard:paypal_settings"],
    )
    def test_page_contains_no_unrendered_template_syntax(self, staff_client, url_name):
        body = staff_client.get(reverse(url_name)).content.decode()

        # Only the opening delimiters are checked. Inline CSS legitimately
        # produces "%}" (from `width:100%}`) and "}}" (from adjacent rule
        # closes), so those would false-positive. "{#" and "{%" cannot occur in
        # valid CSS or HTML, which makes them reliable evidence of a tag that
        # was never parsed.
        for marker in ("{#", "{%"):
            assert marker not in body, (
                f"{url_name} leaked raw template syntax {marker!r} into the page"
            )


@pytest.mark.django_db
class TestStaffSignIn:
    """
    The branded sign-in page that replaced Django's admin login.

    Worth testing beyond "it renders": the page is the authentication boundary,
    and its error message is deliberately vague for a reason.
    """

    def test_the_page_renders_our_own_template(self, client):
        response = client.get(reverse("dashboard:login"))
        body = response.content.decode()

        assert response.status_code == 200
        assert "dashboard/login.html" in [t.name for t in response.templates if t.name]
        assert "Austin Limo Shuttle" in body
        # Vendored, never a CDN -- the CSP would block an external stylesheet
        # silently and the page would render unstyled with no server error.
        assert "vendor/bootstrap/bootstrap.min.css" in body
        assert "cdn." not in body

    def test_no_inline_script_because_the_csp_forbids_it(self, client):
        """
        The CSP sets script-src 'self'. An inline <script> is dropped by the
        browser with no server-side error -- the page looks perfect and the
        behaviour silently does not happen. The password reveal shipped inline
        the first time and did nothing in production while passing locally.
        """
        body = client.get(reverse("dashboard:login")).content.decode()

        import re
        inline = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", body, re.S)
        substantive = [s for s in inline if s.strip()]
        assert not substantive, f"inline script on the login page: {substantive[:1]}"
        assert "js/login.js" in body

    def test_correct_credentials_reach_the_dashboard(self, client, roles):
        User.objects.create_user(
            email="dispatcher@example.com", password="DashLocal!2026", is_staff=True,
        )
        response = client.post(
            reverse("dashboard:login"),
            {"username": "dispatcher@example.com", "password": "DashLocal!2026"},
        )
        assert response.status_code == 302
        assert response["Location"] == reverse("dashboard:home")

    def test_a_wrong_password_does_not_say_which_half_was_wrong(self, client):
        User.objects.create_user(email="real@example.com", password="DashLocal!2026")
        response = client.post(
            reverse("dashboard:login"),
            {"username": "real@example.com", "password": "wrong-password"},
        )
        body = response.content.decode().lower()

        assert response.status_code == 200
        assert "email or password is incorrect" in body
        # Naming the field would confirm the address exists.
        assert "password is correct" not in body
        assert "no account" not in body

    def test_next_is_honoured_so_a_deep_link_still_lands(self, client, roles):
        User.objects.create_user(
            email="deep@example.com", password="DashLocal!2026", is_staff=True,
        )
        response = client.post(
            f"{reverse('dashboard:login')}?next={reverse('dashboard:dispatch')}",
            {"username": "deep@example.com", "password": "DashLocal!2026",
             "next": reverse("dashboard:dispatch")},
        )
        assert response["Location"] == reverse("dashboard:dispatch")

    def test_signing_out_requires_post_and_returns_to_the_gate(self, client, roles):
        User.objects.create_user(
            email="out@example.com", password="DashLocal!2026", is_staff=True,
        )
        client.login(username="out@example.com", password="DashLocal!2026")

        # GET must not log anyone out -- that would be a CSRF-able side effect.
        assert client.get(reverse("dashboard:logout")).status_code == 405

        response = client.post(reverse("dashboard:logout"))
        assert response.status_code == 302
        assert reverse("dashboard:login") in response["Location"]
        assert client.get(reverse("dashboard:home")).status_code == 302


@pytest.mark.django_db
class TestAdminLoginIsFunnelled:
    """
    The admin ships its own login view. Left alone it is a second sign-in
    screen for the same credentials, in a different visual language.
    """

    def test_admin_login_redirects_to_the_branded_gate(self, client):
        response = client.get("/admin/login/")
        assert response.status_code == 302
        assert reverse("dashboard:login") in response["Location"]

    def test_it_carries_the_destination_across(self, client):
        response = client.get("/admin/login/", {"next": "/admin/fleet/vehicle/"})
        assert "next=%2Fadmin%2Ffleet%2Fvehicle%2F" in response["Location"]

    def test_it_is_not_an_open_redirect(self, client):
        """Reflecting ?next= unchecked would make this a phishing primitive."""
        response = client.get("/admin/login/", {"next": "https://evil.example.com/"})
        assert "evil.example.com" not in response["Location"]
        assert "next=%2Fadmin%2F" in response["Location"]

    def test_the_admin_itself_still_works_once_signed_in(self, client, roles):
        user = User.objects.create_superuser(
            email="boss@example.com", password="DashLocal!2026",
        )
        client.force_login(user)
        assert client.get("/admin/").status_code == 200


@pytest.mark.django_db
class TestPagination:
    """
    Both lists used to truncate — bookings at 50, enquiries at 100 — and told
    you to narrow the filters. With 2,217 bookings imported, older records were
    simply unreachable through the interface.
    """

    def _staff(self, client, roles):
        staff_in(DISPATCHER, roles)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")

    def test_bookings_paginate_instead_of_truncating(self, client, roles, vehicle):
        for i in range(120):
            Booking.objects.create(
                vehicle=vehicle, pickup_address=f"pickup {i}",
                pickup_at=timezone.now() + timedelta(hours=i + 1),
                total=Decimal("50.00"),
            )
        self._staff(client, roles)

        first = client.get(reverse("dashboard:bookings"))
        assert first.context["page"].paginator.count == 120
        assert first.context["page"].paginator.num_pages == 3
        assert len(first.context["bookings"]) == 50
        assert b"Only the first" not in first.content

        last = client.get(reverse("dashboard:bookings"), {"page": 3})
        assert len(last.context["bookings"]) == 20

        # Every record is reachable, which is the whole point.
        seen = set()
        for number in (1, 2, 3):
            response = client.get(reverse("dashboard:bookings"), {"page": number})
            seen.update(b.reference for b in response.context["bookings"])
        assert len(seen) == 120

    def test_filters_survive_a_page_change(self, client, roles, vehicle):
        for i in range(60):
            Booking.objects.create(
                vehicle=vehicle, pickup_address="x",
                pickup_at=timezone.now() + timedelta(hours=i + 1),
                total=Decimal("50.00"),
                status=Booking.Status.CANCELLED if i % 2 else Booking.Status.CONFIRMED,
            )
        self._staff(client, roles)

        response = client.get(
            reverse("dashboard:bookings"),
            {"status": Booking.Status.CONFIRMED, "page": 1},
        )
        # The links must carry the filter, or page 2 shows a different set than
        # the one being paged through.
        assert "status=confirmed" in response.context["querystring"]
        assert "page=" not in response.context["querystring"]
        assert response.context["page"].paginator.count == 30

    def test_csv_export_is_the_whole_filtered_set_not_one_page(
        self, client, roles, vehicle,
    ):
        for i in range(70):
            Booking.objects.create(
                vehicle=vehicle, pickup_address="x",
                pickup_at=timezone.now() + timedelta(hours=i + 1),
                total=Decimal("50.00"),
            )
        self._staff(client, roles)

        response = client.get(reverse("dashboard:bookings"), {"export": "csv"})
        rows = response.content.decode().strip().splitlines()
        assert len(rows) == 71  # 70 bookings plus the header

    def test_a_silly_page_number_does_not_500(self, client, roles, booking):
        self._staff(client, roles)
        for value in ("0", "-1", "abc", "99999"):
            assert client.get(
                reverse("dashboard:bookings"), {"page": value}
            ).status_code == 200

    def test_enquiries_paginate_too(self, client, roles):
        for i in range(130):
            ContactMessage.objects.create(
                name=f"Person {i}", email=f"p{i}@example.org",
                message="Do you cover Round Rock?", is_read=True,
                # No auto_now_add on this model -- the API view sets it.
                created_at=timezone.now(),
            )
        self._staff(client, roles)

        response = client.get(reverse("dashboard:enquiries"), {"state": "all"})
        assert response.context["page"].paginator.count == 130
        assert len(response.context["enquiries"]) == 50

        page3 = client.get(
            reverse("dashboard:enquiries"), {"state": "all", "page": 3},
        )
        assert len(page3.context["enquiries"]) == 30
        assert "state=all" in page3.context["querystring"]


@pytest.mark.django_db
class TestQuickFiltersAndCalendar:
    def _staff(self, client, roles):
        staff_in(DISPATCHER, roles)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")

    def test_today_filter_shows_only_todays_pickups(self, client, roles, vehicle):
        today = timezone.localdate()
        # Noon today in the business timezone -- using now.replace(hour=12) sets
        # noon UTC, whose *local* date can be a different day near midnight, which
        # made this test flaky depending on the hour it ran.
        local_noon = timezone.make_aware(datetime.combine(today, time(12, 0)))
        todays = Booking.objects.create(
            vehicle=vehicle, pickup_address="today", total=Decimal("50"),
            pickup_at=local_noon,
        )
        next_week = Booking.objects.create(
            vehicle=vehicle, pickup_address="later", total=Decimal("50"),
            pickup_at=local_noon + timedelta(days=7),
        )
        self._staff(client, roles)

        response = client.get(
            reverse("dashboard:bookings"),
            {"from": today.isoformat(), "to": today.isoformat()},
        )
        body = response.content.decode()
        assert todays.reference in body
        assert next_week.reference not in body
        assert response.context["active_quick"] == "today"

    def test_tomorrow_filter(self, client, roles, vehicle):
        tomorrow = timezone.localdate() + timedelta(days=1)
        booking = Booking.objects.create(
            vehicle=vehicle, pickup_address="tomorrow", total=Decimal("50"),
            pickup_at=timezone.now() + timedelta(days=1),
        )
        self._staff(client, roles)

        response = client.get(
            reverse("dashboard:bookings"),
            {"from": tomorrow.isoformat(), "to": tomorrow.isoformat()},
        )
        assert booking.reference in response.content.decode()
        assert response.context["active_quick"] == "tomorrow"

    def test_calendar_renders_a_full_month_grid(self, client, roles, booking):
        self._staff(client, roles)
        response = client.get(reverse("dashboard:calendar"))

        assert response.status_code == 200
        # Whole weeks always, so every row has seven cells.
        assert all(len(week) == 7 for week in response.context["weeks"])
        assert len(response.context["weeks"]) in (4, 5, 6)

    def test_calendar_places_a_booking_on_its_own_day(self, client, roles, vehicle):
        when = timezone.now() + timedelta(days=3)
        booking = Booking.objects.create(
            vehicle=vehicle, pickup_address="x", total=Decimal("50"), pickup_at=when,
        )
        self._staff(client, roles)

        response = client.get(reverse("dashboard:calendar"))
        target = timezone.localtime(when).date()
        placed = [
            day for week in response.context["weeks"] for day in week
            if day["date"] == target
        ]
        assert placed and booking in placed[0]["bookings"]

    def test_calendar_hides_cancelled_bookings(self, client, roles, vehicle):
        Booking.objects.create(
            vehicle=vehicle, pickup_address="x", total=Decimal("50"),
            pickup_at=timezone.now() + timedelta(days=2),
            status=Booking.Status.CANCELLED,
        )
        self._staff(client, roles)
        response = client.get(reverse("dashboard:calendar"))
        assert response.context["month_total"] == 0

    def test_calendar_month_navigation(self, client, roles):
        self._staff(client, roles)
        response = client.get(reverse("dashboard:calendar"), {"year": 2026, "month": 1})
        assert "January 2026" in response.content.decode()
        # December of the previous year, not month zero.
        assert response.context["prev"] == {"year": 2025, "month": 12}
        assert response.context["next"] == {"year": 2026, "month": 2}

    def test_calendar_survives_a_nonsense_month(self, client, roles):
        self._staff(client, roles)
        for params in ({"month": "13"}, {"month": "abc"}, {"year": "0"}):
            assert client.get(
                reverse("dashboard:calendar"), params
            ).status_code == 200


@pytest.mark.django_db
class TestManagedRecords:
    """
    The screens that replace Django's admin.

    The client is never to be sent to /admin/, so anything they need must work
    here — and must respect the same permission boundaries the admin did.
    """

    def _manager(self, client, roles):
        user = staff_in(MANAGER, roles)
        client.login(username="manager@example.com", password="DashLocal!2026")
        return user

    def test_every_registered_screen_loads_for_a_manager(self, client, roles):
        from dashboard.crud import REGISTRY
        self._manager(client, roles)
        for slug in REGISTRY:
            response = client.get(reverse("dashboard:managed_list", args=[slug]))
            assert response.status_code == 200, f"{slug} returned {response.status_code}"

    def test_a_driver_can_be_created_and_edited(self, client, roles):
        self._manager(client, roles)

        client.post(reverse("dashboard:managed_create", args=["drivers"]), {
            "full_name": "Alex Ruiz", "phone": "5125550134",
            "email": "alex@example.org", "is_active": "on", "notes": "",
        })
        driver = Driver.objects.get(full_name="Alex Ruiz")

        client.post(reverse("dashboard:managed_edit", args=["drivers", driver.pk]), {
            "full_name": "Alex Ruiz", "phone": "5125550199",
            "email": "alex@example.org", "notes": "",
        })
        driver.refresh_from_db()
        assert driver.phone == "5125550199"
        assert driver.is_active is False  # checkbox omitted means unchecked

    def test_dispatcher_cannot_reach_the_rate_card(self, client, roles):
        """A rate card edit reprices every future quote. Managers only."""
        staff_in(DISPATCHER, roles)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")

        assert client.get(
            reverse("dashboard:managed_create", args=["vehicles"])
        ).status_code == 403

    def test_editor_can_reach_content_but_not_vehicles(self, client, roles):
        staff_in(EDITOR, roles)
        client.login(username="editor@example.com", password="DashLocal!2026")

        # An Editor has no bookings permission, so the dashboard gate itself
        # turns them away -- content editing happens through the same gate.
        assert client.get(
            reverse("dashboard:managed_list", args=["pages"])
        ).status_code in (302, 403)

    def test_staff_and_customer_lists_do_not_bleed_into_each_other(
        self, client, roles,
    ):
        """Both are rows in one table; each screen must exclude the other."""
        self._manager(client, roles)
        User.objects.create_user(email="buyer@example.org", password="DashLocal!2026")

        staff_page = client.get(reverse("dashboard:managed_list", args=["staff"]))
        customer_page = client.get(reverse("dashboard:managed_list", args=["customers"]))

        # Against the rows, not the rendered page: the sidebar prints the
        # signed-in user's own email on every screen, which would make a
        # whole-page search pass or fail for the wrong reason.
        def emails(response):
            return {row["instance"].email for row in response.context["rows"]}

        assert "buyer@example.org" not in emails(staff_page)
        assert "buyer@example.org" in emails(customer_page)
        assert "manager@example.com" in emails(staff_page)
        assert "manager@example.com" not in emails(customer_page)

    def test_a_new_staff_account_gets_its_role_and_can_sign_in(self, client, roles):
        self._manager(client, roles)

        client.post(reverse("dashboard:managed_create", args=["staff"]), {
            "email": "newhire@example.com", "first_name": "New", "last_name": "Hire",
            "phone": "", "is_active": "on",
            "role": Group.objects.get(name=DISPATCHER).pk,
            "new_password": "AnotherStrongPass!99",
        })

        user = User.objects.get(email="newhire@example.com")
        assert user.is_staff
        assert list(user.groups.values_list("name", flat=True)) == [DISPATCHER]
        assert user.check_password("AnotherStrongPass!99")

    def test_a_weak_staff_password_is_refused(self, client, roles):
        self._manager(client, roles)
        client.post(reverse("dashboard:managed_create", args=["staff"]), {
            "email": "weak@example.com", "is_active": "on", "new_password": "1234",
        })
        assert not User.objects.filter(email="weak@example.com").exists()

    def test_editing_staff_without_a_password_keeps_the_old_one(self, client, roles):
        self._manager(client, roles)
        user = User.objects.create_user(
            email="keeps@example.com", password="DashLocal!2026", is_staff=True,
        )

        client.post(reverse("dashboard:managed_edit", args=["staff", user.pk]), {
            "email": "keeps@example.com", "first_name": "Still", "last_name": "Here",
            "phone": "", "is_active": "on", "new_password": "",
        })

        user.refresh_from_db()
        assert user.first_name == "Still"
        assert user.check_password("DashLocal!2026")

    def test_staff_accounts_cannot_be_deleted(self, client, roles):
        """The audit trail points at them; deactivation is the supported route."""
        user = self._manager(client, roles)
        response = client.post(
            reverse("dashboard:managed_delete", args=["staff", user.pk])
        )
        assert response.status_code == 403
        assert User.objects.filter(pk=user.pk).exists()

    def test_an_unknown_slug_is_a_404_not_a_500(self, client, roles):
        self._manager(client, roles)
        assert client.get(
            reverse("dashboard:managed_list", args=["nonsense"])
        ).status_code == 404


@pytest.mark.django_db
class TestRateCardValidation:
    """
    Distance bands are cumulative, so a card can be wrong while every row in it
    is individually valid. These are the two failures that misprice silently.
    """

    def _post_bands(self, client, vehicle, bands):
        data = {
            "name": vehicle.name, "slug": vehicle.slug, "description": "",
            "features": "", "passenger_capacity": "3", "luggage_capacity": "2",
            "hourly_rate": "85.00", "meet_greet_fee": "0.00",
            "minimum_fare": "45.00", "display_order": "0", "is_active": "on",
            "bands-TOTAL_FORMS": str(len(bands)),
            "bands-INITIAL_FORMS": "0",
            "bands-MIN_NUM_FORMS": "0",
            "bands-MAX_NUM_FORMS": "1000",
        }
        for i, (start, end, rate) in enumerate(bands):
            data[f"bands-{i}-from_miles"] = str(start)
            data[f"bands-{i}-to_miles"] = "" if end is None else str(end)
            data[f"bands-{i}-rate_per_mile"] = str(rate)
        return client.post(
            reverse("dashboard:managed_edit", args=["vehicles", vehicle.pk]), data,
        )

    def test_a_gap_between_bands_is_refused(self, client, roles, vehicle):
        staff_in(MANAGER, roles)
        client.login(username="manager@example.com", password="DashLocal!2026")

        # Nothing prices miles 6 to 10, so those four miles would cost nothing.
        response = self._post_bands(
            client, vehicle, [(0, 6, "3.50"), (10, None, "2.90")],
        )
        assert response.status_code == 200
        assert b"Nothing prices the miles between" in response.content
        assert vehicle.bands.count() == 0

    def test_overlapping_bands_are_refused(self, client, roles, vehicle):
        staff_in(MANAGER, roles)
        client.login(username="manager@example.com", password="DashLocal!2026")

        # Miles 5 to 6 would be charged by both bands.
        response = self._post_bands(
            client, vehicle, [(0, 6, "3.50"), (5, None, "2.90")],
        )
        assert response.status_code == 200
        assert b"charged twice" in response.content
        assert vehicle.bands.count() == 0

    def test_a_card_not_starting_at_zero_is_refused(self, client, roles, vehicle):
        staff_in(MANAGER, roles)
        client.login(username="manager@example.com", password="DashLocal!2026")

        response = self._post_bands(client, vehicle, [(2, None, "3.50")])
        assert b"must start at 0 miles" in response.content
        assert vehicle.bands.count() == 0

    def test_a_continuous_card_saves(self, client, roles, vehicle):
        staff_in(MANAGER, roles)
        client.login(username="manager@example.com", password="DashLocal!2026")

        response = self._post_bands(
            client, vehicle, [(0, 6, "3.50"), (6, 50, "2.90"), (50, None, "2.40")],
        )
        assert response.status_code == 302
        assert vehicle.bands.count() == 3


@pytest.mark.django_db
class TestRateCardRemoveControl:
    """
    The inline rate-card table renders Django's per-row DELETE field as a
    styled "Remove" trash button (no JS -- the CSP forbids it). Two things
    must hold: the DELETE field must NOT get its own stray column header, and
    the checkbox must still render so a Save actually deletes the ticked rows.
    """

    def _render_vehicle_form(self, client, roles, vehicle):
        staff_in(MANAGER, roles)
        client.login(username="manager@example.com", password="DashLocal!2026")
        response = client.get(
            reverse("dashboard:managed_edit", args=["vehicles", vehicle.pk])
        )
        assert response.status_code == 200
        return response.content.decode()

    def test_no_stray_delete_column_header(self, client, roles, vehicle):
        body = self._render_vehicle_form(client, roles, vehicle)
        import re

        headers = re.findall(r"<th[^>]*>(.*?)</th>", body, re.S)
        labels = [re.sub(r"<[^>]+>", "", h).strip().upper() for h in headers]
        # Django labels the DELETE field "Delete"; the human column is "Remove".
        assert "DELETE" not in labels
        assert "Remove" in [re.sub(r"<[^>]+>", "", h).strip() for h in headers]

    def test_delete_checkbox_still_renders_so_deletion_works(
        self, client, roles, vehicle,
    ):
        body = self._render_vehicle_form(client, roles, vehicle)
        # The native DELETE checkbox is what Save acts on; it must survive,
        # wrapped in the styled remove-row button.
        assert 'name="bands-0-DELETE"' in body
        assert "remove-row-btn" in body

    def test_ticking_delete_removes_the_row_on_save(self, client, roles, vehicle):
        """End-to-end: the hidden checkbox still drives a real deletion."""
        from fleet.models import DistanceBand

        DistanceBand.objects.create(
            vehicle=vehicle, from_miles=0, to_miles=None, rate_per_mile="3.00",
        )
        staff_in(MANAGER, roles)
        client.login(username="manager@example.com", password="DashLocal!2026")

        band = vehicle.bands.get()
        data = {
            "name": vehicle.name, "slug": vehicle.slug, "description": "",
            "features": "", "passenger_capacity": "3", "luggage_capacity": "2",
            "hourly_rate": "85.00", "meet_greet_fee": "0.00",
            "minimum_fare": "45.00", "display_order": "0", "is_active": "on",
            "bands-TOTAL_FORMS": "1", "bands-INITIAL_FORMS": "1",
            "bands-MIN_NUM_FORMS": "0", "bands-MAX_NUM_FORMS": "1000",
            "bands-0-id": str(band.pk),
            "bands-0-from_miles": "0", "bands-0-to_miles": "",
            "bands-0-rate_per_mile": "3.00",
            "bands-0-DELETE": "on",
        }
        response = client.post(
            reverse("dashboard:managed_edit", args=["vehicles", vehicle.pk]), data,
        )
        assert response.status_code == 302
        assert vehicle.bands.count() == 0


@pytest.mark.django_db
class TestSingletonSettingsScreens:
    def test_site_settings_saves(self, client, roles):
        staff_in(MANAGER, roles)
        client.login(username="manager@example.com", password="DashLocal!2026")

        response = client.post(reverse("dashboard:site_settings"), {
            "contact_phone": "+1 (512) 555-0134",
            "contact_email": "info@austinlimoshuttle.com",
            "ops_notification_email": "dispatch@austinlimoshuttle.com",
            "facebook": "", "instagram": "", "twitter": "", "linkedin": "",
        })
        assert response.status_code == 302

        from content.models import SiteSettings
        assert SiteSettings.load().contact_phone == "+1 (512) 555-0134"

    def test_pricing_settings_are_manager_only(self, client, roles):
        staff_in(DISPATCHER, roles)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")
        assert client.get(reverse("dashboard:pricing_settings")).status_code == 403


@pytest.mark.django_db
class TestManualBooking:
    """The rebuilt New Booking page: engine pricing, 3 trip types, customer, cash."""

    def _login(self, client, roles):
        staff_in(MANAGER, roles)
        client.login(username="manager@example.com", password="DashLocal!2026")

    def _payload(self, vehicle, **over):
        data = dict(
            pickup_sign="Jane Doe", guest_phone="+15125550100", guest_email="",
            vehicle=str(vehicle.pk), pickup_at="2026-12-01T14:00",
            pickup_address="Austin", dropoff_address="", hours="",
            passenger_count="1", luggage_count="0", flight_number="",
            status=Booking.Status.CONFIRMED, notes="",
            trip_mode="hourly", city_route="", override_total="",
            customer_id="", driver="", payment_method="cash",
        )
        data.update(over)
        return data

    def test_hourly_is_priced_by_the_engine(self, client, roles, vehicle):
        self._login(client, roles)
        r = client.post(reverse("dashboard:booking_create"),
                        self._payload(vehicle, trip_mode="hourly", hours="3"))
        assert r.status_code == 302
        b = Booking.objects.get()
        assert b.trip_type == Booking.TripType.HOURLY
        assert b.total == Decimal("255.00")  # 3h x $85

    def test_override_sets_total_and_records_it(self, client, roles, vehicle):
        self._login(client, roles)
        r = client.post(reverse("dashboard:booking_create"),
                        self._payload(vehicle, trip_mode="hourly", hours="3", override_total="200"))
        assert r.status_code == 302
        b = Booking.objects.get()
        assert b.total == Decimal("200.00")
        assert "agreed by staff" in b.price_lines.get().label

    def test_hourly_requires_hours(self, client, roles, vehicle):
        self._login(client, roles)
        r = client.post(reverse("dashboard:booking_create"),
                        self._payload(vehicle, trip_mode="hourly", hours=""))
        assert r.status_code == 200
        assert not Booking.objects.exists()

    def test_transfer_requires_a_dropoff(self, client, roles, vehicle):
        self._login(client, roles)
        r = client.post(reverse("dashboard:booking_create"),
                        self._payload(vehicle, trip_mode="transfer", dropoff_address=""))
        assert r.status_code == 200
        assert not Booking.objects.exists()

    def test_city_uses_the_flat_route_price(self, client, roles, vehicle):
        from pricing.models import CityRoute, CityRoutePrice
        route = CityRoute.objects.create(origin="Austin", destination="Houston")
        CityRoutePrice.objects.create(route=route, vehicle=vehicle, price=Decimal("395"))
        self._login(client, roles)
        r = client.post(reverse("dashboard:booking_create"),
                        self._payload(vehicle, trip_mode="city", city_route=str(route.pk)))
        assert r.status_code == 302
        b = Booking.objects.get()
        assert b.total == Decimal("395.00")
        assert b.city_route_id == route.pk

    def test_new_customer_created_from_email(self, client, roles, vehicle):
        self._login(client, roles)
        client.post(reverse("dashboard:booking_create"),
                    self._payload(vehicle, hours="2", guest_email="fresh@example.com"))
        b = Booking.objects.get()
        assert b.customer and b.customer.email == "fresh@example.com"

    def test_no_email_is_a_guest(self, client, roles, vehicle):
        self._login(client, roles)
        client.post(reverse("dashboard:booking_create"),
                    self._payload(vehicle, hours="2", guest_email=""))
        assert Booking.objects.get().customer is None

    def test_cash_records_awaiting_collection(self, client, roles, vehicle):
        from payments.models import Payment
        self._login(client, roles)
        client.post(reverse("dashboard:booking_create"),
                    self._payload(vehicle, hours="2", payment_method="cash"))
        p = Booking.objects.get().payments.get()
        assert p.provider == Payment.Provider.CASH
        assert p.status == Payment.Status.PROCESSING

    def test_mark_cash_collected(self, client, roles, vehicle):
        from payments.models import Payment
        self._login(client, roles)
        client.post(reverse("dashboard:booking_create"), self._payload(vehicle, hours="2"))
        b = Booking.objects.get()
        client.post(reverse("dashboard:booking_mark_cash_collected", args=[b.reference]))
        assert b.payments.get().status == Payment.Status.SUCCEEDED

    def test_card_requires_a_customer(self, client, roles, vehicle):
        self._login(client, roles)
        r = client.post(reverse("dashboard:booking_create"),
                        self._payload(vehicle, hours="2", payment_method="card",
                                      stripe_payment_method_id="pm_x", guest_email=""))
        assert r.status_code == 200
        assert not Booking.objects.exists()  # card needs a customer -> rejected


@pytest.mark.django_db
class TestTripEvents:
    """
    Back-office trip-event history + map. This lane only *reads* the events that
    @bookings-core's DriverTripEvent records; rows are created directly here to
    keep the read tests isolated from record()'s status/signal side effects.
    """

    def _event(self, booking, event_type=DriverTripEvent.EventType.ARRIVED,
               lat=None, lng=None, driver=None):
        return DriverTripEvent.objects.create(
            booking=booking, event_type=event_type,
            latitude=lat, longitude=lng, driver=driver,
        )

    def _as_dispatcher(self, client, roles):
        staff_in(DISPATCHER, roles)
        client.login(username="dispatcher@example.com", password="DashLocal!2026")

    # --- staff gating -----------------------------------------------------
    def test_feed_redirects_anonymous_to_dashboard_login(self, client):
        response = client.get(reverse("dashboard:trip_events"))
        assert response.status_code == 302
        assert "/dashboard/login/" in response["Location"]
        assert "/admin/login/" not in response["Location"]

    def test_feed_forbids_non_booking_staff(self, client, roles):
        """An editor has no bookings.view_booking, so no trip history either."""
        staff_in(EDITOR, roles)
        client.login(username="editor@example.com", password="DashLocal!2026")
        assert client.get(reverse("dashboard:trip_events")).status_code == 403

    def test_feed_allows_dispatcher(self, client, roles):
        self._as_dispatcher(client, roles)
        assert client.get(reverse("dashboard:trip_events")).status_code == 200

    # --- listing ----------------------------------------------------------
    def test_feed_lists_events_with_type_booking_and_driver(self, client, roles, booking):
        driver = Driver.objects.create(full_name="Alex Ruiz")
        self._event(booking, DriverTripEvent.EventType.ON_WAY,
                    lat=Decimal("30.194500"), lng=Decimal("-97.669800"), driver=driver)
        self._as_dispatcher(client, roles)
        html = client.get(reverse("dashboard:trip_events")).content.decode()
        assert "On the way" in html          # event type label
        assert booking.reference in html     # booking reference
        assert "Alex Ruiz" in html           # driver
        assert "30.194500" in html           # lat/lng

    def test_booking_detail_lists_its_own_events(self, client, roles, booking):
        self._event(booking, DriverTripEvent.EventType.ARRIVED,
                    lat=Decimal("30.1"), lng=Decimal("-97.6"))
        self._as_dispatcher(client, roles)
        html = client.get(
            reverse("dashboard:booking_detail", args=[booking.reference])
        ).content.decode()
        assert "Trip events" in html
        assert "Arrived at pickup" in html

    # --- events without coordinates --------------------------------------
    def test_event_without_coords_shown_as_location_unknown(self, client, roles, booking):
        self._event(booking, DriverTripEvent.EventType.ON_WAY)  # null lat/lng
        self._as_dispatcher(client, roles)
        html = client.get(
            reverse("dashboard:booking_detail", args=[booking.reference])
        ).content.decode()
        # The per-row "location unknown" marker (its own icon) must be present.
        assert "location unknown" in html
        assert "bi-geo-alt-slash" in html

    def test_event_with_coords_is_not_location_unknown(self, client, roles, booking):
        self._event(booking, DriverTripEvent.EventType.ARRIVED,
                    lat=Decimal("30.19"), lng=Decimal("-97.66"))
        self._as_dispatcher(client, roles)
        html = client.get(
            reverse("dashboard:booking_detail", args=[booking.reference])
        ).content.decode()
        # No row carries the unknown-location marker (the caption mentioning the
        # phrase is not a row), and the coordinates are shown instead.
        assert "bi-geo-alt-slash" not in html
        assert "30.19" in html

    def test_only_located_events_become_map_pins(self, client, roles, booking):
        """The json_script feeding the map carries the located event, not the null one."""
        self._event(booking, DriverTripEvent.EventType.ON_WAY)  # no fix
        self._event(booking, DriverTripEvent.EventType.ARRIVED,
                    lat=Decimal("30.265000"), lng=Decimal("-97.745000"))
        self._as_dispatcher(client, roles)
        html = client.get(reverse("dashboard:trip_events")).content.decode()
        assert '"lat": 30.265' in html
        # exactly one pin: both events share the booking, so a single ref appears
        # in the json payload per located event.
        assert html.count('"lat":') == 1

    # --- map uses the self-hosted Leaflet, never a CDN -------------------
    def test_map_references_local_leaflet_not_a_cdn(self, client, roles, booking):
        self._event(booking, DriverTripEvent.EventType.ARRIVED,
                    lat=Decimal("30.19"), lng=Decimal("-97.66"))
        self._as_dispatcher(client, roles)
        html = client.get(reverse("dashboard:trip_events")).content.decode()
        assert "vendor/leaflet/leaflet.js" in html
        assert "vendor/leaflet/leaflet.css" in html
        assert "js/trip-map.js" in html
        for cdn in ("unpkg.com", "cdnjs", "jsdelivr", "cdn.leaflet"):
            assert cdn not in html

    def test_leaflet_is_actually_vendored_and_tiles_point_at_osm(self):
        """The local Leaflet lib is on disk and our init script uses OSM tiles."""
        from django.contrib.staticfiles import finders

        assert finders.find("vendor/leaflet/leaflet.js")
        assert finders.find("vendor/leaflet/leaflet.css")
        trip_map = finders.find("js/trip-map.js")
        assert trip_map
        with open(trip_map, encoding="utf-8") as fh:
            source = fh.read()
        assert "tile.openstreetmap.org" in source
        for cdn in ("unpkg.com", "cdnjs", "jsdelivr"):
            assert cdn not in source

    def test_leaflet_survives_manifest_collectstatic(self, tmp_path):
        """
        Regression guard for the prod boot crash: under
        CompressedManifestStaticFilesStorage (prod), collectstatic post-processes
        leaflet.js/.css and resolves every reference they contain -- url(images/..)
        in the CSS and the //# sourceMappingURL=leaflet.js.map comment in the JS.
        A referenced-but-unvendored asset raises MissingFileError and crash-loops
        the backend. We reproduce that exact code path with Django's own
        ManifestStaticFilesStorage (whitenoise's prod storage subclasses it) over
        just the vendored Leaflet tree, so if anyone drops leaflet.js.map or an
        images/*.png again this fails here instead of at deploy.
        """
        import shutil
        from pathlib import Path

        from django.contrib.staticfiles import finders
        from django.contrib.staticfiles.storage import ManifestStaticFilesStorage

        leaflet_js = finders.find("vendor/leaflet/leaflet.js")
        assert leaflet_js, "vendored leaflet.js is missing"
        vendor_src = Path(leaflet_js).parent

        # Mirror the vendored tree into a throwaway STATIC_ROOT, exactly as
        # collectstatic's copy step would, then run manifest post-processing.
        static_root = tmp_path / "static"
        dest = static_root / "vendor" / "leaflet"
        shutil.copytree(vendor_src, dest)

        storage = ManifestStaticFilesStorage(location=str(static_root))
        collected = {}
        for path in static_root.rglob("*"):
            if path.is_file():
                name = str(path.relative_to(static_root))
                collected[name] = (storage, name)

        # post_process yields (name, hashed_name, processed); ManifestStaticFilesStorage
        # raises MissingFileError here if any referenced asset is absent.
        results = list(storage.post_process(collected))
        for name, hashed_name, processed in results:
            assert not isinstance(processed, Exception), \
                f"post_process failed for {name}: {processed!r}"
        assert hashed_name  # at least one file was hashed
