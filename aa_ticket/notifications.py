"""Routes ticket events to Alliance Auth notifications, Discord DMs and webhooks.

See the design document, section 9.
"""

from django.contrib.auth.models import User
from django.core.cache import cache
from django.utils.translation import pgettext

from allianceauth.notifications import notify
from allianceauth.services.hooks import get_extension_logger

from . import access
from .app_settings import UNCLAIMED_REPLY_NOTICE_SECONDS, unclaimed_reply_key
from .constants import Event, Status
from .discord import dm
from .links import ticket_url
from .models import Department, Ticket, TicketSettings
from .tasks import send_dm, send_webhook
from .translation import user_language
from .utils import display_name

logger = get_extension_logger(__name__)

# The only event data a direct message needs; free text such as reasons stays out of the broker.
DM_DATA_KEYS = ("by_staff", "assignee", "assignee_id", "department")

REQUESTER_EVENTS = {
    Event.CLAIMED,
    Event.ASSIGNED,
    Event.CLOSED,
    Event.REOPENED,
    Event.TRANSFERRED,
    Event.PRIORITY_CHANGED,
}

EVENT_LEVEL = {
    Event.AUTOCLOSE_WARNING: "warning",
    Event.AWAITING_STAFF_REMINDER: "warning",
    Event.ESCALATION_REQUESTED: "warning",
    Event.CLOSED: "success",
}


def _channel_targets(ticket, event, data):
    """List of (department_id, mention) for webhook messages."""
    mention_new = ticket.priority.mention_on_new
    if event == Event.SUBMITTED:
        return [(ticket.department_id, mention_new)]
    if event == Event.REPLIED:
        # The requester added something to a ticket nobody has claimed yet: tell the channel,
        # without a mention and at most once an hour per ticket (the limit is applied in dispatch,
        # only when a message is really going out).
        if data.get("by_staff") or ticket.status != Status.OPEN:
            return []
        return [(ticket.department_id, False)]
    if event == Event.TRANSFERRED:
        return [(ticket.department_id, mention_new)]
    if event == Event.INVITED and data.get("department_id"):
        return [(data["department_id"], mention_new)]
    if event == Event.ESCALATION_REQUESTED and data.get("department_id"):
        return [(data["department_id"], True)]
    if event == Event.UNCLAIMED_REMINDER:
        return [(ticket.department_id, True)]
    if event == Event.ESCALATION_REMINDER and ticket.department.parent_id:
        return [(ticket.department.parent_id, True)]
    if event == Event.AWAITING_STAFF_REMINDER:
        return [(ticket.department_id, False)]
    if event == Event.ASSIGNEE_LEFT:
        return [(ticket.department_id, False)]
    return []


def _personal_recipient_ids(ticket, event, data):
    ids = []
    if event in REQUESTER_EVENTS:
        ids.append(ticket.requester_id)
    if event == Event.REPLIED:
        if data.get("by_staff"):
            ids.append(ticket.requester_id)
        if ticket.assignee_id:
            ids.append(ticket.assignee_id)
    if event in (Event.CLOSED, Event.REOPENED) and ticket.assignee_id:
        ids.append(ticket.assignee_id)
    if event == Event.ESCALATION_REQUESTED:
        if ticket.assignee_id:
            ids.append(ticket.assignee_id)
        target = Department.objects.filter(pk=data.get("department_id")).first()
        if target is not None and not target.webhook_url:
            ids.extend(access.department_staff(target).values_list("pk", flat=True))
    if event == Event.ASSIGNED and data.get("assignee_id"):
        ids.append(data["assignee_id"])
    if event == Event.AUTOCLOSE_WARNING:
        ids.append(ticket.requester_id)
        if ticket.assignee_id:
            ids.append(ticket.assignee_id)
    if event == Event.AWAITING_STAFF_REMINDER and ticket.assignee_id:
        ids.append(ticket.assignee_id)
    seen = []
    for pk in ids:
        if pk and pk not in seen:
            seen.append(pk)
    return seen


