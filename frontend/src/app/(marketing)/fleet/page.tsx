"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { catalogService } from "@/lib/api/catalog.service";
import { VEHICLE_PLACEHOLDER } from "@/lib/fleet/images";
import type { Vehicle } from "@/types/api";

export default function FleetPage() {
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    catalogService
      .listVehicles()
      .then((v) => active && setVehicles(v))
      .catch(() => active && setVehicles([]))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  return (
    <>
      <div className="section pt-60 pb-60 bg-primary">
        <div className="container-sub">
          <h1 className="heading-44-medium color-white mb-5 wow fadeInDown">Our Fleet</h1>
          <div className="box-breadcrumb wow fadeInUp">
            <ul>
              <li> <Link href="/">Home</Link></li>
              <li> <Link href="/fleet">Our Fleet</Link></li>
            </ul>
          </div>
        </div>
      </div>
      <section className="section pt-60 bg-white latest-new-white">
        <div className="container-sub">
          <div className="row align-items-center">
            <div className="col-lg-6 col-md-6 col-sm-6 text-center text-sm-start mb-30">
              <h2 className="heading-24-medium wow fadeInLeft">Choose Your Fleet</h2>
            </div>
          </div>

          <div className="row mt-30">
            {loading && <div className="col-12"><p className="text-16 color-grey">Loading the fleet…</p></div>}
            {!loading && !vehicles.length && (
              <div className="col-12"><p className="text-16 color-grey">No vehicles are available right now.</p></div>
            )}
            {vehicles.map((v) => (
              <div className="col-lg-4 col-md-6 mb-30" key={v.slug}>
                <div className="cardFleet wow fadeInDown">
                  <div className="cardInfo">
                    <Link href={`/fleet/${v.slug}`}>
                      <h3 className="text-20-medium color-text mb-10">{v.name}</h3>
                    </Link>
                    <p className="text-14 color-text mb-30">{v.description || "Professional chauffeur service across Central Texas."}</p>
                  </div>
                  <div className="cardImage mb-30">
                    <Link href={`/fleet/${v.slug}`}><img src={v.photo || VEHICLE_PLACEHOLDER} alt={v.name} /></Link>
                  </div>
                  <div className="cardInfoBottom">
                    <div className="passenger"><span className="icon-circle icon-passenger"></span><span className="text-14">Passengers{" "}<span>{v.passenger_capacity}</span></span></div>
                    <div className="luggage"><span className="icon-circle icon-luggage"></span><span className="text-14">Luggage{" "}<span>{v.luggage_capacity}</span></span></div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
