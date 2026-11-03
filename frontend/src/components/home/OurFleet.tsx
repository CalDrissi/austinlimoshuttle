"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Swiper, SwiperSlide } from "swiper/react";
import { Navigation } from "swiper/modules";
import "swiper/css/navigation";
import { catalogService } from "@/lib/api/catalog.service";
import { VEHICLE_PLACEHOLDER } from "@/lib/fleet/images";
import type { Vehicle } from "@/types/api";

export default function OurFleet() {
  const [fleet, setFleet] = useState<Vehicle[]>([]);

  useEffect(() => {
    let active = true;
    catalogService
      .listVehicles()
      .then((v) => active && setFleet(v))
      .catch(() => active && setFleet([]));
    return () => { active = false; };
  }, []);

  return (
    <section className="section pt-120 pb-120 bg-our-fleet">
      <div className="container-sub">
        <div className="row align-items-center">
          <div className="col-lg-6 col-7">
            <h2 className="heading-44-medium title-fleet wow fadeInDown">Our Fleet</h2>
          </div>
          <div className="col-lg-6 col-5 text-end">
            <Link className="text-16-medium color-primary wow fadeInDown" href="/fleet">
              More Fleet
              <svg
                className="icon-16"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M4.5 19.5l15-15m0 0H8.25m11.25 0v11.25"
                />
              </svg>
            </Link>
          </div>
        </div>
      </div>
      <div className="box-slide-fleet mt-50">
        <div className="box-swiper">
          <Swiper
            className="swiper-container swiper-group-4-fleet pb-0"
            modules={[Navigation]}
            spaceBetween={30}
            navigation={{
              prevEl: ".swiper-button-prev-fleet",
              nextEl: ".swiper-button-next-fleet",
            }}
            breakpoints={{
              0: { slidesPerView: 1 },
              576: { slidesPerView: 2 },
              768: { slidesPerView: 3 },
              1200: { slidesPerView: 3 },
            }}
          >
            {fleet.map((v) => (
              <SwiperSlide key={v.slug}>
                <div className="cardFleet wow fadeInDown">
                  <div className="cardInfo">
                    <Link href={`/fleet/${v.slug}`}>
                      <h3 className="text-20-medium color-text mb-10">{v.name}</h3>
                    </Link>
                    <p className="text-14 color-text mb-30">{v.description || "Professional chauffeur service across Central Texas."}</p>
                  </div>
                  <div className="cardImage mb-30">
                    <Link href={`/fleet/${v.slug}`}>
                      <img src={v.photo || VEHICLE_PLACEHOLDER} alt={v.name} />
                    </Link>
                  </div>
                  <div className="cardInfoBottom">
                    <div className="passenger">
                      <span className="icon-circle icon-passenger"></span>
                      <span className="text-14">
                        Passengers <span>{v.passenger_capacity}</span>
                      </span>
                    </div>
                    <div className="luggage">
                      <span className="icon-circle icon-luggage"></span>
                      <span className="text-14">
                        Luggage <span>{v.luggage_capacity}</span>
                      </span>
                    </div>
                  </div>
                </div>
              </SwiperSlide>
            ))}
          </Swiper>
          <div className="box-pagination-fleet">
            <div className="swiper-button-prev swiper-button-prev-fleet">
              <svg
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18"
                />
              </svg>
            </div>
            <div className="swiper-button-next swiper-button-next-fleet">
              <svg
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                viewBox="0 0 24 24"
                xmlns="http://www.w3.org/2000/svg"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"
                />
              </svg>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
