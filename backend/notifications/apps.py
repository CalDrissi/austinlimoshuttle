from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'notifications'

    def ready(self):
        # Wire cross-app signal receivers here (not at module import time) so
        # the app registry is loaded before we import bookings -- no import cycle.
        from . import signals
        signals.connect()
