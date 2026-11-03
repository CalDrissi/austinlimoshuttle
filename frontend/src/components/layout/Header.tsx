"use client";

import Link from "next/link";
import Image from "next/image";
import { useState } from "react";
import { useAuth } from "@/hooks/useAuth";

// Ported from the template header (design-reference/index.html): a services
// dropdown, a "For business" dropdown, and two flat links, with a language
// selector and a sign-in button on the right.
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

                <div
                  className={`burger-icon burger-icon-white${mobileOpen ? " burger-close" : ""}`}
                  onClick={() => setMobileOpen(!mobileOpen)}
                >
                  <span className="burger-icon-mid" />
                  <span className="burger-icon-bottom" />
                </div>
              </div>

              <div className="header-right">
                <div className="d-none d-xxl-inline-block box-dropdown-cart align-middle mr-10">
                  <span className="text-14-medium icon-list icon-account">
                    <span className="text-14-medium color-white arrow-down">EN</span>
                  </span>
                  <div className="dropdown-account">
                    <ul>
                      <li><a className="font-md" href="#">English</a></li>
                      <li><a className="font-md" href="#">Español</a></li>
                      <li><a className="font-md" href="#">Français</a></li>
                    </ul>
                  </div>
                </div>
                <div className="box-button-login d-inline-block align-middle">
                  <Link className="btn btn-default hover-up" href={user ? "/account" : "/login"}>
                    {user ? (user.first_name || "My account") : "Sign in"}
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Mobile nav */}
      <div className={`mobile-header-active mobile-header-wrapper-style${mobileOpen ? " sidebar-visible" : ""}`}>
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
                <Link href={user ? "/account" : "/login"} onClick={close}
                      className="btn btn-default hover-up w-100">
                  {user ? (user.first_name || "My account") : "Sign in"}
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
