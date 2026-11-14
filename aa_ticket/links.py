from django.conf import settings
from django.urls import reverse


def ticket_url(ticket):
    base = getattr(settings, "SITE_URL", "").rstrip("/")
    return base + reverse("aa_ticket:detail", args=[ticket.pk])
