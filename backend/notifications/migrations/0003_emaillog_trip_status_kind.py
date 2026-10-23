from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0002_smslog_smssettings"),
    ]

    operations = [
        migrations.AlterField(
            model_name="emaillog",
            name="kind",
            field=models.CharField(
                choices=[
                    ("booking_confirmation", "Booking confirmation"),
                    ("booking_cancelled", "Booking cancelled"),
                    ("driver_assigned", "Driver assigned"),
                    ("ops_new_booking", "Operations: new booking"),
                    ("pickup_reminder", "Pickup reminder"),
                    ("trip_status", "Trip status update"),
                    ("test", "Test message"),
                    ("other", "Other"),
                ],
                db_index=True,
                default="other",
                max_length=32,
            ),
        ),
    ]
