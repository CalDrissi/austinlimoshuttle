"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { useBookingStore } from "@/lib/booking/store";
import { bookingService } from "@/lib/api/booking.service";
import { API_BASE_URL } from "@/lib/api/config";

function money(amount: string, currency: string) {
  const symbol = currency === "USD" ? "$" : `${currency} `;
  return `${symbol}${Number(amount).toFixed(2)}`;
}

// Ported from the template's booking-receved.html (box-completed-booking →
// box-info-book-border tiles → box-booking-border list-prices), wired to the
// real booking: reference, polled status, and the trip snapshot.
export default function BookingConfirmationPage() {
  const { user, isLoading } = useAuth();
  const reference = useBookingStore((s) => s.reference);
  const clearDraft = useBookingStore((s) => s.clearDraft);

  const [snap] = useState(() => {
    const st = useBookingStore.getState();
    return { search: st.search, quote: st.quote, contact: st.contact };
  });

  const { data: status } = useQuery({
    queryKey: ["booking-status", reference],
    enabled: !!reference,
    queryFn: () => bookingService.status(reference!),
    refetchInterval: (q) =>
      q.state.data && q.state.data.status !== "pending" ? false : 4000,
  });

  useEffect(() => {
    if (reference) clearDraft();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const currency = status?.currency ?? snap.quote?.currency ?? "USD";
  const total = status?.total ?? snap.quote?.total;

  if (!reference) {
    return (
      <section className="section">
        <div className="container-sub">
          <div className="box-completed-booking">
            <div className="text-center">
              <h4 className="heading-24-medium color-text mb-10">No booking found</h4>
              <p className="text-14 color-grey mb-40">Start a new booking from the home page.</p>
              <Link className="btn btn-primary hover-up" href="/">Back to Home</Link>
            </div>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="section">
      <div className="container-sub">
        <div className="box-completed-booking">
          <div className="text-center">
            <img className="mb-20" src="/assets/imgs/page/booking/completed.png" alt="Booking received" />
            <h4 className="heading-24-medium color-text mb-10">Your booking was submitted successfully!</h4>
            <p className="text-14 color-grey mb-40">
              {snap.contact.email
                ? `A confirmation email is on its way to ${snap.contact.email}.`
                : "A confirmation email is on its way."}
            </p>
          </div>

          {!isLoading && !user && <div className="mm-feedback mb-20"><p>Create an account to track this ride</p><Link className="btn btn-primary" href={`/register?email=${encodeURIComponent(snap.contact.email || "")}&next=${encodeURIComponent("/account?tab=bookings")}`}>Create an account</Link></div>}
          {user && <p className="text-center mb-20"><Link href="/account?tab=bookings">View My bookings</Link></p>}
          <div className="box-info-book-border">
            <div className="info-1"><span className="color-text text-14">Order Number</span><br /><span className="color-text text-14-medium">#{reference}</span></div>
            <div className="info-1"><span className="color-text text-14">Date</span><br /><span className="color-text text-14-medium">{snap.search?.date ?? "-"}</span></div>
            {total && <div className="info-1"><span className="color-text text-14">Total</span><br /><span className="color-text text-14-medium">{money(total, currency)}</span></div>}
            <div className="info-1"><span className="color-text text-14">Status</span><br /><span className="color-text text-14-medium">{status?.status_display ?? "Processing"}</span></div>
          </div>

          {snap.search && (
            <div className="box-booking-border">
              <h6 className="heading-20-medium color-text">Reservation Information</h6>
              <ul className="list-prices">
                <li><span className="text-top">Pick Up Address</span><span className="text-bottom">{snap.search.pickupAddress}</span></li>
                {snap.search.tripType === "hourly" ? (
                  <li><span className="text-top">Booking type</span><span className="text-bottom">By the hour · {snap.search.hours} hour{snap.search.hours === 1 ? "" : "s"}</span></li>
                ) : (
                  <li><span className="text-top">Drop Off Address</span><span className="text-bottom">{snap.search.dropoffAddress}</span></li>
                )}
                <li><span className="text-top">Pick Up Date</span><span className="text-bottom">{snap.search.date}</span></li>
                <li><span className="text-top">Pick Up Time</span><span className="text-bottom">{snap.search.time}</span></li>
                {snap.search.meetGreet && <li><span className="text-top">Meet &amp; Greet</span><span className="text-bottom">Included</span></li>}
              </ul>
            </div>
          )}

          <div className="box-booking-border">
            <h6 className="heading-20-medium color-text">Selected Car</h6>
            <ul className="list-prices">
              <li><span className="text-top">Class</span><span className="text-bottom">{status?.vehicle_name ?? snap.quote?.vehicle_name ?? "-"}</span></li>
              {total && <li><span className="text-top">Fare</span><span className="text-bottom">{money(total, currency)}</span></li>}
            </ul>
          </div>

          {snap.contact.name && (
            <div className="box-booking-border">
              <h6 className="heading-20-medium color-text">Passenger Information</h6>
              <ul className="list-prices">
                <li><span className="text-top">Name</span><span className="text-bottom">{snap.contact.name}</span></li>
                {snap.contact.email && <li><span className="text-top">Email</span><span className="text-bottom">{snap.contact.email}</span></li>}
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
