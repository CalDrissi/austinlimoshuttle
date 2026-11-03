# Contracts — cross-agent interface decisions

Durable record of interfaces agents depend on across lanes. Update the moment your change affects
another lane's inputs/outputs, **before** merging. Newest at top. Format:

```
## YYYY-MM-DD — <short title>
- Owner: @handle
- Change: what the interface now is (signature / shape / endpoint / event)
- Affects: @handle, @handle
- Migration: what dependents must do
```

---

## 2026-11-03 — City-to-city intercity pricing (per-vehicle intercity rate card + min distance)
- Owner: @fleet
- Affects: @pricing-engine (quote rule), @pricing-rates (owns CityRoute/CityRoutePrice — now superseded
  by free-form intercity), @dashboard (admin editing of the new card + field), @api (exposing both cards)
- Change: additive. Nothing existing changed — `DistanceBand` (`related_name="bands"`), `CityRoute`,
  `CityRoutePrice` and the pricing engine are all untouched.

### What's new

**`fleet.models.IntercityBand`** — the city-to-city (free-form origin→destination) per-mile rate card.
A second, independent band card that **mirrors `DistanceBand` exactly** (both now inherit the shared
abstract `fleet.models.RateBand`, so band arithmetic/validation is identical and stays in sync).

| Field | Type | Notes |
|-------|------|-------|
| `vehicle` | FK → `fleet.Vehicle`, `on_delete=CASCADE`, **`related_name="intercity_bands"`** | Fetch a vehicle's intercity card: `vehicle.intercity_bands.all()` (ordered by `from_miles`). |
| `from_miles` | `DecimalField(max_digits=6, decimal_places=2, default=0)` | Lower bound, **inclusive**. |
| `to_miles` | `DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)` | Upper bound, **exclusive**. `null` = final unbounded band. |
| `rate_per_mile` | `DecimalField(max_digits=8, decimal_places=2)` | Per-mile rate inside this band. |

- **Cumulative bands**, same semantics as `DistanceBand`: `band.miles_within(total)` returns miles of
  `total` inside that band; `band.contains(miles)` is lower-inclusive/upper-exclusive; `band.clean()`
  rejects `to_miles <= from_miles`. Unique constraint `unique_intercity_band_start_per_vehicle` on
  `(vehicle, from_miles)` — **separate** from DistanceBand's constraint, so the same `from_miles` may
  exist on both cards for one vehicle.

**`fleet.Vehicle.city_to_city_min_miles`** — `DecimalField(max_digits=6, decimal_places=2, null=True,
blank=True, MinValueValidator(0))`. Per-vehicle minimum trip distance (miles) that unlocks intercity pricing:
- **`NULL` (default) → intercity NOT offered** for this vehicle: always price with the normal `bands`.
- **`0` → no minimum**: intercity applies at any distance (when `intercity_bands` exist).
- **`> 0` → threshold**: intercity applies only at trip distance **≥** this value.

### Intended quote rule (for @pricing-engine to implement — NOT built here)
For a free-form city-to-city trip of `distance` miles on a vehicle `v`:
```
if v.city_to_city_min_miles is not None
   and v.intercity_bands.exists()
   and distance >= v.city_to_city_min_miles:
       price using v.intercity_bands        # INTERCITY card
else:
       price using v.bands                  # NORMAL card (existing behaviour)
```
i.e. `distance >= min` → intercity bands; `distance < min` (or not offered / no intercity bands) → normal
`bands`. The band-charging math is the existing cumulative algorithm applied to whichever card is chosen.
The engine itself is unchanged in this task; this is the interface it should build against.

- Migration: `fleet/migrations/0002_vehicle_city_to_city_min_miles_intercityband.py` (additive — adds the
  field + creates the table; applies cleanly; no data migration needed). Dependents: build new behaviour
  against the above; existing `bands`-only vehicles keep today's behaviour because the field defaults to NULL.

---

## 2026-10-23 — DriverTripEvent (driver trip-status events)
- Owner: @bookings-core
- Affects: @driver-portal (creates events), @notifications (listens to the signal),
  @dashboard-bookings (reads events for history + map)

### Model — `bookings.models.DriverTripEvent`
Immutable live status ping sent by a driver during a trip. One row per ping.

| Field | Type | Notes |
|-------|------|-------|
| `booking` | FK → `bookings.Booking`, `on_delete=CASCADE`, `related_name="trip_events"` | Read a booking's timeline via `booking.trip_events.all()` (ordered by `created_at`). |
| `event_type` | `CharField(max_length=12, choices=EventType)` | See choices below. |
| `latitude` | `DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)` | GPS lat; **null when the device has no fix/permission**. |
| `longitude` | `DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)` | GPS lng; null with latitude. |
| `location_accuracy` | `DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)` | Accuracy radius in **metres**, optional. |
| `driver` | FK → `bookings.Driver`, `on_delete=SET_NULL`, `null=True, blank=True`, `related_name="trip_events"` | Acting driver; nullable so deleting a driver never erases history. |
| `created_at` | `DateTimeField(auto_now_add=True, db_index=True)` | Server timestamp of the ping. |

`EventType` choices (value → label): `on_way` → "On the way", `arrived` → "Arrived at pickup",
`on_board` → "Passenger on board", `completed` → "Trip completed".

Indexed on `(booking, created_at)`. Default ordering `["booking", "created_at", "id"]`.
Migration: `bookings/migrations/0005_drivertripevent.py`.

### Creation entry point (use this — do NOT create rows directly)
```python
DriverTripEvent.record(booking, event_type, lat=None, lng=None, accuracy=None, driver=None)
# -> returns the created DriverTripEvent
```
- Creates the row, advances status if applicable (below), then fires the signal — the row +
  status write happen in one `transaction.atomic()`; the signal is sent right after.
- Sends **no** emails / notifications itself. Side effects belong to subscribers.
- `event_type` accepts a `DriverTripEvent.EventType.*` value (or its string).

### Signal — `bookings.signals.driver_trip_event_recorded`
`django.dispatch.Signal` fired by `record()` on every new event.
- Payload: `sender=DriverTripEvent` (the model class), `instance=<DriverTripEvent>`.
- Subscribe without importing bookings' internals, e.g. in @notifications:
  ```python
  from bookings.signals import driver_trip_event_recorded
  from bookings.models import DriverTripEvent
  driver_trip_event_recorded.connect(my_receiver, sender=DriverTripEvent)
  ```
  bookings only ever **sends** this signal; it never imports notifications/driver/api.

### Booking.status side effect (minimal, backwards-compatible)
- A `completed` event sets `Booking.status = COMPLETED`, **only** when the booking is in a
  non-terminal state (not already `cancelled` or `completed`). Saved via
  `update_fields=["status", "updated_at"]`. Idempotent: repeat `completed` pings are no-ops.
- `on_way` / `arrived` / `on_board` do **NOT** change `Booking.status` — there is no matching
  `Booking.Status` value; they are live telemetry, not lifecycle transitions.
- No `BookingStatusChange` audit row is written by `record()` (kept out of scope here);
  @dashboard-bookings owns any audit-trail entry it wants for the completion.

### Migration: what dependents must do
Nothing to migrate against the old behaviour (purely additive). @driver-portal should route all
event creation through `record()`; @notifications connects to the signal above; @dashboard-bookings
reads `booking.trip_events`.
