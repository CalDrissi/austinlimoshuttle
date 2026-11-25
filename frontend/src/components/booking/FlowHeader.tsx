"use client";

import Link from "next/link";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { authService } from "@/lib/api/auth.service";
import { notify } from "@/lib/feedback";
import { useAuth } from "@/hooks/useAuth";
import { useSiteSettings } from "@/hooks/useSiteSettings";
import { telHref } from "@/lib/api/site.service";
import { useBookingStore, useHydrated } from "@/lib/booking/store";
import { formatTime } from "@/lib/format";
import TripEditor from "@/components/booking/TripEditor";

/** "Austin-Bergstrom International Airport (AUS), Presidential Blvd…" -> "Austin-Bergstrom International Airport (AUS)" */
function shortAddress(value: string): string {
  return value.split(",")[0].trim();
}

/** "YYYY-MM-DD" -> "Sat, November 28" without the UTC shift of new Date(string). */
function pillDate(value: string): string {
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return value;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
    .toLocaleDateString("en-US", { weekday: "short", month: "long", day: "numeric" });
}

function ArrowIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

/** Blacklane-style booking-flow header: logo left, trip-summary pills centred,
 *  hamburger menu right. Clicking a pill edits the trip in place — an overlay
 *  with the same TripEditor the Ride Summary uses, never a trip back home. */
export default function FlowHeader() {
  const search = useBookingStore((s) => s.search);
  const hydrated = useHydrated();
  const { user, isLoading: authLoading } = useAuth();
  const site = useSiteSettings();
  const qc = useQueryClient();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const editPanelRef = useRef<HTMLDivElement>(null);

  // Signing in anywhere in the flow replaces the booker identity: the booking
  // belongs to the account, so any guest contact typed earlier must not survive.
  // Keyed by email so a re-render or profile refetch doesn't clobber edits.
  useEffect(() => {
    if (!hydrated || authLoading) return; // never act on the pre-fetch null
    const store = useBookingStore.getState();
    if (user) store.adoptAccountIdentity(user);
    else store.clearAccountIdentity();
  }, [user, authLoading, hydrated]);

  useEffect(() => { setMenuOpen(false); }, [pathname]);

  // Trip-editor overlay: Esc closes, focus starts inside.
  useEffect(() => {
    if (!editing) return;
    editPanelRef.current?.querySelector<HTMLElement>("input, select, button")?.focus();
    const keydown = (e: KeyboardEvent) => { if (e.key === "Escape") setEditing(false); };
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  }, [editing]);
  useEffect(() => {
    const outside = (e: PointerEvent) => {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, []);

  const logout = async () => {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await authService.logout();
      qc.setQueryData(["me"], null);
      qc.removeQueries({ queryKey: ["my-bookings"] });
      qc.removeQueries({ queryKey: ["my-cards"] });
      notify("You've been signed out");
    } catch { notify("Could not sign out — please try again."); }
    finally { setSigningOut(false); setMenuOpen(false); }
  };

  return (
    <header className="fh">
      <div className="fh-row">
        <Link href="/" className="fh-logo" aria-label="M&M Austin Limousine home">
          <Image src="/assets/imgs/template/mm-logo.png" alt="M&M Austin Limousine" width={118} height={52} priority />
        </Link>

        {hydrated && search && (
          <div className="fh-pills">
            <button type="button" className="fh-pill" title="Edit your trip" onClick={() => setEditing(true)}>
              <b>{shortAddress(search.pickupAddress)}</b>
              {search.tripType === "hourly" ? (
                <em>{search.hours} hours</em>
              ) : (
                <>
                  <span className="fh-pill-icon"><ArrowIcon /></span>
                  <b>{shortAddress(search.dropoffAddress)}</b>
                </>
              )}
            </button>
            <button type="button" className="fh-pill fh-pill-when" title="Edit your trip" onClick={() => setEditing(true)}>
              <span className="fh-seg">{pillDate(search.date)}</span>
              <span className="fh-seg">
                <span className="fh-pill-icon"><ArrowIcon /></span>
                {formatTime(search.time)}
              </span>
            </button>
          </div>
        )}

        <div className="fh-menu" ref={menuRef}>
          <button
            type="button"
            className="fh-burger"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
            aria-controls="fh-menu-links"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              {menuOpen ? <path d="m6 6 12 12M6 18 18 6" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
            </svg>
          </button>
          {menuOpen && (
            <div id="fh-menu-links" className="fh-menu-panel">
              <Link href="/" onClick={() => setMenuOpen(false)}>Home</Link>
              <Link href="/fleet" onClick={() => setMenuOpen(false)}>Our fleet</Link>
              <hr />
              {user ? (
                <>
                  <Link href="/account" onClick={() => setMenuOpen(false)}>My account</Link>
                  <Link href="/account?tab=bookings" onClick={() => setMenuOpen(false)}>My bookings</Link>
                  <button onClick={logout} disabled={signingOut}>{signingOut ? "Signing out…" : "Sign out"}</button>
                </>
              ) : (
                <Link href="/login" onClick={() => setMenuOpen(false)}>Sign in</Link>
              )}
              {site?.contact_phone && (
                <>
                  <hr />
                  <a href={telHref(site.contact_phone)}>Call us · {site.contact_phone}</a>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* In-place trip edit: same editor + reprice path as the Ride Summary
          (applyRequote), shown as an overlay so the current step is kept. */}
      {editing && search && (
        <div className="mm-auth-layer" role="presentation">
          <div className="mm-auth-backdrop" onClick={() => setEditing(false)} aria-hidden="true" />
          <div ref={editPanelRef} className="mm-auth-panel" role="dialog" aria-modal="true" aria-label="Edit your trip">
            <TripEditor search={search} onClose={() => setEditing(false)} />
          </div>
        </div>
      )}
    </header>
  );
}
