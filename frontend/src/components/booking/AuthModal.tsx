"use client";

import { useEffect, useRef } from "react";
import { useState } from "react";
import { LoginFields, RegisterFields } from "@/components/auth/AuthForms";

/**
 * In-flow sign-in / create-account dialog (owner decision: auth never
 * navigates away from the booking flow). Desktop: centred white dialog;
 * phones: bottom sheet. Esc, overlay click and the X all dismiss; focus is
 * trapped while open. Success just closes — useAuth() flips the rail.
 */
export default function AuthModal({ open, initialTab, onClose }: {
  open: boolean;
  initialTab: "login" | "register";
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"login" | "register">(initialTab);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => { if (open) setTab(initialTab); }, [open, initialTab]);

  useEffect(() => {
    if (!open) return;
    const scrollY = window.scrollY;
    const body = document.body;
    const previous = { overflow: body.style.overflow, position: body.style.position, top: body.style.top, width: body.style.width };
    Object.assign(body.style, { overflow: "hidden", position: "fixed", top: `-${scrollY}px`, width: "100%" });
    panelRef.current?.querySelector<HTMLElement>("input, button")?.focus();
    const keydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); }
      if (e.key === "Tab") {
        const items = panelRef.current?.querySelectorAll<HTMLElement>("a[href], button:not(:disabled), input:not(:disabled)");
        if (!items?.length) return;
        const first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      Object.assign(body.style, previous);
      window.scrollTo(0, scrollY);
      document.removeEventListener("keydown", keydown);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="mm-auth-layer" role="presentation">
      <div className="mm-auth-backdrop" onClick={onClose} aria-hidden="true" />
      <div ref={panelRef} className="mm-auth-panel" role="dialog" aria-modal="true" aria-labelledby="mm-auth-title">
        <div className="mm-auth-head">
          <span id="mm-auth-title">{tab === "login" ? "Sign in" : "Create your account"}</span>
          <button type="button" className="mm-auth-close" aria-label="Close" onClick={onClose}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="m6 6 12 12M6 18 18 6" /></svg>
          </button>
        </div>
        <div className="mm-auth-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={tab === "login"} className={tab === "login" ? "on" : ""} onClick={() => setTab("login")}>Sign in</button>
          <button type="button" role="tab" aria-selected={tab === "register"} className={tab === "register" ? "on" : ""} onClick={() => setTab("register")}>Create account</button>
        </div>
        <div className="mm-auth-body">
          {tab === "login"
            ? <LoginFields idPrefix="modal-login" onSuccess={onClose} />
            : <RegisterFields onSuccess={onClose} />}
          <p className="mm-auth-guest">No account needed to book — close this window to continue as a guest.</p>
        </div>
      </div>
    </div>
  );
}
