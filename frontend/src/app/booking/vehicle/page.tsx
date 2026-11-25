"use client";

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { quoteService, quoteRequest } from "@/lib/api/quote.service";
import { catalogService } from "@/lib/api/catalog.service";
import { useBookingStore } from "@/lib/booking/store";
import { VEHICLE_PLACEHOLDER } from "@/lib/fleet/images";
import OrderSummary from "@/components/booking/OrderSummary";
import type { QuoteResult, Vehicle } from "@/types/api";

function money(amount: string, currency: string) {
  const symbol = currency === "USD" ? "$" : `${currency} `;
  return `${symbol}${Number(amount).toFixed(2)}`;
}

function PaxIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5" />
    </svg>
  );
}
function BagIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="5" y="7" width="14" height="14" rx="2" /><path d="M9 7V5a3 3 0 0 1 6 0v2" />
    </svg>
  );
}

function VehicleCard({ quote, vehicle, meetGreet, selected, onSelect }: {
  quote: QuoteResult;
  vehicle?: Vehicle;
  meetGreet: boolean;
  selected: boolean;
  onSelect: (q: QuoteResult) => void;
}) {
  return (
    <div id={`vehicle-${quote.vehicle_id}`} className={`blf-car${selected ? " on" : ""}`}>
      <div className="blf-car-media">
        <img src={vehicle?.photo || VEHICLE_PLACEHOLDER} alt={quote.vehicle_name} />
      </div>
      <div className="blf-car-body">
        <h5 className="blf-car-name">{quote.vehicle_name}</h5>
        <div className="blf-car-caps">
          <span><PaxIcon /> {vehicle?.passenger_capacity ?? "–"}</span>
          <span><BagIcon /> {vehicle?.luggage_capacity ?? "–"}</span>
        </div>
        {vehicle?.description && <p className="blf-car-desc">{vehicle.description}</p>}
        <p className="blf-car-perks">
          {meetGreet && <span>Meet &amp; Greet included</span>}
          <span>Free cancellation</span>
          <span>Free waiting time</span>
        </p>
        {selected && <p role="status" className="blf-car-chosen">Selected for your trip — you can still choose any car below.</p>}
      </div>
      <div className="blf-car-side">
        <div className="blf-car-price">{money(quote.total, quote.currency)}</div>
        <div className="blf-car-incl">All-inclusive — taxes &amp; fees included</div>
        <button className="blf-btn" onClick={() => onSelect(quote)}>{selected ? "Continue" : "Select"}</button>
      </div>
    </div>
  );
}

/** Compact trip recap above the vehicle list, with an edit link back home. */
function TripStrip({ journey }: { journey?: { distance_miles: string; duration_minutes: number } | null }) {
  const search = useBookingStore((s) => s.search);
  if (!search) return null;
  const date = (() => {
    const m = search.date.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return search.date;
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
      .toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  })();
  return (
    <div className="blf-strip">
      <div className="blf-strip-info">
        <div className="blf-strip-route">
          <span>{search.pickupAddress}</span>
          {search.tripType === "hourly"
            ? <em>· {search.hours} hours at your disposal</em>
            : <><span className="blf-strip-arrow" aria-hidden="true">→</span><span>{search.dropoffAddress}</span></>}
        </div>
        <div className="blf-strip-meta">
          {date} at {search.time}
          {journey && <> · {Number(journey.distance_miles).toFixed(1)} mi · {journey.duration_minutes} min</>}
        </div>
      </div>
      <a className="blf-strip-edit" href="/">Edit</a>
    </div>
  );
}

export default function BookingVehiclePage() {
  const router = useRouter();
  const search = useBookingStore((s) => s.search);
  const setQuote = useBookingStore((s) => s.setQuote);
  const selectedQuote = useBookingStore((s) => s.quote);
  const preselectedVehicleId = useBookingStore((s) => s.preselectedVehicleId);
  const setPreselectedVehicle = useBookingStore((s) => s.setPreselectedVehicle);


  const { data, isLoading, error } = useQuery({
    queryKey: ["quotes", search],
    enabled: !!search,
    retry: false,
    queryFn: () => quoteService.create(quoteRequest(search!)),
  });

  useEffect(() => {
    if (!data || preselectedVehicleId == null) return;
    const preferred = data.quotes.find((q) => q.vehicle_id === preselectedVehicleId);
    if (preferred) {
      setQuote(preferred);
      document.getElementById(`vehicle-${preferred.vehicle_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    setPreselectedVehicle(null);
  }, [data, preselectedVehicleId, setQuote, setPreselectedVehicle]);

  const setJourney = useBookingStore((s) => s.setJourney);
  useEffect(() => { if (data) setJourney(data.journey); }, [data, setJourney]);

  const { data: vehicles } = useQuery({
    queryKey: ["vehicles"],
    queryFn: () => catalogService.listVehicles(),
    // Catalog is cheap and must reflect a back-office photo/capacity change
    // promptly, so always revalidate rather than serving the 60s global cache.
    staleTime: 0,
  });
  const byId = new Map((vehicles ?? []).map((v) => [v.id, v]));

  const handleSelect = (quote: QuoteResult) => {
    setQuote(quote);
    router.push("/booking/extra");
  };

  return (
    <section className="section">
      <div className="container-sub">
        <div className="box-row-tab mt-50">
          <div className="box-tab-left">
            <div className="box-content-detail">
              <h3 className="heading-24-medium color-text mb-20">Choose your experience</h3>
              {search && <TripStrip journey={data?.journey} />}

              {!search && (
                <p className="text-16 color-grey">Start with a search from the <a href="/">home page</a>.</p>
              )}
              {search && isLoading && <p role="status" className="text-16 color-grey">Pricing vehicles for your journey…</p>}
              {error && (
                <p className="text-16" style={{ color: "#c0392b" }}>
                  We couldn't price that trip — check your addresses. <a href="/">Edit your search</a>
                </p>
              )}

              {data && data.quotes.length === 0 && <p role="status" className="mm-feedback">No vehicles fit this trip. <a href="/">Try different addresses or a different time</a>.</p>}
              <div className="list-vehicles">
                {data?.quotes.map((q) => (
                  <VehicleCard
                    key={q.vehicle_id}
                    quote={q}
                    vehicle={byId.get(q.vehicle_id)}
                    selected={selectedQuote?.vehicle_id === q.vehicle_id}
                    meetGreet={!!search?.meetGreet}
                    onSelect={handleSelect}
                  />
                ))}
              </div>
            </div>
          </div>
          <OrderSummary journey={data?.journey} />
        </div>
      </div>
    </section>
  );
}
