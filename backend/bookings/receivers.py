"""
Receivers the bookings app subscribes to framework signals with.

Kept separate from `signals.py`, which only *defines* signals bookings sends
(one-way dependency; see that module's docstring).
"""

from __future__ import annotations

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in, dispatch_uid="bookings.claim_guest_bookings")
def claim_guest_bookings(sender, request, user, **kwargs):
    """
    Attach a guest's bookings to their account the moment they sign in.

    A guest booking (customer NULL, guest_email set) is otherwise unmanageable:
    the confirmation page says "create an account to track this ride", so that
    promise is kept here. Signing in proves control of the mailbox the booking
    receipt went to, which is the same bar the receipt itself sets — hence
    claim-by-verified-email. Exact (case-insensitive) match, unclaimed bookings
    only; guest_* fields are kept as the historical record of who booked.

    Fires on every login path — password, one-time code, and registration
    (which logs the new account in) — because they all call auth.login().
    """
    from .models import Booking

    email = (user.email or "").strip()
    if not email:
        return
    Booking.objects.filter(
        customer__isnull=True, guest_email__iexact=email,
    ).update(customer=user)
