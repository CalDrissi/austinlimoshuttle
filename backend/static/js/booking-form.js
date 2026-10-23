/* Manual booking form: Google Places autocomplete + Stripe card collection.
 * Loaded as an external file so the dashboard CSP can stay free of
 * script-src 'unsafe-inline'. Config comes from data-* attributes on the form.
 */
(function () {
  "use strict";

  /* --- Google Places autocomplete (new API) on the address inputs --- */
  window.__initPlaces = async function () {
    try {
      const { AutocompleteSuggestion, AutocompleteSessionToken } =
        await google.maps.importLibrary("places");
      ["id_pickup_address", "id_dropoff_address"].forEach(function (id) {
        attachAC(id, AutocompleteSuggestion, AutocompleteSessionToken);
      });
    } catch (e) {
      console.warn("Places init failed", e);
    }
  };

  function attachAC(id, AS, Token) {
    const input = document.getElementById(id);
    if (!input) return;
    input.setAttribute("autocomplete", "off");
    const wrap = document.createElement("div");
    wrap.style.position = "relative";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const box = document.createElement("div");
    box.style.cssText =
      "position:absolute;left:0;right:0;z-index:1080;background:#fff;border:1px solid #ddd;border-radius:6px;max-height:220px;overflow:auto;display:none;box-shadow:0 6px 18px rgba(0,0,0,.12)";
    wrap.appendChild(box);
    let token = new Token();
    let timer;
    input.addEventListener("input", function () {
      clearTimeout(timer);
      const q = input.value.trim();
      if (q.length < 3) {
        box.style.display = "none";
        return;
      }
      timer = setTimeout(async function () {
        try {
          const { suggestions } = await AS.fetchAutocompleteSuggestions({
            input: q,
            sessionToken: token,
            includedRegionCodes: ["us"],
            locationBias: { center: { lat: 30.2672, lng: -97.7431 }, radius: 50000 },
          });
          box.innerHTML = "";
          (suggestions || []).forEach(function (s) {
            const p = s.placePrediction;
            if (!p) return;
            const d = document.createElement("div");
            d.textContent = p.text.text;
            d.style.cssText = "padding:8px 12px;cursor:pointer;font-size:14px";
            d.onmouseover = function () { d.style.background = "#f4f4f5"; };
            d.onmouseout = function () { d.style.background = "#fff"; };
            d.onmousedown = function (e) {
              e.preventDefault();
              input.value = p.text.text;
              box.style.display = "none";
              token = new Token();
            };
            box.appendChild(d);
          });
          box.style.display = suggestions && suggestions.length ? "block" : "none";
        } catch (e) {
          box.style.display = "none";
        }
      }, 250);
    });
    document.addEventListener("click", function (e) {
      if (!wrap.contains(e.target)) box.style.display = "none";
    });
  }

  /* --- Stripe card collection for the manual booking --- */
  const form = document.getElementById("booking-form");
  if (!form) return;
  const pk = form.dataset.stripePk || "";
  if (!pk || typeof Stripe === "undefined") return;

  const stripe = Stripe(pk);
  const elements = stripe.elements();
  const card = elements.create("card", { hidePostalCode: true });
  let mounted = false;
  let submitting = false;

  function showCard(on) {
    const w = document.getElementById("card-wrap");
    if (!w) return;
    w.style.display = on ? "block" : "none";
    if (on && !mounted) {
      card.mount("#card-element");
      mounted = true;
    }
  }

  // Delegated so dynamically-injected saved-card radios toggle the card field too.
  form.addEventListener("change", function (e) {
    if (e.target && e.target.name === "payment_method") {
      showCard(e.target.value === "card" && e.target.checked);
    }
  });

  card.on("change", function (ev) {
    document.getElementById("card-errors").textContent = ev.error ? ev.error.message : "";
  });

  form.addEventListener("submit", function (e) {
    const sel = document.querySelector('input[name="payment_method"]:checked');
    if (!sel || sel.value !== "card" || submitting) return; // cash -> normal submit
    e.preventDefault();
    const btn = document.getElementById("submit-btn");
    btn.disabled = true;
    btn.textContent = "Charging…";
    stripe.createPaymentMethod({ type: "card", card: card }).then(function (res) {
      if (res.error) {
        document.getElementById("card-errors").textContent = res.error.message;
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-check-lg me-1"></i>Create booking';
        return;
      }
      document.getElementById("stripe_payment_method_id").value = res.paymentMethod.id;
      submitting = true;
      form.submit();
    });
  });
})();

/* --- Trip type + live "Get price" (new-booking form) ---
 * Shows only the inputs each trip type needs, and fetches the fare from the same
 * engine as the website. The server re-prices authoritatively on submit, so this
 * is a live preview only.
 */
