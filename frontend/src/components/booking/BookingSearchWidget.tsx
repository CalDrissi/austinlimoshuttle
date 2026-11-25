"use client";

import { useState, useRef, useEffect, useLayoutEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { DayPicker as ReactDayPicker } from "react-day-picker";
import "react-day-picker/style.css";
import { quoteService, quoteRequest } from "@/lib/api/quote.service";
import { ApiRequestError } from "@/lib/api/client";
import { useSiteSettings } from "@/hooks/useSiteSettings";
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
 * Shared by the expanding hero widget and the legacy AddressField (TripEditor).
 * Keystrokes are debounced and grouped under one session token for billing; if
 * Places can't load (missing/blocked key) the caller's field degrades to a
 * plain text input with no suggestions.
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

/** Close a panel when clicking anywhere outside `ref`. */
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

/* ================= expanding hero widget ================= */

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

const TIMES: string[] = [];
for (let h = 0; h < 24; h++) {
  for (const m of [0, 15, 30, 45]) {
    const hour = h % 12 || 12;
    const ampm = h < 12 ? "AM" : "PM";
    TIMES.push(`${hour}:${String(m).padStart(2, "0")} ${ampm}`);
  }
}

/** "h:mm AM/PM" -> minutes since midnight. */
function slotMinutes(t: string): number {
  const m = t.match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i);
  if (!m) return 0;
  return ((Number(m[1]) % 12) + (/PM/i.test(m[3]) ? 12 : 0)) * 60 + Number(m[2]);
}

/**
 * Austin's current wall-clock as a local Date. Trips are priced and validated
 * in America/Chicago, so "is this slot in the past" must be judged against
 * Austin's clock, not the visitor's.
 */
function austinNow(): Date {
  return new Date(new Date().toLocaleString("en-US", { timeZone: "America/Chicago" }));
}

type TripType = "transfer" | "hourly" | "city";
type Pane = "pickup" | "dropoff" | "date" | "time" | "duration";

const TABS: [TripType, string][] = [
  ["transfer", "One way"],
  ["hourly", "By the hour"],
  ["city", "City to city"],
];

// Hourly hire runs 3–24 hours; 3 is the business minimum.
const HOUR_OPTIONS = Array.from({ length: 22 }, (_, i) => i + 3);

