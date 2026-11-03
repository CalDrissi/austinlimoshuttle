"""The five launch fleet vehicles are seeded by migration 0003.

Because Django runs migrations to build the test database, the data migration
has already created these rows before any test runs — so this asserts the
seed landed with the expected slugs, active flags, photos, and specs.
"""

import pytest

from fleet.models import Vehicle

SEEDED = {
    "cadillac-escalade": ("Cadillac Escalade", 6, 6, 1),
    "chevrolet-suburban": ("Chevrolet Suburban", 7, 7, 2),
    "mercedes-e-class": ("Mercedes-Benz E-Class", 3, 3, 3),
    "mercedes-sprinter": ("Mercedes-Benz Sprinter", 12, 12, 4),
    "chrysler-300-limo": ("Chrysler 300 Stretch Limo", 8, 4, 5),
}


@pytest.mark.django_db
def test_all_five_vehicles_seeded():
    seeded = Vehicle.objects.filter(slug__in=SEEDED)
    assert seeded.count() == 5


@pytest.mark.django_db
def test_seeded_vehicles_are_active_with_photos_and_specs():
    for slug, (name, pax, luggage, order) in SEEDED.items():
        vehicle = Vehicle.objects.get(slug=slug)
        assert vehicle.name == name
        assert vehicle.is_active is True
        assert vehicle.passenger_capacity == pax
        assert vehicle.luggage_capacity == luggage
        assert vehicle.display_order == order
        assert vehicle.description.strip(), f"{slug} has no description"
        # photo field is populated and points into the fleet/ upload dir
        assert vehicle.photo, f"{slug} has no photo"
        assert vehicle.photo.name.startswith("fleet/")
