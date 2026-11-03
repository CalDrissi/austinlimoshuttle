// Types that mirror the Django API exactly (see backend/api/serializers.py).
// Money is always a decimal STRING — the backend never emits a float and never
// accepts a price. Do not add a numeric price field to anything here.

// ---- catalog & content ----------------------------------------------------

export interface Vehicle {
  id: number;
  name: string;
  slug: string;
  description: string;
  features: string;
  passenger_capacity: number;
  luggage_capacity: number;
  /** "From" price for display only — the real fare comes from a quote. */
  minimum_fare: string;
  /** Absolute URL of the uploaded photo, or null (use a placeholder). */
  photo: string | null;
}

export interface Page {
  slug: string;
  url: string;
  title: string;
  page_type: string;
  body: string;
  meta_title: string;
  meta_description: string;
  meta_keywords: string;
}

export interface SiteSettings {
  contact_email: string;
  contact_phone: string;
  facebook: string;
  instagram: string;
  twitter: string;
  linkedin: string;
}

export interface BlackoutDate {
  date: string;
  name: string;
  percentage: string;
}

export interface TimeSurcharge {
  name: string;
  start_time: string;
  end_time: string;
  percentage: string;
  crosses_midnight: boolean;
}

export interface Availability {
  blackout_dates: BlackoutDate[];
  time_surcharges: TimeSurcharge[];
}

// ---- quoting --------------------------------------------------------------

export interface QuoteRequest {
  pickup_address: string;
  /** Transfer only — supply this OR `hours`, never both. */
  dropoff_address?: string;
  /** ISO 8601 with timezone, e.g. 2026-09-01T14:30:00-05:00. */
  pickup_at: string;
  /** Hourly hire only. */
  hours?: string;
  meet_and_greet?: boolean;
  /**
   * Free-form city-to-city: a point-to-point trip (needs `dropoff_address`) that
   * asks the engine to prefer each vehicle's intercity rate card. The server
   * measures the distance from the two addresses and silently falls back to the
   * normal transfer card when the trip is below a vehicle's minimum distance.
   */
  city_to_city?: boolean;
}

export type QuoteLineKind =
  | "base" | "band" | "surcharge" | "meet_greet" | "minimum_adjustment" | "tax";

export interface QuoteLine {
  kind: QuoteLineKind;
  label: string;
  amount: string;
}

export interface QuoteResult {
  vehicle_id: number;
  vehicle_name: string;
  subtotal: string;
  surcharge_total: string;
  tax: string;
  total: string;
  currency: string;
  lines: QuoteLine[];
  /** Signed, short-lived. Present to POST /bookings/. */
  quote_token: string;
}

export interface Journey {
  distance_miles: string;
  duration_minutes: number;
  pickup_address: string;
  dropoff_address: string;
}

export interface QuoteResponse {
  journey: Journey | null;
  quotes: QuoteResult[];
}

// ---- bookings -------------------------------------------------------------

export interface BookingCreateRequest {
  quote_token: string;
  passenger_count?: number;
  luggage_count?: number;
  flight_number?: string;
  pickup_sign?: string;
  notes?: string;
  /** Guest checkout — required when not signed in. */
  guest_email?: string;
  guest_name?: string;
  /** Contact phone — required for guest checkout. */
  guest_phone?: string;
}

export type BookingStatusValue =
  | "pending" | "confirmed" | "assigned" | "completed" | "cancelled";

export interface BookingPriceLine {
  kind: string;
  label: string;
  amount: string;
}

export interface Booking {
  reference: string;
  status: BookingStatusValue;
  status_display: string;
  trip_type: string;
  pickup_address: string;
  dropoff_address: string;
  pickup_at: string;
  distance_miles: string;
  duration_minutes: number;
  hours: string | null;
  passenger_count: number;
  luggage_count: number;
  flight_number: string;
  pickup_sign: string;
  meet_and_greet: boolean;
  notes: string;
  vehicle_name: string;
  subtotal: string;
  surcharge_total: string;
  tax: string;
  total: string;
  currency: string;
  price_lines: BookingPriceLine[];
  created_at: string;
  /** Whether the customer may still edit non-price details (within the window). */
  is_amendable: boolean;
  /** The cutoff after which online edits are blocked. */
  amendment_deadline: string;
}

/** The narrow, public confirmation shape (no addresses/passenger data). */
export interface BookingStatus {
  reference: string;
  status: BookingStatusValue;
  status_display: string;
  pickup_at: string;
  vehicle_name: string;
  total: string;
  currency: string;
}

// ---- auth -----------------------------------------------------------------

export interface User {
  email: string;
  first_name: string;
  last_name: string;
  phone?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
  first_name?: string;
  last_name?: string;
  phone?: string;
}

// ---- payments -------------------------------------------------------------

export interface PaymentConfig {
  enabled: boolean;
  publishable_key: string;
  mode: string | null;
}

export interface PaymentIntentResponse {
  client_secret: string;
  publishable_key: string;
  amount: string;
  currency: string;
  reference: string;
}

// ---- enquiries ------------------------------------------------------------

export interface EnquiryRequest {
  name: string;
  email: string;
  phone?: string;
  nature?: string;
  subject?: string;
  message: string;
  company_name?: string;
}

// ---- errors ---------------------------------------------------------------

export interface ApiError {
  /** DRF returns { detail } for errors, or field-keyed arrays for validation. */
  detail?: string;
  [field: string]: unknown;
}
