"use client";

import { useRef, useState } from "react";
import { Swiper, SwiperSlide } from "swiper/react";
import { Autoplay } from "swiper/modules";
import type { Swiper as SwiperClass } from "swiper";

// Ported from index.html "How It Works" — the template synced a slick image
// gallery with a vertical step nav. Reimplemented with Swiper so the steps and
// the image stay in sync (clicking a step slides the image; autoplay advances
// both) instead of relying on a jQuery plugin we don't run.
const STEPS = [
  {
    title: "Tell Us Your Trip",
    text: "Enter your pickup and drop-off addresses, or book a car and chauffeur by the hour for events, meetings, and nights out around Austin.",
    image: "/assets/imgs/page/homepage1/laptop.png",
  },
  {
    title: "Pick Your Vehicle",
    text: "Choose the sedan, SUV, or Sprinter that fits your party and luggage, then get an upfront quote with no hidden fees.",
    image: "/assets/imgs/page/homepage1/desktop.png",
  },
  {
    title: "Ride With a Pro",
    text: "Your licensed, insured chauffeur tracks your flight and arrives early, so you ride on time across Central Texas.",
    image: "/assets/imgs/page/homepage1/desktop2.png",
  },
];

export default function HowItWorks() {
  const [active, setActive] = useState(0);
  const swiperRef = useRef<SwiperClass | null>(null);

  return (
    <section className="section pt-120 pb-20 bg-primary bg-how-it-works">
      <div className="container-sub">
        <h2 className="heading-44-medium color-white mb-60 wow fadeInUp">How It Works</h2>
        <div className="row align-items-center">
          <div className="col-lg-6 order-lg-last">
            <div className="box-main-slider">
              <div className="detail-gallery">
                <Swiper
                  modules={[Autoplay]}
                  loop
                  autoplay={{ delay: 3500, disableOnInteraction: false }}
                  onSwiper={(s) => { swiperRef.current = s; }}
                  onSlideChange={(s) => setActive(s.realIndex)}
                >
                  {STEPS.map((s, i) => (
                    <SwiperSlide key={i}>
                      <figure><img src={s.image} alt={s.title} /></figure>
                    </SwiperSlide>
                  ))}
                </Swiper>
              </div>
            </div>
          </div>
          <div className="col-lg-6 order-lg-first">
            <ul className="slider-nav-thumbnails list-how">
              {STEPS.map((s, i) => (
                <li
                  key={i}
                  className={active === i ? "active" : ""}
                  onClick={() => { swiperRef.current?.slideToLoop(i); setActive(i); }}
                  style={{ cursor: "pointer" }}
                >
                  <span className="line-white" />
                  <h4 className="text-20-medium mb-20">{s.title}</h4>
                  <p className="text-16">{s.text}</p>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
