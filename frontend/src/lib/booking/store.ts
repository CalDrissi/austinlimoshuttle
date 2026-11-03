"use client";

import { useEffect, useState } from "react";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { QuoteResult } from "@/types/api";

/** Raw search inputs — kept for display and to (re)request a quote. */
export interface Search {
  /**
   * "transfer" = point-to-point (needs a drop-off); "hourly" = by-the-hour
   * (needs hours); "city" = free-form city-to-city — a point-to-point trip
   * (pickup + drop-off addresses, like a transfer) that the server prices on the
   * measured distance against each vehicle's intercity rate card.
   */
  tripType: "transfer" | "hourly" | "city";
  pickupAddress: string;
  pickupCoordinates?: { lat: number; lng: number };
  dropoffCoordinates?: { lat: number; lng: number };
  dropoffAddress: string; // empty for an hourly hire
  hours?: number; // set for an hourly hire
  date: string; // YYYY-MM-DD
  time: string; // HH:MM
  meetGreet: boolean;
}

export interface Trip {
  passengerCount: number;
  luggageCount: number;
  flightNumber?: string;
  pickupSign?: string;
  notes?: string;
  /** When the booker isn't the passenger, capture who's actually travelling. */
  forSomeoneElse?: boolean;
  passengerName?: string;
  passengerPhone?: string;
}

/** The booker's contact details. Phone is required for every booking. */
export interface Contact {
  name?: string;
  email?: string;
  phone?: string;
}

interface BookingState {
  search: Search | null;
  /** The vehicle the customer chose, with its signed quote_token. */
  quote: QuoteResult | null;
  trip: Trip;
  contact: Contact;
  /** Set once POST /bookings/ succeeds. */
  reference: string | null;

  setSearch: (search: Search) => void;
  setQuote: (quote: QuoteResult) => void;
  setTrip: (trip: Partial<Trip>) => void;
  setContact: (contact: Contact) => void;
  setReference: (reference: string) => void;
  /** Clear the in-progress selections but keep the booking reference. */
  clearDraft: () => void;
  reset: () => void;
}

const initial = {
  search: null,
  quote: null,
  trip: { passengerCount: 1, luggageCount: 0 } as Trip,
  contact: {} as Contact,
  reference: null,
};

export const useBookingStore = create<BookingState>()(
  persist(
    (set) => ({
      ...initial,
      // A new search invalidates any vehicle chosen for the previous one --
      // otherwise the Ride Summary shows a stale price until a vehicle is picked.
      setSearch: (search) => set({ search, quote: null }),
      setQuote: (quote) => set({ quote }),
      setTrip: (trip) => set((s) => ({ trip: { ...s.trip, ...trip } })),
      setContact: (contact) => set({ contact }),
      setReference: (reference) => set({ reference }),
      clearDraft: () =>
        set({ search: null, quote: null, trip: { passengerCount: 1, luggageCount: 0 }, contact: {} }),
      reset: () => set(initial),
    }),
    {
      name: "mm-booking",
      storage:
        typeof window !== "undefined"
          ? {
              getItem: (k) => JSON.parse(sessionStorage.getItem(k) ?? "null"),
              setItem: (k, v) => sessionStorage.setItem(k, JSON.stringify(v)),
              removeItem: (k) => sessionStorage.removeItem(k),
            }
          : undefined,
    },
  ),
);

/**
 * The pickup timestamp for a quote.
 *
 * Sent as a NAIVE wall-clock string (no timezone). The pickup happens at this
 * local time in Austin, so the API interprets it in the business timezone
 * (America/Chicago). Converting to the visitor's UTC (toISOString) would shift
 * the hour and wrongly trigger the night surcharge for anyone not in Central.
 */
/**
 * True once the persisted store has re-hydrated from sessionStorage. Guards that
 * redirect on "no quote/reference" must wait for this, or a page refresh fires
 * the redirect before the saved state loads and bounces the user.
 */
export function useHydrated(): boolean {
  // Starts false (also the SSR value, so no hydration mismatch); the persist API
  // is only touched on the client inside the effect.
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    const unsub = useBookingStore.persist.onFinishHydration(() => setHydrated(true));
    if (useBookingStore.persist.hasHydrated()) setHydrated(true);
    return unsub;
  }, []);
  return hydrated;
}

export function pickupIso(search: Search): string {
  // The TimePicker emits "h:mm AM/PM"; normalise to 24-hour wall-clock. Sent
  // naive (no offset) so the API reads it in the business tz (America/Chicago).
  let hh = 0;
  let mm = 0;
  const ampm = search.time.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
  if (ampm) {
    hh = parseInt(ampm[1], 10) % 12;
    if (/PM/i.test(ampm[3])) hh += 12;
    mm = parseInt(ampm[2], 10);
  } else {
    const [h, m] = search.time.split(":").map(Number);
    hh = h || 0;
    mm = m || 0;
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${search.date}T${pad(hh)}:${pad(mm)}:00`;
}
