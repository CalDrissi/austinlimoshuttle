"use client";

import Link from "next/link";
import Image from "next/image";
import { useState, useRef, useEffect } from "react";
import { usePathname } from "next/navigation";
import { authService } from "@/lib/api/auth.service";
import { notify } from "@/lib/feedback";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { useSiteSettings } from "@/hooks/useSiteSettings";
import { telHref } from "@/lib/api/site.service";

const MENU = [{ label: "Home", href: "/" }, { label: "Our fleet", href: "/fleet" }];

export default function Header() {
  const { user } = useAuth();
  const site = useSiteSettings();
  const qc = useQueryClient();
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const close = () => setMobileOpen(false);

  useEffect(() => { setMobileOpen(false); setAccountOpen(false); }, [pathname]);
  useEffect(() => {
    const outside = (e: PointerEvent) => {
      if (!accountRef.current?.contains(e.target as Node)) setAccountOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, []);
  useEffect(() => {
    if (!mobileOpen) return;
    const scrollY = window.scrollY;
    const body = document.body;
    const previous = { overflow: body.style.overflow, position: body.style.position, top: body.style.top, width: body.style.width };
    Object.assign(body.style, { overflow: "hidden", position: "fixed", top: `-${scrollY}px`, width: "100%" });
    panelRef.current?.querySelector<HTMLElement>("button, a")?.focus();
    const keydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); setMobileOpen(false); }
      if (e.key === "Tab") {
        const items = panelRef.current?.querySelectorAll<HTMLElement>("a[href], button:not(:disabled)");
        if (!items?.length) return;
        const first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    const desktop = window.matchMedia("(min-width: 1200px)");
    const resize = () => { if (desktop.matches) setMobileOpen(false); };
    document.addEventListener("keydown", keydown);
    desktop.addEventListener("change", resize);
    return () => {
      Object.assign(body.style, previous);
      window.scrollTo(0, scrollY);
      document.removeEventListener("keydown", keydown);
      desktop.removeEventListener("change", resize);
      toggleRef.current?.focus();
    };
  }, [mobileOpen]);

  const logout = async () => {
    if (signingOut) return;
    close(); setAccountOpen(false); setSigningOut(true);
    try {
      await authService.logout(); qc.setQueryData(["me"], null);
      qc.removeQueries({ queryKey: ["my-bookings"] }); qc.removeQueries({ queryKey: ["my-cards"] });
      notify("You've been signed out");
    } catch { notify("Could not sign out — please try again."); }
    finally { setSigningOut(false); }
  };
  const callButton = site?.contact_phone ? <a className="mm-header-call" href={telHref(site.contact_phone)} onClick={close} aria-label={`Call us at ${site.contact_phone}`}><PhoneIcon /><span>Call us · {site.contact_phone}</span></a> : null;

  return <>
    <header className="mm-storefront-header">
      <div className="container mm-header-row">
        <Link href="/" className="mm-header-logo" aria-label="M&M Austin Limousine home"><Image src="/assets/imgs/template/mm-logo-white.png" alt="M&M Austin Limousine" width={150} height={66} priority /></Link>
        <nav className="mm-desktop-nav" aria-label="Main navigation">{MENU.map(item => <Link key={item.href} href={item.href} aria-current={pathname === item.href ? "page" : undefined}>{item.label}</Link>)}</nav>
        <div className="mm-header-actions">
          {callButton}
          {user ? <div className="mm-account-menu" ref={accountRef} onKeyDown={e => { if (e.key === "Escape") { setAccountOpen(false); accountRef.current?.querySelector("button")?.focus(); } }}>
            <button className="mm-header-account" aria-expanded={accountOpen} aria-controls="account-links" onClick={() => setAccountOpen(open => !open)}>Account · {user.first_name || "My account"} ▾</button>
            {accountOpen && <div id="account-links" className="mm-account-links"><Link href="/account" onClick={() => setAccountOpen(false)}>My account</Link><Link href="/account?tab=bookings" onClick={() => setAccountOpen(false)}>My bookings</Link><button onClick={logout} disabled={signingOut}>{signingOut ? "Signing out…" : "Sign out"}</button></div>}
          </div> : <Link className="mm-header-account" href="/login">Sign in</Link>}
        </div>
        <button ref={toggleRef} type="button" className="mm-menu-toggle" aria-label={mobileOpen ? "Close menu" : "Open menu"} aria-expanded={mobileOpen} aria-controls="storefront-mobile-menu" onClick={() => setMobileOpen(open => !open)}><MenuIcon open={mobileOpen} /></button>
      </div>
    </header>
    {mobileOpen && <div className="mm-mobile-layer">
      <div className="mm-menu-backdrop" onClick={close} aria-hidden="true" />
      <div ref={panelRef} id="storefront-mobile-menu" className="mm-mobile-panel" role="dialog" aria-modal="true" aria-labelledby="mm-menu-title">
        <div className="mm-mobile-panel-heading"><span id="mm-menu-title">Menu</span><button type="button" className="mm-menu-close" aria-label="Close menu" onClick={close}><MenuIcon open /></button></div>
        <nav aria-label="Mobile navigation">{MENU.map(item => <Link key={item.href} href={item.href} onClick={close} aria-current={pathname === item.href ? "page" : undefined}>{item.label}</Link>)}</nav>
        <div className="mm-mobile-account"><span className="mm-menu-section-label">{user ? "Your account" : "Account"}</span>
          {user ? <><Link href="/account" onClick={close}>My account</Link><Link href="/account?tab=bookings" onClick={close}>My bookings</Link><button onClick={logout} disabled={signingOut}>{signingOut ? "Signing out…" : "Sign out"}</button></> : <Link href="/login" onClick={close}>Sign in</Link>}
        </div>
        {callButton && <div className="mm-mobile-contact">{callButton}</div>}
      </div>
    </div>}
  </>;
}

function MenuIcon({ open }: { open: boolean }) {
  return <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">{open ? <path d="m6 6 12 12M6 18 18 6" /> : <path d="M4 6h16M4 12h16M4 18h16" />}</svg>;
}

// Inline so the icon inherits the button's text colour (currentColor) and flips
// correctly on the btn-default hover state (white → dark), which a static
// background SVG could not do.
function PhoneIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true"
         style={{ flexShrink: 0 }}>
      <path d="M6.6 10.8c1.4 2.8 3.8 5.2 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1C10.6 21 3 13.4 3 4c0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1l-2.3 2.2z"
            fill="currentColor" />
    </svg>
  );
}
