const FAQ_BODY =
  "Sad ipscing elitrsed diamnonu myeir mod, sadipscing elitrsed dia morem ipsum dolor situamet consetetur loutrytru hury. Lorem ipsum dolor sitametco nsetetur sa cingelitrse diamonu eirmoid, sad ipscing elitrstrud diamtre ute riyutroui tout.";

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
              <div className="accordion-item">
                <h5 className="accordion-header" id="headingOne">
                  <button
                    className="accordion-button text-heading-5"
                    type="button"
                    data-bs-toggle="collapse"
                    data-bs-target="#collapseOne"
                    aria-expanded="true"
                    aria-controls="collapseOne"
                  >
                    How do I create an account?
                  </button>
                </h5>
                <div
                  className="accordion-collapse collapse show"
                  id="collapseOne"
                  aria-labelledby="headingOne"
                  data-bs-parent="#accordionFAQ"
                >
                  <div className="accordion-body">{FAQ_BODY}</div>
                </div>
              </div>
              <div className="accordion-item">
                <h5 className="accordion-header" id="headingTwo">
                  <button
                    className="accordion-button text-heading-5 collapsed"
                    type="button"
                    data-bs-toggle="collapse"
                    data-bs-target="#collapseTwo"
                    aria-expanded="false"
                    aria-controls="collapseTwo"
                  >
                    How do I earn Easy Ride Rewards points?
                  </button>
                </h5>
                <div
                  className="accordion-collapse collapse"
                  id="collapseTwo"
                  aria-labelledby="headingTwo"
                  data-bs-parent="#accordionFAQ"
                >
                  <div className="accordion-body">{FAQ_BODY}</div>
                </div>
              </div>
              <div className="accordion-item">
                <h5 className="accordion-header" id="headingThree">
                  <button
                    className="accordion-button text-heading-5 collapsed"
                    type="button"
                    data-bs-toggle="collapse"
                    data-bs-target="#collapseThree"
                    aria-expanded="false"
                    aria-controls="collapseThree"
                  >
                    How can I add my credit card on the app for payments?
                  </button>
                </h5>
                <div
                  className="accordion-collapse collapse"
                  id="collapseThree"
                  aria-labelledby="headingThree"
                  data-bs-parent="#accordionFAQ"
                >
                  <div className="accordion-body">{FAQ_BODY}</div>
                </div>
              </div>
              <div className="accordion-item">
                <h5 className="accordion-header" id="headingFour">
                  <button
                    className="accordion-button text-heading-5 collapsed"
                    type="button"
                    data-bs-toggle="collapse"
                    data-bs-target="#collapseFour"
                    aria-expanded="false"
                    aria-controls="collapseFour"
                  >
                    How do I become a Captain?
                  </button>
                </h5>
                <div
                  className="accordion-collapse collapse"
                  id="collapseFour"
                  aria-labelledby="headingFour"
                  data-bs-parent="#accordionFAQ"
                >
                  <div className="accordion-body">{FAQ_BODY}</div>
                </div>
              </div>
              <div className="accordion-item">
                <h5 className="accordion-header" id="headingFive">
                  <button
                    className="accordion-button text-heading-5 collapsed"
                    type="button"
                    data-bs-toggle="collapse"
                    data-bs-target="#collapseFive"
                    aria-expanded="false"
                    aria-controls="collapseFive"
                  >
                    Where can I get more information, support or make a claim?
                  </button>
                </h5>
                <div
                  className="accordion-collapse collapse"
                  id="collapseFive"
                  aria-labelledby="headingFive"
                  data-bs-parent="#accordionFAQ"
                >
                  <div className="accordion-body">{FAQ_BODY}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
