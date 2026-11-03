"""Context available to every dashboard template."""

from datetime import timedelta

from django.utils import timezone

from bookings.models import Booking
from enquiries.models import ContactMessage

from .crud import REGISTRY, visible_to
from .permissions import is_manager, role_names


def staff_context(request):
    """
    Role information and navigation badges.

    Set here rather than in each view so a new screen cannot accidentally hide
    (or reveal) the Settings link, or lose its unread badge, by forgetting to
    pass them.

    Only runs for authenticated staff -- an anonymous request must not trigger
    two count queries on every page, including the login form.
    """
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}

    context = {"roles": role_names(user), "is_manager": is_manager(user)}

    if not user.is_staff:
        return context

    now = timezone.now()
    context["nav_dispatch_count"] = (
        Booking.objects.filter(
            pickup_at__gte=now - timedelta(hours=4),
            pickup_at__lte=now + timedelta(days=2),
        )
        .exclude(status=Booking.Status.CANCELLED)
        .count()
    )
    context["nav_unread_enquiries"] = ContactMessage.objects.filter(is_read=False).count()

    # The manageable records this user may see, grouped for the sidebar. Built
    # from the registry and their permissions, so a Dispatcher is never shown a
    # link to the rate card and an Editor is never shown one to staff accounts.
    visible = {entry.slug for entry in visible_to(user)}
    context["nav_managed"] = [
        {
            "label": label,
            "items": [
                {"slug": slug, "title": REGISTRY[slug].label_plural,
                 "icon": REGISTRY[slug].icon}
                for slug in slugs if slug in visible
            ],
        }
        for label, slugs in (
            ("Fleet & pricing", ["vehicles", "surcharges", "blackout-dates"]),
            ("Website", ["pages", "testimonials", "banners", "gallery"]),
            ("People", ["drivers", "staff", "customers"]),
        )
    ]
    context["nav_managed"] = [group for group in context["nav_managed"] if group["items"]]
    return context
