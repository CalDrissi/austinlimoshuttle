"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { catalogService } from "@/lib/api/catalog.service";
import { VEHICLE_PLACEHOLDER } from "@/lib/fleet/images";
import BookingSearchWidget from "@/components/booking/BookingSearchWidget";
import type { Vehicle } from "@/types/api";

/** Marketing copy from the DB is newline-separated; render it as a tick list. */
function featureList(features: string): string[] {
  return features
    .split(/\r?\n/)
    .map((f) => f.trim())
    .filter(Boolean);
}

// Shown when a vehicle has no stored features, so the "We offer" block is never
// empty (mirrors the template's generic list).
const DEFAULT_OFFERS = [
  "Professional, fully-licensed chauffeurs",
  "Clean, serviced and fully insured vehicles",
  "Free cancellation up to 1 hour before pickup",
  "Flat, all-inclusive pricing — no surprises",
];

const PERKS = [
  { icon: "/assets/imgs/page/fleet/camera.png", title: "Safety First",
    desc: "Every journey is with a professional, background-checked chauffeur, held to the highest standards." },
  { icon: "/assets/imgs/page/fleet/water.png", title: "Prices With No Surprises",
    desc: "You see the full fare before you book. No meters, no hidden extras, no surge pricing." },
  { icon: "/assets/imgs/page/fleet/coffee.png", title: "Private Travel Solutions",
    desc: "Door-to-door comfort for airport transfers, events and corporate travel across Central Texas." },
];

export default function FleetDetailPage() {
  const router = useRouter();
  const params = useParams<{ slug: string }>();
  const slug = params?.slug;

  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "notfound">("loading");

  useEffect(() => {
    if (!slug) return;
    let active = true;
    catalogService
      .getVehicle(slug)
      .then((v) => {
        if (!active) return;
        setVehicle(v);
        setState(v ? "ready" : "notfound");
      })
      .catch(() => active && setState("notfound"));
    return () => { active = false; };
  }, [slug]);

  if (state === "loading") {
    return <section className="section pt-80 pb-80"><div className="container-sub"><p className="text-16 color-grey">Loading…</p></div></section>;
  }

  if (state === "notfound" || !vehicle) {
    return (
      <section className="section pt-80 pb-80">
        <div className="container-sub text-center">
          <h2 className="heading-44-medium color-text mb-20">Vehicle not found</h2>
          <p className="text-16 color-grey mb-30">That vehicle class isn&rsquo;t in our fleet.</p>
          <button className="btn btn-primary hover-up" onClick={() => router.push("/fleet")}>Back to the fleet</button>
        </div>
      </section>
    );
  }

  const offers = featureList(vehicle.features);
  const fromPrice = Number(vehicle.minimum_fare);

  return (
    <>
      {/* Hero / breadcrumb */}
      <div className="section pt-60 pb-60 bg-primary">
        <div className="container-sub">
          <h1 className="heading-44-medium color-white mb-5 wow fadeInDown">{vehicle.name}</h1>
          <div className="box-breadcrumb wow fadeInUp">
            <ul>
              <li><Link href="/">Home</Link></li>
              <li><Link href="/fleet">Our Fleet</Link></li>
              <li>{vehicle.name}</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Image + overview */}
      <section className="section pt-60">
        <div className="container-sub">
          <div className="row align-items-center">
            <div className="col-lg-6 mb-30">
              <img className="w-100" style={{ borderRadius: 16 }} src={vehicle.photo || VEHICLE_PLACEHOLDER} alt={vehicle.name} />
            </div>
            <div className="col-lg-6 mb-30">
              <div className="content-single">
                <h2 className="heading-44-medium mb-20 color-text title-fleet">{vehicle.name}</h2>
                {vehicle.description && <p className="text-16 color-grey mb-20">{vehicle.description}</p>}

                <div className="d-flex" style={{ gap: 32, margin: "10px 0 24px" }}>
                  <div>
                    <div className="text-14 color-grey">Passengers</div>
                    <div className="heading-24-medium color-text">{vehicle.passenger_capacity}</div>
                  </div>
                  <div>
                    <div className="text-14 color-grey">Luggage</div>
                    <div className="heading-24-medium color-text">{vehicle.luggage_capacity}</div>
                  </div>
                  {fromPrice > 0 && (
                    <div>
                      <div className="text-14 color-grey">From</div>
                      <div className="heading-24-medium color-text">${fromPrice.toFixed(0)}</div>
                    </div>
                  )}
                </div>

                <h6 className="heading-24-medium color-text mb-20">We offer</h6>
                <ul className="list-ticks list-ticks-small">
                  {(offers.length ? offers : DEFAULT_OFFERS).map((o, i) => (
                    <li key={i} className="text-16 mb-20">{o}</li>
                  ))}
                </ul>

                <div className="mt-30">
                  <Link className="btn btn-primary btn-book hover-up" href="#book-this-vehicle">
                    Book Now
                    <svg className="icon-16 ml-5" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 19.5l15-15m0 0H8.25m11.25 0v11.25" />
                    </svg>
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Embedded booking form, pre-selected to this vehicle. Reuses the hero
          search widget; the resulting search carries this vehicle so the funnel
          auto-selects it and skips the pick step. */}
      <section id="book-this-vehicle" className="section pt-60 pb-60 mt-60 bg-1">
        <div className="container-sub">
          <h2 className="heading-44-medium color-text mb-10 text-center">Book the {vehicle.name}</h2>
          <p className="text-16 color-grey mb-40 text-center">
            Enter your trip details — we&rsquo;ll price this vehicle for your journey.
          </p>
          <div className="mm-book-embed">
            <BookingSearchWidget preselectVehicleId={vehicle.id} vehicleName={vehicle.name} />
          </div>
        </div>
      </section>

      {/* Generic perks */}
      <section className="section mt-60 mb-60">
        <div className="container-sub">
          <h2 className="heading-44-medium wow fadeInLeft">Why travel with us</h2>
          <div className="row mt-50 cardIconTitleDescLeft">
            {PERKS.map((p) => (
              <div key={p.title} className="col-lg-4 col-md-6 col-sm-6 mb-30">
                <div className="cardIconTitleDesc">
                  <div className="cardIcon"><img src={p.icon} alt="" /></div>
                  <div className="cardTitle"><h5 className="text-20-medium color-text">{p.title}</h5></div>
                  <div className="cardDesc"><p className="text-16 color-text">{p.desc}</p></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
