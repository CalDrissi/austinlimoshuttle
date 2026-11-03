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
    path("account/cards/", views.my_cards, name="my_cards"),
    path("account/cards/<int:pk>/", views.my_card_delete, name="my_card_delete"),

    # Auth
    path("auth/csrf/", views.auth_csrf, name="csrf"),
    path("auth/login/", views.auth_login, name="login"),
    path("auth/logout/", views.auth_logout, name="logout"),
    path("auth/register/", views.auth_register, name="register"),
    path("auth/password-reset/", views.auth_password_reset, name="password_reset"),
    path("auth/me/", views.auth_me, name="me"),

    # Payments
    path("payments/config/", payment_views.payment_config, name="payment_config"),
    path("payments/intent/", payment_views.create_intent, name="payment_intent"),
    path("payments/webhook/", payment_views.webhook, name="payment_webhook"),

    # Enquiries
    path("enquiries/", views.create_enquiry, name="enquiries"),
]
