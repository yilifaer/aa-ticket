"""The small line at the bottom of every Discord message.

Always English, like the notices of other alliance bots:
"This was a Ticket Bot Notice from <sender> to <recipient> at 2026-11-15 11:03:28 EVE".
"""

import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from ..constants import Event
from ..utils import display_name

SYSTEM_SENDER = "Alliance Auth"
FOOTER_LIMIT = 2048  # Discord's limit for footer text


def sender_name(event, actor):
    """Who caused the message. New tickets and automatic messages come from Alliance Auth."""
    if actor is None or event == Event.SUBMITTED:
        return SYSTEM_SENDER
    return display_name(actor) or actor.get_username()


def event_time(value):
    """The time of the event as an aware datetime. Accepts an ISO string; falls back to now."""
    if isinstance(value, str):
        value = parse_datetime(value)
    if value is None:
        return timezone.now()
    if timezone.is_naive(value):
        value = timezone.make_aware(value, datetime.timezone.utc)
    return value


def notice(sender, recipient, at):
    when = timezone.localtime(event_time(at), datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    text = f"This was a Ticket Bot Notice from {sender} to {recipient} at {when} EVE"
    return text[:FOOTER_LIMIT]
