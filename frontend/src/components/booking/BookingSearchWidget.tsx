"use client";

import { useState, useRef, useEffect, useCallback, useId } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { DayPicker as ReactDayPicker } from "react-day-picker";
import "react-day-picker/style.css";
import { quoteService, quoteRequest } from "@/lib/api/quote.service";
import { useBookingStore } from "@/lib/booking/store";
import {
  loadGoogleMaps,
  fetchPlaceSuggestions,
  newSessionToken,
  type PlaceSuggestion,
} from "@/lib/google/places";

const PLANE_ICON = "/assets/imgs/page/homepage1/plane.png";
const PIN_ICON = "/assets/imgs/page/homepage1/building.png";

// Below this length Google predictions are too noisy to be worth a billed call.
const MIN_QUERY = 3;

/**
 * Google Places suggestions for a free-text address query.
 *
 * Shared by the dark hero widget's location fields and the legacy AddressField
 * (TripEditor). Keystrokes are debounced and grouped under one session token
 * for billing; if Places can't load (missing/blocked key) the caller's field
 * degrades to a plain text input with no dropdown.
 */
function usePlacesSuggestions(value: string, open: boolean) {
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const tokenRef = useRef<unknown>(null);
  const [mapsReady, setMapsReady] = useState(false);
  const reqRef = useRef(0); // guards against out-of-order responses

  // Start the shared loader before the first keystroke. Readiness is a search
  // dependency so a query entered while Maps was cold is automatically replayed.
  useEffect(() => {
    let cancelled = false;
    loadGoogleMaps().then(() => {
      if (!cancelled) setMapsReady(true);
    }).catch((error: unknown) => {
      console.warn("Google Maps pre-warm failed; address search will retry.", error);
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const reqId = ++reqRef.current;
    const q = value.trim();
    setSuggestions([]);
    if (!open || q.length < MIN_QUERY) {
      setLoading(false);
      return;
    }
    setLoading(true);
    const search = async () => {
      // A rejected loader is retryable. Give a transient cold-start failure one
      // more attempt while retaining the same query and its loading indicator.
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          await loadGoogleMaps();
          if (reqId !== reqRef.current) return;
          if (!tokenRef.current) tokenRef.current = await newSessionToken();
          const results = await fetchPlaceSuggestions(q, tokenRef.current);
          if (reqId === reqRef.current) {
            setSuggestions(results);
            setLoading(false);
          }
          return;
        } catch (error) {
          if (reqId !== reqRef.current) return;
          console.warn("Address autocomplete attempt failed.", error);
          if (attempt === 1) setLoading(false);
        }
      }
    };
    const timeout = setTimeout(() => { void search(); }, 250);
    return () => {
      clearTimeout(timeout);
      // Also invalidate requests on edits, selection, blur, and unmount.
      ++reqRef.current;
    };
  }, [value, open, mapsReady]);

  // A selection ends the Places billing session.
  const endSession = useCallback(() => { tokenRef.current = null; }, []);

  return { suggestions, loading, endSession, clearSuggestions: () => setSuggestions([]) };
}

/** Close a dropdown when clicking anywhere outside `ref`. */
function useOutsideClose(ref: React.RefObject<HTMLElement | null>, close: () => void) {
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [ref, close]);
}

/**
 * Legacy light-theme address field (kept for TripEditor on the booking flow).
 * Free text is always allowed — the backend geocodes whatever is submitted, so
 * the suggestions only save typing.
 */
