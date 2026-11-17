"use client";
import { useQuery } from "@tanstack/react-query";
import { catalogService } from "@/lib/api/catalog.service";
import { useBookingStore } from "./store";

/** Match the API: zero capacity means unconfigured/unlimited. Fail closed until the catalog loads. */
export function useCapacity() {
  const quote = useBookingStore((s) => s.quote);
  const trip = useBookingStore((s) => s.trip);
  const { data, isPending, isError } = useQuery({ queryKey: ["vehicles"], queryFn: () => catalogService.listVehicles(), staleTime: 0 });
  const vehicle = data?.find((v) => v.id === quote?.vehicle_id);
  const over = !!vehicle && ((!!vehicle.passenger_capacity && trip.passengerCount > vehicle.passenger_capacity) || (!!vehicle.luggage_capacity && trip.luggageCount > vehicle.luggage_capacity));
  const invalid = !Number.isInteger(trip.passengerCount) || trip.passengerCount < 1 || !Number.isInteger(trip.luggageCount) || trip.luggageCount < 0;
  return { over, blocked: isPending || isError || !vehicle || over || invalid };
}
