"""Discord webhook messages for department channels.

The ticket body is never included: people in the channel may not be allowed
to read it. Role mentions go into `content` and are whitelisted through
`allowed_mentions`, so text written by players can never ping anyone.
"""

import math
import re

import requests

from django.core.exceptions import ValidationError
from django.utils.translation import pgettext
from django.utils.translation import pgettext_lazy

from ..app_settings import WEBHOOK_TEST_TIMEOUT, WEBHOOK_TIMEOUT
from ..constants import PRIORITY_HEX, Event
from ..links import ticket_url
from ..translation import channel_language_active
from ..utils import display_name
from .footer import SYSTEM_SENDER, notice, sender_name

WEBHOOK_URL_RE = re.compile(
    r"^https://(?:(?:canary|ptb)\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+$"
)
TITLE_LIMIT = 256
USERNAME = "Tickets"


def validate_webhook_url(value):
    if not value or not WEBHOOK_URL_RE.match(value):
        raise ValidationError(
            pgettext_lazy("aa_ticket", 
                "Paste the full webhook URL from Discord. It starts with "
                "https://discord.com/api/webhooks/"
            )
        )


def _event_text(ticket, event, department):
    if event == Event.SUBMITTED:
        return pgettext("aa_ticket", "New ticket")
    if event == Event.TRANSFERRED:
        return pgettext("aa_ticket", "Ticket transferred to %(department)s") % {"department": ticket.department.name}
    if event == Event.INVITED:
        return pgettext("aa_ticket", "%(department)s was invited to help") % {"department": department.name}
    if event == Event.ESCALATION_REQUESTED:
        return pgettext("aa_ticket", "The requester asked %(department)s to step in") % {"department": department.name}
    if event == Event.UNCLAIMED_REMINDER:
        return pgettext("aa_ticket", "Still unclaimed — please take a look")
    if event == Event.ESCALATION_REMINDER:
        return pgettext("aa_ticket", "A ticket of %(department)s is still unclaimed") % {"department": ticket.department.name}
    if event == Event.REPLIED:
        return pgettext("aa_ticket", "The requester added information to an unclaimed ticket")
    if event == Event.ASSIGNEE_LEFT:
        return pgettext("aa_ticket", "The assignee left the department — the ticket needs a new handler")
    if event == Event.AWAITING_STAFF_REMINDER:
        return pgettext("aa_ticket", "The requester is still waiting for a reply")
    return str(Event(event).label) if event in Event.values else event


def build_payload(ticket, event, mention, department, actor=None, at=None):
    role_ids = [str(x) for x in department.mention_role_id_list()] if mention else []
    with channel_language_active():
        title = f"{ticket.display_number} {ticket.title}"
        if len(title) > TITLE_LIMIT:
            title = title[: TITLE_LIMIT - 1] + "…"
        fields = [
            {"name": pgettext("aa_ticket", "Department"), "value": ticket.department.name, "inline": True},
            {"name": pgettext("aa_ticket", "Priority"), "value": ticket.priority.name, "inline": True},
        ]
        if ticket.category_id:
            fields.append({"name": pgettext("aa_ticket", "Category"), "value": ticket.category.name, "inline": True})
        fields.append(
            {"name": pgettext("aa_ticket", "Requester"), "value": display_name(ticket.requester) or "-", "inline": True}
        )
        embed = {
            "title": title,
            "url": ticket_url(ticket),
            "description": _event_text(ticket, event, department),
            "color": PRIORITY_HEX.get(ticket.priority.color, PRIORITY_HEX["primary"]),
            "fields": fields,
            "footer": {"text": notice(sender_name(event, actor), department.name, at)},
        }
    return {
        "username": USERNAME,
        "content": " ".join(f"<@&{rid}>" for rid in role_ids),
        "allowed_mentions": {"parse": [], "roles": role_ids},
        "embeds": [embed],
    }


def post_webhook(url, payload, timeout=WEBHOOK_TIMEOUT):
    return requests.post(url, json=payload, timeout=timeout)


def retry_after_seconds(response):
    try:
        value = float(response.json().get("retry_after", 1))
    except (ValueError, AttributeError, TypeError):
        value = 1
    return max(1, math.ceil(value))


def send_test_message(department, sender=None):
    """Send a test message right away. Returns (ok, user-facing text)."""
    if not department.webhook_url:
        return False, pgettext("aa_ticket", "No webhook configured.")
    with channel_language_active():
        return _send_test_message(department, sender)


def _send_test_message(department, sender=None):
    payload = {
        "username": USERNAME,
        "content": "",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "title": pgettext("aa_ticket", "Test message"),
                "description": pgettext("aa_ticket", "Tickets for %(department)s will be announced in this channel.")
                % {"department": department.name},
                "footer": {
                    "text": notice((display_name(sender) or sender.get_username()) if sender else SYSTEM_SENDER, department.name, None)
                },
            }
        ],
    }
    try:
        response = post_webhook(department.webhook_url, payload, timeout=WEBHOOK_TEST_TIMEOUT)
    except requests.RequestException as exc:
        return False, pgettext("aa_ticket", "Sending failed (%(reason)s).") % {"reason": type(exc).__name__}
    if response.ok:
        return True, pgettext("aa_ticket", "Test message sent. Check the Discord channel.")
    return False, pgettext("aa_ticket", "Discord refused the message (HTTP %(status)s). Check the webhook URL.") % {
        "status": response.status_code
    }
