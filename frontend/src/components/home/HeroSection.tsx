"use client";

import ReactDOM from "react-dom";
import { Swiper, SwiperSlide } from "swiper/react";
import { Navigation, Pagination, Autoplay } from "swiper/modules";
import "swiper/css/navigation";
import "swiper/css/pagination";
import BookingSearchWidget from "@/components/booking/BookingSearchWidget";

const HERO_DIR = "/assets/imgs/page/homepage1/hero";
const WIDTHS = [640, 768, 1024, 1366, 1672] as const;
const SIZES = "100vw";

// Dark-luxury hero carousel: SUV + Austin skyline, chauffeur at the door,
// leather interior. Source is right-weighted with dark left negative space so
// the headline + booking form stay readable; a left scrim reinforces it.
const SLIDES = [
  { name: "hero1", alt: "Black Cadillac Escalade with the Austin skyline at night" },
  { name: "hero2", alt: "Chauffeur opening the door of a luxury sedan" },
  { name: "hero3", alt: "Premium leather interior of a luxury vehicle" },
];

const srcSet = (name: string, ext: string) =>
  WIDTHS.map((w) => `${HERO_DIR}/${name}-${w}.${ext} ${w}w`).join(", ");

export default function HeroSection() {
  // Preload only the first slide (LCP). Prefer AVIF, fall back to WebP.
  ReactDOM.preload(`${HERO_DIR}/${SLIDES[0].name}-1024.webp`, {
    as: "image",
    fetchPriority: "high",
    imageSrcSet: srcSet(SLIDES[0].name, "webp"),
    imageSizes: SIZES,
  });

  return (
    <section className="section banner-home1">
      <div className="box-swiper">
        <Swiper
          className="swiper-container swiper-banner-1 pb-0"
          modules={[Navigation, Pagination, Autoplay]}
          loop
          autoplay={{ delay: 5000, disableOnInteraction: false }}
          navigation={{
            prevEl: ".swiper-button-prev-banner",
            nextEl: ".swiper-button-next-banner",
          }}
          pagination={{ el: ".swiper-pagination-banner", type: "fraction" }}
        >
          {SLIDES.map((slide, i) => (
            <SwiperSlide key={slide.name}>
              <div className="box-cover-image">
                <picture>
                  <source type="image/avif" srcSet={srcSet(slide.name, "avif")} sizes={SIZES} />
                  <source type="image/webp" srcSet={srcSet(slide.name, "webp")} sizes={SIZES} />
                  <img
                    className="hero-slide-img"
                    src={`${HERO_DIR}/${slide.name}-1024.webp`}
                    srcSet={srcSet(slide.name, "webp")}
                    sizes={SIZES}
                    alt={slide.alt}
                    width={1672}
                    height={941}
                    loading={i === 0 ? "eager" : "lazy"}
                    fetchPriority={i === 0 ? "high" : "low"}
                    decoding="async"
                  />
                </picture>
                <span className="hero-scrim" aria-hidden="true" />
              </div>
              <div className="box-banner-info">
                <p className="text-16 color-white">Where Would You Like To Go?</p>
                <h2 className="heading-52-medium color-white">
                  Your Personal <br className="d-none d-lg-block" />
                  Chauffeur Services
                </h2>
              </div>
            </SwiperSlide>
          ))}
        </Swiper>

        <div className="box-pagination-button">
          <div className="swiper-button-prev swiper-button-prev-banner" />
          <div className="swiper-button-next swiper-button-next-banner" />
          <div className="swiper-pagination swiper-pagination-banner swiper-pagination-fraction" />
        </div>
      </div>

      <BookingSearchWidget />
    </section>
  );
}
