"use client";

/**
 * The ONE booking-flow rail (owner blueprint 2026-11-25). Every step mounts
 * this same component: map card → trip facts → vehicle + all-inclusive total
 * → Edit trip → the step's CTA → (step 1 only) the booker block.
 *
 * Desktop: sticky right rail. Phones (<992px): the rail collapses — steps 2–4
 * get a collapsible trip-summary strip at the top instead, step 1 keeps the
 * full rail (map + interpreted addresses + bookers) inline — and every step
 * gets the same sticky bottom bar: total + step CTA.
 */

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useBookingStore } from "@/lib/booking/store";
import { catalogService } from "@/lib/api/catalog.service";
import { money, formatDate, formatTime, tripTypeLabel, materiallyDiffers } from "@/lib/format";
import ItineraryMap from "./ItineraryMap";
import TripEditorOverlay from "./TripEditorOverlay";

export interface FlowCta {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
}

function ChevronDown({ up }: { up?: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
         style={up ? { transform: "rotate(180deg)" } : undefined}>
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="blv-fact">
      <span className="blv-fact-label">{label}</span>
      <span className="blv-fact-value">{children}</span>
    </div>
  );
}

function Interpreted({ typed, resolved }: { typed: string; resolved?: string }) {
  if (!resolved || !materiallyDiffers(typed, resolved)) return null;
  return <span className="blv-route-interpreted">interpreted as {resolved}</span>;
}

/** "Austin-Bergstrom International Airport (AUS), Presidential Blvd…" -> first segment. */
function shortAddress(value: string): string {
  return value.split(",")[0].trim();
}

export default function FlowRail({ step, cta, bookers, stickyExtra }: {
  step: "vehicle" | "extra" | "passenger" | "payment";
  cta: FlowCta | null;
  /** Identity decision block — rendered on step 1 only (pass it only there). */
  bookers?: ReactNode;
  /** Extra control in the mobile sticky bar (step 1 keeps its Sign-in shortcut). */
  stickyExtra?: ReactNode;
}) {
  const { search, quote, trip, journey } = useBookingStore();
  const [editing, setEditing] = useState(false);
  const [stripOpen, setStripOpen] = useState(false);
  const { data: vehicles } = useQuery({ queryKey: ["vehicles"], queryFn: () => catalogService.listVehicles(), staleTime: 0 });
  if (!search) return null;
  const vehicle = vehicles?.find((v) => v.id === quote?.vehicle_id);
  const hourly = search.tripType === "hourly";

  const ctaButton = cta && (
    <button className="blv-cta" type="button" onClick={cta.onClick} disabled={cta.disabled || cta.busy}>
      {cta.busy && <span className="mm-btn-spinner" aria-hidden="true" />}
      {cta.label}
    </button>
  );

  const facts = (
    <div className="blv-facts">
      <Fact label="Type">{tripTypeLabel(search.tripType, search.hours)}</Fact>
      <ul className="blv-route" aria-label="Itinerary">
        <li>
          <span className="blv-route-pin">A</span>
          <span className="blv-route-text">{search.pickupAddress}<Interpreted typed={search.pickupAddress} resolved={journey?.pickup_address} /></span>
        </li>
        {!hourly && (
          <li>
            <span className="blv-route-pin">B</span>
            <span className="blv-route-text">{search.dropoffAddress}<Interpreted typed={search.dropoffAddress} resolved={journey?.dropoff_address} /></span>
          </li>
        )}
      </ul>
      <Fact label="Date · time">{formatDate(search.date)} · {formatTime(search.time)}</Fact>
      {journey && <Fact label="Distance · duration">{Number(journey.distance_miles).toFixed(1)} mi · {journey.duration_minutes} min</Fact>}
      {!hourly && <Fact label="Meet & Greet">{search.meetGreet ? "Yes" : "No"}</Fact>}
      <Fact label="Passengers · luggage">
        {trip.passengerCount}{vehicle?.passenger_capacity ? ` / ${vehicle.passenger_capacity} seats` : ""} · {trip.luggageCount}{vehicle?.luggage_capacity ? ` / ${vehicle.luggage_capacity} bags` : ""}
      </Fact>
      {trip.forSomeoneElse && (
        <>
          <Fact label="Passenger">{trip.passengerName || "Not entered"}</Fact>
          {trip.passengerPhone && <Fact label="Passenger phone">{trip.passengerPhone}</Fact>}
        </>
      )}
    </div>
  );

  const totalBlock = quote ? (
    <>
      <hr className="blv-rail-hr" />
      <div className="blv-rail-row">
        <span className="blv-rail-name">{quote.vehicle_name}</span>
        <span className="blv-rail-price">{money(quote.total, quote.currency)}{hourly && !!search.hours && <small> for {search.hours} hours</small>}</span>
      </div>
      <div className="blv-rail-sub">{quote.vehicle_name} or similar</div>
      <div className="blv-rail-note">All fees included</div>
    </>
  ) : (
    <>
      <hr className="blv-rail-hr" />
      <div className="blv-rail-empty">Choose a vehicle class to continue.</div>
    </>
  );

  const editButton = (
    <button type="button" className="blv-edit" onClick={() => setEditing(true)}>Edit trip</button>
  );

  return (
    <>
      {/* Phones, steps 2–4: collapsible trip summary at the top of the page. */}
      {step !== "vehicle" && (
        <div className="blv-strip">
          <button type="button" className="blv-strip-head" aria-expanded={stripOpen} onClick={() => setStripOpen((open) => !open)}>
            <span className="blv-strip-route">
              {shortAddress(search.pickupAddress)}{hourly ? ` · ${search.hours} hours` : ` → ${shortAddress(search.dropoffAddress)}`}
            </span>
            <span className="blv-strip-when">{formatDate(search.date)} · {formatTime(search.time)}</span>
            <ChevronDown up={stripOpen} />
          </button>
          {stripOpen && (
            <div className="blv-strip-body">
              {facts}
              {quote && (
                <div className="blv-rail-row">
                  <span className="blv-rail-name">{quote.vehicle_name}</span>
                  <span className="blv-rail-price">{money(quote.total, quote.currency)}</span>
                </div>
              )}
              {editButton}
            </div>
          )}
        </div>
      )}

      <aside className={`blv-rail${step === "vehicle" ? " mobilekeep" : ""}`} aria-label="Your trip">
        <div className="blv-rail-map">
          <ItineraryMap search={search} />
        </div>
        <div className="blv-railcard">
          {facts}
          {totalBlock}
          {editButton}
          {ctaButton}
          {bookers}
        </div>
      </aside>

      {/* Phones: sticky bottom bar — total + the step CTA, identical on every step. */}
      <div className="blv-sticky">
        {stickyExtra}
        <div className="blv-sticky-main">
          {quote && <strong className="blv-sticky-total">{money(quote.total, quote.currency)}</strong>}
          {ctaButton}
        </div>
      </div>

      {editing && <TripEditorOverlay search={search} onClose={() => setEditing(false)} />}
    </>
  );
}
