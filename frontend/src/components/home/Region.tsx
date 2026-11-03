import HomepagePicture from "./HomepagePicture";

export default function Region() {
  return (
    <section className="section pt-120 pb-120 bg-region">
      <div className="container-sub">
        <div className="row align-items-center">
          <div className="col-lg-6 mb-30">
            <div className="box-gallery justify-content-center justify-content-lg-start">
              <div className="gallery-1 wow fadeInRight">
                <HomepagePicture image="austin-skyline" alt="Austin skyline" sizes="(max-width: 575px) 55vw, 311px" />
              </div>
              <div className="gallery-2 wow fadeInLeft">
                <HomepagePicture image="austin-capitol" alt="Texas State Capitol in Austin" sizes="(max-width: 575px) 44vw, 249px" />
                <HomepagePicture image="austin-pickup" alt="Chauffeured pickup in Austin" sizes="(max-width: 575px) 44vw, 249px" />
              </div>
            </div>
          </div>
          <div className="col-lg-6 mb-30">
            <div className="box-region-right wow fadeInUp">
              <h2 className="heading-44-medium color-text mb-30">
                Serving the greater Austin area
              </h2>
              <p className="text-16 color-text mb-30">
                M&amp;M Austin Limousine covers Austin-Bergstrom Airport (AUS), Downtown, The Domain,
                Round Rock and the wider Central Texas region.
              </p>
              <a className="btn btn-primary" href="/fleet">
                Our Service Area
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
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
