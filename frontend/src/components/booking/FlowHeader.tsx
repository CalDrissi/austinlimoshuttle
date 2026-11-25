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
function PlaneIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z" />
    </svg>
  );
}

/** Blacklane-style booking-flow header: logo left, trip-summary pills centred,
 *  hamburger menu right. The pills are read-only — clicking returns home to edit. */
export default function FlowHeader() {
  const search = useBookingStore((s) => s.search);
  const flight = useBookingStore((s) => s.trip.flightNumber);
  const hydrated = useHydrated();
  const { user } = useAuth();
  const site = useSiteSettings();
  const qc = useQueryClient();
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setMenuOpen(false); }, [pathname]);
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
            <Link href="/" className="fh-pill" title="Edit your trip">
              <b>{shortAddress(search.pickupAddress)}</b>
              {search.tripType === "hourly" ? (
                <em>{search.hours} hours</em>
              ) : (
                <>
                  <span className="fh-pill-icon"><ArrowIcon /></span>
                  <b>{shortAddress(search.dropoffAddress)}</b>
                </>
              )}
            </Link>
            <Link href="/" className="fh-pill fh-pill-when" title="Edit your trip">
              <span className="fh-seg">{pillDate(search.date)}</span>
              {search.tripType !== "hourly" && (
                <span className="fh-seg">
                  <span className="fh-pill-icon"><PlaneIcon /></span>
                  {flight ? flight : <em>Add flight no.</em>}
                </span>
              )}
              <span className="fh-seg">
                <span className="fh-pill-icon"><ArrowIcon /></span>
                {search.time}
              </span>
            </Link>
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
    </header>
  );
}
