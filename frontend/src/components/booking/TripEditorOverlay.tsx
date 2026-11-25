"use client";

import { useEffect, useRef } from "react";
import type { Search } from "@/lib/booking/store";
import TripEditor from "./TripEditor";

/** The one presentation of the trip editor: a dialog overlay above the current
 *  step (opened from the header pills and every rail's "Edit trip" button).
 *  Esc and the backdrop close it; focus starts inside. */
export default function TripEditorOverlay({ search, onClose }: { search: Search; onClose: () => void }) {
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    panelRef.current?.querySelector<HTMLElement>("input, select, button")?.focus();
    const keydown = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", keydown);
    return () => document.removeEventListener("keydown", keydown);
  }, [onClose]);

  return (
    <div className="mm-auth-layer" role="presentation">
      <div className="mm-auth-backdrop" onClick={onClose} aria-hidden="true" />
      <div ref={panelRef} className="mm-auth-panel" role="dialog" aria-modal="true" aria-label="Edit your trip">
        <TripEditor search={search} onClose={onClose} />
      </div>
    </div>
  );
}
