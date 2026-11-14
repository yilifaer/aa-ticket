from django.apps import AppConfig

from . import __version__


class AaTicketConfig(AppConfig):
    name = "aa_ticket"
    label = "aa_ticket"
    verbose_name = f"Tickets v{__version__}"
    default_auto_field = "django.db.models.BigAutoField"
