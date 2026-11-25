"""
SMS delivery via Twilio's HTTP API.

Mirrors notifications/mailer.py: dashboard-managed credentials, every attempt
logged to SmsLog, and sends NEVER raise -- a texting outage must never break a
booking. Uses `requests` (already a dependency); no Twilio SDK needed.
"""

from __future__ import annotations

import logging

import requests
from django.template.loader import render_to_string
from django.utils import timezone

from .models import SmsLog, SmsSettings
from .phone import to_e164

logger = logging.getLogger(__name__)

TWILIO_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
TIMEOUT = 15


def _send(to: str, body: str, *, kind: str, booking=None) -> bool:
    """
    Send one text. Returns True on success. Logs every attempt; never raises.

    No-op (returns False) when SMS is disabled/unconfigured or the recipient has
    no usable number -- callers can fire this unconditionally.
    """
    config = SmsSettings.load()
    if not config.is_configured:
        return False

    number = to_e164(to)
    if not number:
        SmsLog.objects.create(
            kind=kind, to_number=(to or "")[:20], body=body, booking=booking,
            succeeded=False, error="No valid phone number.",
        )
        return False

    try:
        resp = requests.post(
            TWILIO_URL.format(sid=config.account_sid),
            data={"From": config.from_number, "To": number, "Body": body},
            auth=(config.account_sid, config.auth_token),
            timeout=TIMEOUT,
        )
        ok = resp.status_code in (200, 201)
        sid, error = "", ""
        if ok:
            sid = (resp.json() or {}).get("sid", "")
        else:
            # Twilio returns a JSON {message, code}; fall back to raw text.
            try:
                error = (resp.json() or {}).get("message", "") or resp.text[:500]
            except ValueError:
                error = resp.text[:500]
    except requests.RequestException as exc:
        ok, sid, error = False, "", str(exc)[:500]

    SmsLog.objects.create(
        kind=kind, to_number=number, body=body, booking=booking,
        succeeded=ok, provider_sid=sid, error=error,
    )
    if not ok:
        logger.warning("SMS %s to %s failed: %s", kind, number, error)
    return ok


def _render(template: str, booking) -> str:
    return render_to_string(f"notifications/sms/{template}.txt", {"booking": booking}).strip()


def send_booking_confirmation(booking) -> bool:
    config = SmsSettings.load()
    if not config.confirmation_enabled:
        return False
    return _send(
        booking.contact_phone, _render("booking_confirmation", booking),
        kind=SmsLog.Kind.CONFIRMATION, booking=booking,
    )


def send_pickup_reminder(booking) -> bool:
    config = SmsSettings.load()
    if not config.reminder_enabled:
        return False
    return _send(
        booking.contact_phone, _render("pickup_reminder", booking),
        kind=SmsLog.Kind.REMINDER, booking=booking,
    )


def send_test_message(to: str) -> tuple[bool, str]:
    """Send a test text and record the result on the settings row."""
    config = SmsSettings.load()
    ok = _send(to, "M&M Austin Limousine: your SMS is set up correctly.", kind=SmsLog.Kind.TEST)
    config.last_test_at = timezone.now()
    config.last_test_ok = ok
    config.last_test_error = "" if ok else (
        SmsLog.objects.filter(kind=SmsLog.Kind.TEST).first().error
        if SmsLog.objects.filter(kind=SmsLog.Kind.TEST).exists() else "Not configured."
    )
    config.save(update_fields=["last_test_at", "last_test_ok", "last_test_error"])
    return ok, config.last_test_error
