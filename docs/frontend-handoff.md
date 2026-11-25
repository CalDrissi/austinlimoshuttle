# Luxride Frontend — Developer Handoff Document

**Project:** Luxride Limo & Chauffeur Booking — Next.js Frontend  
**Stack:** Next.js 15 · React 19 · TypeScript · Zustand · TanStack Query v5  
**Design source:** Luxride commercial HTML template (jQuery/Bootstrap — do not modify)  
**Backend:** Python REST API (endpoint docs via Swagger — not yet connected)  
**Status:** Foundation + booking wizard entry complete. Marketing pages and wizard steps 2–4 are stubs awaiting design decisions and API integration.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Getting Started](#2-getting-started)
3. [Environment Variables](#3-environment-variables)
4. [Project Structure](#4-project-structure)
5. [Routing Architecture](#5-routing-architecture)
6. [Styling System](#6-styling-system)
7. [Component Library & Storybook](#7-component-library--storybook)
8. [API Layer](#8-api-layer)
9. [Booking Wizard State](#9-booking-wizard-state)
10. [TypeScript Domain Types](#10-typescript-domain-types)
11. [What Is Built](#11-what-is-built)
12. [What Is a Stub (needs implementation)](#12-what-is-a-stub-needs-implementation)
13. [How to Connect the Real Backend](#13-how-to-connect-the-real-backend)
14. [How to Add a New Page](#14-how-to-add-a-new-page)
15. [Known Issues & Quirks](#15-known-issues--quirks)
16. [Design Reference](#16-design-reference)
17. [Deployment Notes](#17-deployment-notes)

---

## 1. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Node.js | ≥ 20 (tested on 26.7.0) | Use nvm if needed |
| npm | ≥ 10 | Ships with Node 20+ |
| Git | any | |

Do **not** use Yarn or pnpm — the lock file is `package-lock.json`.

---

## 2. Getting Started

```bash
# 1. Install dependencies
cd luxride-app
npm install

# 2. Create local env file (see section 3)
cp .env.example .env.local
# edit .env.local — set NEXT_PUBLIC_API_BASE_URL

# 3. Run dev server
npm run dev
# → http://localhost:3000

# 4. Run Storybook (component library)
npm run storybook
# → http://localhost:6006

# 5. Type-check
npx tsc --noEmit

# 6. Lint
npm run lint
```

### First-time on a new machine — SWC note

Next.js defaults to using a native binary called SWC for compilation. If you see a `dlopen` error about `@next/swc-darwin-arm64` (or the linux equivalent) on first run, the binary may be missing or corrupted. The project already has a `.babelrc` fallback that makes Next.js use Babel instead — **no action needed**. The app will print a yellow warning and compile normally.

If SWC is available on your machine and you want to use it (faster builds), delete `.babelrc` — but read the caveat in section 15 first.

---

## 3. Environment Variables

Create `luxride-app/.env.local` (never commit this file):

```env
# URL of the Python REST API — trailing slash not needed
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api

# Set to "true" to run with mock data (no backend needed)
# Set to "false" (or omit) to hit the real API
NEXT_PUBLIC_USE_MOCKS=true

# Stripe publishable key (needed only when payment step is wired up)
NEXT_PUBLIC_STRIPE_PK=pk_test_...

# PayPal client ID (needed only when PayPal is wired up)
NEXT_PUBLIC_PAYPAL_CLIENT_ID=...
```

The `.env.example` file at the root documents all variables without values.

**During development use `NEXT_PUBLIC_USE_MOCKS=true`** — the entire app works without the Python server being up.

---

## 4. Project Structure

```
luxride-app/
├── .babelrc                    # Forces Babel instead of SWC (see section 15)
├── .storybook/
│   ├── main.ts                 # Storybook config — @storybook/nextjs framework
│   └── preview.ts              # Global CSS imports for Storybook
├── next.config.ts              # Minimal Next.js config
├── tsconfig.json               # Strict TypeScript
├── public/
│   ├── assets/
│   │   ├── css/
│   │   │   ├── luxride.css             # Main Luxride stylesheet (DO NOT EDIT)
│   │   │   └── vendors/                # bootstrap, normalize, animate, icons, etc.
│   │   └── imgs/                       # All template images (~200 files)
│   └── fonts/
│       └── uicons/                     # Icon font files (.eot, .woff, .woff2)
└── src/
    ├── app/                            # Next.js App Router
    │   ├── layout.tsx                  # Root layout — CSS links, font, Providers
    │   ├── page.tsx                    # Home page ( / )
    │   ├── not-found.tsx               # 404 page
    │   ├── (marketing)/                # Route group — marketing pages
    │   │   ├── layout.tsx              # Header + Footer wrapper
    │   │   ├── fleet/page.tsx
    │   │   ├── services/page.tsx
    │   │   ├── about/page.tsx
    │   │   ├── blog/page.tsx
    │   │   ├── pricing/page.tsx
    │   │   ├── contact/page.tsx
    │   │   ├── terms/page.tsx
    │   │   └── coming-soon/page.tsx
    │   ├── (auth)/                     # Route group — auth pages (no header/footer chrome yet)
    │   │   ├── layout.tsx
    │   │   ├── login/page.tsx
    │   │   └── register/page.tsx
    │   └── booking/                    # 5-step booking wizard
    │       ├── layout.tsx              # Header + BookingSteps tab bar + Footer
    │       ├── vehicle/page.tsx        # Step 1 — IMPLEMENTED
    │       ├── extra/page.tsx          # Step 2 — STUB
    │       ├── passenger/page.tsx      # Step 3 — STUB
    │       ├── payment/page.tsx        # Step 4 — STUB
    │       └── confirmation/page.tsx   # Step 5 — IMPLEMENTED
    ├── components/
    │   ├── layout/
    │   │   ├── Header.tsx              # Sticky header, desktop nav, mobile drawer
    │   │   ├── Footer.tsx              # Full footer with links + app download buttons
    │   │   └── ScrollToTop.tsx         # Floating scroll-to-top button
    │   ├── home/
    │   │   └── HeroSection.tsx         # Swiper banner + BookingSearchWidget overlay
    │   ├── booking/
    │   │   ├── BookingSearchWidget.tsx  # From/To/Date/Time search + store seeding
    │   │   └── BookingSteps.tsx         # Step tab bar (active/done state from pathname)
    │   └── ui/
    │       ├── DayPicker.tsx            # react-day-picker popup with custom input
    │       └── TimePicker.tsx           # Custom 15-min interval time list popup
    ├── hooks/
    │   └── useInView.ts                # IntersectionObserver → triggers animate.css classes
    ├── lib/
    │   ├── api/
    │   │   ├── config.ts               # Reads env vars — API_BASE_URL + USE_MOCKS flag
    │   │   ├── client.ts               # fetch wrapper — apiGet/apiPost/apiPut/apiDelete
    │   │   ├── auth.service.ts         # login, register, logout, me — mock/http toggle
    │   │   ├── fleet.service.ts        # listVehicles, getVehicle — mock/http toggle
    │   │   ├── booking.service.ts      # createBooking, getBooking, createPaymentIntent
    │   │   └── mocks/
    │   │       └── fleet.ts            # 4 sample vehicles (seeds the booking wizard)
    │   └── booking/
    │       └── store.ts                # Zustand booking wizard state (sessionStorage persist)
    ├── providers/
    │   └── Providers.tsx               # TanStack Query QueryClientProvider
    ├── stories/                        # Storybook — atomic design
    │   ├── StyleGuide/                 # Colors, Typography, Icons, Spacing
    │   ├── Atoms/                      # Button, Input, Badge
    │   ├── Molecules/                  # FleetCard, QuantityStepper
    │   ├── Organisms/                  # Header, Footer, BookingSearchWidget, BookingSteps
    │   ├── Templates/                  # MarketingLayout, BookingLayout
    │   └── Pages/                      # Home
    ├── styles/                         # CSS copies for Storybook (mirrors public/assets/css)
    │   ├── luxride.css
    │   └── vendors/
    └── types/
        └── index.ts                    # All TypeScript domain interfaces
```

---

## 5. Routing Architecture

### Route groups

Next.js App Router "route groups" (folders in parentheses like `(marketing)`) let pages share a layout without the folder name appearing in the URL.

| Group | URL prefix | Layout wraps |
|---|---|---|
| `(marketing)` | `/fleet`, `/about`, `/blog`, etc. | Header + Footer |
| `(auth)` | `/login`, `/register` | bare `<main>` only |
| `booking` | `/booking/*` | Header + BookingSteps tab bar + Footer |
| root | `/` | Root layout only (adds its own Header + Footer inline) |

### All routes

| Route | File | Status |
|---|---|---|
| `/` | `app/page.tsx` | Hero + search widget built |
| `/fleet` | `app/(marketing)/fleet/page.tsx` | Stub |
| `/services` | `app/(marketing)/services/page.tsx` | Stub |
| `/about` | `app/(marketing)/about/page.tsx` | Stub |
| `/blog` | `app/(marketing)/blog/page.tsx` | Stub |
| `/pricing` | `app/(marketing)/pricing/page.tsx` | Stub |
| `/contact` | `app/(marketing)/contact/page.tsx` | Stub |
| `/terms` | `app/(marketing)/terms/page.tsx` | Stub |
| `/coming-soon` | `app/(marketing)/coming-soon/page.tsx` | Stub |
| `/login` | `app/(auth)/login/page.tsx` | Stub |
| `/register` | `app/(auth)/register/page.tsx` | Stub |
| `/booking/vehicle` | `app/booking/vehicle/page.tsx` | **Built** — lists vehicles from API/mock |
| `/booking/extra` | `app/booking/extra/page.tsx` | Stub |
| `/booking/passenger` | `app/booking/passenger/page.tsx` | Stub |
| `/booking/payment` | `app/booking/payment/page.tsx` | Stub |
| `/booking/confirmation` | `app/booking/confirmation/page.tsx` | **Built** — reads store, shows summary |
| `*` | `app/not-found.tsx` | Stub |

---

## 6. Styling System

### How CSS is loaded

All CSS is served as **static files** from `public/assets/css/` and loaded via `<link>` tags in `src/app/layout.tsx`. This is intentional — the Luxride stylesheet uses relative `url()` paths like `url(../imgs/template/icons/next-day.png)`. If the CSS were imported as a JS module, the webpack/Next.js bundler would try to resolve those paths and fail. Serving from `public/` bypasses the bundler entirely.

**Load order (layout.tsx `<head>`):**
1. Bunny Fonts — DM Sans 400/500/700
2. `normalize.css`
3. `bootstrap.min.css`
4. `uicons-regular-rounded.css` (icon font)
5. `animate.css`
6. `luxride.css` — main design system (loads last so it wins)

### Icon font

The UI uses Uicons (flaticon). Usage:
```html
<span className="fi fi-rr-search" />    <!-- search icon -->
<span className="fi fi-rr-car-side" />  <!-- car icon -->
```
All icon names are listed in `public/fonts/uicons/` and the CSS defines `.fi-*` classes.

The template also uses its own semantic icon classes like `icon-from`, `icon-to`, `icon-date`, `icon-time` (defined in `luxride.css`). Use those for the search widget elements.

### CSS classes to know

Most component styling comes from classes already defined in `luxride.css`. Key patterns:

```
.section            — page section wrapper with top/bottom padding
.container          — max-width centered container
.container-sub      — slightly wider variant used in footer
.heading-52-medium  — large display heading
.heading-36-medium  — section heading
.heading-24-medium  — card heading
.text-16            — body text 16px
.text-14            — small text 14px
.color-primary      — brand dark color (#0E0E0E)
.color-white        — white
.color-grey         — muted grey
.btn                — base button
.btn-default        — dark filled button
.btn-white          — white outlined button
.item-vehicle       — vehicle card in booking step 1
.list-tabs-step     — booking wizard step tab bar
.box-search-ride    — the hero search widget container
.mobile-header-*    — mobile drawer nav classes
.sticky-bar         — makes header stick on scroll
```

### Do NOT modify `public/assets/css/luxride.css`

This file is a copy from the original template. All customizations should be done in a new file (e.g. `public/assets/css/custom.css`) loaded after `luxride.css`. Add a `<link>` to it in `layout.tsx`.

---

## 7. Component Library & Storybook

Run Storybook with:
```bash
npm run storybook
# http://localhost:6006
```

Storybook is organized using **Atomic Design**:

| Category | Stories | Description |
|---|---|---|
| `StyleGuide/Colors` | Color palette | All brand colors with hex values |
| `StyleGuide/Typography` | Type scale | All heading and text classes |
| `StyleGuide/Icons` | Icon reference | All Uicon glyphs |
| `StyleGuide/Spacing` | Spacing system | Margin/padding scale |
| `Atoms/Button` | Variants, sizes | `.btn-default`, `.btn-white`, etc. |
| `Atoms/Input` | States | Text input with label and validation |
| `Atoms/Badge` | Types | Status badges |
| `Molecules/FleetCard` | Default, selected | Vehicle selection card |
| `Molecules/QuantityStepper` | Default | +/− counter for extras |
| `Organisms/Header` | Default | Full sticky navigation |
| `Organisms/Footer` | Default | Full footer |
| `Organisms/BookingSearchWidget` | Default | Hero search form |
| `Organisms/BookingSteps` | All step states | Tab bar for booking wizard |
| `Templates/MarketingLayout` | Default | Header + main + Footer shell |
| `Templates/BookingLayout` | Default | Header + steps + main + Footer shell |
| `Pages/Home` | Default | Full homepage composition |

Storybook uses the same CSS stack as the app — all Luxride classes work inside stories.

**Adding a new story:**
```tsx
// src/stories/Atoms/MyComponent.stories.tsx
import type { Meta, StoryObj } from "@storybook/react";
import MyComponent from "@/components/ui/MyComponent";

const meta: Meta<typeof MyComponent> = {
  title: "Atoms/MyComponent",
  component: MyComponent,
};
export default meta;

type Story = StoryObj<typeof MyComponent>;
export const Default: Story = { args: { label: "Click me" } };
```

---

## 8. API Layer

### Architecture

Every feature has a **service module** in `src/lib/api/` that exports both a real HTTP implementation and a mock implementation. A single flag — `NEXT_PUBLIC_USE_MOCKS` — switches between them. No component code changes when you flip the flag.

```
src/lib/api/
├── config.ts          — reads env vars
├── client.ts          — fetch wrapper (apiGet, apiPost, apiPut, apiDelete)
├── auth.service.ts    — login, register, logout, me
├── fleet.service.ts   — listVehicles, getVehicle
├── booking.service.ts — createBooking, getBooking, listMyBookings, createPaymentIntent
└── mocks/
    └── fleet.ts       — 4 sample vehicles
```

### HTTP client (`client.ts`)

```typescript
// All requests automatically include credentials (cookies) for session auth
// Throws ApiRequestError on non-2xx responses
// Returns undefined for 204 No Content

import { apiGet, apiPost, apiPut, apiDelete } from "@/lib/api/client";

const vehicles = await apiGet<Vehicle[]>("/fleet/vehicles/");
const booking = await apiPost<Booking>("/bookings/", payload);
```

### Using a service in a component

```typescript
import { useQuery, useMutation } from "@tanstack/react-query";
import { fleetService } from "@/lib/api/fleet.service";

// In a Server Component or Client Component:
const { data, isLoading, error } = useQuery({
  queryKey: ["vehicles"],
  queryFn: () => fleetService.listVehicles(),
});
```

### Adding a new service

1. Define the TypeScript types in `src/types/index.ts`
2. Create `src/lib/api/mocks/myfeature.ts` with hardcoded data
3. Create `src/lib/api/myfeature.service.ts`:

```typescript
import { USE_MOCKS } from "./config";
import { apiGet, apiPost } from "./client";
import { mockData } from "./mocks/myfeature";
import type { MyType } from "@/types";

const http = {
  list: () => apiGet<MyType[]>("/myfeature/"),
  create: (data: Partial<MyType>) => apiPost<MyType>("/myfeature/", data),
};

const mocks = {
  list: async () => mockData,
  create: async (data: Partial<MyType>) => ({ id: "mock-1", ...data } as MyType),
};

export const myFeatureService = USE_MOCKS ? mocks : http;
```

### Auth — cookie-based session

The HTTP client sends `credentials: "include"` on every request. This means:

- The Python backend must respond with a `Set-Cookie` header on login containing an httpOnly, Secure, SameSite=Lax session cookie
- Subsequent requests automatically carry that cookie — no token management in JS
- Logout hits the backend which clears the cookie server-side

**Expected Python endpoints:**

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/auth/login/` | `{ email, password }` | `{ user: User }` + Set-Cookie |
| POST | `/api/auth/register/` | `{ name, email, password, phone? }` | `{ user: User }` + Set-Cookie |
| POST | `/api/auth/logout/` | (empty) | 204 + clears cookie |
| GET | `/api/auth/me/` | — | `User` object; anonymous → 204 no body (treat as signed-out) |

---

## 9. Booking Wizard State

The booking wizard is a 5-step flow. State is held in a **Zustand store** persisted to `sessionStorage` so a page refresh mid-flow does not lose the user's selections.

```
/booking/vehicle    → user picks a vehicle          → setVehicle()  → push /booking/extra
/booking/extra      → user picks add-ons            → setExtras()   → push /booking/passenger
/booking/passenger  → user enters passenger info    → setPassenger()→ push /booking/payment
/booking/payment    → user pays (Stripe/PayPal)     → setPayment()  → POST /bookings/ → push /booking/confirmation
/booking/confirmation → success screen, store.reset()
```

### Store slices

```typescript
import { useBookingStore } from "@/lib/booking/store";

// Read
const vehicle = useBookingStore((s) => s.vehicle);
const search  = useBookingStore((s) => s.search);

// Write
const setVehicle  = useBookingStore((s) => s.setVehicle);
const setExtras   = useBookingStore((s) => s.setExtras);
const setPassenger = useBookingStore((s) => s.setPassenger);
const setPayment  = useBookingStore((s) => s.setPayment);
const reset       = useBookingStore((s) => s.reset);
```

### Seeding the store from the hero search

`BookingSearchWidget` calls `setSearch({ from, to, date, time })` then navigates to `/booking/vehicle`. The vehicle page reads nothing from the search state (it just lists available vehicles). Downstream steps can read `search` to display trip details in the order summary sidebar.

### SessionStorage key

The store persists under the key `luxride-booking`. You can inspect it in DevTools → Application → Session Storage.

---

## 10. TypeScript Domain Types

All shared interfaces live in `src/types/index.ts`. These are hand-written now and will be replaced by auto-generated types from the Swagger spec when it is available (using `openapi-typescript`).

```typescript
Vehicle         — id, slug, name, class, image, passengers, luggage, price, facilities[]
Location        — id, label, type ("airport" | "city" | "address")
BookingSearch   — from, to, date (ISO string), time (HH:MM)
ExtraItem       — id, label, qty, priceEach
PassengerDetails — name, lastName, email, phone, passengers, luggage, notes?
BillingDetails  — name, lastName, company?, address, country, city, zip
PaymentDetails  — method ("card" | "paypal"), billing
Booking         — id, status, search, vehicle, extras, passenger, totalPrice, createdAt
Service         — id, slug, title, description, image, icon
Post            — id, slug, title, excerpt, image, date, category, author
TeamMember      — id, slug, name, role, image, bio?
PricingTier     — id, name, price, period, features[], highlighted?
User            — id, name, email, phone?
ApiError        — message, code?, field?
```

When the Swagger spec arrives:
```bash
npx openapi-typescript http://localhost:8000/api/schema/ -o src/types/api.d.ts
```
Then update service modules to import from `api.d.ts` instead of `index.ts`.

---

## 11. What Is Built

### Fully implemented

| Item | Location | Notes |
|---|---|---|
| Root layout | `app/layout.tsx` | CSS links, font, Providers, ScrollToTop |
| React Query provider | `providers/Providers.tsx` | 60s stale time, 1 retry |
| API client | `lib/api/client.ts` | fetch + cookie + error normalization |
| Mock/real toggle | `lib/api/config.ts` | env var driven |
| Fleet service | `lib/api/fleet.service.ts` | listVehicles, getVehicle |
| Auth service | `lib/api/auth.service.ts` | login, register, logout, me |
| Booking service | `lib/api/booking.service.ts` | createBooking, getBooking, createPaymentIntent |
| Mock fleet data | `lib/api/mocks/fleet.ts` | 4 vehicles with realistic prices |
| Booking Zustand store | `lib/booking/store.ts` | sessionStorage persist, all 5 slices |
| Domain types | `types/index.ts` | All 12 interfaces |
| Header | `components/layout/Header.tsx` | Sticky, desktop nav + dropdowns, mobile drawer |
| Footer | `components/layout/Footer.tsx` | Full 5-column layout |
| ScrollToTop | `components/layout/ScrollToTop.tsx` | Appears after 300px scroll |
| Hero section | `components/home/HeroSection.tsx` | Swiper carousel (5 slides, autoplay, nav, fraction) |
| BookingSearchWidget | `components/booking/BookingSearchWidget.tsx` | From/To/Date/Time, seeds store, routes to /booking/vehicle |
| BookingSteps tab bar | `components/booking/BookingSteps.tsx` | Active/done derived from pathname |
| DayPicker | `components/ui/DayPicker.tsx` | Popup calendar, past dates disabled |
| TimePicker | `components/ui/TimePicker.tsx` | 15-min interval scrollable list |
| useInView hook | `hooks/useInView.ts` | IntersectionObserver, one-shot, disconnects after trigger |
| Marketing layout | `app/(marketing)/layout.tsx` | Header + children + Footer |
| Booking layout | `app/booking/layout.tsx` | Header + BookingSteps + children + Footer |
| Home page | `app/page.tsx` | Hero + search widget |
| Booking vehicle page | `app/booking/vehicle/page.tsx` | Fetches vehicles, VehicleCard, select → store → /extra |
| Booking confirmation | `app/booking/confirmation/page.tsx` | Reads store, displays trip summary |
| Storybook atomic design | `src/stories/` | 15 stories across 6 categories |

---

## 12. What Is a Stub (needs implementation)

These files exist with a placeholder `<h2>` or "Step coming soon…" body. All routing is wired — you can navigate to them, they just need content.

### Marketing pages — all in `app/(marketing)/`

Port content from the matching HTML template file in the design reference (see section 16). Each page should:
1. Have a page-level banner/hero section
2. Main content sections
3. Use `export const metadata` for SEO title/description

| Page | Template file to port from |
|---|---|
| `/fleet` | `fleet.html` or `fleet-list.html` |
| `/services` | `services.html` |
| `/about` | `about.html` |
| `/blog` | `blog.html` |
| `/pricing` | `pricing.html` |
| `/contact` | `contact.html` |
| `/terms` | `terms.html` |
| `/coming-soon` | `coming-soon.html` |

### Auth pages — `app/(auth)/`

| Page | Template to port from | Notes |
|---|---|---|
| `/login` | `login.html` | Use `react-hook-form` + `zod`, call `authService.login()` |
| `/register` | `register.html` | Same pattern |

After login success, redirect to `/account` or the `?next=` query param.

### Booking wizard steps 2–4

| Step | File | Template to port | Store action to call |
|---|---|---|---|
| Extra | `booking/extra/page.tsx` | `booking-extra.html` | `setExtras({ items, flightNo, trainNo, notes })` |
| Passenger | `booking/passenger/page.tsx` | `booking-passenger.html` | `setPassenger({ name, lastName, email, phone, passengers, luggage })` |
| Payment | `booking/payment/page.tsx` | `booking-payment.html` | `setPayment({ method, billing })` then POST booking |

Payment step implementation checklist:
- [ ] Load `@stripe/react-stripe-js` `<PaymentElement>` (publishable key from `NEXT_PUBLIC_STRIPE_PK`)
- [ ] Call `bookingService.createPaymentIntent(bookingPreviewId)` to get `clientSecret`
- [ ] On Stripe confirm success, POST `/bookings/` with full payload via `bookingService.createBooking()`
- [ ] On success, call `store.reset()` and `router.push("/booking/confirmation")`
- [ ] **Never** send raw card numbers to the Python backend — all card data goes browser → Stripe only

### Route protection / middleware

No `middleware.ts` exists yet. Add it to gate `/booking/*` and `/account/*`:

```typescript
// src/middleware.ts
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(req: NextRequest) {
  const session = req.cookies.get("sessionid"); // adjust cookie name to match Python backend
  if (!session && req.nextUrl.pathname.startsWith("/account")) {
    return NextResponse.redirect(new URL(`/login?next=${req.nextUrl.pathname}`, req.url));
  }
}

export const config = { matcher: ["/account/:path*"] };
```

### Account section

Not scaffolded yet. Needs:
- `/account` — booking history (`bookingService.listMyBookings()`)
- `/account/invoice/[id]` — single booking invoice

---

## 13. How to Connect the Real Backend

### Step 1 — Set env vars

```env
# .env.local
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
NEXT_PUBLIC_USE_MOCKS=false
```

### Step 2 — Verify CORS on the Python side

The Python backend must allow the Next.js dev origin:
```python
# Django example
CORS_ALLOWED_ORIGINS = ["http://localhost:3000"]
CORS_ALLOW_CREDENTIALS = True  # required for cookie auth
```

### Step 3 — Match API paths

The service modules use these URL patterns (relative to `API_BASE_URL`):

```
GET  /fleet/vehicles/          → list vehicles
GET  /fleet/vehicles/{slug}/   → single vehicle
POST /auth/login/              → login
POST /auth/register/           → register  
POST /auth/logout/             → logout
GET  /auth/me/                 → current user (204 empty when anonymous)
POST /bookings/                → create booking
GET  /bookings/                → list user's bookings
GET  /bookings/{id}/           → single booking
POST /payments/intent/         → create Stripe payment intent → returns { clientSecret }
```

If your Python backend uses different paths, update the strings in the `http` objects inside each `*.service.ts` file.

### Step 4 — Generate types from Swagger (optional but recommended)

```bash
npm install -D openapi-typescript
npx openapi-typescript http://localhost:8000/api/schema/ -o src/types/api.d.ts
```

Then gradually replace the hand-written interfaces in `src/types/index.ts` with imports from `api.d.ts`.

### Step 5 — Smoke test per service

```bash
# With the Python server running and NEXT_PUBLIC_USE_MOCKS=false:
# 1. Open http://localhost:3000
# 2. Use the search widget → navigate to /booking/vehicle
# 3. Check Network tab: GET /api/fleet/vehicles/ should return 200 with vehicle array
# 4. Try login at /login
# 5. Check Application → Cookies: session cookie should appear after login
```

---

## 14. How to Add a New Page

### Example: adding `/fleet/[slug]` (vehicle detail)

1. **Create the file:**
   ```
   src/app/(marketing)/fleet/[slug]/page.tsx
   ```

2. **Write the page:**
   ```typescript
   import { fleetService } from "@/lib/api/fleet.service";

   interface Props { params: Promise<{ slug: string }> }

   export default async function FleetSinglePage({ params }: Props) {
     const { slug } = await params;
     const vehicle = await fleetService.getVehicle(slug);

     return (
       <section className="section pt-60 pb-60">
         <div className="container">
           <h1 className="heading-36-medium">{vehicle.name}</h1>
           {/* port from fleet-single.html */}
         </div>
       </section>
     );
   }

   export async function generateMetadata({ params }: Props) {
     const { slug } = await params;
     const vehicle = await fleetService.getVehicle(slug);
     return { title: vehicle.name };
   }
   ```

3. **Add a mock** in `src/lib/api/mocks/fleet.ts` so dev works without the backend.

4. **Add to nav** in `Header.tsx` NAV_LINKS if needed.

5. **Add a story** in `src/stories/Pages/FleetSingle.stories.tsx`.

---

## 15. Known Issues & Quirks

### SWC binary corrupted

`@next/swc-darwin-arm64` (the native Rust compiler) was partially downloaded and is broken. The `.babelrc` file forces Next.js to use Babel instead:

```json
{ "presets": ["next/babel"] }
```

**Consequence:** `next/font` cannot be used in Babel mode. The app uses a `<link>` to Bunny Fonts (a GDPR-friendly Google Fonts mirror) in the root `<head>` instead. Do not add `import { DM_Sans } from "next/font/google"` — it will throw a build error.

**To fix properly:** Delete `node_modules/@next/swc-darwin-arm64` and reinstall it with a stable connection:
```bash
rm -rf node_modules/@next/swc-darwin-arm64
npm install @next/swc-darwin-arm64
# Then delete .babelrc
```
After that, `next/font` will work and you can replace the `<link>` with `next/font/google`.

### CSS loaded as static files (not JS imports)

As explained in section 6, `luxride.css` cannot be imported as a JS module because of relative `url()` references inside it. It is served from `public/assets/css/`. **Do not move it** or try to `import "../styles/luxride.css"` in a component — it will break in production.

### Location suggestions are hardcoded

`BookingSearchWidget.tsx` has a `SAMPLE_LOCATIONS` array with 5 London locations. Before launch, replace this with a real autocomplete endpoint (Google Places API or your backend's location search endpoint).

### Images use `<img>` in some stories

Storybook stories may render images with `<img>` instead of Next.js `<Image>` in some cases. This is fine for Storybook — `next/image` optimization only runs in the Next.js runtime.

### `.DS_Store` files

macOS generates `.DS_Store` files. They are harmless but should be added to `.gitignore` before the first git commit:
```
.DS_Store
**/.DS_Store
```

### `safe.svg.html` and `dot-active.svg.html`

Some files in `public/assets/imgs/` have `.svg.html` extensions — these are artifacts from how Netlify CDN cached the original template assets. They are not used by any component and can be deleted.

---

## 16. Design Reference

The original static HTML template is located at:
```
/Users/caldrissi/Desktop/m&M-frontend/luxride/
```

**This folder must never be modified.** It is the acceptance oracle — every page in the Next.js app should visually match its HTML counterpart when viewed side-by-side.

To browse the template locally, serve it with:
```bash
npx serve /Users/caldrissi/Desktop/m\&M-frontend/luxride -l 9090
# → http://localhost:9090
```

### Key template files to reference when building stubs

| Template file | Corresponding Next.js route |
|---|---|
| `index.html` | `/` (home — hero variant 1) |
| `fleet.html` | `/fleet` |
| `fleet-list.html` | `/fleet` (alternate layout) |
| `fleet-single.html` | `/fleet/[slug]` |
| `services.html` | `/services` |
| `about.html` | `/about` |
| `our-team.html` | `/team` (not yet scaffolded) |
| `pricing.html` | `/pricing` |
| `blog.html` | `/blog` |
| `blog-single.html` | `/blog/[slug]` (not yet scaffolded) |
| `contact.html` | `/contact` |
| `terms.html` | `/terms` |
| `coming-soon.html` | `/coming-soon` |
| `login.html` | `/login` |
| `register.html` | `/register` |
| `booking-vehicle.html` | `/booking/vehicle` |
| `booking-extra.html` | `/booking/extra` |
| `booking-passenger.html` | `/booking/passenger` |
| `booking-payment.html` | `/booking/payment` |
| `booking-confirmation.html` | `/booking/confirmation` |

---

## 17. Deployment Notes

### Environment variables in production

Set these in your hosting platform (Vercel, Coolify, etc.):

```
NEXT_PUBLIC_API_BASE_URL=https://api.yourdomain.com/api
NEXT_PUBLIC_USE_MOCKS=false
NEXT_PUBLIC_STRIPE_PK=pk_live_...
NEXT_PUBLIC_PAYPAL_CLIENT_ID=...
```

### Build command

```bash
npm run build
npm run start
```

### CORS

The production backend must allow the production frontend origin with `credentials: true`.

### SWC on CI/Linux

On a Linux CI runner, `@next/swc-linux-x64-gnu` will be installed. Delete `.babelrc` for production builds — SWC will work correctly on Linux even if it does not work on the developer's corrupted Mac install. If you keep `.babelrc`, builds will work but will be slower and `next/font` will be unavailable.

### Static assets

All images, fonts, and CSS in `public/` are served by Next.js as static assets with long cache headers. No CDN configuration needed beyond what your hosting platform provides.

---

## Appendix: npm scripts

| Script | Command | Purpose |
|---|---|---|
| `npm run dev` | `next dev` | Dev server on :3000 with HMR |
| `npm run build` | `next build` | Production build |
| `npm run start` | `next start` | Serve production build |
| `npm run lint` | `next lint` | ESLint check |
| `npm run storybook` | `storybook dev -p 6006` | Component library on :6006 |
| `npm run build-storybook` | `storybook build` | Static Storybook export |
| `npx tsc --noEmit` | — | Type-check without building |

---

## Appendix: Dependencies reference

### Production

| Package | Version | Purpose |
|---|---|---|
| `next` | 15.3.3 | Framework |
| `react` | ^19 | UI library |
| `react-dom` | ^19 | DOM renderer |
| `@tanstack/react-query` | ^5 | Data fetching, caching, mutations |
| `zustand` | ^5 | Booking wizard state (sessionStorage persist) |
| `swiper` | ^11 | Hero carousel, fleet galleries |
| `react-day-picker` | ^9 | Date selection popup |
| `react-select` | ^5 | Enhanced select dropdowns |
| `rc-slider` | ^11 | Price range filter (fleet page) |
| `react-hook-form` | ^7 | Form state and validation |
| `zod` | ^3 | Schema validation |
| `react-countup` | ^6 | Animated number counters |
| `@stripe/stripe-js` | ^5 | Stripe.js loader |
| `@stripe/react-stripe-js` | ^3 | Stripe React components |

### Development

| Package | Version | Purpose |
|---|---|---|
| `storybook` | ^8 | Component explorer |
| `@storybook/nextjs` | ^8 | Next.js framework adapter for Storybook |
| `@storybook/addon-essentials` | ^8 | Controls, actions, docs |
| `typescript` | ^5 | Type checking |

---

*Document version: 2026-09-12 · Prepared for backend integration handoff*
