"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { useSiteSettings } from "@/hooks/useSiteSettings";
import { telHref } from "@/lib/api/site.service";
import { useBookingStore, useHydrated } from "@/lib/booking/store";
import { loadConfirmationSnapshot, type ConfirmationSnapshot } from "@/lib/booking/confirmation";
import { bookingService } from "@/lib/api/booking.service";
import { API_BASE_URL } from "@/lib/api/config";
import { money, formatDate, formatTime } from "@/lib/format";

// Ported from the template's booking-receved.html (box-completed-booking →
// box-info-book-border tiles → box-booking-border list-prices), wired to the
// real booking: reference, polled status, and the trip snapshot. The snapshot
// is persisted per-reference in sessionStorage at payment time, so a refresh
// here (after the draft store is cleared) still shows the full confirmation.
export default function BookingConfirmationPage() {
  const { user, isLoading } = useAuth();
  const site = useSiteSettings();
  const hydrated = useHydrated();
  const reference = useBookingStore((s) => s.reference);

  const [snap, setSnap] = useState<ConfirmationSnapshot | null>(null);
  useEffect(() => {
    if (!hydrated || !reference) return;
    // Prefer the persisted snapshot; fall back to whatever draft remains
    // (first arrival in an exotic path), then clear the draft — the funnel is
    // over and its state must not leak into the next booking.
    const stored = loadConfirmationSnapshot(reference);
    if (stored) setSnap(stored);
    else {
      const st = useBookingStore.getState();
      setSnap({
        search: st.search, contact: st.contact, trip: st.trip,
        vehicleName: st.quote?.vehicle_name ?? "", total: st.quote?.total ?? "",
        currency: st.quote?.currency ?? "USD", method: "cash",
      });
    }
    useBookingStore.getState().clearDraft();
  }, [hydrated, reference]);

  const { data: status } = useQuery({
    queryKey: ["booking-status", reference],
    enabled: !!reference,
    queryFn: () => bookingService.status(reference!),
    refetchInterval: (q) =>
      q.state.data && q.state.data.status !== "pending" ? false : 4000,
  });

  // Wait for the persisted store — rendering "No booking found" before
  // hydration would flash it at every refresh of a real confirmation.
  if (!hydrated) return null;

  if (!reference) {
    return (
      <section className="section">
        <div className="container-sub">
          <div className="box-completed-booking">
            <div className="text-center">
              <h4 className="heading-24-medium color-text mb-10">There&rsquo;s no booking in progress</h4>
              <p className="text-14 color-grey mb-40">
                Looking for a ride you already booked? It&rsquo;s saved in your account.
                Otherwise, start a new quote from the home page — it takes under a minute.
              </p>
              <Link className="btn btn-primary hover-up mr-10" href="/">Get a quote</Link>
              <Link className="btn btn-border hover-up" href="/account?tab=bookings">My bookings</Link>
            </div>
          </div>
        </div>
      </section>
    );
  }

  const currency = status?.currency ?? snap?.currency ?? "USD";
  const total = status?.total ?? (snap?.total || undefined);
  const confirmed = !!status && status.status !== "pending";
  const passengerName = snap?.trip.forSomeoneElse && snap.trip.passengerName
    ? snap.trip.passengerName
    : "";

  return (
    <section className="section">
      <div className="container-sub">
        <div className="box-completed-booking">
          <div className="text-center">
            {/* Flow-blue success badge (the template PNG was its orange brand). */}
            <svg className="mb-20" width="72" height="72" viewBox="0 0 72 72" role="img" aria-label="Booking received">
              <circle cx="36" cy="36" r="36" fill="#0f63bd" />
              <path d="m22 37 10 10 18-21" fill="none" stroke="#fff" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <h4 className="heading-24-medium color-text mb-10">Your booking was submitted successfully!</h4>
            <p className="text-14 color-grey mb-20">
              {snap?.contact.email
                ? `A confirmation email is on its way to ${snap.contact.email}.`
                : "A confirmation email is on its way."}
            </p>
            <p role="status" className="text-14 mb-40">
              {confirmed
                ? <>Status: <b>{status.status_display}</b> — you&rsquo;re all set.</>
                : <>Status: <b>Processing</b> — we&rsquo;re confirming your ride, this takes a
                    moment. This page updates automatically.</>}
            </p>
          </div>

          {!isLoading && !user && <div className="mm-feedback mb-20"><p>Create an account to track this ride</p><Link className="btn btn-primary" href={`/register?email=${encodeURIComponent(snap?.contact.email || "")}&next=${encodeURIComponent("/account?tab=bookings")}`}>Create an account</Link></div>}
          {user && <p className="text-center mb-20"><Link href="/account?tab=bookings">View My bookings</Link></p>}
          <div className="box-info-book-border">
            <div className="info-1"><span className="color-text text-14">Order Number</span><br /><span className="color-text text-14-medium">#{reference}</span></div>
            {snap?.search && <div className="info-1"><span className="color-text text-14">Date</span><br /><span className="color-text text-14-medium">{formatDate(snap.search.date)}</span></div>}
            {total && <div className="info-1"><span className="color-text text-14">Total</span><br /><span className="color-text text-14-medium">{money(total, currency)}</span></div>}
            <div className="info-1"><span className="color-text text-14">Payment</span><br /><span className="color-text text-14-medium">{snap?.method === "card" ? "Paid by card" : "Cash — pay your chauffeur at pickup"}</span></div>
          </div>

          <div className="box-booking-border">
            <h6 className="heading-20-medium color-text">What happens next</h6>
            <ul className="list-prices">
              <li><span className="text-top">Right now</span><span className="text-bottom">Our office reviews your booking and emails your confirmation.</span></li>
              <li><span className="text-top">Before pickup</span><span className="text-bottom">You&rsquo;ll receive your chauffeur&rsquo;s details ahead of your ride.</span></li>
              <li><span className="text-top">Questions or changes</span><span className="text-bottom">
                {site?.contact_phone
                  ? <>Call us any time at <a href={telHref(site.contact_phone)}>{site.contact_phone}</a>{site.contact_email ? <> or email <a href={`mailto:${site.contact_email}`}>{site.contact_email}</a></> : null}.</>
                  : "Contact our office — details are in your confirmation email."}
              </span></li>
            </ul>
          </div>

          {snap?.search && (
            <div className="box-booking-border">
              <h6 className="heading-20-medium color-text">Reservation Information</h6>
              <ul className="list-prices">
                <li><span className="text-top">Pick Up Address</span><span className="text-bottom">{snap.search.pickupAddress}</span></li>
                {snap.search.tripType === "hourly" ? (
                  <li><span className="text-top">Booking type</span><span className="text-bottom">By the hour · {snap.search.hours} hour{snap.search.hours === 1 ? "" : "s"}</span></li>
                ) : (
                  <>
                    <li><span className="text-top">Drop Off Address</span><span className="text-bottom">{snap.search.dropoffAddress}</span></li>
                    {snap.search.tripType === "city" && <li><span className="text-top">Booking type</span><span className="text-bottom">City-to-city</span></li>}
                  </>
                )}
                <li><span className="text-top">Pick Up Date</span><span className="text-bottom">{formatDate(snap.search.date)}</span></li>
                <li><span className="text-top">Pick Up Time</span><span className="text-bottom">{formatTime(snap.search.time)}</span></li>
                {snap.search.meetGreet && <li><span className="text-top">Meet &amp; Greet</span><span className="text-bottom">Included</span></li>}
              </ul>
            </div>
          )}

          <div className="box-booking-border">
            <h6 className="heading-20-medium color-text">Selected Car</h6>
            <ul className="list-prices">
              <li><span className="text-top">Class</span><span className="text-bottom">{status?.vehicle_name ?? snap?.vehicleName ?? "-"}</span></li>
              {total && <li><span className="text-top">Fare</span><span className="text-bottom">{money(total, currency)}</span></li>}
            </ul>
          </div>

          {snap?.contact.name && (
            <div className="box-booking-border">
              <h6 className="heading-20-medium color-text">{passengerName ? "Booked by" : "Passenger Information"}</h6>
              <ul className="list-prices">
                <li><span className="text-top">Name</span><span className="text-bottom">{snap.contact.name}</span></li>
                {snap.contact.email && <li><span className="text-top">Email</span><span className="text-bottom">{snap.contact.email}</span></li>}
              </ul>
            </div>
          )}

          {passengerName && (
            <div className="box-booking-border">
              <h6 className="heading-20-medium color-text">Who&rsquo;s travelling</h6>
              <ul className="list-prices">
                <li><span className="text-top">Passenger</span><span className="text-bottom">{passengerName}</span></li>
                {snap?.trip.passengerPhone && <li><span className="text-top">Passenger phone</span><span className="text-bottom">{snap.trip.passengerPhone}</span></li>}
              </ul>
            </div>
          )}

          <div className="text-center mt-40">
            <a className="btn btn-primary hover-up mr-10" href={`${API_BASE_URL}/bookings/${reference}/receipt/`} target="_blank" rel="noopener noreferrer">
              Download receipt (PDF)
            </a>
            <Link className="btn btn-border hover-up" href="/">Back to Home</Link>
          </div>
        </div>
      </div>
    </section>
  );
}
