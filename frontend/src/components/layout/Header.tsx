"use client";

import Link from "next/link";
import Image from "next/image";
import { useState, useRef, useEffect } from "react";
import { authService } from "@/lib/api/auth.service";
import { notify } from "@/lib/feedback";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { useSiteSettings } from "@/hooks/useSiteSettings";
import { telHref } from "@/lib/api/site.service";

// Ported from the template header (design-reference/index.html): a services
// dropdown, a "For business" dropdown, and two flat links, with a sign-in
// button on the right.
interface MenuItem {
  label: string;
  href: string;
  children?: { label: string; href: string }[];
}

// The storefront currently ships two pages — Home and the fleet — so the nav is
// two flat links. The former services / for-business / for-chauffeurs / help
// entries pointed at marketing pages that have been removed; rather than leave
// orphaned dropdowns or dead links, the menu is rebuilt to match the live site.
const MENU: MenuItem[] = [
  { label: "Home", href: "/" },
  { label: "Our fleet", href: "/fleet" },
];

export default function Header() {
  const { user } = useAuth();
  const site = useSiteSettings();
  const qc = useQueryClient();
  const [accountOpen, setAccountOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const accountRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const outside = (e: MouseEvent) => { if (!accountRef.current?.contains(e.target as Node)) setAccountOpen(false); };
    document.addEventListener("mousedown", outside);
    return () => document.removeEventListener("mousedown", outside);
  }, []);
  const logout = async () => {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await authService.logout(); qc.setQueryData(["me"], null);
      qc.removeQueries({ queryKey: ["my-bookings"] }); qc.removeQueries({ queryKey: ["my-cards"] });
      setAccountOpen(false); setMobileOpen(false); notify("You've been signed out");
    } catch { notify("Could not sign out — please try again."); }
    finally { setSigningOut(false); }
  };
  const [mobileOpen, setMobileOpen] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);
  const close = () => setMobileOpen(false);

  return (
    <>
      <div className={`body-overlay-1${mobileOpen ? " active" : ""}`} onClick={close} />

      <header className="header sticky-bar">
        <div className="container">
          <div className="main-header">
            <div className="header-left">
              <div className="header-logo">
                <Link className="d-flex" href="/">
                  <Image src="/assets/imgs/template/mm-logo-white.png" alt="M&amp;M Austin Limousine"
                         width={150} height={66} priority />
                </Link>
              </div>

              <div className="header-nav">
                <nav className="nav-main-menu d-none d-xl-block">
                  <ul className="main-menu">
                    {MENU.map((item) => (
                      <li key={item.label} className={item.children ? "has-children" : ""}>
                        <Link href={item.href}>{item.label}</Link>
                        {item.children && (
                          <ul className="sub-menu">
                            {item.children.map((c) => (
                              <li key={c.label}><Link href={c.href}>{c.label}</Link></li>
                            ))}
                          </ul>
                        )}
                      </li>
                    ))}
                  </ul>
                </nav>

                <button
                  type="button"
                  aria-label={mobileOpen ? "Close menu" : "Open menu"}
                  aria-expanded={mobileOpen}
                  aria-controls="storefront-mobile-menu"
                  className={`burger-icon burger-icon-white${mobileOpen ? " burger-close" : ""}`}
                  onClick={() => setMobileOpen(!mobileOpen)}
                >
                  <span className="burger-icon-mid" />
                  <span className="burger-icon-bottom" />
                </button>
              </div>

              <div className="header-right">
                {/* A blank number renders nothing rather than a dead tel: link. */}
                {site?.contact_phone && (
                  <a className="btn btn-default hover-up d-none d-md-inline-flex align-items-center align-middle mr-10"
                     href={telHref(site.contact_phone)} aria-label={`Call us at ${site.contact_phone}`}>
                    <PhoneIcon />
                    <span className="ms-2">{site.contact_phone}</span>
                  </a>
                )}
                <div className="box-button-login d-inline-block align-middle">
                  {user ? <div className="mm-account-menu" ref={accountRef} onKeyDown={(e) => { if (e.key === "Escape") { setAccountOpen(false); accountRef.current?.querySelector("button")?.focus(); } }}>
                    <button className="btn btn-default" aria-expanded={accountOpen} aria-controls="account-links" onClick={() => setAccountOpen(!accountOpen)}>
                      <span className="mm-account-avatar" aria-hidden="true">{(user.first_name || user.email)[0].toUpperCase()}</span>
                      Account · {user.first_name || "My account"} ▾
                    </button>
                    {accountOpen && <div id="account-links" className="mm-account-links">
                      <Link href="/account" onClick={() => setAccountOpen(false)}>My account</Link>
                      <Link href="/account?tab=bookings" onClick={() => setAccountOpen(false)}>My bookings</Link>
                      <button onClick={logout} disabled={signingOut}>{signingOut ? "Signing out…" : "Sign out"}</button>
                    </div>}
                  </div> : <Link className="btn btn-default hover-up" href="/login">Sign in</Link>}
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Mobile nav */}
      <div id="storefront-mobile-menu" className={`mobile-header-active mobile-header-wrapper-style${mobileOpen ? " sidebar-visible" : ""}`}>
        <div className="mobile-header-wrapper-inner">
          <div className="mobile-header-content-area">
            <div className="perfect-scroll">
              <div className="mobile-menu-wrap mobile-header-border">
                <nav className="mt-15">
                  <ul className="mobile-menu font-heading">
                    {MENU.map((item, i) => (
                      <li key={item.label} className={item.children ? "has-children" : ""}>
                        {item.children && (
                          <span
                            className="menu-expand"
                            onClick={() => setExpanded(expanded === i ? null : i)}
                          >
                            ▾
                          </span>
                        )}
                        <Link href={item.href} onClick={close}>{item.label}</Link>
                        {item.children && (
                          <ul className="sub-menu" style={{ display: expanded === i ? "block" : "none" }}>
                            {item.children.map((c) => (
                              <li key={c.label}><Link href={c.href} onClick={close}>{c.label}</Link></li>
                            ))}
                          </ul>
                        )}
                      </li>
                    ))}
                  </ul>
                </nav>
              </div>
              <div className="site-copyright mt-30">
                {site?.contact_phone && (
                  <a className="btn btn-default hover-up w-100 d-inline-flex align-items-center justify-content-center mb-10"
                     href={telHref(site.contact_phone)} onClick={close}
                     aria-label={`Call us at ${site.contact_phone}`}>
                    <PhoneIcon />
                    <span className="ms-2">Call us · {site.contact_phone}</span>
                  </a>
                )}
                <Link href={user ? "/account" : "/login"} onClick={close}
                      className="btn btn-default hover-up w-100">
                  {user ? "My account" : "Sign in"}
                </Link>
                {user && <><Link className="btn btn-default w-100 mt-10" href="/account?tab=bookings" onClick={close}>My bookings</Link><button className="btn btn-default w-100 mt-10" onClick={logout} disabled={signingOut}>Sign out</button></>}
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
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
