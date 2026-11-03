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

## 2026-11-03 — Free-form city-to-city API (quote request/response + token; city-routes endpoint removed)
- Owner: @api-core
- Affects: @frontend-booking (quote + booking requests), @api-quotes (quote token now carries
  `city_to_city`, not a route id), @pricing-rates (API no longer references CityRoute/CityRoutePrice —
  clears Phase-3 model deletion), @bookings-core (amend re-price gap, below)
- Change: the city-to-city quote is now a **free-form origin→destination trip**, measured and priced
  exactly like a transfer. There is no fixed route id and no city-pair lookup anymore.

### `POST /api/quotes/` — request (unchanged field set; `city_to_city` re-defined)
```jsonc
{
  "pickup_address": "Austin, TX",       // required
  "dropoff_address": "Houston, TX",     // required for a transfer AND for city_to_city
  "pickup_at": "2026-09-01T14:30:00-05:00",
  "meet_and_greet": false,              // optional
  "city_to_city": true                  // optional; see below
}
```
- `city_to_city: true` **no longer means a fixed route**. It is a flag that tells the engine to
  prefer each vehicle's INTERCITY rate card. The server still **measures the distance from the two
  addresses** (same Google Distance Matrix path as a transfer) — a billed lookup now happens for
  city-to-city too. `dropoff_address` is **required** when `city_to_city` is true; `hours` is rejected.
- A vehicle is priced on its intercity card only when it offers intercity pricing and the trip is at
  least its minimum distance; otherwise it **silently** falls back to the normal transfer card (no
  error, no 422). See @pricing-engine's entry for the exact rule.

### `POST /api/quotes/` — response (shape UNCHANGED; `journey` now populated for city_to_city)
Same `{ "journey": {...} | null, "quotes": [ { vehicle_id, vehicle_name, subtotal, surcharge_total,
tax, total, currency, lines[], quote_token } ] }`. The only observable difference: a city-to-city
quote now returns a non-null `journey` (distance/duration/resolved addresses), because the trip is
measured. Previously it was `null` for the fixed-route path.

### `POST /api/bookings/` — unchanged
Still takes a `quote_token` + passenger/guest details; no money field. The `city_to_city` flag rides
**inside the signed token**, so the fare is recomputed on the correct (intercity/normal) card at
redeem time. Nothing new for the client to send.

### REMOVED
- `GET /api/city-routes/` endpoint (cities + route pairs) — **deleted**. The storefront's
  City-to-City tab must switch to free-form address inputs (pickup + drop-off), not a dropdown of
  fixed cities. @frontend-booking: drop any fetch of `/api/city-routes/` and the city dropdown.
- `CityRouteOptionsSerializer` / `CityRouteOptionSerializer` removed.
- The quote token field `rt` (route id) is replaced by `c2c` (bool). Old outstanding tokens issued
  with `rt` will simply ignore it and price as a normal trip on redeem — acceptable (tokens are
  short-lived).

### Cross-lane edits made in this task (noted per lane ownership)
- `backend/api/quotes.py` is @api-quotes' lane. This cohesive change required it: `QuoteRequest.route_id`
  → `city_to_city: bool`, token key `rt` → `c2c`, and `redeem()` now calls `quote(..., city_to_city=…)`
  instead of resolving a `CityRoute`. @api-quotes please confirm.
- **@bookings-core follow-up (amend re-price gap):** the `Booking` row has **no persisted
  city-to-city marker** now that `city_route` is no longer set by the API (it defaults to null; the FK
  is untouched for Phase 3). On a customer *amend* that changes `pickup_at`, the API re-prices on the
  vehicle's NORMAL transfer card, because it can't tell a stored free-form intercity trip from a plain
  transfer. To preserve intercity pricing across a time-amend, `Booking` needs a persisted
  `city_to_city` flag (or a `CITY_TO_CITY` trip type); the API would then pass it into `quote()`.
  Low impact (time-only amends of intercity trips are rare), flagged for a later phase.

---

## 2026-11-03 — City-to-city marker on Booking (persist + re-quote hook)
- Owner: @bookings-core
- Affects: @api (api/views.py `create_booking` + the `amend` re-quote path, api/quotes.py),
  @dashboard (dashboard/views.py — any staff create/re-price path that builds a Booking)
- Change: additive + backwards-compatible. `bookings.Booking` now persists whether a trip was
  booked city-to-city, and owns the re-quote that keeps intercity pricing.

