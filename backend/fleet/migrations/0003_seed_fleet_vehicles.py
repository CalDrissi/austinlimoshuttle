"""Seed the five live fleet vehicle classes (with optimized photos).

Idempotent: each vehicle is matched by `slug` via get_or_create, so re-running
(or deploying on top of an already-seeded DB) is a no-op. The optimized WebP
photos are committed under `fleet/seed_images/` and copied into MEDIA_ROOT the
first time a vehicle is created, so the records carry working photos on both
local and testmode after `migrate`.

Rates here are sensible launch defaults; staff tune them from the admin.
"""

from decimal import Decimal
from pathlib import Path

from django.core.files import File
from django.db import migrations

SEED_IMAGE_DIR = Path(__file__).resolve().parent.parent / "seed_images"

VEHICLES = [
    {
        "slug": "cadillac-escalade",
        "name": "Cadillac Escalade",
        "image": "cadillac-escalade.webp",
        "passenger_capacity": 6,
        "luggage_capacity": 6,
        "hourly_rate": "95.00",
        "minimum_fare": "150.00",
        "meet_greet_fee": "25.00",
        "display_order": 1,
        "description": (
            "Our flagship luxury SUV. The Escalade carries up to six guests in a "
            "hand-finished leather cabin with room for a full load of luggage — "
            "the first choice for executive airport transfers and a night on the town."
        ),
    },
    {
        "slug": "chevrolet-suburban",
        "name": "Chevrolet Suburban",
        "image": "chevrolet-suburban.webp",
        "passenger_capacity": 7,
        "luggage_capacity": 7,
        "hourly_rate": "90.00",
        "minimum_fare": "140.00",
        "meet_greet_fee": "25.00",
        "display_order": 2,
        "description": (
            "A full-size SUV built for space. The Suburban seats seven with their "
            "bags in comfort, making it the practical pick for family airport runs "
            "and group travel around Austin."
        ),
    },
    {
        "slug": "mercedes-e-class",
        "name": "Mercedes-Benz E-Class",
        "image": "mercedes-e-class.webp",
        "passenger_capacity": 3,
        "luggage_capacity": 3,
        "hourly_rate": "75.00",
        "minimum_fare": "100.00",
        "meet_greet_fee": "20.00",
        "display_order": 3,
        "description": (
            "An understated executive sedan. The E-Class offers a quiet, refined "
            "ride for up to three passengers — the right call for solo travelers "
            "and small parties who want to arrive in style."
        ),
    },
    {
        "slug": "mercedes-sprinter",
        "name": "Mercedes-Benz Sprinter",
        "image": "mercedes-sprinter.webp",
        "passenger_capacity": 12,
        "luggage_capacity": 12,
        "hourly_rate": "135.00",
        "minimum_fare": "225.00",
        "meet_greet_fee": "30.00",
        "display_order": 4,
        "description": (
            "Our largest vehicle. The Sprinter van seats twelve with generous "
            "luggage space and easy step-in access — ideal for corporate groups, "
            "wedding parties, and winery tours."
        ),
    },
    {
        "slug": "chrysler-300-limo",
        "name": "Chrysler 300 Stretch Limo",
        "image": "chrysler-300-limo.webp",
        "passenger_capacity": 8,
        "luggage_capacity": 4,
        "hourly_rate": "120.00",
        "minimum_fare": "200.00",
        "meet_greet_fee": "25.00",
        "display_order": 5,
        "description": (
            "A classic stretch limousine for a statement arrival. Seating eight in "
            "a plush, mood-lit cabin, the Chrysler 300 is the Austin favorite for "
            "proms, weddings, and bachelor and bachelorette nights."
        ),
    },
]


def seed_vehicles(apps, schema_editor):
    Vehicle = apps.get_model("fleet", "Vehicle")
    for spec in VEHICLES:
        vehicle, _created = Vehicle.objects.get_or_create(
            slug=spec["slug"],
            defaults={
                "name": spec["name"],
                "description": spec["description"],
                "passenger_capacity": spec["passenger_capacity"],
                "luggage_capacity": spec["luggage_capacity"],
                "hourly_rate": Decimal(spec["hourly_rate"]),
                "minimum_fare": Decimal(spec["minimum_fare"]),
                "meet_greet_fee": Decimal(spec["meet_greet_fee"]),
                "display_order": spec["display_order"],
                "is_active": True,
            },
        )
        # Attach the committed photo only if the vehicle has none yet, so a
        # re-run (or a photo an operator has already replaced) is left untouched.
        if not vehicle.photo:
            src = SEED_IMAGE_DIR / spec["image"]
            if src.exists():
                with src.open("rb") as fh:
                    vehicle.photo.save(spec["image"], File(fh), save=True)


def unseed_vehicles(apps, schema_editor):
    Vehicle = apps.get_model("fleet", "Vehicle")
    slugs = [spec["slug"] for spec in VEHICLES]
    Vehicle.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0002_vehicle_city_to_city_min_miles_intercityband"),
    ]

    operations = [
        migrations.RunPython(seed_vehicles, unseed_vehicles),
    ]