/** Our mark for the expanded panel's idle state (original art). */
function BrandMark() {
  return (
    <svg width="36" height="36" viewBox="0 0 36 36" fill="none" aria-hidden="true">
      <circle cx="18" cy="15" r="8" stroke="#3b82d7" strokeWidth="2.4" />
      <circle cx="18" cy="15" r="2.6" fill="#3b82d7" />
      <path d="M18 23v7M11.5 32h13" stroke="#3b82d7" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

export default function BookingSearchWidget({ preselectedVehicleId = null }: { preselectedVehicleId?: number | null }) {
  const router = useRouter();
  const qc = useQueryClient();
  const site = useSiteSettings();
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

  // Which pane the panel is expanded for. `shownPane` lags on close so the
  // content stays rendered during the collapse animation.
  const [pane, setPane] = useState<Pane | null>(null);
  const lastPaneRef = useRef<Pane>("pickup");
  if (pane) lastPaneRef.current = pane;
  const shownPane = pane ?? lastPaneRef.current;

  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const fieldRefs = useRef<Partial<Record<Pane, HTMLDivElement | null>>>({});
  const triggerRefs = useRef<Partial<Record<Pane, HTMLButtonElement | null>>>({});
  const pickupInputRef = useRef<HTMLInputElement>(null);
  const dropoffInputRef = useRef<HTMLInputElement>(null);
  const timeListRef = useRef<HTMLDivElement>(null);

  // Never offer a slot that is already unbookable: for an Austin-today date,
  // drop times before now + the office minimum lead. Other dates keep the
  // full grid.
  const availableTimes = useMemo(() => {
    const day = date ? parseYmd(date) : undefined;
    if (!day) return TIMES;
    const cutoff = new Date(austinNow().getTime() + (site?.min_booking_lead_hours ?? 0) * 3_600_000);
    const startOfDay = new Date(day);
    if (startOfDay.getTime() + 24 * 3_600_000 <= cutoff.getTime()) return []; // whole day gone
    if (startOfDay.getTime() > cutoff.getTime()) return TIMES; // a future day
    return TIMES.filter((t) => startOfDay.getTime() + slotMinutes(t) * 60_000 >= cutoff.getTime());
  }, [date, site?.min_booking_lead_hours]);

  // A date change can strand an already-picked time in the past; clear it so
  // the schedule never silently holds an unbookable slot.
  useEffect(() => {
    if (time && !availableTimes.includes(time)) setTime("");
  }, [time, availableTimes]);

  const close = useCallback(() => setPane(null), []);
  useOutsideClose(rootRef, close);

  // Location suggestions follow whichever location field is active.
  const locPane = pane === "pickup" || pane === "dropoff" ? pane : null;
  const locValue = locPane === "pickup" ? from : locPane === "dropoff" ? to : "";
  const { suggestions, loading, endSession, clearSuggestions } = usePlacesSuggestions(locValue, !!locPane);
  const [activeIdx, setActiveIdx] = useState(-1);
  useEffect(() => { setActiveIdx(-1); }, [suggestions]);

  // Align the expanded content under the active field (desktop). Clamped so
  // the content block never overruns the panel; the idle placeholder ignores
  // the indent entirely (it centers against the full panel width). On stacked
  // mobile the CSS zeroes the indent.
  const [indent, setIndent] = useState(0);
  useLayoutEffect(() => {
    // Rough width of each pane's content block, for clamping the indent.
    const CONTENT_W: Record<Pane, number> = { pickup: 600, dropoff: 600, date: 360, time: 270, duration: 270 };
    const measure = () => {
      const field = pane ? fieldRefs.current[pane] : null;
      const panel = panelRef.current;
      if (!pane || !field || !panel) return;
      const raw = Math.round(field.getBoundingClientRect().left - panel.getBoundingClientRect().left) - 10;
      const max = Math.round(panel.getBoundingClientRect().width) - CONTENT_W[pane] - 36;
      setIndent(Math.max(0, Math.min(raw, max)));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [pane]);

  // Keep the panel (and the focused input) visible above the on-screen
  // keyboard when a pane opens on small screens.
  useEffect(() => {
    if (pane && window.matchMedia("(max-width: 1199.98px)").matches) {
      panelRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [pane]);

  /* ----- keyboard support for the list + calendar panes (listbox pattern:
     the container keeps focus, aria-activedescendant names the active row) ----- */
  const [listIdx, setListIdx] = useState(0);
  const listOptions = shownPane === "duration" ? HOUR_OPTIONS.map((h) => `${h} hours`) : availableTimes;
  const listValue = shownPane === "duration" ? `${hours} hours` : time;

  // When a list pane opens: focus it, start on the chosen row, bring it into view.
  useEffect(() => {
    if (pane === "time" || pane === "duration") {
      const options = pane === "duration" ? HOUR_OPTIONS.map((h) => `${h} hours`) : availableTimes;
      const chosen = pane === "duration" ? `${hours} hours` : time;
      const idx = options.indexOf(chosen);
      setListIdx(idx >= 0 ? idx : 0);
      timeListRef.current?.focus({ preventScroll: true });
      requestAnimationFrame(() => {
        timeListRef.current?.querySelector(".sel, .act")?.scrollIntoView({ block: "center" });
      });
    }
    // Opening the calendar moves focus into the day grid so arrow keys work
    // immediately (react-day-picker handles the arrows once focus is inside).
    if (pane === "date") {
      requestAnimationFrame(() => {
        panelRef.current
          ?.querySelector<HTMLElement>(
            ".rdp-selected .rdp-day_button, .rdp-today .rdp-day_button, .rdp-day_button:not([disabled])",
          )
          ?.focus();
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-run on open only
  }, [pane]);

  const closePaneToTrigger = (which: Pane) => {
    setPane(null);
    triggerRefs.current[which]?.focus();
  };

  const pickListOption = (idx: number) => {
    const value = listOptions[idx];
    if (value === undefined) return;
    if (shownPane === "duration") setHours(value.replace(/\D/g, ""));
    else setTime(value);
    closePaneToTrigger(shownPane);
  };

  const onListKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const last = listOptions.length - 1;
    const move = (to: number) => {
      const next = Math.max(0, Math.min(last, to));
      setListIdx(next);
      document.getElementById(`blw-opt-${next}`)?.scrollIntoView({ block: "nearest" });
    };
    switch (e.key) {
      case "ArrowDown": e.preventDefault(); move(listIdx + 1); break;
      case "ArrowUp": e.preventDefault(); move(listIdx - 1); break;
      case "Home": e.preventDefault(); move(0); break;
      case "End": e.preventDefault(); move(last); break;
      case "Enter":
      case " ": e.preventDefault(); pickListOption(listIdx); break;
      case "Escape": e.preventDefault(); closePaneToTrigger(shownPane); break;
    }
  };

  const changeTab = (value: TripType) => {
    setError("");
    setTripType(value);
    // Meet & Greet is only offered on point-to-point trips; leaving them must
    // drop it or an hourly quote silently carries the hidden fee.
    if (value === "hourly") setMeetGreet(false);
    if (pane === "dropoff" || pane === "duration") setPane(null);
  };

  const pickSuggestion = (s: PlaceSuggestion) => {
    if (locPane === "pickup") setFrom(s.full); else setTo(s.full);
    clearSuggestions();
    endSession();
    setPane(null);
  };

  const onLocKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") { setPane(null); (e.target as HTMLInputElement).blur(); return; }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (suggestions.length) setActiveIdx((i) => (i + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (suggestions.length) setActiveIdx((i) => (i <= 0 ? suggestions.length - 1 : i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeIdx >= 0 && suggestions[activeIdx]) pickSuggestion(suggestions[activeIdx]);
      else { setPane(null); (e.target as HTMLInputElement).blur(); }
    }
  };

  const handleSearch = async () => {
    if (busy) return;
    setPane(null);
    if (!from.trim() || !date || !time) {
      // Name the drop-off too when this trip type needs one, so the user isn't
      // sent around a second validation loop after filling the first three.
      const dropoffMissing =
        (tripType === "transfer" || tripType === "city") && !to.trim();
      setError(
        dropoffMissing
          ? "Please fill in date, time, pickup and drop-off."
          : "Please fill in date, time and pickup.",
      );
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
      if (from.trim().toLowerCase() === to.trim().toLowerCase()) {
        setError("Pickup and drop-off are the same address");
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
    } catch (e) {
      // The server says exactly what's wrong (lead time, unroutable address,
      // no vehicle for the trip) — show that, not a blanket "check addresses".
      setError(e instanceof ApiRequestError && e.message !== "Request failed"
        ? e.message
        : "We couldn't price that trip — check your addresses");
    }
    finally { setBusy(false); }
  };

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const selectedDay = date ? parseYmd(date) : undefined;
  const dateDisplay = selectedDay
    ? selectedDay.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" })
    : "";

  const locField = (which: "pickup" | "dropoff", label: string, value: string, set: (v: string) => void, inputRef: React.RefObject<HTMLInputElement | null>) => (
    <div
      className={`blw-field blw-loc${pane === which ? " live" : ""}`}
      ref={(el) => { fieldRefs.current[which] = el; }}
      onClick={() => inputRef.current?.focus()}
    >
      <span className="blw-label">{label}</span>
      <input
        ref={inputRef}
        className="blw-input"
        type="text"
        autoComplete="off"
        role="combobox"
        aria-expanded={pane === which}
        aria-autocomplete="list"
        placeholder="Address, airport, hotel…"
        value={value}
        onChange={(e) => { set(e.target.value); setPane(which); }}
        onFocus={() => setPane(which)}
        onKeyDown={onLocKeyDown}
      />
      {value !== "" && (
        <button
          type="button"
          className="blw-clear"
          aria-label={`Clear ${label.toLowerCase()}`}
          onMouseDown={(e) => e.preventDefault()}
          onClick={(e) => {
            e.stopPropagation();
            set("");
            setPane(which); // stay expanded so the user can retype immediately
            inputRef.current?.focus();
          }}
        >
          ✕
        </button>
      )}
    </div>
  );

  const triggerField = (which: Pane, label: string, display: string, placeholder: string, extraClass = "") => (
    <div
      className={`blw-field${extraClass ? ` ${extraClass}` : ""}${pane === which ? " live" : ""}`}
      ref={(el) => { fieldRefs.current[which] = el; }}
    >
      <button
        type="button"
        ref={(el) => { triggerRefs.current[which] = el; }}
        className="blw-trigger"
        aria-expanded={pane === which}
        onClick={() => setPane(pane === which ? null : which)}
        onKeyDown={(e) => { if (e.key === "Escape") setPane(null); }}
      >
        <span className="blw-label">{label}</span>
        <span className={`blw-value${display ? "" : " empty"}`}>{display || placeholder}</span>
      </button>
    </div>
  );

  /* ----- expanded-area content for each pane ----- */

  const locContent = () => {
    if (locValue.trim().length < MIN_QUERY) {
      return (
        <div className="blw-idle">
          <BrandMark />
          <p className="blw-idle-line">
            Your chauffeur, anywhere in Austin.<br />We will be there on time.
          </p>
        </div>
      );
    }
    return (
      <div className="blw-sugs" role="listbox">
        {suggestions.length ? (
          <>
            {suggestions.map((s, i) => (
              <div
                key={s.id}
                role="option"
                aria-selected={i === activeIdx}
                className={`blw-sug${i === activeIdx ? " on" : ""}`}
                onMouseEnter={() => setActiveIdx(i)}
                onMouseDown={(e) => { e.preventDefault(); pickSuggestion(s); }}
              >
                <img src={s.isAirport ? PLANE_ICON : PIN_ICON} alt="" />
                <span className="blw-sug-text">
                  <span className="blw-sug-title">{s.primary}</span>
                  {s.secondary && <span className="blw-sug-sub">{s.secondary}</span>}
                </span>
              </div>
            ))}
            <div className="blw-powered">powered by Google</div>
          </>
        ) : (
          <div className="blw-sug-empty">
            {loading ? "Searching…" : "No matches — you can enter any address."}
          </div>
        )}
      </div>
    );
  };

  const areaContent = () => {
    switch (shownPane) {
      case "pickup":
      case "dropoff":
        return locContent();
      case "date":
        return (
          <div
            className="blw-cal"
            onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); closePaneToTrigger("date"); } }}
          >
            <ReactDayPicker
              mode="single"
              selected={selectedDay}
              defaultMonth={selectedDay ?? today}
              disabled={{ before: today }}
              onSelect={(d) => { if (d) { setDate(toYmd(d)); closePaneToTrigger("date"); } }}
            />
          </div>
        );
      case "time":
      case "duration":
        return (
          <div
            className="blw-list"
            role="listbox"
            aria-label={shownPane === "duration" ? "Duration" : "Pickup time"}
            tabIndex={0}
            aria-activedescendant={listOptions.length ? `blw-opt-${listIdx}` : undefined}
            onKeyDown={onListKeyDown}
            ref={timeListRef}
          >
            {listOptions.length === 0 && (
              <div className="blw-sug-empty">No times left today — pick another date.</div>
            )}
            {listOptions.map((label, i) => (
              <div
                key={label}
                id={`blw-opt-${i}`}
                role="option"
                aria-selected={label === listValue}
                className={`blw-list-item${label === listValue ? " sel" : ""}${i === listIdx ? " act" : ""}`}
                onMouseMove={() => setListIdx(i)}
                onMouseDown={(e) => { e.preventDefault(); pickListOption(i); }}
              >
                {label}
              </div>
            ))}
          </div>
        );
    }
  };

  return (
    <div className="mm-search-dock blw" ref={rootRef}>
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

      <div className={`blw-panel${pane ? " open" : ""}`} ref={panelRef}>
        <div className="blw-bar">
          {locField("pickup", "Pickup location", from, setFrom, pickupInputRef)}
          {tripType === "hourly"
            ? triggerField("duration", "Duration", `${hours} hours`, "Select duration")
            : locField("dropoff", "Drop-off location", to, setTo, dropoffInputRef)}
          <div className="blw-sched">
            {triggerField("date", "Date", dateDisplay, "Select date")}
            {triggerField("time", "Pickup time", time, "Select time")}
          </div>
          <button className="blw-go" type="button" disabled={busy} aria-busy={busy} onClick={handleSearch}>
            {busy ? "Finding your cars…" : "View options"}
          </button>
        </div>

        <div className={`blw-expand${pane ? " open" : ""}`} aria-hidden={!pane}>
          <div className="blw-expand-clip">
            <div className="blw-area" style={{ "--blw-indent": `${indent}px` } as React.CSSProperties}>
              <button type="button" className="blw-close" aria-label="Close" onClick={close}>✕</button>
              <div className="blw-area-inner">{areaContent()}</div>
            </div>
          </div>
        </div>
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
