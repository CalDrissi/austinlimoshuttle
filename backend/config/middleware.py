"""
Security headers not covered by Django's SecurityMiddleware.

Django 5.2 ships no Content-Security-Policy support, and `django-csp` is a whole
dependency for two response headers. This is deliberately small: it sets a
policy and nothing else.

The policy is written for the Django-served surfaces (admin and dashboard),
which use no inline scripts of their own. The Next.js frontend is served
separately and will need its own policy, including whatever Stripe Elements
requires when payments are wired up.
"""

from django.utils.deprecation import MiddlewareMixin

# Django's admin uses inline styles heavily, so 'unsafe-inline' is unavoidable
# for style-src. Scripts are deliberately NOT granted it.
#
# Stripe Elements and the Google Maps/Places JS used by the manual-booking form
# load scripts and open connections (and, for Stripe, an iframe) to a handful of
# trusted third-party hosts. Those hosts are allow-listed explicitly below; no
# inline script is ever permitted.
STRIPE_JS = "https://js.stripe.com"
STRIPE_API = "https://api.stripe.com"
MAPS_HOSTS = "https://maps.googleapis.com https://maps.gstatic.com https://places.googleapis.com"
# The back-office dashboard renders a self-hosted Leaflet map (JS/CSS served
# from our own origin); only its raster tile IMAGES come from OpenStreetMap.
# So the OSM tile host is added to img-src alone -- script-src stays locked
# down and never gains a third-party map host for this feature.
OSM_TILES = "https://*.tile.openstreetmap.org"

CSP_DIRECTIVES = {
    "default-src": "'self'",
    "script-src": f"'self' {STRIPE_JS} https://maps.googleapis.com https://maps.gstatic.com",
    "style-src": "'self' 'unsafe-inline'",
    "img-src": f"'self' data: https://*.googleapis.com https://*.gstatic.com {OSM_TILES}",
    "font-src": "'self'",
    "connect-src": f"'self' {STRIPE_API} {MAPS_HOSTS}",
    "frame-src": STRIPE_JS,
    "frame-ancestors": "'none'",
    "form-action": "'self'",
    "base-uri": "'self'",
    "object-src": "'none'",
}


class SecurityHeadersMiddleware(MiddlewareMixin):
    """Adds Content-Security-Policy and Permissions-Policy to every response."""

    def process_response(self, request, response):
        if "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = "; ".join(
                f"{directive} {value}" for directive, value in CSP_DIRECTIVES.items()
            )

        if "Permissions-Policy" not in response:
            # Nothing here needs a camera, microphone or the payment API.
            # Geolocation is granted to our own origin only (self): the driver
            # app under /driver/ reads navigator.geolocation to stamp each
            # status event with coords. Third-party frames get nothing.
            response["Permissions-Policy"] = (
                "geolocation=(self), camera=(), microphone=(), payment=()"
            )

        return response
