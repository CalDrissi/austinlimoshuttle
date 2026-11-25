"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const STEPS = [
  { label: "Vehicle", href: "/booking/vehicle", icon: "icon-vehicle", num: "01" },
  { label: "Extras", href: "/booking/extra", icon: "icon-extra", num: "02" },
  { label: "Details", href: "/booking/passenger", icon: "icon-pax", num: "03" },
  { label: "Payment", href: "/booking/payment", icon: "icon-payment", num: "04" },
];

export default function BookingSteps() {
  const pathname = usePathname();
  const currentIdx = STEPS.findIndex((s) => s.href === pathname);

  // The vehicle step matches Blacklane's anatomy exactly: trip pills in the
  // flow header, no step bar. Later steps keep the bar for back-navigation.
  if (pathname === "/booking/vehicle") return null;

  return (
    <section className="section pt-20">
      <div className="container-sub">
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
