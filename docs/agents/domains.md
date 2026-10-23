# Domain agents — the standing fleet (20)

Each agent owns a lane: the **paths** it may edit, the **graph scope** it queries, and the
**verifier criteria** its changes must pass. Handles are stable (`@name`). Stay in your paths;
cross-lane work goes through the owning agent + `CONTRACTS.md`.

> Coordinator, repo-manager, code-verifier, business-verifier are separate fleet roles (not in
> this list) — see `CLAUDE.md` merge gate.

## Backend (16)

| Handle | Owns (paths) | Graph scope | Verifier |
|---|---|---|---|
| `@pricing-engine` | `backend/pricing/engine.py`, `backend/pricing/distance.py` | quote, surcharge, DistanceLookup, Journey | `pricing` tests |
| `@pricing-rates` | `backend/pricing/models.py`, `backend/pricing/admin.py` (rate cards, CityRoute, bands) | CityRoute, CityRoutePrice, DistanceBand | `pricing` tests |
| `@fleet` | `backend/fleet/**` | Vehicle, fleet admin, images | `fleet` tests |
| `@payments-gateway` | `backend/payments/gateway.py`, `backend/payments/models.py` | gateway, Payment, SavedCard, Stripe | `payments` tests |
| `@payments-api` | `backend/api/payment*`, payment webhooks | payment intent, webhook | `payments` + `api` tests |
| `@bookings-core` | `backend/bookings/**` | Booking, status, lifecycle | `bookings` tests |
| `@dashboard-bookings` | `backend/dashboard/views.py`, booking templates | booking_create, _quote_manual, dashboard views | `dashboard` tests |
| `@dashboard-forms` | `backend/dashboard/forms.py` | ManualBookingForm, BootstrapFormMixin | `dashboard` tests |
| `@dashboard-crud` | `backend/dashboard/crud*`, `managed.py`, context processors | crud, context processors | `dashboard` tests |
| `@driver-portal` | `backend/driver/**` | driver views, auth | `driver` tests |
| `@api-quotes` | `backend/api/quotes*`, quote endpoints in `api/views.py` | QuoteRequest, QuoteThrottle, redeem | `api` tests |
| `@api-core` | `backend/api/serializers.py`, `backend/api/views.py`, throttles, `api/urls.py` | serializers, throttles, api views | `api` tests |
| `@accounts` | `backend/accounts/**` | User, auth, password reset | `accounts` tests |
| `@notifications` | `backend/notifications/**` | email backend, scheduler, EmailSettings | `notifications` tests |
| `@content-enquiries` | `backend/content/**`, `backend/enquiries/**` | CMS pages/banners/gallery, enquiries | `content` + `enquiries` tests |
| `@platform` | `backend/config/**`, `backend/legacy_import/**`, settings, middleware, root URLs | session, CSRF, middleware, settings | `config` tests |

## Frontend (4)

| Handle | Owns (paths) | Graph scope | Verifier |
|---|---|---|---|
| `@frontend-marketing` | `frontend/src/app/(marketing)/**`, fleet pages | marketing pages, VehicleCard, fleet | `npm run build` |
| `@frontend-booking` | `frontend/src/**` booking/checkout flow | booking flow, checkout | `npm run build` |
| `@frontend-account` | `frontend/src/**` client dashboard, auth pages | LoginForm, dashboard, account | `npm run build` |
| `@frontend-lib` | `frontend/src/lib/**`, `frontend/src/types/**`, shared components | api services, types, shared ui | `npm run build` |

## Boundary rules
- Shared files touched by many lanes (`backend/api/urls.py`, root settings) are owned by
  `@api-core` / `@platform`; others propose changes via a message, not a direct edit.
- A feature spanning lanes (e.g. a pricing field reaching the storefront) is split by the
  coordinator into per-lane tasks, chained through `CONTRACTS.md`.
