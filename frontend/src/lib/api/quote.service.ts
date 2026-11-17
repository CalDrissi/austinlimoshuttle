import { pickupIso } from "@/lib/booking/store";
import { apiPost } from "./client";
import type { QuoteRequest, QuoteResponse } from "@/types/api";

/**
 * Price a journey across every vehicle. The server measures the distance from
 * the two addresses and returns a signed `quote_token` per vehicle — the only
 * way to create a booking. No price or distance is ever sent by the client.
 */
export const quoteService = {
  create: (body: QuoteRequest) => apiPost<QuoteResponse>("/quotes/", body),
};

/** Shared request mapping for initial searches and in-flow edits. */
export function quoteRequest(search: import("@/lib/booking/store").Search): QuoteRequest {
  return {
    pickup_address: search.pickupAddress,
    pickup_at: pickupIso(search),
    meet_and_greet: search.meetGreet,
    ...(search.tripType === "hourly"
      ? { hours: String(search.hours ?? 3) }
      : { dropoff_address: search.dropoffAddress, ...(search.tripType === "city" ? { city_to_city: true } : {}) }),
  };
}
