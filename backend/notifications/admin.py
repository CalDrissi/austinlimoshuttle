"""
Read-only EmailLog triage in the Django admin.

The dashboard's Recent-messages card is the day-to-day view; this is the
unabridged, filterable log for digging into deliverability questions. Strictly
read-only: the log is evidence of what was sent, and evidence doesn't get
edited.
"""

from django.contrib import admin

from .models import EmailLog


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ("sent_at", "kind", "to_email", "subject", "succeeded",
                    "has_attachment", "booking")
    list_filter = ("succeeded", "kind", "has_attachment")
    search_fields = ("to_email", "subject", "error", "booking__reference")
    date_hierarchy = "sent_at"
    ordering = ("-sent_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
