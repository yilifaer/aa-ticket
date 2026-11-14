from django.apps import AppConfig



class AaTicketConfig(AppConfig):
    name = "aa_ticket"
    label = "aa_ticket"
    verbose_name = "Tickets"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import checks  # noqa: F401
