"use client";
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { DayPicker as ReactDayPicker } from "react-day-picker";
import { useBookingStore, type Search } from "@/lib/booking/store";
import { quoteService, quoteRequest } from "@/lib/api/quote.service";
import { formatDate, formatTime, tripTypeLabel } from "@/lib/format";
import { AddressField } from "./BookingSearchWidget";

// The flow never shows an ISO date or a 24-hour clock — the editor's own
// controls are a formatted date button (calendar popover) and a 12-hour time
// list, matching what the widget and rail display.
const TIMES: string[] = [];
for (let h = 0; h < 24; h++) {
  for (const m of [0, 15, 30, 45]) {
    TIMES.push(`${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`);
  }
}

function toYmd(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** "YYYY-MM-DD" -> local Date without the UTC shift of new Date(string). */
function fromYmd(ymd: string): Date | undefined {
  const m = ymd.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : undefined;
}

export default function TripEditor({ search, onClose }: { search: Search; onClose: () => void }) {
  const [draft, setDraft] = useState({ ...search, hours: Math.max(3, search.hours ?? 3) });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [calendarOpen, setCalendarOpen] = useState(false);
  const dateButtonRef = useRef<HTMLButtonElement>(null);
  const apply = useBookingStore((s) => s.applyRequote);
  const cache = useQueryClient();
  const update = (patch: Partial<Search>) => setDraft((s) => ({ ...s, ...patch }));
  const today = new Date();
  const save = async () => {
    if (!draft.pickupAddress.trim() || !draft.date || !draft.time || (draft.tripType !== "hourly" && !draft.dropoffAddress.trim())) {
      setError("Enter pickup, date, time and a drop-off for point-to-point trips."); return;
    }
    if (draft.tripType !== "hourly" && draft.pickupAddress.trim().toLowerCase() === draft.dropoffAddress.trim().toLowerCase()) {
      setError("Pickup and drop-off are the same address"); return;
    }
    setBusy(true); setError("");
    try {
      const next = { ...draft,
        // Meet & Greet is a point-to-point extra; an hourly hire must never carry it.
        meetGreet: draft.tripType === "hourly" ? false : draft.meetGreet,
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
      {(["transfer", "hourly", "city"] as const).map((value) => <label key={value}><input type="radio" name="trip-type" value={value} checked={draft.tripType === value} onChange={() => update({ tripType: value })} /> {tripTypeLabel(value)}</label>)}
    </div>
    <AddressField label="Pickup" value={draft.pickupAddress} onChange={(pickupAddress) => update({ pickupAddress, pickupCoordinates: undefined })} placeholder="Pickup address" />
    {draft.tripType !== "hourly" ? <AddressField label="Drop-off" value={draft.dropoffAddress} onChange={(dropoffAddress) => update({ dropoffAddress, dropoffCoordinates: undefined })} placeholder="Drop-off address" /> :
      <label>Hours<select className="form-control" value={draft.hours ?? 3} onChange={(e) => update({ hours: Number(e.target.value) })}>{Array.from({length:22}, (_, i) => <option key={i} value={i+3}>{i+3}</option>)}</select></label>}
    <div className="mm-editor-date">
      <span className="mm-editor-label" id="trip-editor-date-label">Date</span>
      <button type="button" ref={dateButtonRef} className="form-control mm-editor-date-btn" aria-labelledby="trip-editor-date-label"
              aria-expanded={calendarOpen} onClick={() => setCalendarOpen((open) => !open)}>
        {draft.date ? formatDate(draft.date) : "Select date"}
      </button>
      {calendarOpen && (
        <div className="mm-dropdown mm-daypicker">
          <ReactDayPicker
            mode="single"
            selected={fromYmd(draft.date)}
            defaultMonth={fromYmd(draft.date) ?? today}
            disabled={{ before: today }}
            onSelect={(d) => { if (d) { update({ date: toYmd(d) }); setCalendarOpen(false); dateButtonRef.current?.focus(); } }}
          />
        </div>
      )}
    </div>
    <label>Time<select className="form-control" value={formatTime(draft.time)} onChange={(e) => update({ time: e.target.value })}>
      {!TIMES.includes(formatTime(draft.time)) && <option value={draft.time}>{formatTime(draft.time)}</option>}
      {TIMES.map((t) => <option key={t} value={t}>{t}</option>)}
    </select></label>
    {error && <p role="alert" style={{color:"#b42318"}}>{error}</p>}
    <div style={{display:"flex", gap:12, flexWrap:"wrap"}}><button type="button" className="btn btn-primary" onClick={save}>{busy ? "Updating prices…" : "Save & reprice"}</button><button type="button" className="btn btn-link" onClick={onClose}>Cancel</button></div>
  </fieldset>;
}