### What's new on `bookings.models.Booking`
- **Field** `is_city_to_city = BooleanField(default=False)`. True when the journey was booked as a
  free-form city-to-city (intercity) trip. A plain boolean, **not** a new `TripType`: for pricing a
  c2c trip *is* a distance-based `TRANSFER`, differing only in which rate card applies. Defaults
  False, so every existing booking is unaffected. Migration `bookings/migrations/0006_booking_is_city_to_city.py`.
- **Method** `Booking.reprice(*, pickup_at=None) -> Quote`. The single re-quote entry point for an
  existing booking. Calls `pricing.engine.quote()` with the booking's own attributes and forwards
  `city_to_city=self.is_city_to_city`, so an amended intercity trip stays on the intercity card
  instead of silently falling back to the normal distance bands. Reuses stored `distance_miles`
  (TRANSFER) / `hours` (HOURLY) and `meet_and_greet`; pass `pickup_at` to price a proposed new time.
  Returns a fresh `Quote` and does **not** persist — the caller writes the figures if it chooses to.

### Hooks other lanes must wire (bookings cannot reach into your views)
1. **@api — booking creation** (`api/views.py` `create_booking`, ~L446 `Booking.objects.create(...)`):
   set `is_city_to_city=<the c2c flag the quote was issued with>` when creating the Booking. The
   storefront already carries `city_to_city` into the quote request (api/serializers.py L103,
   api/views.py L282); sign it into the quote token (quotes.QuoteRequest) and stamp it onto the
   Booking so the marker survives, exactly as `route_id` does today.
2. **@api — amend re-quote** (`api/views.py` amend branch, ~L690): replace the current
   `quote(..., route=booking.city_route)` call (now broken — the engine dropped `route=`) with
   `recomputed = booking.reprice(pickup_at=booking.pickup_at)`. That single call restores the build
   and preserves intercity pricing on amend.
3. **@dashboard**: any staff create/re-price path that builds or re-prices a Booking should set/read
   `is_city_to_city` and re-quote via `booking.reprice()` for the same reason.
- Migration (what dependents must do): apply migration 0006; no data backfill needed (all existing
  rows are correctly `False`). `Booking.city_route` is untouched and still present.

---

## 2026-11-03 — City-to-city quoting is free-form + distance-based (quote() call shape)
- Owner: @pricing-engine
- Affects: @api (api/views.py, api/quotes.py), @dashboard (dashboard/views.py) — every caller that
  passes `route=` or prices via `CityRoute.find_pair`/`CityRoute.match`; @pricing-rates (may now
  delete CityRoute/CityRoutePrice in Phase 3 — the engine no longer references them)
- Change: `pricing.engine.quote()` / `quote_all()` **no longer accept `route=<CityRoute>`**. The old
  flat, all-in route-price path (no surcharge/tax) is removed. City-to-city is now a free-form
  origin→destination trip priced on distance, implementing @fleet's Phase-1 rule below. New signatures:
  - `quote(vehicle, *, pickup_at, distance_miles=None, hours=None, meet_and_greet=False,
    city_to_city=False, settings=None, surcharges=None, blackouts=None, bands=None,
    intercity_bands=None)` — `route` **removed**; `city_to_city: bool` and `intercity_bands: list|None`
    (optional preload, parallels `bands`) **added**.
  - `quote_all(pickup_at, *, distance_miles=None, hours=None, meet_and_greet=False,
    city_to_city=False)` — `route` **removed**; `city_to_city: bool` **added**.
  With `city_to_city=True` the engine selects the intercity card vs normal `bands` internally per
  @fleet's rule (intercity when `city_to_city_min_miles` is not NULL, the vehicle has
  `intercity_bands`, and `distance >= min`; `min==0` = any distance; otherwise **silent** fallback to
  normal `bands` — no error). Surcharge, meet&greet, minimum fare and tax then apply exactly as for a
  transfer. The returned `Quote` shape is unchanged (standard BAND/SURCHARGE/MEET_GREET/MINIMUM/TAX lines).
- Migration (what @api / @dashboard must do):
  - Stop passing `route=` to `quote`/`quote_all`. For a city-to-city request, resolve the free-form
    pickup/drop-off addresses to a distance via `distance.lookup()` (the same path used for a transfer),
    then call `quote_all(pickup_at, distance_miles=<measured>, city_to_city=True)`.
  - Drop the `CityRoute.find_pair()` / `CityRoute.match()` / `route.price_for()` pricing lookups — the
    engine no longer consumes a route object. City/route selection UI backed by `CityRoute` needs
    rethinking (free-form addresses now); coordinate @api ↔ @frontend.
  - `bookings.Booking.city_route` FK and any admin/forms referencing CityRoute/CityRoutePrice still
    exist until their owning lanes remove them; only the **engine's** use is gone.

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