export function AddressField({ label, value, onChange, placeholder }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const { suggestions, loading, endSession, clearSuggestions } = usePlacesSuggestions(value, open);

  useOutsideClose(ref, useCallback(() => setOpen(false), []));

  const pick = (s: PlaceSuggestion) => {
    onChange(s.full);
    setOpen(false);
    clearSuggestions();
    endSession();
  };

  return (
    <div className="search-inputs mm-picker" ref={ref} onClick={() => inputRef.current?.focus()}>
      <label>{label}</label>
      <input
        ref={inputRef}
        className="search-input"
        type="text"
        autoComplete="off"
        placeholder={placeholder}
        value={value}
        onChange={(e) => { onChange(e.target.value); setOpen(true); }}
        onFocus={() => { setOpen(true); }}
      />
      {open && (value.trim().length >= MIN_QUERY) && (
        <div className="mm-dropdown mm-loc-list">
          {suggestions.length ? (
            suggestions.map((s) => (
              <div
                key={s.id}
                className="mm-loc-item"
                onMouseDown={(e) => { e.preventDefault(); pick(s); }}
              >
                <img src={s.isAirport ? PLANE_ICON : PIN_ICON} alt="" />
                <span className="mm-loc-text">
                  <span className="mm-loc-title">{s.primary}</span>
                  {s.secondary && <span className="mm-loc-sub">{s.secondary}</span>}
                </span>
              </div>
            ))
          ) : (
            <div className="mm-loc-empty">
              {loading ? "Searching…" : "No matches — you can enter any address."}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ================= dark hero widget fields ================= */

/**
 * Typeable location field with a keyboard-navigable suggestion dropdown
 * (ArrowUp/Down to move, Enter to select, Escape to close).
 */
function LocationField({ label, value, onChange, placeholder }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const { suggestions, loading, endSession, clearSuggestions } = usePlacesSuggestions(value, open);

  useOutsideClose(ref, useCallback(() => setOpen(false), []));

  // New results restart keyboard navigation from the top.
  useEffect(() => { setActive(-1); }, [suggestions]);

  const pick = (s: PlaceSuggestion) => {
    onChange(s.full);
    setOpen(false);
    clearSuggestions();
    endSession();
  };

  const listOpen = open && value.trim().length >= MIN_QUERY;

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") { setOpen(false); return; }
    if (!listOpen || !suggestions.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => (i + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      pick(suggestions[active]);
    }
  };

  return (
    <div className="blw-field blw-loc" ref={ref} onClick={() => inputRef.current?.focus()}>
      <span className="blw-label">{label}</span>
      <input
        ref={inputRef}
        className="blw-input"
        type="text"
        autoComplete="off"
        role="combobox"
        aria-expanded={listOpen}
        aria-controls={listId}
        aria-autocomplete="list"
        placeholder={placeholder}
        value={value}
        onChange={(e) => { onChange(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {listOpen && (
        <div className="blw-pop blw-loc-pop" id={listId} role="listbox">
          {suggestions.length ? (
            suggestions.map((s, i) => (
              <div
                key={s.id}
                role="option"
                aria-selected={i === active}
                className={`blw-loc-item${i === active ? " on" : ""}`}
                onMouseEnter={() => setActive(i)}
                onMouseDown={(e) => { e.preventDefault(); pick(s); }}
              >
                <img src={s.isAirport ? PLANE_ICON : PIN_ICON} alt="" />
                <span className="blw-loc-text">
                  <span className="blw-loc-title">{s.primary}</span>
                  {s.secondary && <span className="blw-loc-sub">{s.secondary}</span>}
                </span>
              </div>
            ))
          ) : (
            <div className="blw-loc-empty">
              {loading ? "Searching…" : "No matches — you can enter any address."}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// "YYYY-MM-DD" <-> local Date, without the UTC shift `new Date(string)` causes.
function parseYmd(value: string): Date | undefined {
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return undefined;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
}
function toYmd(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Date field opening an inline dark calendar (past days disabled, today ringed). */
function DateField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useOutsideClose(ref, useCallback(() => setOpen(false), []));

  const selected = value ? parseYmd(value) : undefined;
  const display = selected
    ? selected.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" })
    : "";
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  return (
    <div className="blw-field blw-date" ref={ref}>
      <button
        type="button"
        className="blw-trigger"
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="blw-label">Date</span>
        <span className={`blw-value${display ? "" : " empty"}`}>{display || "Select date"}</span>
      </button>
      {open && (
        <div className="blw-pop blw-cal" role="dialog" aria-label="Choose a date">
          <ReactDayPicker
            mode="single"
            selected={selected}
            defaultMonth={selected ?? today}
            disabled={{ before: today }}
            onSelect={(d) => {
              if (d) { onChange(toYmd(d)); setOpen(false); }
            }}
          />
        </div>
      )}
    </div>
  );
}

const TIMES: string[] = [];
for (let h = 0; h < 24; h++) {
  for (const m of [0, 15, 30, 45]) {
    const hour = h % 12 || 12;
    const ampm = h < 12 ? "AM" : "PM";
    TIMES.push(`${hour}:${String(m).padStart(2, "0")} ${ampm}`);
  }
}

/** A scrollable dark list dropdown (used for pickup time and hourly duration). */
function ListField({ label, value, display, placeholder, options, onPick }: {
  label: string;
  value: string;
  display: string;
  placeholder: string;
  options: { key: string; text: string }[];
  onPick: (key: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  useOutsideClose(ref, useCallback(() => setOpen(false), []));

  // Open with the current choice in view.
  useEffect(() => {
    if (open) {
      listRef.current?.querySelector(".sel")?.scrollIntoView({ block: "center" });
    }
  }, [open]);

  return (
    <div className="blw-field" ref={ref}>
      <button
        type="button"
        className="blw-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className="blw-label">{label}</span>
        <span className={`blw-value${display ? "" : " empty"}`}>{display || placeholder}</span>
      </button>
      {open && (
        <div className="blw-pop blw-list" role="listbox" ref={listRef}>
          {options.map((o) => (
            <div
              key={o.key}
              role="option"
              aria-selected={o.key === value}
              className={`blw-list-item${o.key === value ? " sel" : ""}`}
              onMouseDown={(e) => { e.preventDefault(); onPick(o.key); setOpen(false); }}
            >
              {o.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ================= the widget ================= */

type TripType = "transfer" | "hourly" | "city";

const TABS: [TripType, string][] = [
  ["transfer", "One way"],
  ["hourly", "By the hour"],
  ["city", "City to city"],
];

// Hourly hire runs 3–24 hours; 3 is the business minimum.
const HOUR_OPTIONS = Array.from({ length: 22 }, (_, i) => i + 3);

export default function BookingSearchWidget({ preselectedVehicleId = null }: { preselectedVehicleId?: number | null }) {
  const router = useRouter();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const setSearch = useBookingStore((s) => s.setSearch);

  const [tripType, setTripType] = useState<TripType>("transfer");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [hours, setHours] = useState("3");
  const [meetGreet, setMeetGreet] = useState(false);
  const [error, setError] = useState("");

  const changeTab = (value: TripType) => {
    setError("");
    setTripType(value);
  };

  const handleSearch = async () => {
    if (busy) return;
    if (!from.trim() || !date || !time) {
      setError("Please fill in date, time and pickup.");
      return;
    }
    // A one-way transfer and a city-to-city trip both need a drop-off address;
    // only an hourly hire omits it.
    if (tripType === "transfer" || tripType === "city") {
      if (!to.trim()) {
        setError(
          tripType === "city"
            ? "Please enter a drop-off address for your city-to-city trip."
            : "Please enter a drop-off address, or switch to “By the hour”.",
        );
        return;
      }
      setSearch({
        tripType,
        pickupAddress: from.trim(), dropoffAddress: to.trim(),
        date, time, meetGreet,
      }, preselectedVehicleId);
    } else {
      setSearch({
        tripType: "hourly",
        pickupAddress: from.trim(), dropoffAddress: "", hours: Number(hours),
        date, time, meetGreet,
      }, preselectedVehicleId);
    }
    const search = useBookingStore.getState().search!;
    setBusy(true); setError("");
    try {
      await qc.fetchQuery({ queryKey: ["quotes", search], queryFn: () => quoteService.create(quoteRequest(search)), staleTime: 0, retry: false });
      router.push("/booking/vehicle");
    } catch { setError("We couldn't price that trip — check your addresses"); }
    finally { setBusy(false); }
  };

  return (
    <div className="mm-search-dock blw">
      <div className="blw-tabs" role="tablist" aria-label="Trip type">
        {TABS.map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={tripType === value}
            className={`blw-tab${tripType === value ? " on" : ""}`}
            onClick={() => changeTab(value)}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="blw-panel">
        <div className="blw-fields">
          <LocationField
            label="Pickup location"
            value={from}
            onChange={setFrom}
            placeholder="Address, airport, hotel…"
          />
          {tripType === "hourly" ? (
            <ListField
              label="Duration"
              value={hours}
              display={`${hours} hours`}
              placeholder="Select duration"
              options={HOUR_OPTIONS.map((h) => ({ key: String(h), text: `${h} hours` }))}
              onPick={setHours}
            />
          ) : (
            <LocationField
              label="Drop-off location"
              value={to}
              onChange={setTo}
              placeholder="Address, airport, hotel…"
            />
          )}
          <DateField value={date} onChange={setDate} />
          <ListField
            label="Pickup time"
            value={time}
            display={time}
            placeholder="Select time"
            options={TIMES.map((t) => ({ key: t, text: t }))}
            onPick={setTime}
          />
        </div>
        <button className="blw-go" type="button" disabled={busy} aria-busy={busy} onClick={handleSearch}>
          {busy ? "Finding your cars…" : "View options"}
        </button>
      </div>

      <div className="blw-foot">
        {tripType !== "hourly" && (
          <label className="blw-check">
            <input type="checkbox" checked={meetGreet} onChange={(e) => setMeetGreet(e.target.checked)} />
            <span className="blw-check-box" />
            <span className="blw-check-label">Meet &amp; Greet at pickup</span>
          </label>
        )}
        {error && <div role="alert" className="blw-error">{error}</div>}
      </div>
    </div>
  );
}
