"""Public API routes consumed by the Next.js frontend."""

from django.urls import path

from . import payment_views, views

app_name = "api"

urlpatterns = [
    # Content
    path("pages/", views.page_list, name="pages"),
    path("pages/<slug:slug>/", views.page_detail, name="page_detail"),
    path("vehicles/", views.vehicle_list, name="vehicles"),
    path("site-settings/", views.site_settings, name="site_settings"),
    path("availability/", views.availability, name="availability"),

    # Quoting and booking
    path("quotes/", views.create_quote, name="quotes"),
    path("bookings/", views.create_booking, name="create_booking"),
    path("bookings/<str:reference>/status/", views.booking_status,
         name="booking_status"),
    path("bookings/<str:reference>/receipt/", views.booking_receipt,
         name="booking_receipt"),
    path("bookings/<str:reference>/pay-cash/", payment_views.pay_cash,
         name="pay_cash"),

    # Customer account
    path("account/bookings/", views.my_bookings, name="my_bookings"),
    path("account/bookings/<str:reference>/", views.my_booking_detail,
         name="my_booking_detail"),
    path("account/bookings/<str:reference>/amend-request/", views.amend_request,
         name="amend_request"),
    path("account/bookings/<str:reference>/cancel-request/", views.cancel_request,
         name="cancel_request"),
    path("account/profile/", views.account_profile, name="account_profile"),
    path("account/cards/", views.my_cards, name="my_cards"),
    path("account/cards/setup-intent/", views.my_card_setup_intent,
         name="my_card_setup_intent"),
    path("account/cards/<int:pk>/", views.my_card_delete, name="my_card_delete"),
    path("account/cards/<int:pk>/default/", views.my_card_set_default,
         name="my_card_set_default"),

    # Staff: booking change-request review queue (staff-only, is_staff).
    path("staff/amendment-requests/", views.staff_amendment_requests,
         name="staff_amendment_requests"),
    path("staff/amendment-requests/<int:pk>/approve/",
         views.staff_amendment_approve, name="staff_amendment_approve"),
    path("staff/amendment-requests/<int:pk>/decline/",
         views.staff_amendment_decline, name="staff_amendment_decline"),

    # Auth
    path("auth/csrf/", views.auth_csrf, name="csrf"),
    path("auth/login/", views.auth_login, name="login"),
    path("auth/logout/", views.auth_logout, name="logout"),
    path("auth/register/", views.auth_register, name="register"),
    path("auth/password-reset/", views.auth_password_reset, name="password_reset"),
    path("auth/send-code/", views.auth_send_code, name="send_code"),
    path("auth/verify-code/", views.auth_verify_code, name="verify_code"),
    path("auth/me/", views.auth_me, name="me"),

    # Payments
    path("payments/config/", payment_views.payment_config, name="payment_config"),
    path("payments/intent/", payment_views.create_intent, name="payment_intent"),
    path("payments/webhook/", payment_views.webhook, name="payment_webhook"),

    # Enquiries
    path("enquiries/", views.create_enquiry, name="enquiries"),
]
