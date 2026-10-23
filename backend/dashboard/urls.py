"""Dashboard URLs."""

from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    # Staff sign-in. Django's admin login used to be the gate, which meant the
    # first screen anyone saw was Django's, not ours.
    path(
        "login/",
        # redirect_authenticated_user is intentionally off: a stale or non-staff
        # session must not bounce the visitor into the 403 home page -- they can
        # always re-authenticate as staff from this form.
        auth_views.LoginView.as_view(
            template_name="dashboard/login.html",
        ),
        name="login",
    ),
    # LogoutView is POST-only from Django 5, so the sidebar link is a form.
    path(
        "logout/",
        auth_views.LogoutView.as_view(next_page="dashboard:login"),
        name="logout",
    ),

    path("", views.home, name="home"),
    path("dispatch/", views.dispatch, name="dispatch"),
    path("calendar/", views.calendar_view, name="calendar"),
    path("bookings/", views.booking_list, name="bookings"),
    path("bookings/new/", views.booking_create, name="booking_create"),
    path("bookings/quote/", views.booking_quote, name="booking_quote"),
    path("bookings/customer-lookup/", views.booking_customer_lookup, name="booking_customer_lookup"),
    path("bookings/<str:reference>/cash-collected/", views.booking_mark_cash_collected, name="booking_mark_cash_collected"),
    path("bookings/<str:reference>/", views.booking_detail, name="booking_detail"),
    path("bookings/<str:reference>/edit/", views.booking_edit, name="booking_edit"),
    path("bookings/<str:reference>/update/", views.booking_update, name="booking_update"),
    path("bookings/<str:reference>/refund/", views.issue_refund, name="issue_refund"),
    path("charge/", views.charge_card, name="charge_card"),
    path("settings/payments/", views.payment_settings, name="payment_settings"),
    path("settings/paypal/", views.paypal_settings, name="paypal_settings"),
    path("settings/email/", views.email_settings, name="email_settings"),
    path("settings/sms/", views.sms_settings, name="sms_settings"),
    path("enquiries/", views.enquiry_inbox, name="enquiries"),
    path("enquiries/<int:pk>/", views.enquiry_detail, name="enquiry_detail"),

    # Give drivers a login for the mobile driver app.
    path("drivers/access/", views.driver_access, name="driver_access"),

    # Site-wide configuration that used to live in Django's admin.
    path("settings/site/", views.site_settings, name="site_settings"),
    path("settings/pricing/", views.pricing_settings, name="pricing_settings"),

    # Managed records: drivers, vehicles, rates, content, people. One set of
    # views over the dashboard.managed registry -- see dashboard/crud.py.
    path("manage/<slug:slug>/", views.managed_list, name="managed_list"),
    path("manage/<slug:slug>/new/", views.managed_edit, name="managed_create"),
    path("manage/<slug:slug>/<int:pk>/", views.managed_edit, name="managed_edit"),
    path("manage/<slug:slug>/<int:pk>/delete/", views.managed_delete,
         name="managed_delete"),
]
