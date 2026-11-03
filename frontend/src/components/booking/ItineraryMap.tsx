"use client";

import { useEffect, useRef, useState } from "react";
import type { Search } from "@/lib/booking/store";
import { loadGoogleMaps } from "@/lib/google/places";

// Keep the untyped Maps SDK boundary local, as in the shared Places loader.
/* eslint-disable @typescript-eslint/no-explicit-any */
export default function ItineraryMap({ search }: { search: Search }) {
  const container = useRef<HTMLDivElement>(null);
  const [unavailable, setUnavailable] = useState(false);
  const destination = search.tripType === "hourly" ? "" : search.dropoffAddress;

  useEffect(() => {
    let cancelled = false;
    const overlays: any[] = [];
    let observer: ResizeObserver | undefined;
    setUnavailable(false);
    async function initialize() {
      try {
        const google = await loadGoogleMaps();
        const [{ Map }, { Geocoder }, { Marker }] = await Promise.all([
          google.maps.importLibrary("maps"),
          google.maps.importLibrary("geocoding"),
          google.maps.importLibrary("marker"),
        ]);
        const geocoder = new Geocoder();
        async function locate(address: string, coordinates?: { lat: number; lng: number }) {
          if (coordinates && Number.isFinite(coordinates.lat) && Number.isFinite(coordinates.lng)
            && Math.abs(coordinates.lat) <= 90 && Math.abs(coordinates.lng) <= 180) return coordinates;
          const { results } = await geocoder.geocode({ address });
          if (!results?.[0]) throw new Error("Address not found");
          return results[0].geometry.location;
        }
        const [pickup, dropoff] = await Promise.all([
          locate(search.pickupAddress, search.pickupCoordinates),
          destination ? locate(destination, search.dropoffCoordinates) : Promise.resolve(null),
        ]);
        if (cancelled || !container.current) return;
        const map = new Map(container.current, {
          center: pickup, zoom: 13, mapTypeControl: false, streetViewControl: false,
          fullscreenControl: false, gestureHandling: "cooperative",
        });
        const bounds = new google.maps.LatLngBounds();
        [[pickup, "A", search.pickupAddress], [dropoff, "B", destination]].forEach(([position, label, title]) => {
          if (!position) return;
          bounds.extend(position);
          overlays.push(new Marker({ map, position, title, label: { text: label, color: "#ffffff" } }));
        });
        const fit = () => { if (dropoff) map.fitBounds(bounds, 40); else map.setCenter(pickup); };
        fit();
        observer = new ResizeObserver(fit);
        observer.observe(container.current);
        if (dropoff) {
          // Routes API may be disabled on a deployment; keep the A/B map usable.
          try {
            const { Route } = await google.maps.importLibrary("routes");
            const { routes } = await Route.computeRoutes({
              origin: pickup, destination: dropoff, travelMode: "DRIVING", fields: ["path"],
            });
            if (cancelled || !routes?.[0]) return;
            const lines = routes[0].createPolylines({
              polylineOptions: { strokeColor: "#111111", strokeWeight: 4, strokeOpacity: 0.85 },
            });
            lines.forEach((line: any) => line.setMap(map));
            overlays.push(...lines);
            routes[0].path.forEach((point: any) => bounds.extend(point));
            fit();
          } catch { /* Markers remain visible without route permission. */ }
        }
      } catch {
        if (!cancelled) setUnavailable(true);
      }
    }
    void initialize();
    return () => {
      cancelled = true;
      observer?.disconnect();
      overlays.forEach((overlay) => overlay.setMap(null));
    };
  }, [search.pickupAddress, destination, search.pickupCoordinates, search.dropoffCoordinates]);

  if (unavailable) return <p className="text-14 mm-map-unavailable mt-20">Map unavailable</p>;
  return <div ref={container} className="mm-itinerary-map mt-20" role="region"
    aria-label={destination ? `Route from ${search.pickupAddress} to ${destination}` : `Pickup: ${search.pickupAddress}`} />;
}
