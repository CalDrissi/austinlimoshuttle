"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { quoteService, quoteRequest } from "@/lib/api/quote.service";
import { catalogService } from "@/lib/api/catalog.service";
import { useBookingStore } from "@/lib/booking/store";
import { useAuth } from "@/hooks/useAuth";
import { VEHICLE_PLACEHOLDER } from "@/lib/fleet/images";
import ItineraryMap from "@/components/booking/ItineraryMap";
import AuthModal from "@/components/booking/AuthModal";
import type { QuoteResult, Vehicle } from "@/types/api";

/** Blacklane prints "US$ 167.94"; mirror that for USD. */
function money(amount: string, currency: string) {
  const prefix = currency === "USD" ? "US$ " : `${currency} `;
  return `${prefix}${Number(amount).toFixed(2)}`;
}

function PaxIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 3.6-6.5 8-6.5s8 2.5 8 6.5" />
    </svg>
  );
}
function BagIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="5" y="7" width="14" height="14" rx="2" /><path d="M9 7V5a3 3 0 0 1 6 0v2" />
    </svg>
  );
}
function PersonBadgeIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="12" r="9.2" /><circle cx="12" cy="9.5" r="3" /><path d="M6.4 19a6.8 6.8 0 0 1 11.2 0" />
    </svg>
  );
}
function ChevronDown({ up }: { up?: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
         style={up ? { transform: "rotate(180deg)" } : undefined}>
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}
function ChevronRight() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}
function TicketIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 9V7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v2a3 3 0 0 0 0 6v2a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-2a3 3 0 0 0 0-6z" />
      <path d="M13 5v2M13 11v2M13 17v2" strokeDasharray="0.1 3.4" />
    </svg>
  );
}
function CheckIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0f63bd" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="m4.5 12.5 5 5 10-11" />
    </svg>
  );
}

/** One class card: photo on a tinted ground, name + price, capacities. */
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
        <img
          src={vehicle?.photo || VEHICLE_PLACEHOLDER}
          alt={quote.vehicle_name}
          loading="lazy"
          onError={(e) => {
            const img = e.currentTarget;
            if (!img.src.endsWith(VEHICLE_PLACEHOLDER)) img.src = VEHICLE_PLACEHOLDER;
          }}
        />
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

/** Horizontal class row (live Blacklane is a slider, not a wrapping grid):
 *  fixed-width large cards, native snap scrolling, round prev/next buttons
 *  that appear only when the row actually overflows. */
function ClassRow({ children }: { children: React.ReactNode }) {
  const row = useRef<HTMLDivElement>(null);
  const [canPrev, setCanPrev] = useState(false);
  const [canNext, setCanNext] = useState(false);

  useEffect(() => {
    const el = row.current;
    if (!el) return;
    const update = () => {
      setCanPrev(el.scrollLeft > 4);
      setCanNext(el.scrollLeft + el.clientWidth < el.scrollWidth - 4);
    };
    update();
    el.addEventListener("scroll", update, { passive: true });
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => { el.removeEventListener("scroll", update); observer.disconnect(); };
  }, [children]);

  const page = (dir: 1 | -1) => {
    const el = row.current;
    if (!el) return;
    const card = el.querySelector<HTMLElement>(".blv-card");
    el.scrollBy({ left: dir * ((card?.offsetWidth ?? 420) + 16), behavior: "smooth" });
  };

  return (
    <div className="blv-rowwrap">
      <div className="blv-grid" ref={row}>{children}</div>
      {canPrev && (
        <button type="button" className="blv-nav blv-nav-prev" aria-label="Previous vehicles" onClick={() => page(-1)}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m15 6-6 6 6 6" /></svg>
        </button>
      )}
      {canNext && (
        <button type="button" className="blv-nav blv-nav-next" aria-label="More vehicles" onClick={() => page(1)}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6" /></svg>
        </button>
      )}
    </div>
  );
}