def personal_text(ticket, event, data, recipient_id=None):
    """One-line, translated description of an event for one recipient."""
    if event == Event.CLAIMED:
        return pgettext("aa_ticket", "%(name)s is now handling your ticket.") % {"name": data.get("assignee", "")}
    if event == Event.ASSIGNED:
        if recipient_id and recipient_id == data.get("assignee_id"):
            return pgettext("aa_ticket", "You were assigned this ticket.")
        return pgettext("aa_ticket", "%(name)s is now handling your ticket.") % {"name": data.get("assignee", "")}
    if event == Event.REPLIED:
        if data.get("by_staff"):
            return pgettext("aa_ticket", "There is a new reply on your ticket.")
        return pgettext("aa_ticket", "The requester replied.")
    if event == Event.CLOSED:
        return pgettext("aa_ticket", "The ticket was closed.")
    if event == Event.REOPENED:
        return pgettext("aa_ticket", "The ticket was reopened.")
    if event == Event.TRANSFERRED:
        return pgettext("aa_ticket", "The ticket was transferred to %(department)s.") % {"department": ticket.department.name}
    if event == Event.PRIORITY_CHANGED:
        return pgettext("aa_ticket", "The priority was changed to %(priority)s.") % {"priority": ticket.priority.name}
    if event == Event.ESCALATION_REQUESTED:
        return pgettext("aa_ticket", "The requester asked %(department)s to step in.") % {"department": data.get("department", "")}
    if event == Event.AUTOCLOSE_WARNING:
        hours = TicketSettings.get_solo().autoclose_warning_hours
        return pgettext("aa_ticket", "This ticket will close automatically in %(hours)d hours unless someone replies.") % {
            "hours": hours
        }
    if event == Event.AWAITING_STAFF_REMINDER:
        return pgettext("aa_ticket", "The requester is still waiting for a reply.")
    return str(Event(event).label) if event in Event.values else event


def _clear_caches(ticket, actor_id, data):
    """Refresh the menu badge and the dashboard card of everyone this ticket concerns."""
    import time

    from .auth_hooks import badge_cache_key, card_version_key

    department_ids = {ticket.department_id, data.get("from_department_id"), data.get("department_id")}
    department_ids |= set(ticket.collaborating_departments.values_list("pk", flat=True))
    department_ids.discard(None)
    user_ids = set(
        User.objects.filter(groups__aa_ticket_departments__in=department_ids).values_list("pk", flat=True)
    )
    people = (ticket.requester_id, ticket.assignee_id, actor_id, data.get("previous_assignee_id"), data.get("assignee_id"))
    user_ids |= {pk for pk in people if pk}
    cache.delete_many([badge_cache_key(User(pk=pk)) for pk in user_ids])
    version = time.time_ns()
    cache.set_many({card_version_key(pk): version for pk in user_ids}, 3600)


def personal_title(ticket):
    return f"{ticket.display_number} {ticket.title}"[:250]


def dispatch(event, ticket_id, actor_id, data):
    """Called after a ticket event has been committed."""
    ticket = (
        Ticket.objects.select_related("department", "priority", "requester", "assignee")
        .filter(pk=ticket_id)
        .first()
    )
    if ticket is None:
        return
    data = data or {}

    targets = _channel_targets(ticket, event, data)
    # only departments that are active and really have a channel to post to
    existing = set(
        Department.objects.filter(pk__in=[pk for pk, _m in targets], is_active=True)
        .exclude(webhook_url="")
        .values_list("pk", flat=True)
    )
    limited = event == Event.REPLIED
    limit_key = unclaimed_reply_key(ticket.pk)
    # Alliance Auth notifications first: they only need the database, not the task broker.
    dm_available = dm.is_available()
    url = ticket_url(ticket)
    dm_data = {k: data[k] for k in DM_DATA_KEYS if k in data}
    for user_id in _personal_recipient_ids(ticket, event, data):
        if user_id == actor_id:
            continue
        try:
            user = User.objects.filter(pk=user_id, is_active=True).first()
            if user is None or not user.has_perm("aa_ticket.basic_access") or not access.can_view(user, ticket):
                continue
            with user_language(user):
                text = personal_text(ticket, event, data, recipient_id=user.pk)
                notify(
                    user=user,
                    title=personal_title(ticket),
                    message=f"{text}\n{url}",
                    level=EVENT_LEVEL.get(event, "info"),
                )
            if dm_available:
                send_dm.delay(user.pk, ticket.pk, event, dm_data)
        except Exception as exc:  # noqa: BLE001 - one recipient must not block the others
            logger.warning("Notification for ticket %s to user %s failed: %s", ticket.display_number, user_id, type(exc).__name__)

    for department_id, mention in targets:
        if department_id in existing:
            if limited and not cache.add(limit_key, 1, UNCLAIMED_REPLY_NOTICE_SECONDS):
                continue  # this ticket already had its notice within the last hour
            try:
                send_webhook.delay(department_id, ticket.pk, event, mention)
            except Exception as exc:  # noqa: BLE001 - broker down: keep going
                if limited:
                    cache.delete(limit_key)  # nothing was sent, so the next reply may try again
                logger.warning("Could not queue Discord message for ticket %s: %s", ticket.display_number, type(exc).__name__)

    try:
        _clear_caches(ticket, actor_id, data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not refresh menu badges: %s", type(exc).__name__)


__all__ = ["dispatch", "personal_text", "display_name"]
