"use client";

import Link from "next/link";
import { Swiper, SwiperSlide } from "swiper/react";
import { Navigation } from "swiper/modules";
import "swiper/css/navigation";

const SERVICES = [
  {
    title: "Airport Transfers",
    desc: "Door-to-door service to and from Austin-Bergstrom (AUS) with flight tracking and a meet-and-greet.",
    img: "/assets/imgs/page/homepage1/service3.png",
  },
  {
    title: "Corporate & Events",
    desc: "On-time, professional transportation for meetings, conventions, weddings, and nights out.",
    img: "/assets/imgs/page/homepage1/service1.png",
  },
  {
    title: "Sprinter & Group Travel",
    desc: "Mercedes-Benz Sprinter vans and SUVs for larger parties, luggage, and corporate groups.",
    img: "/assets/imgs/page/homepage1/service5.png",
  },
];

export default function OurService() {
  return (
    <section className="section pt-90 pb-120 bg-our-service">
      <div className="container-sub">
        <div className="row align-items-center">
          <div className="col-lg-6 col-sm-7 col-7">
            <h2 className="heading-44-medium title-fleet wow fadeInDown">Our Services</h2>
          </div>
          <div className="col-lg-6 col-sm-5 col-5 text-end">
            <Link
              className="text-16-medium color-primary d-flex align-items-center justify-content-end wow fadeInDown"
              href="/fleet"
            >
              More Services
              <svg
                className="icon-16 ml-5"
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
            className="swiper-container swiper-group-4-service pb-0"
            modules={[Navigation]}
            spaceBetween={30}
            navigation={{
              prevEl: ".swiper-button-prev-service",
              nextEl: ".swiper-button-next-service",
            }}
            breakpoints={{
              0: { slidesPerView: 1 },
              576: { slidesPerView: 2 },
              768: { slidesPerView: 3 },
              1200: { slidesPerView: 3 },
            }}
          >
            {SERVICES.map((service, i) => (
              <SwiperSlide key={i}>
                <div className="cardService wow fadeInRight">
                  <div className="cardInfo">
                    <h3 className="cardTitle text-20-medium color-white mb-10">{service.title}</h3>
                    <div className="box-inner-info">
                      <p className="cardDesc text-14 color-white mb-30">{service.desc}</p>
                      <Link className="cardLink btn btn-arrow-up" href="/fleet">
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
                  <div className="cardImage">
                    <img src={service.img} alt="Luxride" />
                  </div>
                </div>
              </SwiperSlide>
            ))}
          </Swiper>
          <div className="box-pagination-fleet">
            <div className="swiper-button-prev swiper-button-prev-service">
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
            <div className="swiper-button-next swiper-button-next-service">
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