(function () {
  "use strict";
  var form = document.getElementById("booking-form");
  if (!form) return;
  var group = document.getElementById("trip-mode-group");
  if (!group) return; // not the new-booking form

  var quoteUrl = form.dataset.quoteUrl || "";
  var quoteBox = document.getElementById("quote-box");
  var getBtn = document.getElementById("get-price-btn");

  function currentMode() {
    var checked = form.querySelector('input[name="trip_mode"]:checked');
    return checked ? checked.value : "transfer";
  }

  // Show only the fields that belong to the selected trip type.
  function applyMode() {
    var mode = currentMode();
    document.querySelectorAll(".trip-field").forEach(function (el) {
      var modes = (el.getAttribute("data-modes") || "").split(/\s+/);
      el.style.display = modes.indexOf(mode) !== -1 ? "" : "none";
    });
    if (quoteBox) quoteBox.innerHTML = ""; // stale once the trip changes
  }

  group.querySelectorAll('input[name="trip_mode"]').forEach(function (r) {
    r.addEventListener("change", applyMode);
  });
  applyMode();

  function field(name) {
    var el = form.querySelector('[name="' + name + '"]');
    return el ? el.value : "";
  }

  function getPrice() {
    if (!quoteUrl || !quoteBox) return;
    quoteBox.innerHTML = '<span class="text-secondary small">Pricing…</span>';
    var body = new URLSearchParams();
    body.set("trip_mode", currentMode());
    body.set("vehicle", field("vehicle"));
    body.set("pickup_at", field("pickup_at"));
    body.set("pickup_address", field("pickup_address"));
    body.set("dropoff_address", field("dropoff_address"));
    body.set("hours", field("hours"));
    body.set("city_route", field("city_route"));
    var mg = form.querySelector('[name="meet_and_greet"]');
    body.set("meet_and_greet", mg && mg.checked ? "on" : "");
    body.set("csrfmiddlewaretoken", field("csrfmiddlewaretoken"));
    fetch(quoteUrl, {
      method: "POST", credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" }, body: body,
    })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.ok) {
          quoteBox.innerHTML = '<div class="small text-danger">' + (d.error || "Couldn't price that.") + "</div>";
          return;
        }
        var rows = (d.lines || []).map(function (l) {
          return '<div class="d-flex justify-content-between"><span>' + l.label +
                 '</span><span>$' + l.amount + "</span></div>";
        }).join("");
        var dist = d.distance_miles ? '<div class="text-secondary small mb-1">' + d.distance_miles + " miles</div>" : "";
        quoteBox.innerHTML =
          '<div class="border rounded p-2 bg-light">' + dist + rows +
          '<div class="d-flex justify-content-between fw-semibold border-top mt-1 pt-1">' +
          "<span>System price</span><span>$" + d.total + " " + d.currency + "</span></div>" +
          '<div class="form-text mt-1">Leave Override blank to use this price.</div></div>';
      })
      .catch(function () {
        quoteBox.innerHTML = '<div class="small text-danger">Couldn\'t reach the pricing service.</div>';
      });
  }

  if (getBtn) getBtn.addEventListener("click", getPrice);
})();

/* --- Find / attach a customer (new-booking form) --- */
(function () {
  "use strict";
  var form = document.getElementById("booking-form");
  if (!form) return;
  var url = form.dataset.customerUrl || "";
  var input = document.getElementById("cust-search");
  var btn = document.getElementById("cust-search-btn");
  var results = document.getElementById("cust-results");
  var linked = document.getElementById("cust-linked");
  var hid = document.getElementById("id_customer_id");
  if (!url || !input || !btn || !results || !hid) return;

  var savedBox = document.getElementById("saved-cards");
  var savedHid = document.getElementById("saved_card_id");

  function renderSavedCards(cards) {
    if (!savedBox) return;
    if (!cards || !cards.length) { savedBox.innerHTML = ""; return; }
    var html = '<div class="small text-secondary mb-1">Or charge a saved card:</div><div class="d-flex flex-wrap gap-2">';
    cards.forEach(function (c) {
      var id = "pm-saved-" + c.id;
      html += '<input type="radio" class="btn-check" name="payment_method" id="' + id +
        '" value="saved" data-card-id="' + c.id + '" autocomplete="off">' +
        '<label class="btn btn-outline-secondary btn-sm" for="' + id + '">' +
        c.brand + " ••" + c.last4 + "</label>";
    });
    savedBox.innerHTML = html + "</div>";
  }

  // Keep the hidden saved_card_id in sync with the chosen saved-card radio.
  form.addEventListener("change", function (e) {
    if (!e.target || e.target.name !== "payment_method" || !savedHid) return;
    savedHid.value = (e.target.value === "saved" && e.target.dataset.cardId) ? e.target.dataset.cardId : "";
  });

  function setVal(name, v) {
    var el = form.querySelector('[name="' + name + '"]');
    if (el) el.value = v || "";
  }

  function search() {
    var q = input.value.trim();
    if (q.length < 3) { results.innerHTML = ""; return; }
    results.innerHTML = '<div class="list-group-item small text-secondary">Searching…</div>';
    fetch(url + "?q=" + encodeURIComponent(q), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d.results || !d.results.length) {
          results.innerHTML = '<div class="list-group-item small text-secondary">No match. Fill in the details to create a new customer.</div>';
          return;
        }
        results.innerHTML = "";
        d.results.forEach(function (u) {
          var a = document.createElement("button");
          a.type = "button";
          a.className = "list-group-item list-group-item-action";
          a.innerHTML = "<strong>" + (u.name || u.email) + "</strong> " +
            '<span class="text-secondary small">' + (u.phone || "") + " · " + u.email +
            (u.has_card ? ' · <span class="text-success">card on file</span>' : "") + "</span>";
          a.addEventListener("click", function () {
            hid.value = u.id;
            setVal("pickup_sign", u.name);
            setVal("guest_phone", u.phone);
            setVal("guest_email", u.email);
            results.innerHTML = "";
            linked.textContent = "Linked to " + (u.name || u.email) + "'s account." +
              (u.has_card ? " Card on file available." : "");
            renderSavedCards(u.cards || []);
          });
          results.appendChild(a);
        });
      })
      .catch(function () {
        results.innerHTML = '<div class="list-group-item small text-danger">Lookup failed.</div>';
      });
  }

  btn.addEventListener("click", search);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); search(); }
  });
  // Editing the email after linking means they're changing the customer -> unlink.
  var emailEl = form.querySelector('[name="guest_email"]');
  if (emailEl) emailEl.addEventListener("input", function () {
    hid.value = ""; linked.textContent = "";
    if (savedBox) savedBox.innerHTML = "";
    if (savedHid) savedHid.value = "";
  });
})();
