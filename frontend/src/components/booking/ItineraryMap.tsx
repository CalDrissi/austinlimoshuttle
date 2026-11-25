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
        const [{ Map }, { Geocoder }, { AdvancedMarkerElement, PinElement }] = await Promise.all([
          google.maps.importLibrary("maps"),
          google.maps.importLibrary("geocoding"),
          google.maps.importLibrary("marker"),
        ]);
        const geocoder = new Geocoder();
        async function locate(address: string) {
          const { results } = await geocoder.geocode({ address });
          if (!results?.[0]) throw new Error("Address not found");
          return results[0].geometry.location;
        }
        const [pickup, dropoff] = await Promise.all([
          search.pickupCoordinates ?? locate(search.pickupAddress),
          destination ? (search.dropoffCoordinates ?? locate(destination)) : Promise.resolve(null),
        ]);
        if (cancelled || !container.current) return;
        const map = new Map(container.current, {
          center: pickup, zoom: 13, mapTypeControl: false, streetViewControl: false,
          fullscreenControl: false, gestureHandling: "cooperative",
          // AdvancedMarkerElement (the non-deprecated marker) requires a map id;
          // Google's shared DEMO_MAP_ID is the documented one for default styling.
          mapId: "DEMO_MAP_ID",
        });
        const bounds = new google.maps.LatLngBounds();
        [[pickup, "A", search.pickupAddress], [dropoff, "B", destination]].forEach(([position, glyph, title]) => {
          if (!position) return;
          bounds.extend(position);
          const pin = new PinElement({
            glyph: glyph as string, glyphColor: "#ffffff",
            background: "#111111", borderColor: "#111111",
          });
          overlays.push(new AdvancedMarkerElement({
            map, position, title: title as string, content: pin.element,
          }));
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
      // AdvancedMarkerElement detaches via `.map = null`; polylines via setMap.
      overlays.forEach((overlay) => {
        if (typeof overlay.setMap === "function") overlay.setMap(null);
        else overlay.map = null;
      });
    };
  }, [search.pickupAddress, destination, search.pickupCoordinates, search.dropoffCoordinates]);

  if (unavailable) return <p className="text-14 mm-map-unavailable mt-20">Map unavailable</p>;
  return <div ref={container} className="mm-itinerary-map mt-20" role="region"
    aria-label={destination ? `Route from ${search.pickupAddress} to ${destination}` : `Pickup: ${search.pickupAddress}`} />;
}
