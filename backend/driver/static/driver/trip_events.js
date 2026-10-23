/*
 * Live trip-status buttons on the driver trip-detail screen.
 *
 * Each status form (On My Way / Arrived / Client On Board / Completed) posts to
 * the trip action endpoint. Before posting we try to attach the device's GPS
 * fix so the office can plot the route. Geolocation is best-effort: if the
 * browser has no geolocation API, the driver denies permission, or the lookup
 * errors/times out, we submit the form anyway with no coordinates -- the event
 * must still record (the backend treats missing coords as null).
 *
 * CSP-safe: self-hosted, no inline handlers. Loaded via <script src> with the
 * app's script-src 'self'. Listeners are wired up from here, not from markup.
 */
(function () {
  "use strict";

  // getCurrentPosition is async; form.submit() (used to re-submit below) does
  // NOT fire the submit event again, so the handler never re-enters. The guard
  // is belt-and-braces in case a browser behaves otherwise.
  function send(form) {
    if (form.dataset.sending === "1") {
      return;
    }
    form.dataset.sending = "1";
    form.submit();
  }

  function setField(form, name, value) {
    var el = form.querySelector('[name="' + name + '"]');
    if (el && value !== null && value !== undefined) {
      el.value = value;
    }
  }

  function onSubmit(form, event) {
    if (form.dataset.sending === "1") {
      return; // already posting with (or without) coords
    }
    event.preventDefault();

    var button = form.querySelector("button");
    if (button) {
      button.disabled = true;
    }

    if (!navigator.geolocation) {
      send(form);
      return;
    }

    navigator.geolocation.getCurrentPosition(
      function (position) {
        var c = position.coords;
        setField(form, "latitude", c.latitude);
        setField(form, "longitude", c.longitude);
        if (c.accuracy !== null && c.accuracy !== undefined) {
          setField(form, "accuracy", c.accuracy);
        }
        send(form);
      },
      function () {
        send(form); // denied / unavailable / timeout -> record without coords
      },
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 0 }
    );
  }

  function init() {
    var forms = document.querySelectorAll("form.js-trip-event");
    Array.prototype.forEach.call(forms, function (form) {
      form.addEventListener("submit", function (event) {
        onSubmit(form, event);
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
