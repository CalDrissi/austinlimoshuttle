"use client";

import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { quoteService } from "@/lib/api/quote.service";
import { catalogService } from "@/lib/api/catalog.service";
import { useBookingStore, pickupIso } from "@/lib/booking/store";
import { VEHICLE_PLACEHOLDER } from "@/lib/fleet/images";
import OrderSummary from "@/components/booking/OrderSummary";
import type { QuoteResult, Vehicle } from "@/types/api";

function money(amount: string, currency: string) {
  const symbol = currency === "USD" ? "$" : `${currency} `;
  return `${symbol}${Number(amount).toFixed(2)}`;
}

function VehicleCard({ quote, vehicle, meetGreet, onSelect }: {
  quote: QuoteResult;
  vehicle?: Vehicle;
  meetGreet: boolean;
  onSelect: (q: QuoteResult) => void;
}) {
  return (
    <div className="item-vehicle">
      <div className="vehicle-left">
        <div className="vehicle-image"><img src={vehicle?.photo || VEHICLE_PLACEHOLDER} alt={quote.vehicle_name} /></div>
        <div className="vehicle-facilities">
          {meetGreet && <div className="text-fact meet-greeting">Meet &amp; Greet included</div>}
          <div className="text-fact free-cancel">Free cancellation</div>
          <div className="text-fact free-waiting">Free Waiting time</div>
          <div className="text-fact safe-travel">Safe and secure travel</div>
        </div>
      </div>
      <div className="vehicle-right">
        <h5 className="text-20-medium color-text mb-10">{quote.vehicle_name}</h5>
        {vehicle?.description && <p className="text-14 color-text mb-20">{vehicle.description}</p>}
        <div className="vehicle-passenger-luggage mb-10">
          <span className="passenger">Passengers {vehicle?.passenger_capacity ?? "-"}</span>
          <span className="luggage">Luggage {vehicle?.luggage_capacity ?? "-"}</span>
        </div>
        <div className="vehicle-price"><h4 className="heading-30-medium color-text">{money(quote.total, quote.currency)}</h4></div>
        <div className="price-desc mb-20">All-inclusive — taxes &amp; fees included.</div>
        <button className="btn btn-primary w-100" onClick={() => onSelect(quote)}>Select</button>
      </div>
    </div>
  );
}

export default function BookingVehiclePage() {
  const router = useRouter();
  const search = useBookingStore((s) => s.search);
  const setQuote = useBookingStore((s) => s.setQuote);
  const clearPreferredVehicle = useBookingStore((s) => s.clearPreferredVehicle);

  const { data, isLoading, error } = useQuery({
    queryKey: ["quotes", search],
    enabled: !!search,
    retry: false,
    queryFn: () => {
      if (search!.tripType === "hourly") {
        return quoteService.create({
          pickup_address: search!.pickupAddress,
          hours: String(search!.hours ?? ""),
          pickup_at: pickupIso(search!),
          meet_and_greet: search!.meetGreet,
        });
      }
      return quoteService.create({
        pickup_address: search!.pickupAddress,
        dropoff_address: search!.dropoffAddress,
        pickup_at: pickupIso(search!),
        meet_and_greet: search!.meetGreet,
        ...(search!.tripType === "city" ? { city_to_city: true } : {}),
      });
    },
  });

  const { data: vehicles } = useQuery({
    queryKey: ["vehicles"],
    queryFn: () => catalogService.listVehicles(),
    // Catalog is cheap and must reflect a back-office photo/capacity change
    // promptly, so always revalidate rather than serving the 60s global cache.
    staleTime: 0,
  });
  const byId = new Map((vehicles ?? []).map((v) => [v.id, v]));

  // When the funnel began on a vehicle's detail page, that class is already
  // chosen: once its quote arrives, select it and skip ahead to the extras
  // step. The preference is consumed (whether or not the vehicle was priced for
  // this journey) so a Back from the next step shows the full list instead of
  // bouncing forward again; if the vehicle couldn't be priced, we simply fall
  // through to the normal list below.
  const preferredId = search?.preferredVehicleId;
  const consumed = useRef(false);
  useEffect(() => {
    if (consumed.current || preferredId == null || !data) return;
    consumed.current = true;
    const match = data.quotes.find((q) => q.vehicle_id === preferredId);
    clearPreferredVehicle();
    if (match) {
      setQuote(match);
      router.replace("/booking/extra");
    }
  }, [preferredId, data, clearPreferredVehicle, setQuote, router]);

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
              <h3 className="heading-24-medium color-text mb-30">Select Your Car</h3>

              {!search && (
                <p className="text-16 color-grey">Start with a search from the <a href="/">home page</a>.</p>
              )}
              {(isLoading || (preferredId != null && !error)) && (
                <p className="text-16 color-grey">Pricing vehicles for your journey…</p>
              )}
              {error && (
                <p className="text-16" style={{ color: "#c0392b" }}>
                  {(error as Error).message || "Could not price that journey. Check the addresses and try again."}
                </p>
              )}

              <div className="list-vehicles">
                {preferredId == null && data?.quotes.map((q) => (
                  <VehicleCard
                    key={q.vehicle_id}
                    quote={q}
                    vehicle={byId.get(q.vehicle_id)}
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
