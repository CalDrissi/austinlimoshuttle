import { apiGet, apiPost, apiPatch } from "./client";
import type { Booking, BookingStatus, BookingCreateRequest, BookingAmendment } from "@/types/api";

/**
 * Bookings. A booking is created from a signed `quote_token` (never a price);
 * the server recomputes the fare from the token. Account endpoints require the
 * session cookie; status is public (keyed by the reference).
 */
export const bookingService = {
  /** Create a pending booking from a quote token. */
  create: (body: BookingCreateRequest) => apiPost<Booking>("/bookings/", body),

  /** Public confirmation status — poll this after payment. */
  status: (reference: string) =>
    apiGet<BookingStatus>(`/bookings/${reference}/status/`),

  /** Signed-in customer's own bookings. */
  mine: () => apiGet<Booking[]>("/account/bookings/"),
  mineDetail: (reference: string) =>
    apiGet<Booking>(`/account/bookings/${reference}/`),

  cancel: (reference: string) =>
    apiPatch<Booking>(`/account/bookings/${reference}/`, { action: "cancel" }),

  /** Submit proposed changes for staff approval within the edit window. */
  amendRequest: (reference: string, changes: BookingAmendRequest) =>
    apiPost<BookingAmendment>(`/account/bookings/${reference}/amend-request/`, changes),
};

/** Customer-editable fields within the amendment window. */
export interface BookingAmendRequest {
  passenger_count?: number;
  luggage_count?: number;
  flight_number?: string;
  pickup_sign?: string;
  notes?: string;
  phone?: string;
  /** Austin wall-clock "YYYY-MM-DDTHH:mm"; a change re-prices the booking. */
  pickup_at?: string;
}
