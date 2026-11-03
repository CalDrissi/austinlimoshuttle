const FAQS = [
  {
    id: "One",
    question: "What areas do you serve?",
    answer:
      "We cover Austin and the wider Central Texas region, including Austin-Bergstrom International Airport (AUS), Downtown, The Domain, Round Rock, Georgetown, and San Marcos. Need a ride outside that area? Reach out and we'll put together a quote.",
    show: true,
  },
  {
    id: "Two",
    question: "How far in advance should I book?",
    answer:
      "For airport transfers and everyday trips we recommend booking at least a few hours ahead so we can confirm your chauffeur. For weddings, corporate events, and group travel, booking a day or more in advance helps us reserve the right vehicle for your party.",
    show: false,
  },
  {
    id: "Three",
    question: "Do you track my flight for airport pickups?",
    answer:
      "Yes. We monitor your flight in real time and adjust your pickup if it lands early or late, so your chauffeur is waiting when you arrive at Austin-Bergstrom (AUS) at no extra charge for reasonable delays.",
    show: false,
  },
  {
    id: "Four",
    question: "How is pricing calculated?",
    answer:
      "You get an upfront quote before you book. Airport transfers use flat rates, and hourly charters are billed by the hour, so there's no surge pricing and no meter. Any applicable tolls, parking, or gratuity are shown clearly before you confirm.",
    show: false,
  },
  {
    id: "Five",
    question: "What is your cancellation policy?",
    answer:
      "Plans change, and we get it. Contact us as early as possible to change or cancel your reservation. As long as you give us reasonable notice before your scheduled pickup, there's no cancellation fee.",
    show: false,
  },
];

export default function Faqs() {
  return (
    <section className="section pt-80 mb-30">
      <div className="container-sub">
        <div className="box-faqs">
          <div className="text-center">
            <h2 className="color-brand-1 mb-20 wow fadeInRight">Frequently Asked Questions</h2>
          </div>
          <div className="mt-60 mb-40">
            <div className="accordion wow fadeInDown" id="accordionFAQ">
              {FAQS.map((faq) => (
                <div className="accordion-item" key={faq.id}>
                  <h5 className="accordion-header" id={`heading${faq.id}`}>
                    <button
                      className={`accordion-button text-heading-5${faq.show ? "" : " collapsed"}`}
                      type="button"
                      data-bs-toggle="collapse"
                      data-bs-target={`#collapse${faq.id}`}
                      aria-expanded={faq.show ? "true" : "false"}
                      aria-controls={`collapse${faq.id}`}
                    >
                      {faq.question}
                    </button>
                  </h5>
                  <div
                    className={`accordion-collapse collapse${faq.show ? " show" : ""}`}
                    id={`collapse${faq.id}`}
                    aria-labelledby={`heading${faq.id}`}
                    data-bs-parent="#accordionFAQ"
                  >
                    <div className="accordion-body">{faq.answer}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
