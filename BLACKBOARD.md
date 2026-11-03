# Blackboard — live fleet coordination

Shared, writable scratchpad for **in-flight** work. Append-only per agent; newest at top of each
section; keep entries short and dated (`YYYY-MM-DD HH:MM @handle — note`). Durable interface
decisions go in `CONTRACTS.md`, not here. The read-only code map is the graphify graph.

## In flight
_One line per active task: `@handle — branch — what / status`._
- 2026-11-03 @dashboard-bookings — agent/dashboard-bookings/c2c-manual-booking — Phase 4b: migrated manual booking `city` mode to free-form + distance (quote(city_to_city=True)), dropped CityRoute from dashboard/views.py. Also edited @dashboard-forms' `ManualBookingForm` (removed `city_route` field, city now requires a drop-off) for this cohesive change. Dashboard suite 100 green. Awaiting merge gate.

## Findings & gotchas
_Short discoveries worth sharing across lanes._

## Blockers / questions
_`@handle — needs X from @other-handle / coordinator`._

## Verifier verdicts
_`branch — code-verifier: pass/fail — business-verifier: pass/fail — merged? reverted?`._
