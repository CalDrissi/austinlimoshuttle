"use client";

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useBookingStore } from "@/lib/booking/store";
import { catalogService } from "@/lib/api/catalog.service";
import ItineraryMap from "./ItineraryMap";
import TripEditor from "./TripEditor";
import type { Journey } from "@/types/api";

function money(amount: string, currency: string) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(Number(amount));
}
function Group({ title, children }: { title: string; children: ReactNode }) {
  return <section style={{borderTop:"1px solid #e5e7eb", paddingTop:16, marginTop:16}}><h3 className="text-16-medium" style={{marginBottom:10}}>{title}</h3>{children}</section>;
}
function Row({ label, children }: { label: string; children: ReactNode }) {
  return <div style={{display:"flex", justifyContent:"space-between", gap:12, marginBottom:7, overflowWrap:"anywhere"}}><span className="color-grey">{label}</span><span style={{textAlign:"right"}}>{children}</span></div>;
}
export default function OrderSummary({ journey: suppliedJourney }: { journey?: Journey | null }) {
  const { search, quote, trip, contact, journey: savedJourney } = useBookingStore();
  const [editing, setEditing] = useState(false);
  const { data: vehicles } = useQuery({ queryKey: ["vehicles"], queryFn: () => catalogService.listVehicles(), staleTime: 0 });
  if (!search) return null;
  const journey = savedJourney ?? suppliedJourney;
  const vehicle = vehicles?.find((v) => v.id === quote?.vehicle_id);
  const paxOver = !!vehicle?.passenger_capacity && trip.passengerCount > vehicle.passenger_capacity;
  const lugOver = !!vehicle?.luggage_capacity && trip.luggageCount > vehicle.luggage_capacity;
  const extras = quote?.lines.filter((line) => line.kind === "meet_greet") ?? [];
  return <aside className="box-tab-right" aria-label="Ride summary">
    <div className="sidebar text-14" style={{overflowWrap:"anywhere"}}>
      <div className="d-flex align-items-center justify-content-between"><h2 className="text-20-medium color-text">Ride Summary</h2><button type="button" className="btn btn-link" aria-expanded={editing} onClick={() => setEditing(!editing)}>Edit</button></div>
      {editing && <TripEditor search={search} onClose={() => setEditing(false)} />}
      <Group title="Trip">
        <Row label="Type">{search.tripType === "city" ? "City-to-City" : search.tripType === "hourly" ? `Hourly · ${search.hours} hours` : "Transfer"}</Row>
        <ul className="mm-summary-routes" aria-label="Itinerary"><li><span className="location-item">A</span><span className="info-location text-14-medium">{search.pickupAddress}</span></li>{search.tripType !== "hourly" && <li><span className="location-item">B</span><span className="info-location text-14-medium">{search.dropoffAddress}</span></li>}</ul>
        <Row label="Date">{search.date}</Row><Row label="Time">{search.time} (Austin)</Row>
        {journey && <><Row label="Distance">{Number(journey.distance_miles).toFixed(1)} miles</Row><Row label="Duration">{journey.duration_minutes} min</Row></>}
        <Row label="Meet & Greet">{search.meetGreet ? "Yes" : "No"}</Row>
        {trip.flightNumber && <Row label="Flight">{trip.flightNumber}</Row>}
        <ItineraryMap search={search} />
      </Group>
      <Group title="Passengers + Luggage">
        <Row label="Passengers">{trip.passengerCount}{vehicle?.passenger_capacity ? ` / ${vehicle.passenger_capacity} seats` : ""}</Row>
        <Row label="Luggage">{trip.luggageCount}{vehicle?.luggage_capacity ? ` / ${vehicle.luggage_capacity} bags` : ""}</Row>
        {(paxOver || lugOver) && <p role="alert" style={{color:"#b42318", fontWeight:600}}>{paxOver && <>Exceeds {vehicle?.name}&apos;s {vehicle?.passenger_capacity} seats. </>}{lugOver && <>Exceeds {vehicle?.name}&apos;s {vehicle?.luggage_capacity} bags. </>}Change vehicle or reduce your party before payment. <a href="/booking/extra">Update details</a></p>}
      </Group>
      <Group title="Vehicle">{quote ? quote.vehicle_name : "Choose a vehicle"}</Group>
      <Group title="Extras">{extras.length ? extras.map((line, i) => <Row key={i} label={line.label}>{money(line.amount, quote!.currency)}</Row>) : search.meetGreet ? "Meet & Greet · price after vehicle selection" : "No paid extras"}
        {trip.pickupSign && <Row label="Pickup sign">{trip.pickupSign}</Row>}{trip.notes && <Row label="Notes">{trip.notes}</Row>}
      </Group>
      <Group title="Passenger / contact">
        {contact.name && <Row label="Name">{contact.name}</Row>}{contact.email && <Row label="Email">{contact.email}</Row>}{contact.phone && <Row label="Phone">{contact.phone}</Row>}
        {!contact.name && !contact.email && !contact.phone && <span className="color-grey">Add your details in the passenger step</span>}
        {trip.forSomeoneElse && <><Row label="Passenger">{trip.passengerName || "Not entered"}</Row>{trip.passengerPhone && <Row label="Passenger phone">{trip.passengerPhone}</Row>}</>}
      </Group>
      <Group title="Total">{quote ? <><p className="text-20-medium">{money(quote.total, quote.currency)}</p><p className="color-grey">Taxes &amp; fees included</p></> : "Select a vehicle to see your fare"}</Group>
    </div>
  </aside>;
}
