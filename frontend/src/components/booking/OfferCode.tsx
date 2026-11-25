"use client";

import { useState } from "react";

/** The flow's ONE offer-code surface (payment step only). No codes exist yet,
 *  so every entry gets the honest "not valid" — never a fake discount. */
export default function OfferCode() {
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState("");

  return (
    <div style={{ marginBottom: 20 }}>
      <button type="button" className="btn btn-link" style={{ padding: 0 }}
              aria-expanded={open}
              onClick={() => { setOpen((o) => !o); setMsg(""); }}>
        Have an offer code?
      </button>
      {open && (
        <div style={{ display: "flex", gap: 8, marginTop: 8, maxWidth: 360 }}>
          <input className="form-control" placeholder="Offer code" value={code}
                 onChange={(e) => { setCode(e.target.value); setMsg(""); }} />
          <button type="button" className="btn btn-border"
                  onClick={() => setMsg(code.trim() ? "This code is not valid." : "Enter an offer code.")}>
            Apply
          </button>
        </div>
      )}
      {open && msg && <p role="alert" className="text-14" style={{ color: "#c0392b", margin: "6px 0 0" }}>{msg}</p>}
    </div>
  );
}
