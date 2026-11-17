"use client";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useBookingStore, type Search } from "@/lib/booking/store";
import { quoteService, quoteRequest } from "@/lib/api/quote.service";
import { AddressField } from "./BookingSearchWidget";

export default function TripEditor({ search, onClose }: { search: Search; onClose: () => void }) {
  const [draft, setDraft] = useState(search);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const apply = useBookingStore((s) => s.applyRequote);
  const cache = useQueryClient();
  const update = (patch: Partial<Search>) => setDraft((s) => ({ ...s, ...patch }));
  const save = async () => {
    if (!draft.pickupAddress.trim() || !draft.date || !draft.time || (draft.tripType !== "hourly" && !draft.dropoffAddress.trim())) {
      setError("Enter pickup, date, time and a drop-off for point-to-point trips."); return;
    }
    setBusy(true); setError("");
    try {
      const next = { ...draft, pickupCoordinates: undefined, dropoffCoordinates: undefined,
        dropoffAddress: draft.tripType === "hourly" ? "" : draft.dropoffAddress.trim(), pickupAddress: draft.pickupAddress.trim() };
      const response = await quoteService.create(quoteRequest(next));
      if (!response.quotes.length) throw new Error("No vehicles are available for this trip. Try another trip.");
      cache.setQueryData(["quotes", next], response);
      apply(next, response);
      onClose();
    } catch (e) { setError(e instanceof Error ? e.message : "Could not update trip. Please retry."); }
    finally { setBusy(false); }
  };
  return <fieldset disabled={busy} className="mm-trip-editor">
    <legend className="text-16-medium">Edit trip</legend>
    <div role="radiogroup" aria-label="Trip type" style={{display:"flex", gap:12, flexWrap:"wrap"}}>
      {([ ["transfer", "Transfer"], ["hourly", "Hourly"], ["city", "City-to-City"] ] as const).map(([value, label]) => <label key={value}><input type="radio" name="trip-type" value={value} checked={draft.tripType === value} onChange={() => update({ tripType: value })} /> {label}</label>)}
    </div>
    <AddressField label="Pickup" value={draft.pickupAddress} onChange={(pickupAddress) => update({ pickupAddress })} placeholder="Pickup address" />
    {draft.tripType !== "hourly" ? <AddressField label="Drop-off" value={draft.dropoffAddress} onChange={(dropoffAddress) => update({ dropoffAddress })} placeholder="Drop-off address" /> :
      <label>Hours<select className="form-control" value={draft.hours ?? 3} onChange={(e) => update({ hours: Number(e.target.value) })}>{Array.from({length:12}, (_, i) => <option key={i} value={i+1}>{i+1}</option>)}</select></label>}
    <label>Date<input className="form-control" type="date" value={draft.date} required onChange={(e) => update({ date: e.target.value })} /></label>
    <label>Time<input className="form-control" type="time" value={normalTime(draft.time)} required onChange={(e) => update({ time: e.target.value })} /></label>
    <label><input type="checkbox" checked={draft.meetGreet} onChange={(e) => update({ meetGreet: e.target.checked })} /> Meet &amp; Greet</label>
    {error && <p role="alert" style={{color:"#b42318"}}>{error}</p>}
    <div style={{display:"flex", gap:12, flexWrap:"wrap"}}><button type="button" className="btn btn-primary" onClick={save}>{busy ? "Updating prices…" : "Save & reprice"}</button><button type="button" className="btn btn-link" onClick={onClose}>Cancel</button></div>
  </fieldset>;
}
function normalTime(time: string) {
  const m = time.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
  return m ? `${String(Number(m[1]) % 12 + (/PM/i.test(m[3]) ? 12 : 0)).padStart(2,"0")}:${m[2]}` : time;
}
