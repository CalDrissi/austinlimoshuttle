"use client";

import Link from "next/link";
import Image from "next/image";
import { useQuery } from "@tanstack/react-query";
import { useSiteSettings } from "@/hooks/useSiteSettings";
import { useAuth } from "@/hooks/useAuth";
import { telHref } from "@/lib/api/site.service";
import { catalogService } from "@/lib/api/catalog.service";

/**
 * Site footer.
 *
 * The template's version carried eleven `href="#"` placeholders, a phone app
 * that does not exist, and columns for New York, London, Berlin, Los Angeles
 * and Paris. Everything here now goes somewhere real, and contact details come
 * from the dashboard so the office can change them without a deploy.
 */

/** Where M&M actually drives. Long-distance transfers are a real product line. */
const SERVICE_AREAS = [
  "Austin",
  "Round Rock",
  "Georgetown",
  "San Marcos",
  "San Antonio",
  "Houston",
];

export default function Footer() {
  const site = useSiteSettings();
  const { user } = useAuth();

  // The real fleet, not a hardcoded copy that drifts when the office renames a
  // vehicle. Same query key as the fleet page, so this is usually a cache hit.
  const { data: fleet } = useQuery({
    queryKey: ["vehicles"],
    queryFn: () => catalogService.listVehicles(),
    staleTime: 60 * 60 * 1000,
  });

  const socials = [
    { url: site?.facebook, className: "icon-facebook", label: "Facebook" },
    { url: site?.twitter, className: "icon-twitter", label: "Twitter" },
    { url: site?.instagram, className: "icon-instagram", label: "Instagram" },
    { url: site?.linkedin, className: "icon-linkedin", label: "LinkedIn" },
  ].filter((s) => s.url);

  return (
    <footer className="footer">
      <div className="footer-1">
        <div className="container-sub">
          <div className="box-footer-top">
            <div className="row align-items-center">
              <div className="col-lg-6 col-md-6 text-md-start text-center mb-15">
                <div className="d-flex align-items-center justify-content-md-start justify-content-center">
                  <Link className="mr-30" href="/">
                    <Image src="/assets/imgs/template/mm-logo-white.png" alt="M&amp;M Austin Limousine"
                      width={150} height={66} />
                  </Link>
                  {site?.contact_phone && (
                    <a className="text-14-medium call-phone color-white hover-up"
                       href={telHref(site.contact_phone)}>
                      {site.contact_phone}
                    </a>
                  )}
                </div>
              </div>

              {/* A social icon with no URL is a dead link, so it renders nothing. */}
              {socials.length > 0 && (
                <div className="col-lg-6 col-md-6 text-md-end text-center mb-15">
                  <div className="d-flex align-items-center justify-content-md-end justify-content-center">
                    <span className="text-18-medium color-white mr-10">Follow Us</span>
                    {socials.map((s) => (
                      <a key={s.className} className={`icon-socials ${s.className}`}
                         href={s.url} aria-label={s.label}
                         target="_blank" rel="noopener noreferrer" />
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Three balanced columns for the Home + Fleet storefront. The old
              "Company" column (about / services / contact / terms) was removed
              with those pages; its one surviving link duplicated this Fleet
              column, so the whole column is gone rather than left half-empty. */}
          <div className="row mb-40">
            <div className="col-lg-4 col-md-6 mb-30">
              <h5 className="text-18-medium color-white mb-20">Our Fleet</h5>
              <ul className="menu-footer">
                {(fleet ?? []).map((v) => (
                  <li key={v.slug}><Link href={`/fleet/${v.slug}`}>{v.name}</Link></li>
                ))}
                <li><Link href="/fleet">View the full fleet</Link></li>
              </ul>
            </div>

            <div className="col-lg-4 col-md-6 mb-30">
              <h5 className="text-18-medium color-white mb-20">Where We Drive</h5>
              {/* Plain text: there are no per-city pages, and a city name that
                  links somewhere else is a lie waiting to be clicked. */}
              <ul className="menu-footer">
                {SERVICE_AREAS.map((area) => (
                  <li key={area}><span className="color-grey">{area}</span></li>
                ))}
              </ul>
            </div>

            <div className="col-lg-4 col-md-6 mb-30">
              <h5 className="text-18-medium color-white mb-20">Book &amp; Manage</h5>
              <ul className="menu-footer">
                {/* The quote starts with the search widget on the home page —
                    deep-linking into the funnel lands on an empty step. */}
                <li><Link href="/">Get a quote</Link></li>
                {user ? (
                  <>
                    <li><Link href="/account">My account</Link></li>
                    <li><Link href="/account?tab=bookings">My bookings</Link></li>
                  </>
                ) : (
                  <>
                    <li><Link href="/login">Sign in</Link></li>
                    <li><Link href="/register">Create an account</Link></li>
                  </>
                )}
                {site?.contact_email && (
                  <li><a href={`mailto:${site.contact_email}`}>{site.contact_email}</a></li>
                )}
              </ul>
            </div>
          </div>
        </div>
      </div>

      <div className="footer-2">
        <div className="container-sub">
          <div className="footer-bottom">
            <div className="row align-items-center">
              <div className="col-md-6 text-center text-md-start">
                <span className="text-14 color-white">
                  © {new Date().getFullYear()} M&amp;M Austin Limousine
                </span>
              </div>
              <div className="col-md-6 text-center text-md-end">
                <ul className="menu-bottom justify-content-center justify-content-md-end">
                  <li><Link href="/">Home</Link></li>
                  <li><Link href="/fleet">Our fleet</Link></li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      </div>
    </footer>
  );
}