export default function BookingVehiclePage() {
  const router = useRouter();
  const { user } = useAuth();
  const search = useBookingStore((s) => s.search);
  const setQuote = useBookingStore((s) => s.setQuote);
  const selectedQuote = useBookingStore((s) => s.quote);
  const preselectedVehicleId = useBookingStore((s) => s.preselectedVehicleId);
  const setPreselectedVehicle = useBookingStore((s) => s.setPreselectedVehicle);
  const setTrip = useBookingStore((s) => s.setTrip);
  const [detailsOpen, setDetailsOpen] = useState(false);
  // Guest is the friction-free default; a signed-in user defaults to "myself".
  const [bookFor, setBookFor] = useState<"me" | "guest">("guest");
  useEffect(() => { if (user) setBookFor("me"); }, [user]);
  const [offerOpen, setOfferOpen] = useState(false);
  const [offerCode, setOfferCode] = useState("");
  const [offerMsg, setOfferMsg] = useState("");
  const [authModal, setAuthModal] = useState<"login" | "register" | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["quotes", search],
    enabled: !!search,
    retry: false,
    queryFn: () => quoteService.create(quoteRequest(search!)),
  });

  // Fleet-page pre-selection wins; otherwise the first class is selected on
  // load (matching Blacklane) so the rail is always populated.
  useEffect(() => {
    if (!data || data.quotes.length === 0) return;
    if (preselectedVehicleId != null) {
      const preferred = data.quotes.find((q) => q.vehicle_id === preselectedVehicleId);
      if (preferred) {
        setQuote(preferred);
        document.getElementById(`vehicle-${preferred.vehicle_id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      }
      setPreselectedVehicle(null);
      return;
    }
    const current = useBookingStore.getState().quote;
    if (!current || !data.quotes.some((q) => q.vehicle_id === current.vehicle_id)) {
      setQuote(data.quotes[0]);
    }
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
    <section className="blv">
      <div className="blv-page">
        {!search && (
          <>
            <h1 className="blv-title">Choose your experience</h1>
            <p className="text-16 color-grey">Start with a search from the <a href="/">home page</a>.</p>
          </>
        )}
        {search && isLoading && (
          <>
            <h1 className="blv-title">Choose your experience</h1>
            <p role="status" className="text-16 color-grey">Pricing vehicles for your journey…</p>
          </>
        )}
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
              <h1 className="blv-title">Choose your experience</h1>
              <ClassRow>
                {data.quotes.map((q) => (
                  <ClassCard
                    key={q.vehicle_id}
                    quote={q}
                    vehicle={byId.get(q.vehicle_id)}
                    selected={selectedQuote?.vehicle_id === q.vehicle_id}
                    onPick={setQuote}
                  />
                ))}
              </ClassRow>

              {selectedQuote && (
                <div className="blv-orsim-mobile">{selectedQuote.vehicle_name} or similar</div>
              )}

              {selVehicle && (
                <div className="blv-more">
                  <button type="button" className="blv-explore" aria-expanded={detailsOpen}
                          onClick={() => setDetailsOpen((open) => !open)}>
                    <ChevronDown up={detailsOpen} /> Explore {selVehicle.name} details
                  </button>
                  {detailsOpen && (
                    <div className="blv-details">
                      {selVehicle.description && <p className="blv-tagline">{selVehicle.description}</p>}
                      <div className="blv-details-caps">
                        <span><PaxIcon /> Up to {selVehicle.passenger_capacity || "–"} passengers</span>
                        <span><BagIcon /> Up to {selVehicle.luggage_capacity || "–"} bags</span>
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="blv-included">
                <h2 className="blv-h2">What&apos;s included</h2>
                <ul>
                  <li><CheckIcon /> Free cancellation up to 1 hour before pickup</li>
                  <li><CheckIcon /> 60 minutes of free wait time on airport pickups</li>
                  <li><CheckIcon /> All-inclusive fares — taxes and gratuity in the price</li>
                  <li><CheckIcon /> Licensed, insured professional chauffeur</li>
                  <li><CheckIcon /> Assistance with luggage at pickup and drop-off</li>
                </ul>
              </div>

              {/* Owner rule: no itemized price breakdown in the customer flow —
                  the all-inclusive total on the rail is the only price shown. */}
              <div className="blv-note">
                <p>Please note:</p>
                <ul>
                  <li>Passenger and luggage capacities are safety limits — if you are unsure, choose a larger class.</li>
                  <li>Vehicle photos are representative; you may be driven in a different vehicle of similar quality.</li>
                </ul>
              </div>
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

                    <div className="blv-bookers">
                      {user ? (
                        <>
                          <button type="button" className={`blv-booker${bookFor === "me" ? " on" : ""}`}
                                  onClick={() => { setBookFor("me"); setTrip({ forSomeoneElse: false }); }}>
                            <span className="blv-booker-icon"><PersonBadgeIcon /></span>
                            <span className="blv-booker-text">
                              <span className="blv-booker-title">Book for myself</span>
                              <span className="blv-booker-sub">{user.email || "Book with your account information"}</span>
                            </span>
                          </button>
                          <button type="button" className={`blv-booker${bookFor === "guest" ? " on" : ""}`}
                                  onClick={() => { setBookFor("guest"); setTrip({ forSomeoneElse: true }); }}>
                            <span className="blv-booker-icon"><PersonBadgeIcon /></span>
                            <span className="blv-booker-text">
                              <span className="blv-booker-title">Book for a guest</span>
                              <span className="blv-booker-sub">Select or add a guest</span>
                            </span>
                            <span className="blv-booker-chevron"><ChevronRight /></span>
                          </button>
                        </>
                      ) : (
                        <>
                          {/* Optional sign-in affordance — opens the in-flow
                              auth dialog and never gates the flow. */}
                          <button type="button" className="blv-booker" onClick={() => setAuthModal("login")}>
                            <span className="blv-booker-icon"><PersonBadgeIcon /></span>
                            <span className="blv-booker-text">
                              <span className="blv-booker-title">Book for myself</span>
                              <span className="blv-booker-sub">Sign in to book with your account information</span>
                            </span>
                            <span className="blv-booker-chevron"><ChevronRight /></span>
                          </button>
                          <div className="blv-register">
                            New here?{" "}
                            <button type="button" onClick={() => setAuthModal("register")}>Create an account</button>
                          </div>
                          <div className="blv-booker on" role="note">
                            <span className="blv-booker-icon"><PersonBadgeIcon /></span>
                            <span className="blv-booker-text">
                              <span className="blv-booker-title">Book for a guest</span>
                              <span className="blv-booker-sub">Continue with your contact details</span>
                            </span>
                          </div>
                        </>
                      )}
                    </div>

                    <hr className="blv-rail-hr" />
                    <div className="blv-offer-row">
                      <button type="button" className="blv-offer" aria-expanded={offerOpen}
                              onClick={() => { setOfferOpen((open) => !open); setOfferMsg(""); }}>
                        <TicketIcon /> Apply offer
                      </button>
                      <span className="blv-rail-note">All fees included</span>
                    </div>
                    {offerOpen && (
                      <div className="blv-offer-box">
                        <input
                          className="form-control"
                          placeholder="Offer code"
                          value={offerCode}
                          onChange={(e) => { setOfferCode(e.target.value); setOfferMsg(""); }}
                        />
                        <button type="button" className="blv-offer-apply"
                                onClick={() => setOfferMsg(offerCode.trim() ? "This code is not valid." : "Enter an offer code.")}>
                          Apply
                        </button>
                        {offerMsg && <p className="blv-offer-err" role="alert">{offerMsg}</p>}
                      </div>
                    )}
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
            Select {selectedQuote.vehicle_name}
          </button>
        </div>
      )}

      <AuthModal open={authModal !== null} initialTab={authModal ?? "login"} onClose={() => setAuthModal(null)} />
    </section>
  );
}
