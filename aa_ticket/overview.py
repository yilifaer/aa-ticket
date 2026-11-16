"""Data for the ticket overview page and the Alliance Auth dashboard card.

Users with view_all only see their own departments here; the workbench shows everything.
"""

from django.db.models import Case, IntegerField, Q, Value, When
from django.urls import reverse
from django.utils.translation import pgettext_lazy

from . import access
from .constants import Status
from .models import Ticket

PREVIEW = 5

_RELATED = (
    "department",
    "priority",
    "requester__profile__main_character",
    "requester_character",
    "assignee__profile__main_character",
)


def _open():
    return Ticket.objects.exclude(status=Status.CLOSED).select_related(*_RELATED)


def own_tickets(user):
    """Tickets the user submitted; waiting for the user (staff replied last) first."""
    waiting = Case(
        When(status=Status.IN_PROGRESS, last_reply_by_staff=True, then=Value(1)),
        default=Value(0),
        output_field=IntegerField(),
    )
    return _open().filter(requester=user).annotate(waiting=waiting).order_by("-waiting", "-last_reply_at")


def assigned_tickets(user):
    """Tickets assigned to the user; waiting for the user (requester replied last) first."""
    visible = access.visible_tickets(user).filter(assignee=user).values("pk")
    return (
        _open()
        .filter(pk__in=visible)
        .exclude(requester=user)
        .order_by("last_reply_by_staff", "-last_reply_at")
    )


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
    is_staff = access.is_department_staff(user)
    own = _section(
        "own",
        pgettext_lazy("aa_ticket", "My submitted tickets"),
        pgettext_lazy("aa_ticket", "No open tickets."),
        own_tickets(user),
        reverse("aa_ticket:my_tickets"),
    )
    if not is_staff:
        return [own]
    workbench = reverse("aa_ticket:workbench")
    mine = _section(
        "mine",
        pgettext_lazy("aa_ticket", "Assigned to me"),
        pgettext_lazy("aa_ticket", "No tickets assigned to you."),
        assigned_tickets(user),
        f"{workbench}?tab=mine",
    )
    if not department_ids:  # view_all without own departments
        return [mine, own]
    return [
        mine,
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
    is_staff = access.is_department_staff(user)
    own = own_tickets(user)
    summary = {
        "is_staff": is_staff,
        "open": own.count(),
        "waiting": own.filter(status=Status.IN_PROGRESS, last_reply_by_staff=True).count(),
        "assigned": 0,
        "unclaimed": 0,
        "urgent": 0,
    }
    recent_q = Q(requester=user)
    if is_staff:
        assigned = assigned_tickets(user)
        summary["assigned"] = assigned.count()
        recent_q |= Q(pk__in=assigned.values("pk"))
    if department_ids:
        unclaimed = unclaimed_tickets(user, department_ids)
        summary["unclaimed"] = unclaimed.count()
        summary["urgent"] = unclaimed.filter(priority__is_urgent=True).count()
        recent_q |= Q(status=Status.OPEN, department_id__in=department_ids)
    if not any(summary[k] for k in ("open", "assigned", "unclaimed")):
        return None
    summary["recent"] = list(_open().filter(recent_q).distinct().order_by("-last_reply_at")[:PREVIEW])
    return summary
