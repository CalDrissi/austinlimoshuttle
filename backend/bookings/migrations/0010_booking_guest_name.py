from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0009_bookingcancellationrequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="guest_name",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Contact name for a booking made without an account. "
                    "Distinct from pickup_sign, which is what the driver's "
                    "placard shows."
                ),
                max_length=150,
            ),
        ),
    ]
