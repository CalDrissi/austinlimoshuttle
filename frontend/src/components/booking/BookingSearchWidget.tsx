"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Image from "next/image";
import DayPicker from "@/components/ui/DayPicker";
import TimePicker from "@/components/ui/TimePicker";
import { catalogService } from "@/lib/api/catalog.service";
import { useBookingStore } from "@/lib/booking/store";
import {
  fetchPlaceSuggestions,
  newSessionToken,
  type PlaceSuggestion,
} from "@/lib/google/places";

const PLANE_ICON = "/assets/imgs/page/homepage1/plane.png";
const PIN_ICON = "/assets/imgs/page/homepage1/building.png";

// Below this length Google predictions are too noisy to be worth a billed call.
const MIN_QUERY = 3;

/**
 * A typeable address field backed by Google Places autocomplete.
 *
 * Free text is always allowed — the backend geocodes whatever is submitted, so
 * the suggestions only save typing. Keystrokes are debounced and grouped under
 * one session token for billing; if Places can't load (missing/blocked key) the
 * field degrades to a plain text input with no dropdown.
 */
function AddressField({ label, value, onChange, placeholder }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
}) {
  const [open, setOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<PlaceSuggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const tokenRef = useRef<unknown>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reqRef = useRef(0); // guards against out-of-order responses

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => {
      document.removeEventListener("mousedown", handler);
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const runSearch = (raw: string) => {
    const q = raw.trim();
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (q.length < MIN_QUERY) {
      setSuggestions([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    debounceRef.current = setTimeout(async () => {
      const reqId = ++reqRef.current;
      try {
        if (!tokenRef.current) tokenRef.current = await newSessionToken();
        const results = await fetchPlaceSuggestions(q, tokenRef.current);
        if (reqId === reqRef.current) setSuggestions(results);
      } catch {
        // Missing/blocked key or API error — fall back to plain free text.
        if (reqId === reqRef.current) setSuggestions([]);
      } finally {
        if (reqId === reqRef.current) setLoading(false);
      }
    }, 250);
  };

  const pick = (s: PlaceSuggestion) => {
    onChange(s.full);
    setOpen(false);
    setSuggestions([]);
    tokenRef.current = null; // a selection ends the billing session
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
        onChange={(e) => { onChange(e.target.value); setOpen(true); runSearch(e.target.value); }}
        onFocus={() => { setOpen(true); if (!suggestions.length) runSearch(value); }}
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

type TripType = "transfer" | "hourly" | "city";

const TABS: [TripType, string][] = [
  ["transfer", "Transfer"],
  ["hourly", "By the hour"],
  ["city", "City to City"],
];

const HOUR_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];

/** A city picker backed by the back-office routes. */
function CityField({ label, value, onChange, cities, placeholder }: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  cities: string[];
  placeholder: string;
}) {
  return (
    <div className="search-inputs">
      <label>{label}</label>
      <select
        className="search-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ border: "none", background: "transparent", width: "100%", cursor: "pointer" }}
      >
        <option value="">{placeholder}</option>
        {cities.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
    </div>
  );
}

export default function BookingSearchWidget() {
  const router = useRouter();
  const setSearch = useBookingStore((s) => s.setSearch);

  const [tripType, setTripType] = useState<TripType>("transfer");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [hours, setHours] = useState("3");
  const [meetGreet, setMeetGreet] = useState(false);
  const [error, setError] = useState("");

  // Cities for the City-to-City tab. Loaded up front (cheap, cached) so the tab
  // only appears once the back office has at least one route to offer.
  const { data: cityData } = useQuery({
    queryKey: ["city-routes"],
    queryFn: () => catalogService.cityRoutes(),
    staleTime: 5 * 60 * 1000,
  });
  const cities = cityData?.cities ?? [];
  const tabs = cities.length ? TABS : TABS.filter(([v]) => v !== "city");

  // From/To hold addresses for a transfer but city names for city-to-city;
  // clear them when crossing that boundary so a stale value can't leak in.
  const changeTab = (value: TripType) => {
    setError("");
    if ((value === "city") !== (tripType === "city")) { setFrom(""); setTo(""); }
    setTripType(value);
  };

  const handleSearch = () => {
    if (tripType === "city") {
      if (!from || !to) {
        setError("Choose both a pickup and a drop-off city.");
        return;
      }
      if (from === to) {
        setError("Pickup and drop-off cities must be different.");
        return;
      }
      if (!date || !time) {
        setError("Please fill in date and time.");
        return;
      }
      setSearch({
        tripType: "city",
        pickupAddress: from, dropoffAddress: to,
        date, time, meetGreet: false,
      });
      router.push("/booking/vehicle");
      return;
    }

    if (!from.trim() || !date || !time) {
      setError("Please fill in date, time and pickup.");
      return;
    }
    if (tripType === "transfer") {
      if (!to.trim()) {
        setError("Please enter a drop-off address, or switch to “By the hour”.");
        return;
      }
      setSearch({
        tripType: "transfer",
        pickupAddress: from.trim(), dropoffAddress: to.trim(),
        date, time, meetGreet,
      });
    } else {
      setSearch({
        tripType: "hourly",
        pickupAddress: from.trim(), dropoffAddress: "", hours: Number(hours),
        date, time, meetGreet,
      });
    }
    router.push("/booking/vehicle");
  };

  return (
    <div className="mm-search-dock">
      {/* Segmented control, docked directly above the search card. */}
      <div className="mm-trip-tabs">
        {tabs.map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => changeTab(value)}
            style={{
              padding: "8px 18px", borderRadius: 7, fontSize: 14, fontWeight: 600,
              cursor: "pointer", border: "none", transition: "all .15s",
              background: tripType === value ? "#0E0E0E" : "transparent",
              color: tripType === value ? "#fff" : "#4a5568",
              boxShadow: tripType === value ? "0 1px 3px rgba(0,0,0,.18)" : "none",
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="box-search-ride">
        <div className="search-item search-date">
          <div className="search-icon"><span className="item-icon icon-date" /></div>
          <div className="search-inputs">
            <label>Date</label>
            <DayPicker value={date} onChange={setDate} placeholder="Select date" />
          </div>
        </div>

        <div className="search-item search-time">
          <div className="search-icon"><span className="item-icon icon-time" /></div>
          <div className="search-inputs">
            <label>Time</label>
            <TimePicker value={time} onChange={setTime} />
          </div>
        </div>

        <div className="search-item search-from">
          <div className="search-icon"><span className="item-icon icon-from" /></div>
          {tripType === "city" ? (
            <CityField label="From" value={from} onChange={setFrom} cities={cities} placeholder="Pickup city" />
          ) : (
            <AddressField label="From" value={from} onChange={setFrom} placeholder="Pickup address" />
          )}
        </div>

        {tripType === "transfer" && (
          <div className="search-item search-to">
            <div className="search-icon"><span className="item-icon icon-to" /></div>
            <AddressField label="To" value={to} onChange={setTo} placeholder="Drop-off address" />
          </div>
        )}
        {tripType === "city" && (
          <div className="search-item search-to">
            <div className="search-icon"><span className="item-icon icon-to" /></div>
            <CityField label="To" value={to} onChange={setTo} cities={cities} placeholder="Drop-off city" />
          </div>
        )}
        {tripType === "hourly" && (
          <div className="search-item search-to search-hours">
            <div className="search-icon"><span className="item-icon icon-time" /></div>
            <div className="search-inputs">
              <label>Hours</label>
              <select
                className="search-input"
                value={hours}
                onChange={(e) => setHours(e.target.value)}
                style={{ border: "none", background: "transparent", width: "100%", cursor: "pointer" }}
              >
                {HOUR_OPTIONS.map((h) => (
                  <option key={h} value={h}>{h} hour{h > 1 ? "s" : ""}</option>
                ))}
              </select>
            </div>
          </div>
        )}

        {/* Meet & Greet doesn't apply to the flat city-to-city fare. */}
        {tripType !== "city" && (
          <div className="search-item search-meet">
            <label className="mm-check">
              <input type="checkbox" checked={meetGreet} onChange={(e) => setMeetGreet(e.target.checked)} />
              <span className="mm-check-box" />
              <span className="mm-check-label">Meet &amp; Greet</span>
            </label>
          </div>
        )}

        <div className="search-item search-button">
          <button className="btn btn-search" type="button" onClick={handleSearch}>
            <Image src="/assets/imgs/template/icons/search.svg" alt="" width={16} height={16} />
            Search
          </button>
        </div>

        {error && <div className="mm-search-error">{error}</div>}
      </div>
    </div>
  );
}
