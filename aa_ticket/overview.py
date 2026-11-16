"""Data for the ticket overview page and the Alliance Auth dashboard card.

Users with view_all only see their own departments here; the workbench shows everything.
"""

from django.db.models import Q
from django.urls import reverse
from django.utils.translation import pgettext_lazy

from . import access
from .constants import Status
from .models import Ticket

PREVIEW = 5

_RELATED = ("department", "priority", "requester", "requester_character", "assignee")


def _open():
    return Ticket.objects.exclude(status=Status.CLOSED).select_related(*_RELATED)


def own_tickets(user):
    """Tickets the user submitted; waiting for the user (staff replied last) first."""
    return _open().filter(requester=user).order_by("-last_reply_by_staff", "-last_reply_at")


def assigned_tickets(user):
    """Tickets assigned to the user; waiting for the user (requester replied last) first."""
    return _open().filter(assignee=user).exclude(requester=user).order_by("last_reply_by_staff", "-last_reply_at")


def unclaimed_tickets(user, department_ids):
    return (
        _open()
        .filter(status=Status.OPEN, department_id__in=department_ids)
        .exclude(requester=user)
        .order_by("-priority__is_urgent", "-priority__order", "created_at")
    )


def escalated_tickets(user, department_ids):
    """Tickets of other departments that our departments were invited to or escalated to."""
    return (
        _open()
        .filter(collaborating_departments__in=department_ids)
        .exclude(department_id__in=department_ids)
        .exclude(requester=user)
        .distinct()
        .order_by("-last_reply_at")
    )


def _section(key, title, empty, queryset, url):
    return {
        "key": key,
        "title": title,
        "empty": empty,
        "items": list(queryset[:PREVIEW]),
        "count": queryset.count(),
        "url": url,
    }


def sections_for(user):
    department_ids = access.staff_department_ids(user)
    own = _section(
        "own",
        pgettext_lazy("aa_ticket", "My submitted tickets"),
        pgettext_lazy("aa_ticket", "No open tickets."),
        own_tickets(user),
        reverse("aa_ticket:my_tickets"),
    )
    if not department_ids:
        return [own]
    workbench = reverse("aa_ticket:workbench")
    return [
        _section(
            "mine",
            pgettext_lazy("aa_ticket", "Assigned to me"),
            pgettext_lazy("aa_ticket", "No tickets assigned to you."),
            assigned_tickets(user),
            f"{workbench}?tab=mine",
        ),
        _section(
            "unclaimed",
            pgettext_lazy("aa_ticket", "Unclaimed in my departments"),
            pgettext_lazy("aa_ticket", "No unclaimed tickets."),
            unclaimed_tickets(user, department_ids),
            f"{workbench}?tab=unclaimed",
        ),
        _section(
            "escalated",
            pgettext_lazy("aa_ticket", "Escalated or shared with my departments"),
            pgettext_lazy("aa_ticket", "No escalated tickets."),
            escalated_tickets(user, department_ids),
            f"{workbench}?tab=collab",
        ),
        own,
    ]


def dashboard_summary(user):
    """Counts and a few recent tickets for the dashboard card, or None if there is nothing to show."""
    department_ids = access.staff_department_ids(user)
    own = own_tickets(user)
    summary = {
        "is_staff": bool(department_ids),
        "open": own.count(),
        "waiting": own.filter(status=Status.IN_PROGRESS, last_reply_by_staff=True).count(),
        "assigned": 0,
        "assigned_waiting": 0,
        "unclaimed": 0,
        "urgent": 0,
    }
    recent_q = Q(requester=user)
    if department_ids:
        assigned = assigned_tickets(user)
        unclaimed = unclaimed_tickets(user, department_ids)
        summary["assigned"] = assigned.count()
        summary["assigned_waiting"] = assigned.filter(last_reply_by_staff=False).count()
        summary["unclaimed"] = unclaimed.count()
        summary["urgent"] = unclaimed.filter(priority__is_urgent=True).count()
        recent_q |= Q(assignee=user) | Q(status=Status.OPEN, department_id__in=department_ids)
    if not any(summary[k] for k in ("open", "assigned", "unclaimed")):
        return None
    summary["recent"] = list(_open().filter(recent_q).distinct().order_by("-last_reply_at")[:PREVIEW])
    return summary
