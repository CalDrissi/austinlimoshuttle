"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { quoteService, quoteRequest } from "@/lib/api/quote.service";
import { catalogService } from "@/lib/api/catalog.service";
import { useBookingStore } from "@/lib/booking/store";
import { VEHICLE_PLACEHOLDER } from "@/lib/fleet/images";
import ItineraryMap from "@/components/booking/ItineraryMap";
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

/** One class card: photo on a tinted ground, name + price, capacities.
 *  Clicking selects the class (the rail / sticky bar continues the flow). */
function ClassCard({ quote, vehicle, selected, onPick }: {
  quote: QuoteResult;
  vehicle?: Vehicle;
  selected: boolean;
  onPick: (q: QuoteResult) => void;
}) {
  return (
    <button
      type="button"
      id={`vehicle-${quote.vehicle_id}`}
      className={`blv-card${selected ? " on" : ""}`}
      aria-pressed={selected}
      onClick={() => onPick(quote)}
    >
      <span className="blv-card-media">
        <img src={vehicle?.photo || VEHICLE_PLACEHOLDER} alt={quote.vehicle_name} loading="lazy" />
      </span>
      <span className="blv-card-row">
        <span className="blv-card-name">{quote.vehicle_name}</span>
        <span className="blv-card-price">{money(quote.total, quote.currency)}</span>
      </span>
      <span className="blv-card-caps">
        <span><PaxIcon /> {vehicle?.passenger_capacity ?? "–"}</span>
        <span><BagIcon /> {vehicle?.luggage_capacity ?? "–"}</span>
      </span>
    </button>
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

  // Fleet-page pre-selection: highlight the embedded vehicle and fill the rail.
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

  const selVehicle = selectedQuote ? byId.get(selectedQuote.vehicle_id) : undefined;

  const handleContinue = () => {
    if (selectedQuote) router.push("/booking/extra");
  };

  return (
    <section className="section blv">
      <div className="container-sub">
        <h3 className="blv-title">Choose your experience</h3>

        {!search && (
          <p className="text-16 color-grey">Start with a search from the <a href="/">home page</a>.</p>
        )}
        {search && isLoading && <p role="status" className="text-16 color-grey">Pricing vehicles for your journey…</p>}
        {error && (
          <p className="text-16" style={{ color: "#b02032" }}>
            We couldn&apos;t price that trip — check your addresses. <a href="/">Edit your search</a>
          </p>
        )}
        {data && data.quotes.length === 0 && (
          <p role="status" className="mm-feedback">No vehicles fit this trip. <a href="/">Try different addresses or a different time</a>.</p>
        )}

        {data && data.quotes.length > 0 && (
          <div className="blv-layout">
            <div className="blv-main">
              <div className="blv-grid">
                {data.quotes.map((q) => (
                  <ClassCard
                    key={q.vehicle_id}
                    quote={q}
                    vehicle={byId.get(q.vehicle_id)}
                    selected={selectedQuote?.vehicle_id === q.vehicle_id}
                    onPick={setQuote}
                  />
                ))}
              </div>

              {selVehicle && (
                <div className="blv-more">
                  <Link className="blv-explore" href={`/fleet/${selVehicle.slug}`}>
                    Explore {selVehicle.name} details
                  </Link>
                  {selVehicle.description && <p className="blv-desc">{selVehicle.description}</p>}
                </div>
              )}
            </div>

            <aside className="blv-rail" aria-label="Your selection">
              {search && <div className="blv-rail-map"><ItineraryMap search={search} /></div>}
              <div className="blv-railcard">
                {selectedQuote ? (
                  <>
                    <div className="blv-rail-row">
                      <span className="blv-rail-name">{selectedQuote.vehicle_name}</span>
                      <span className="blv-rail-price">{money(selectedQuote.total, selectedQuote.currency)}</span>
                    </div>
                    <div className="blv-rail-sub">{selectedQuote.vehicle_name} or similar</div>
                    <hr className="blv-rail-hr" />
                    <div className="blv-rail-note">All fees included — taxes &amp; gratuity in the price.</div>
                    <button className="blv-cta" type="button" onClick={handleContinue}>
                      Select {selectedQuote.vehicle_name}
                    </button>
                  </>
                ) : (
                  <div className="blv-rail-empty">Choose a vehicle class to continue.</div>
                )}
              </div>
            </aside>
          </div>
        )}
      </div>

      {/* Phones: the rail collapses into a sticky bottom bar with the CTA. */}
      {selectedQuote && (
        <div className="blv-sticky">
          <button className="blv-cta" type="button" onClick={handleContinue}>
            Select {selectedQuote.vehicle_name} · {money(selectedQuote.total, selectedQuote.currency)}
          </button>
        </div>
      )}
    </section>
  );
}
