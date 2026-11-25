"use client";

/**
 * Google Places address autocomplete for the From/To fields.
 *
 * Uses the new Places API (`AutocompleteSuggestion.fetchAutocompleteSuggestions`)
 * — the classic `AutocompleteService` is retired for keys created in 2025+, so
 * this needs "Places API (New)" enabled on the key. Predictions are biased to
 * the Austin service area but not restricted, and free text is always allowed:
 * the backend geocodes whatever string ends up in the field.
 *
 * The Google types aren't a project dependency, so the `google` global is typed
 * loosely here and the loose surface is kept inside this module.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

import { API_BASE_URL } from "@/lib/api/config";

const SCRIPT_ID = "gmaps-js";
const AUSTIN = { lat: 30.2672, lng: -97.7431 };
// Places caps a locationBias circle radius at 50 km; this covers the Austin
// metro (Round Rock, Cedar Park, Georgetown, San Marcos) without exceeding it.
const BIAS_RADIUS_M = 50_000;

let loader: Promise<any> | null = null;

/**
 * The key powering Maps JS. The dashboard-managed key (Site details) wins so the
 * office can swap it without a redeploy; the build-time env var is the fallback.
 */
async function resolveApiKey(): Promise<string> {
  try {
    const r = await fetch(`${API_BASE_URL}/site-settings/`, { credentials: "include" });
    if (r.ok) {
      const data = await r.json();
      if (data?.google_maps_api_key) return data.google_maps_api_key as string;
    }
  } catch {
    /* fall through to the env var */
  }
  return process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? "";
}

/** Load the Maps JS API (with Places) once; resolves to the `google` global. */
export function loadGoogleMaps(): Promise<any> {
  if (typeof window === "undefined") return Promise.reject(new Error("not in browser"));
  const w = window as any;
  if (loader) return loader;

  loader = (async () => {
    if (w.google?.maps?.importLibrary) {
      await w.google.maps.importLibrary("places");
      return w.google;
    }
    const key = await resolveApiKey();
    if (!key) throw new Error("No Google Maps API key configured.");
    return await new Promise((resolve, reject) => {
    const ready = async () => {
      try {
        // With loading=async the script's onload can fire BEFORE the bootstrap
        // finishes defining google.maps.importLibrary — wait for it instead of
        // failing (that race broke the route map on every fresh page load).
        for (let waited = 0; !w.google?.maps?.importLibrary && waited < 6000; waited += 50) {
          await new Promise((r) => setTimeout(r, 50));
        }
        await w.google.maps.importLibrary("places");
        resolve(w.google);
      } catch (e) {
        reject(e);
      }
    };
    const existing = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null;
    if (existing) {
      existing.addEventListener("load", ready);
      existing.addEventListener("error", () => reject(new Error("Google Maps failed to load")));
      return;
    }
    const s = document.createElement("script");
    s.id = SCRIPT_ID;
    s.async = true;
    s.src =
      `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}` +
      `&libraries=places&loading=async&v=weekly`;
    s.onload = ready;
    s.onerror = () => reject(new Error("Google Maps failed to load"));
    document.head.appendChild(s);
    });
  })().catch((error: unknown) => {
    // A failed script must not leave a rejected promise (or a dead script tag)
    // cached forever. A later call can inject a fresh script and try again.
    loader = null;
    document.getElementById(SCRIPT_ID)?.remove();
    throw error;
  });
  return loader;
}

export interface PlaceSuggestion {
  id: string;
  primary: string; // e.g. "Austin-Bergstrom International Airport"
  secondary: string; // e.g. "Austin, TX, USA"
  full: string; // the string written into the field / sent to the backend
  isAirport: boolean;
}

/** A per-editing-session token (groups keystrokes into one billable session). */
export async function newSessionToken(): Promise<any> {
  const google = await loadGoogleMaps();
  return new google.maps.places.AutocompleteSessionToken();
}

/** Fetch autocomplete predictions for `input`, biased to the Austin area. */
export async function fetchPlaceSuggestions(
  input: string,
  sessionToken: any,
): Promise<PlaceSuggestion[]> {
  const google = await loadGoogleMaps();
  const { AutocompleteSuggestion } = google.maps.places;
  const { suggestions } = await AutocompleteSuggestion.fetchAutocompleteSuggestions({
    input,
    sessionToken,
    includedRegionCodes: ["us"],
    locationBias: { center: AUSTIN, radius: BIAS_RADIUS_M },
  });
  return (suggestions ?? [])
    .map((s: any) => s.placePrediction)
    .filter(Boolean)
    .map((p: any): PlaceSuggestion => ({
      id: p.placeId ?? p.text?.text ?? "",
      primary: p.mainText?.text ?? p.text?.text ?? "",
      secondary: p.secondaryText?.text ?? "",
      full: p.text?.text ?? p.mainText?.text ?? "",
      isAirport: Array.isArray(p.types) && p.types.includes("airport"),
    }));
}

/** Resolve only a selected prediction; free text still uses geocoding. */
export async function resolvePlaceCoordinates(id: string): Promise<{ lat: number; lng: number } | undefined> {
  try {
    const google = await loadGoogleMaps();
    const place = new google.maps.places.Place({ id });
    await place.fetchFields({ fields: ["location"] });
    return place.location ? { lat: place.location.lat(), lng: place.location.lng() } : undefined;
  } catch { return undefined; }
}
