"use client";

import { useBookingStore } from "@/lib/booking/store";
import ItineraryMap from "./ItineraryMap";
import type { Journey } from "@/types/api";

function money(amount: string, currency: string) {
  const symbol = currency === "USD" ? "$" : `${currency} `;
  return `${symbol}${Number(amount).toFixed(2)}`;
}

/** The "Ride Summary" sidebar from the template's booking pages (.box-tab-right). */
export default function OrderSummary({ journey }: { journey?: Journey | null }) {
  const search = useBookingStore((s) => s.search);
  const quote = useBookingStore((s) => s.quote);
  if (!search) return null;

  return (
    <div className="box-tab-right">
      <div className="sidebar">
        <div className="d-flex align-items-center justify-content-between">
          <h6 className="text-20-medium color-text">Ride Summary</h6>
          <a className="text-14-medium color-text text-decoration-underline" href="/">Edit</a>
        </div>
        <div className="mt-20">
          <ul className="mm-summary-routes" aria-label="Itinerary">
            <li><span className="location-item">A</span><span className="info-location text-14-medium">{search.pickupAddress}</span></li>
            {(search.tripType === "transfer" || search.tripType === "city") && (
              <li><span className="location-item">B</span><span className="info-location text-14-medium">{search.dropoffAddress}</span></li>
            )}
          </ul>
        </div>
        <ItineraryMap search={search} />
        <div className="mt-20">
          <ul className="list-icons">
            {search.tripType === "hourly" && (
              <li><span className="icon-item icon-time" /><span className="info-location text-14-medium">By the hour · {search.hours} hour{search.hours === 1 ? "" : "s"}</span></li>
            )}
            <li><span className="icon-item icon-plan" /><span className="info-location text-14-medium">{search.date}</span></li>
            <li><span className="icon-item icon-time" /><span className="info-location text-14-medium">{search.time}</span></li>
            {search.meetGreet && (
              <li><span className="icon-item icon-plan" /><span className="info-location text-14-medium">Meet &amp; Greet</span></li>
            )}
          </ul>
        </div>
        {journey && (
          <div className="mt-20">
            <div className="box-info-route">
              <div className="info-route-left"><span className="text-14 color-grey">Total Distance</span><span className="text-14-medium color-text">{Number(journey.distance_miles).toFixed(1)} miles</span></div>
              <div className="info-route-left"><span className="text-14 color-grey">Total Time</span><span className="text-14-medium color-text">{journey.duration_minutes} min</span></div>
            </div>
          </div>
        )}
        {quote && (
          <div className="mt-20">
            <div className="box-info-route">
              <div className="info-route-left"><span className="text-14 color-grey">{quote.vehicle_name}</span><span className="text-14-medium color-text">{money(quote.total, quote.currency)}</span></div>
            </div>
          </div>
        )}
      </div>
      <div className="sidebar">
        <ul className="list-ticks list-ticks-small list-ticks-small-booking">
          <li className="text-14 mb-20">Instant confirmation</li>
          <li className="text-14 mb-20">All-inclusive pricing</li>
          <li className="text-14 mb-20">Free cancellation up to 1 hour before pickup</li>
          <li className="text-14 mb-20">Pay by card or cash to the driver</li>
        </ul>
      </div>
    </div>
  );
}
