"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useBookingStore, useHydrated } from "@/lib/booking/store";

const STEPS = [
  { label: "Vehicle", href: "/booking/vehicle", icon: "icon-vehicle", num: "01" },
  { label: "Trip details", href: "/booking/extra", icon: "icon-extra", num: "02" },
  { label: "Passenger", href: "/booking/passenger", icon: "icon-pax", num: "03" },
  { label: "Payment", href: "/booking/payment", icon: "icon-payment", num: "04" },
];

export default function BookingSteps() {
  const pathname = usePathname();
  const hydrated = useHydrated();
  const quote = useBookingStore((s) => s.quote);
  const contact = useBookingStore((s) => s.contact);
  const currentIdx = STEPS.findIndex((s) => s.href === pathname);

  // The vehicle step matches Blacklane's anatomy exactly: trip pills in the
  // flow header, no step bar. Later steps keep the bar for back-navigation.
  if (pathname === "/booking/vehicle") return null;

  // After the booking is placed the funnel is OVER: the stepper is a plain
  // progress record, never a way back into a cleared draft.
  const settled = pathname === "/booking/confirmation";

  // How far forward the stepper may jump: each step is reachable only once the
  // steps before it hold what they collect. Back-navigation is always allowed.
  const phoneOk = (contact.phone ?? "").replace(/\D/g, "").length >= 7;
  const maxReachable = !hydrated || !quote ? 0 : phoneOk ? 3 : 2;

  return (
    <section className="section pt-20">
      <div className="container-sub">
        <div className="box-booking-tabs">
          {STEPS.map((step, i) => {
            const isCurrent = i === currentIdx;
            const done = settled || i < currentIdx;
            const clickable = !settled && !isCurrent && (i < currentIdx || i <= maxReachable);
            const face = (
              <div className={`box-tab-step${isCurrent ? " active" : ""}${done ? " done" : ""}${!clickable && !isCurrent ? " locked" : ""}`}>
                <div className="icon-tab">
                  <span className={`icon-book ${step.icon}`} />
                  <span className="text-tab">{step.label}</span>
                </div>
                <div className="number-tab">
                  <span>{step.num}</span>
                </div>
              </div>
            );
            return (
              <div className="item-tab" key={step.href}>
                {clickable
                  ? <Link href={step.href}>{face}</Link>
                  : <div aria-current={isCurrent ? "step" : undefined} aria-disabled={!isCurrent || undefined}>{face}</div>}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
