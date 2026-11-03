"""
Surcharge rules and pricing configuration.

Legacy behaviour this reproduces exactly (see legacy/pickup_details.php:329-340):

    if ($time < 06:00:00 || $time > 21:00:00)  -> add the late-night percentage
    if the date is a blackout date             -> add that date's percentage

The two percentages are ADDED and applied once to the base fare -- not applied
sequentially. Getting that wrong inflates every surcharged fare.

Legacy stored the late-night window as an English sentence in
`limousin_special_time_rate.title` while the real hours were hardcoded in PHP,
so the admin screen described behaviour the system did not actually have. Here
the times are the rule.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class TimeSurcharge(models.Model):
    """
    A percentage uplift for pickups within a time-of-day window.

    Windows may cross midnight (21:00 -> 06:00), which is the case for the one
    rule inherited from the legacy system.

    Boundary semantics deliberately match legacy: both ends are EXCLUSIVE. A
    pickup at exactly 21:00:00 is not surcharged, because the old condition was
    `> 21:00:00`. Changing this would silently reprice fares.
    """

    name = models.CharField(max_length=120)
    start_time = models.TimeField(help_text="Window opens after this time (exclusive).")
    end_time = models.TimeField(help_text="Window closes at this time (exclusive).")
    percentage = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("500.00"))],
        help_text="Uplift applied to the base fare, e.g. 20.00 for +20%.",
    )
    is_active = models.BooleanField(default=True)

    legacy_rate_id = models.IntegerField(null=True, blank=True, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_time"]
        verbose_name = "time surcharge"

    def __str__(self):
        return f"{self.name} ({self.start_time:%H:%M}–{self.end_time:%H:%M}, +{self.percentage}%)"

    @property
    def crosses_midnight(self) -> bool:
        return self.start_time > self.end_time

    def applies_at(self, at_time) -> bool:
        """Whether this rule covers the given time of day."""
        if not self.is_active:
            return False
        if self.crosses_midnight:
            # e.g. 21:00 -> 06:00 : after 21:00 OR before 06:00
            return at_time > self.start_time or at_time < self.end_time
        return self.start_time < at_time < self.end_time

    def clean(self):
        if self.start_time == self.end_time:
            raise ValidationError("Start and end time must differ.")


class BlackoutDate(models.Model):
    """
    A date carrying its own uplift -- holidays and major Austin events.

    Named "blackout" for continuity with the legacy `limousin_busy_date` table,
    though it does not block booking: it raises the price. Real data includes
    SXSW at +40% and Formula 1 weekend at +80%.
    """

    name = models.CharField(max_length=120, help_text='e.g. "SXSW 2026".')
    description = models.CharField(max_length=255, blank=True)
    date = models.DateField(unique=True)
    percentage = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("500.00"))],
    )
    is_active = models.BooleanField(default=True)

    legacy_busy_date_id = models.IntegerField(null=True, blank=True, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"{self.name} — {self.date} (+{self.percentage}%)"


class PricingSettings(models.Model):
    """
    Site-wide pricing configuration. Singleton.

    Legacy kept the tax rate on the admin *user* row (`limousin_admin.vat`),
    which meant business configuration was attached to whoever happened to be
    logged in.
    """

    tax_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Percentage applied to the fare. 0 disables tax lines.",
    )
    currency = models.CharField(max_length=3, default="USD")
    cancellation_window_hours = models.PositiveSmallIntegerField(
        default=1,
        help_text="Free cancellation up to this many hours before pickup. "
                  "Legacy fleet copy advertised 1 hour.",
    )
    amendment_window_hours = models.PositiveSmallIntegerField(
        default=24,
        help_text="How many hours before pickup a customer may still change "
                  "their booking's details online. 72 = 3 days, 24 = 1 day, "
                  "6 = 6 hours. After this they must contact the office.",
    )
    quote_ttl_minutes = models.PositiveSmallIntegerField(
        default=30, help_text="How long a fare quote stays valid.",
    )
    min_booking_lead_hours = models.PositiveSmallIntegerField(
        default=0,
        help_text="How many hours before pickup a customer may still book online. "
                  "0 = no minimum, 2 = must book 2 hours ahead, 24 = a day ahead. "
                  "Staff booking by phone in the back office are not limited.",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "pricing settings"
        verbose_name_plural = "pricing settings"

    def __str__(self):
        return "Pricing settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce singleton
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Pricing settings cannot be deleted.")

    @classmethod
    def load(cls) -> "PricingSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


def booking_lead_error(pickup_at) -> str | None:
    """
    Message if a pickup is sooner than the office-set minimum lead time, else None.

    Shared by the quote serializer, the quote-token redeem, and the customer
    amendment so the rule is enforced identically everywhere a customer sets a
    time. Returns None when no minimum is configured (0) or the time is fine.
    """
    from datetime import timedelta

    from django.utils import timezone

    hours = PricingSettings.load().min_booking_lead_hours
    if hours and pickup_at < timezone.now() + timedelta(hours=hours):
        return (
            f"Bookings must be made at least {hours} "
            f"hour{'' if hours == 1 else 's'} before pickup. Please choose a later "
            "time, or call us to arrange a last-minute ride."
        )
    return None
