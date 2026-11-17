"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { catalogService } from "@/lib/api/catalog.service";
import { useBookingStore, useHydrated } from "@/lib/booking/store";
import { useCapacity } from "@/lib/booking/useCapacity";
import OrderSummary from "@/components/booking/OrderSummary";

export default function BookingExtraPage() {
  const router = useRouter();
  const quote = useBookingStore((s) => s.quote);
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
  const over = paxOver || lugOver;

  const next = () => { if (!capacity.blocked) router.push("/booking/passenger"); };

  return (
    <section className="section">
      <div className="container-sub">
        <div className="box-row-tab mt-50">
          <div className="box-tab-left">
            <div className="box-content-detail">
              <h3 className="heading-24-medium color-text mb-10">Trip details</h3>
              {vehicle && (maxPax || maxLug) && (
                <p className="text-14 color-grey mb-30">
                  {quote.vehicle_name}
                  {maxPax ? <> seats up to <strong>{maxPax}</strong> passenger{maxPax === 1 ? "" : "s"}</> : null}
                  {maxPax && maxLug ? " and" : null}
                  {maxLug ? <> holds <strong>{maxLug}</strong> bag{maxLug === 1 ? "" : "s"}</> : null}.
                </p>
              )}

        <div className="row">
          <div className="col-6 mb-20">
            <label className="text-14 color-grey">Passengers</label>
            <input type="number" min={1} max={maxPax ?? undefined} className="form-control"
              style={paxOver ? { borderColor: "#c0392b" } : undefined} value={trip.passengerCount}
              onChange={(e) => setTrip({ passengerCount: Math.max(1, Number(e.target.value)) })} />
            {paxOver && <div className="text-14" style={{ color: "#c0392b", marginTop: 4 }}>Max {maxPax} for {quote.vehicle_name} — choose a larger vehicle.</div>}
          </div>
          <div className="col-6 mb-20">
            <label className="text-14 color-grey">Luggage</label>
            <input type="number" min={0} max={maxLug ?? undefined} className="form-control"
              style={lugOver ? { borderColor: "#c0392b" } : undefined} value={trip.luggageCount}
              onChange={(e) => setTrip({ luggageCount: Math.max(0, Number(e.target.value)) })} />
            {lugOver && <div className="text-14" style={{ color: "#c0392b", marginTop: 4 }}>Max {maxLug} bags for {quote.vehicle_name} — choose a larger vehicle.</div>}
          </div>
          <div className="col-6 mb-20">
            <label className="text-14 color-grey">Flight number (optional)</label>
            <input type="text" className="form-control" value={trip.flightNumber ?? ""}
              onChange={(e) => setTrip({ flightNumber: e.target.value })} />
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

              <button className="btn btn-primary hover-up mt-10" onClick={next} disabled={capacity.blocked}>Continue</button>
            </div>
          </div>
          <OrderSummary />
        </div>
      </div>
    </section>
  );
}
