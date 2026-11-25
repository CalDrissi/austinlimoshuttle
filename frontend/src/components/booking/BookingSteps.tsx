"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useBookingStore, useHydrated } from "@/lib/booking/store";

const STEPS = [
  { label: "Vehicle", href: "/booking/vehicle", icon: "icon-vehicle", num: "01" },
  { label: "Extras", href: "/booking/extra", icon: "icon-extra", num: "02" },
  { label: "Details", href: "/booking/passenger", icon: "icon-pax", num: "03" },
  { label: "Payment", href: "/booking/payment", icon: "icon-payment", num: "04" },
];

/** "YYYY-MM-DD" -> "Fri, Nov 28" without the UTC shift of new Date(string). */
function shortDate(value: string): string {
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return value;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
    .toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

/** Centered trip-summary pills (pickup → drop-off | date · time) with an edit
 *  link back to the homepage widget. */
function TripPills() {
  const search = useBookingStore((s) => s.search);
  const hydrated = useHydrated();
  if (!hydrated || !search) return null;
  return (
    <div className="blv-pills">
      <span className="blv-pill blv-pill-route">
        <b>{search.pickupAddress}</b>
        {search.tripType === "hourly"
          ? <em>{search.hours} hours</em>
          : <><span className="blv-pill-arrow" aria-hidden="true">→</span><b>{search.dropoffAddress}</b></>}
      </span>
      <span className="blv-pill">{shortDate(search.date)} · {search.time}</span>
      <Link className="blv-pill-edit" href="/">Edit</Link>
    </div>
  );
}

export default function BookingSteps() {
  const pathname = usePathname();
  const currentIdx = STEPS.findIndex((s) => s.href === pathname);

  return (
    <section className="section pt-20">
      <div className="container-sub">
        <TripPills />
        <div className="box-booking-tabs">
          {STEPS.map((step, i) => (
            <div className="item-tab" key={step.href}>
              <Link href={step.href}>
                <div className={`box-tab-step${i === currentIdx ? " active" : ""}${i < currentIdx ? " done" : ""}`}>
                  <div className="icon-tab">
                    <span className={`icon-book ${step.icon}`} />
                    <span className="text-tab">{step.label}</span>
                  </div>
                  <div className="number-tab">
                    <span>{step.num}</span>
                  </div>
                </div>
              </Link>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
