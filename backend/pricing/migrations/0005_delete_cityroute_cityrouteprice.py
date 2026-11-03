# Drops the now-unused CityRoute / CityRoutePrice tables (city-to-city rework
# phase 3). Every consumer -- the engine, API, dashboard page, manual booking
# form and the Booking.city_route FK -- was removed first; city-to-city is now
# priced per-mile like a transfer. Depends on the bookings migration that drops
# the Booking.city_route FK so the inbound foreign key is gone before the table.
#
# The child table (CityRoutePrice) is dropped before its parent (CityRoute) so
# the FK is gone first, and we DeleteModel (DROP TABLE) rather than RemoveField
# the FK columns: MariaDB refuses a bare DROP COLUMN on route_id while it still
# backs the (route, vehicle) unique index (error 1072).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('pricing', '0004_pricingsettings_min_booking_lead_hours'),
        ('bookings', '0007_remove_booking_city_route'),
    ]

    operations = [
        migrations.DeleteModel(
            name='CityRoutePrice',
        ),
        migrations.DeleteModel(
            name='CityRoute',
        ),
    ]
