from django import template
from django.template.defaultfilters import linebreaksbr, urlize
from django.urls import NoReverseMatch, reverse
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from .. import access
from ..constants import ClosedReason, Event
from ..discord import dm
from ..utils import display_name as _display_name

register = template.Library()

STAFF_ONLY_EVENTS = {
    Event.UNCLAIMED_REMINDER,
    Event.ESCALATION_REMINDER,
    Event.AUTOCLOSE_WARNING,
    Event.AWAITING_STAFF_REMINDER,
}


@register.filter
def rich_text(value):
    """Escape, make links clickable and keep line breaks. No HTML or Markdown."""
    return mark_safe(linebreaksbr(urlize(value or "", autoescape=True), autoescape=False))


@register.filter
def display_name(user):
    return _display_name(user) if user else _("System")


@register.simple_tag
def event_text(message):
    data = message.event_data or {}
    try:
        label = str(Event(message.event_type).label)
    except ValueError:
        label = message.event_type
    event = message.event_type
    detail = ""
    if event == Event.TRANSFERRED:
        detail = _("from %(from)s to %(to)s") % {"from": data.get("from", ""), "to": data.get("to", "")}
    elif event in (Event.INVITED, Event.UNINVITED, Event.ESCALATION_REQUESTED, Event.SUBMITTED):
        detail = data.get("department", "")
    elif event in (Event.PRIORITY_CHANGED, Event.CATEGORY_CHANGED):
        detail = _("to %(value)s") % {"value": data.get("to") or "—"}
    elif event in (Event.CLAIMED, Event.ASSIGNED):
        detail = data.get("assignee", "")
    elif event == Event.CLOSED and data.get("reason"):
        try:
            detail = str(ClosedReason(data["reason"]).label)
        except ValueError:
            detail = ""
    if data.get("reason") and event != Event.CLOSED:
        detail = f"{detail} — {data['reason']}" if detail else data["reason"]
    return f"{label}: {detail}" if detail else label


@register.filter
def visible_event(message, is_staff):
    return is_staff or message.event_type not in STAFF_ONLY_EVENTS


def _url(name):
    try:
        return reverse(name)
    except NoReverseMatch:
        return ""


@register.simple_tag(takes_context=True)
def aa_ticket_nav(context):
    request = context.get("request")
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    is_staff = access.is_department_staff(user)
    return {
        "mine": _url("aa_ticket:my_tickets"),
        "new": _url("aa_ticket:submit"),
        "workbench": _url("aa_ticket:workbench") if is_staff else "",
        "stats": _url("aa_ticket:stats") if is_staff else "",
        "manage": _url("aa_ticket:manage_departments") if user.has_perm("aa_ticket.manage") else (
            _url("aa_ticket:manage_canned") if is_staff else ""
        ),
        "prefs": _url("aa_ticket:prefs") if dm.is_available() else "",
    }
