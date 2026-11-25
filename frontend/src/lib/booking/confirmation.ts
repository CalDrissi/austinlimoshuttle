import type { Contact, Search, Trip } from "./store";

/**
 * What the confirmation page shows, captured at the moment of payment and
 * keyed by reference in sessionStorage. The draft store is CLEARED on the
 * confirmation page (the funnel is over), so a refresh must not depend on it —
 * this snapshot is what survives.
 */
export interface ConfirmationSnapshot {
  search: Search | null;
  vehicleName: string;
  total: string;
  currency: string;
  contact: Contact;
  trip: Trip;
  method: "cash" | "card";
}

const key = (reference: string) => `mm-confirm-${reference}`;

export function saveConfirmationSnapshot(reference: string, snapshot: ConfirmationSnapshot): void {
  try {
    sessionStorage.setItem(key(reference), JSON.stringify(snapshot));
  } catch { /* storage full/blocked — the page falls back to the live status poll */ }
}

export function loadConfirmationSnapshot(reference: string): ConfirmationSnapshot | null {
  try {
    return JSON.parse(sessionStorage.getItem(key(reference)) ?? "null");
  } catch {
    return null;
  }
}
