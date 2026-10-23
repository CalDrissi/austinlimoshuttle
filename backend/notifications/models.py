"""
Email configuration and delivery records.

SMTP credentials are managed in the dashboard, like the Stripe keys, so an
administrator can change mail hosts without a deployment. The password is
encrypted at rest -- a mailbox password is a credential that sends mail as the
business, and a leaked one is a phishing platform with the client's own domain
behind it.
"""

from django.conf import settings as django_settings
from django.core.exceptions import ValidationError
from django.db import models

from config import crypto


class EmailSettings(models.Model):
    """SMTP configuration. Singleton."""

    class Security(models.TextChoices):
        TLS = "tls", "STARTTLS (usually port 587)"
        SSL = "ssl", "SSL/TLS (usually port 465)"
        NONE = "none", "None (not recommended)"

    host = models.CharField(
        max_length=255, blank=True,
        help_text="e.g. mail.austinlimoshuttle.com",
    )
    port = models.PositiveIntegerField(default=587)
    security = models.CharField(
        max_length=4, choices=Security.choices, default=Security.TLS,
    )
    username = models.CharField(max_length=255, blank=True)
    _password = models.TextField(
        "password", blank=True, db_column="password_encrypted",
        help_text="Encrypted at rest.",
    )

    from_name = models.CharField(
        max_length=120, blank=True, default="Austin Limo Shuttle",
        help_text="Display name on outgoing mail.",
    )
    from_email = models.EmailField(
        blank=True, help_text="Must be an address this mailbox is allowed to send as.",
    )
    reply_to = models.EmailField(blank=True)

    ops_notification_email = models.EmailField(
        blank=True,
        help_text="Where new-booking and cancellation alerts are sent.",
    )

    is_enabled = models.BooleanField(
        default=False,
        help_text="Turn off to stop all outgoing mail without deleting the settings.",
    )
    timeout_seconds = models.PositiveSmallIntegerField(default=15)

    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)
    last_test_error = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    class Meta:
        verbose_name = "email settings"
        verbose_name_plural = "email settings"

    def __str__(self):
        return f"SMTP {self.host or 'not configured'}"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Email settings cannot be deleted.")

    @classmethod
    def load(cls) -> "EmailSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    # -- secret -----------------------------------------------------------

    @property
    def password(self) -> str | None:
        return crypto.decrypt(self._password)

    @password.setter
    def password(self, value: str | None) -> None:
        self._password = crypto.encrypt(value)

    @property
    def password_masked(self) -> str:
        stored = self.password
        return f"••••{stored[-2:]}" if stored else ""

    @property
    def has_password(self) -> bool:
        return bool(self._password)

    # -- derived ----------------------------------------------------------

    @property
    def use_tls(self) -> bool:
        return self.security == self.Security.TLS

    @property
    def use_ssl(self) -> bool:
        return self.security == self.Security.SSL

    @property
    def is_configured(self) -> bool:
        return bool(self.is_enabled and self.host and self.from_email)

    @property
    def sender(self) -> str:
        """The From header, with a display name when one is set."""
        if self.from_name and self.from_email:
            return f"{self.from_name} <{self.from_email}>"
        return self.from_email or django_settings.DEFAULT_FROM_EMAIL


class EmailLog(models.Model):
    """
    A record of every message the application tried to send.

    Deliverability is the part of email nobody can see. Without a log, "the
    customer says they never got the confirmation" is unanswerable -- this at
    least distinguishes never-sent from sent-and-lost.
    """

    class Kind(models.TextChoices):
        BOOKING_CONFIRMATION = "booking_confirmation", "Booking confirmation"
        BOOKING_CANCELLED = "booking_cancelled", "Booking cancelled"
        DRIVER_ASSIGNED = "driver_assigned", "Driver assigned"
        OPS_NEW_BOOKING = "ops_new_booking", "Operations: new booking"
        PICKUP_REMINDER = "pickup_reminder", "Pickup reminder"
        TRIP_STATUS = "trip_status", "Trip status update"
        TEST = "test", "Test message"
        OTHER = "other", "Other"

    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER,
                            db_index=True)
    to_email = models.EmailField()
    subject = models.CharField(max_length=255)

    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="emails",
    )

    succeeded = models.BooleanField(default=False, db_index=True)
    error = models.TextField(blank=True)
    has_attachment = models.BooleanField(default=False)

    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        state = "sent" if self.succeeded else "FAILED"
        return f"{self.get_kind_display()} to {self.to_email} ({state})"


class SmsSettings(models.Model):
    """
    SMS (Twilio) configuration. Singleton, dashboard-managed like EmailSettings.

    The auth token is encrypted at rest -- it can send messages billed to the
    business, so a leaked one is someone else's text budget on our account.
    """

    is_enabled = models.BooleanField(
        default=False,
        help_text="Turn off to stop all texts without deleting the credentials.",
    )
    account_sid = models.CharField(
        max_length=64, blank=True, help_text="Twilio Account SID (starts with AC).",
    )
    _auth_token = models.TextField(
        "auth token", blank=True, db_column="auth_token_encrypted",
        help_text="Encrypted at rest.",
    )
    from_number = models.CharField(
        max_length=20, blank=True,
        help_text="The Twilio number texts are sent from, E.164 e.g. +15125550100.",
    )

    confirmation_enabled = models.BooleanField(
        default=True, help_text="Text the customer when a booking is confirmed.",
    )
    reminder_enabled = models.BooleanField(
        default=True, help_text="Text the customer a reminder before pickup.",
    )
    reminder_lead_hours = models.PositiveSmallIntegerField(
        default=24,
        help_text="How many hours before pickup to send the reminder (24 = a day ahead).",
    )

    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)
    last_test_error = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        django_settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    class Meta:
        verbose_name = "SMS settings"
        verbose_name_plural = "SMS settings"

    def __str__(self):
        return f"Twilio {self.from_number or 'not configured'}"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("SMS settings cannot be deleted.")

    @classmethod
    def load(cls) -> "SmsSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def auth_token(self) -> str | None:
        return crypto.decrypt(self._auth_token)

    @auth_token.setter
    def auth_token(self, value: str | None) -> None:
        self._auth_token = crypto.encrypt(value)

    @property
    def auth_token_masked(self) -> str:
        stored = self.auth_token
        return f"••••{stored[-4:]}" if stored else ""

    @property
    def has_auth_token(self) -> bool:
        return bool(self._auth_token)

    @property
    def is_configured(self) -> bool:
        return bool(self.is_enabled and self.account_sid and self.auth_token and self.from_number)


class SmsLog(models.Model):
    """A record of every SMS send attempt. Also the reminder-dedupe source."""

    class Kind(models.TextChoices):
        CONFIRMATION = "confirmation", "Booking confirmation"
        REMINDER = "reminder", "Pickup reminder"
        TEST = "test", "Test"
        OTHER = "other", "Other"

    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.OTHER)
    to_number = models.CharField(max_length=20)
    body = models.TextField(blank=True)
    booking = models.ForeignKey(
        "bookings.Booking", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sms_logs",
    )
    succeeded = models.BooleanField(default=False)
    provider_sid = models.CharField(max_length=64, blank=True)
    error = models.TextField(blank=True)
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return f"{self.get_kind_display()} -> {self.to_number} ({'ok' if self.succeeded else 'failed'})"
