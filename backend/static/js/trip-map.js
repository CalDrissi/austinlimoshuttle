/*
 * Trip-event map for the back office.
 *
 * Renders a Leaflet map with one pin per driver trip-event that has GPS
 * coordinates. Leaflet itself is served from this project's own static files
 * (vendor/leaflet) -- never a CDN -- because the Content-Security-Policy in
 * config/middleware.py sets script-src 'self'. Map tiles come from
 * OpenStreetMap; the CSP img-src must allow https://*.tile.openstreetmap.org.
 *
 * No inline script is permitted either, so the event data is handed to this
 * file through a Django {{ ...|json_script }} block and read here from the DOM.
 */
(function () {
  "use strict";

  function init() {
    var el = document.getElementById("trip-map");
    if (!el || typeof L === "undefined") {
      return;
    }

    // Leaflet's default marker icon is loaded from an images/ folder it tries
    // to locate automatically. Under our vendored layout that detection is
    // unreliable, so we point it at the known static path the template passes.
    var imagePath = el.getAttribute("data-images");
    if (imagePath) {
      L.Icon.Default.imagePath = imagePath;
    }

    var dataEl = document.getElementById("trip-map-points");
    var points = [];
    if (dataEl) {
      try {
        points = JSON.parse(dataEl.textContent) || [];
      } catch (e) {
        points = [];
      }
    }

    var map = L.map(el);

    // OpenStreetMap raster tiles. Self-hosting these is impractical; the host
    // is allow-listed in the CSP img-src instead.
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);

    if (!points.length) {
      // Nothing to plot (no event carried a GPS fix). Show the wider area so
      // the panel is not an empty grey square.
      map.setView([30.2672, -97.7431], 10); // Austin, TX
      return;
    }

    var markers = [];
    points.forEach(function (p) {
      if (typeof p.lat !== "number" || typeof p.lng !== "number") {
        return;
      }
      var marker = L.marker([p.lat, p.lng]);
      var lines = [];
      if (p.label) {
        lines.push("<strong>" + escapeHtml(p.label) + "</strong>");
      }
      if (p.ref) {
        lines.push(escapeHtml(p.ref));
      }
      if (p.driver) {
        lines.push(escapeHtml(p.driver));
      }
      if (p.time) {
        lines.push("<span class=\"text-secondary\">" + escapeHtml(p.time) + "</span>");
      }
      if (lines.length) {
        marker.bindPopup(lines.join("<br>"));
      }
      marker.addTo(map);
      markers.push(marker);
    });

    if (markers.length === 1) {
      map.setView(markers[0].getLatLng(), 14);
    } else if (markers.length > 1) {
      map.fitBounds(L.featureGroup(markers).getBounds().pad(0.2));
    } else {
      map.setView([30.2672, -97.7431], 10);
    }
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
