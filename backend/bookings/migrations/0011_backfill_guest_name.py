"""
Backfill guest_name from pickup_sign for pre-existing guest bookings.

Before guest_name existed, the storefront stored the guest's contact name into
pickup_sign (create_booking's `pickup_sign or guest_name` fallback) and
customer_name fell back to the placard. Without this backfill every historical
guest booking would render as "Guest" across the back office the moment
customer_name stopped reading pickup_sign.
"""

from django.db import migrations
from django.db.models import F


def backfill(apps, schema_editor):
    Booking = apps.get_model("bookings", "Booking")
    Booking.objects.filter(
        customer__isnull=True, guest_name="",
    ).exclude(pickup_sign="").update(guest_name=F("pickup_sign"))


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0010_booking_guest_name"),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
