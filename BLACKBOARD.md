# Blackboard — live fleet coordination

Shared, writable scratchpad for **in-flight** work. Append-only per agent; newest at top of each
section; keep entries short and dated (`YYYY-MM-DD HH:MM @handle — note`). Durable interface
decisions go in `CONTRACTS.md`, not here. The read-only code map is the graphify graph.

## In flight
_One line per active task: `@handle — branch — what / status`._
- 2026-11-03 @dashboard-bookings — agent/dashboard-bookings/c2c-manual-booking — Phase 4b: migrated manual booking `city` mode to free-form + distance (quote(city_to_city=True)), dropped CityRoute from dashboard/views.py. Also edited @dashboard-forms' `ManualBookingForm` (removed `city_route` field, city now requires a drop-off) for this cohesive change. Dashboard suite 100 green. Awaiting merge gate.

- 2026-11-25 @bugfix-round1 — CalDrissi/bugfix-round1-e2e-defects — fixing the 5 E2E defects + 1 polish in one batch (cash refunds w/o Stripe, cash awaiting-collection, guest_name vs placard, quiet /auth/me 204, min-fare label, overview count). New migration bookings.0010 (guest_name). See CONTRACTS.md 2026-11-25 E2E round-1 entry. Full gate then deploy both sides.

## Findings & gotchas
_Short discoveries worth sharing across lanes._
- 2026-11-25 01:20 @notifications — **VPS outbound mail is being refused: the server IP (209.126.15.51) is listed at zen.spamhaus.org ("excess volume")**. Last successful send 00:23 UTC; every send since gets a 550 from the relay. Not code — email P1–P5 deployed fine and EmailLog records the failures (now visible on the dashboard home card). Needs @deploy/ops: check https://check.spamhaus.org, find the volume source, request delisting.
- 2026-11-25 01:15 @notifications — email P1–P5 merged to main (184fa5b) + deployed; hourly pickup-reminder cron installed on the VPS (marker `austinlimoshuttle:send_pickup_reminders`). Amend/cancel endpoints and driver assignment now send TWO emails each — see CONTRACTS.md 2026-11-25.

## Blockers / questions
_`@handle — needs X from @other-handle / coordinator`._

## Verifier verdicts
_`branch — code-verifier: pass/fail — business-verifier: pass/fail — merged? reverted?`._
- 2026-11-25 @email-polish — email+chrome polish batch in flight (branch CalDrissi/email-fix-gaps-coverage): autoescape-off removed from HTML emails (XSS test added), M&M rebrand + logo + links (new DJANGO_PUBLIC_SITE_URL), SiteSettings.contact_phone wired into email ctx, US datetimes, $X.XX money, business days, receipt PDF rebrand+payment line, EmailLog read-only admin, footer auth-aware + real fleet links, fleet titles/breadcrumb, widget drop-off copy. Live DB edits pending: contact_phone → +1 (512) 577-1003 (owner to confirm), Sprinter description, from_name.
