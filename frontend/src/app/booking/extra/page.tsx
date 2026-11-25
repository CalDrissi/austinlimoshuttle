"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { quoteService, quoteRequest } from "@/lib/api/quote.service";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { catalogService } from "@/lib/api/catalog.service";
import { useBookingStore, useHydrated } from "@/lib/booking/store";
import { useCapacity } from "@/lib/booking/useCapacity";
import FlowRail from "@/components/booking/FlowRail";

export default function BookingExtraPage() {
  const router = useRouter();
  const quote = useBookingStore((s) => s.quote);
  const search = useBookingStore((s) => s.search);
  const applyRequote = useBookingStore((s) => s.applyRequote);
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [correction, setCorrection] = useState("");
  const trip = useBookingStore((s) => s.trip);
  const setTrip = useBookingStore((s) => s.setTrip);
  const hydrated = useHydrated();
  const capacity = useCapacity();

  const { data: vehicles } = useQuery({
    queryKey: ["vehicles"],
    queryFn: () => catalogService.listVehicles(),
    staleTime: 0, // reflect back-office capacity changes promptly
  });

  useEffect(() => {
    if (hydrated && !quote) router.replace("/booking/vehicle");
  }, [hydrated, quote, router]);
  if (!hydrated || !quote) return null;

  const vehicle = vehicles?.find((v) => v.id === quote.vehicle_id);
  // A capacity of 0 means "not configured" on the backend -> treated as no limit.
  const maxPax = vehicle?.passenger_capacity || null;
  const maxLug = vehicle?.luggage_capacity || null;
  const paxOver = maxPax != null && trip.passengerCount > maxPax;
  const lugOver = maxLug != null && trip.luggageCount > maxLug;

  const changeMeetGreet = async (checked: boolean) => {
    if (!search) return;
    setBusy(true); setError("");
    try {
      const nextSearch = { ...search, meetGreet: checked };
      const response = await quoteService.create(quoteRequest(nextSearch));
      if (!response.quotes.some((q) => q.vehicle_id === quote.vehicle_id)) throw new Error("This vehicle is unavailable for the updated trip.");
      cache.setQueryData(["quotes", nextSearch], response);
      applyRequote(nextSearch, response);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not update your fare. Please try again."); }
    finally { setBusy(false); }
  };

  const next = () => { if (!capacity.blocked && !busy) router.push("/booking/passenger"); };

  return (
    <section className="blv">
      <div className="blv-page">
        <div className="blv-layout">
          <div className="blv-main">
            <h1 className="blv-title">Trip details</h1>
            <div className="flow-card">
              {vehicle && (maxPax || maxLug) && (
                <p className="text-14 color-grey mb-30">
                  {quote.vehicle_name}
                  {maxPax ? <> seats up to <strong>{maxPax}</strong> passenger{maxPax === 1 ? "" : "s"}</> : null}
                  {maxPax && maxLug ? " and" : null}
                  {maxLug ? <> holds <strong>{maxLug}</strong> bag{maxLug === 1 ? "" : "s"}</> : null}.
                </p>
              )}

              {search && search.tripType !== "hourly" && <div className="mb-20"><label><input type="checkbox" checked={search.meetGreet} disabled={busy} onChange={(e) => changeMeetGreet(e.target.checked)} /> Meet &amp; Greet</label>{busy && <span role="status"> Updating fare…</span>}{error && <p role="alert" style={{color:"#b42318"}}>{error}</p>}</div>}
              <div className="row">
                <div className="col-6 mb-20">
                  <label className="text-14 color-grey">Passengers</label>
                  <input type="number" min={1} max={maxPax ?? undefined} className="form-control"
                    style={paxOver ? { borderColor: "#c0392b" } : undefined} value={trip.passengerCount}
                    onChange={(e) => { const value = Math.floor(Number(e.target.value)); const clamped = Math.min(20, Math.max(1, value)); setCorrection(value < 1 ? "Passenger count was adjusted to 1." : value > 20 ? "Passenger count was adjusted to 20." : ""); setTrip({ passengerCount: clamped }); }} />
                  {correction && <div role="status" className="text-14">{correction}</div>}
                  {paxOver && <div className="text-14" style={{ color: "#c0392b", marginTop: 4 }}>Max {maxPax} for {quote.vehicle_name} — choose a larger vehicle.</div>}
                </div>
                <div className="col-6 mb-20">
                  <label className="text-14 color-grey">Luggage</label>
                  <input type="number" min={0} max={maxLug ?? undefined} className="form-control"
                    style={lugOver ? { borderColor: "#c0392b" } : undefined} value={trip.luggageCount}
                    onChange={(e) => setTrip({ luggageCount: Math.min(20, Math.max(0, Math.floor(Number(e.target.value)))) })} />
                  {lugOver && <div className="text-14" style={{ color: "#c0392b", marginTop: 4 }}>Max {maxLug} bags for {quote.vehicle_name} — choose a larger vehicle.</div>}
                </div>
                <div className="col-6 mb-20">
                  <label className="text-14 color-grey">Name on pickup sign (optional)</label>
                  <input type="text" className="form-control" value={trip.pickupSign ?? ""}
                    onChange={(e) => setTrip({ pickupSign: e.target.value })} />
                </div>
                <div className="col-12 mb-20">
                  <label className="text-14 color-grey">Notes for the driver (optional)</label>
                  <textarea className="form-control" rows={3} value={trip.notes ?? ""}
                    onChange={(e) => setTrip({ notes: e.target.value })} />
                </div>
              </div>
            </div>
          </div>
          <FlowRail step="extra" cta={{ label: "Continue", onClick: next, disabled: capacity.blocked || busy }} />
        </div>
      </div>
    </section>
  );
}
