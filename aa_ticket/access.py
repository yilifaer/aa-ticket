"""Who can see a ticket and who can do what with it.

This module is the single source of truth for access decisions. Views,
services, notifications and statistics must use these functions instead of
writing their own checks. See the design document, sections 6.2 and 6.3.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from .constants import Status
from .models import Department, EscalationRequest, Ticket, TicketSettings

_CACHE_ATTR = "_aa_ticket_staff_ids"

CONTROLLER_ACTIONS = {"assign", "invite", "uninvite", "transfer", "priority", "category"}


def _children_map():
    children = {}
    for pk, parent_id in Department.objects.values_list("pk", "parent_id"):
        children.setdefault(parent_id, []).append(pk)
    return children


def _with_descendants(department_ids):
    if not department_ids:
        return set()
    children = _children_map()
    result = set()
    stack = list(department_ids)
    while stack:
        pk = stack.pop()
        if pk in result:
            continue
        result.add(pk)
        stack.extend(children.get(pk, []))
    return result


def has_view_all(user):
    return user.is_authenticated and user.has_perm("aa_ticket.view_all")


def staff_department_ids(user):
    """IDs of active departments whose staff groups contain this user."""
    if not user.is_authenticated:
        return set()
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is None:
        cached = set(
            Department.objects.filter(is_active=True, groups__user=user)
            .values_list("pk", flat=True)
            .distinct()
        )
        setattr(user, _CACHE_ATTR, cached)
    return cached


def is_department_staff(user):
    return bool(staff_department_ids(user)) or has_view_all(user)


def controller_department_ids(ticket):
    return {ticket.department_id} | {d.pk for d in ticket.department.ancestors()}


def collaborator_department_ids(ticket):
    ids = set()
    for department in ticket.collaborating_departments.all():
        ids.add(department.pk)
        ids.update(d.pk for d in department.ancestors())
    return ids


def is_controller(user, ticket):
    if not user.is_authenticated or user.pk == ticket.requester_id:
        return False
    if has_view_all(user):
        return True
    return bool(staff_department_ids(user) & controller_department_ids(ticket))


def is_collaborator(user, ticket):
    if not user.is_authenticated or user.pk == ticket.requester_id:
        return False
    return bool(staff_department_ids(user) & collaborator_department_ids(ticket))


def is_staff_for(user, ticket):
    return is_controller(user, ticket) or is_collaborator(user, ticket)


def can_view(user, ticket):
    if not user.is_authenticated:
        return False
    return user.pk == ticket.requester_id or is_staff_for(user, ticket)


def can_view_internal(user, ticket):
    return is_staff_for(user, ticket)


def _requester_can_reopen(ticket):
    if not ticket.closed_at:
        return False
    days = TicketSettings.get_solo().reopen_days
    return timezone.now() <= ticket.closed_at + timedelta(days=days)


def can_act(user, ticket, action):
    if not user.is_authenticated:
        return False
    is_requester = user.pk == ticket.requester_id
    closed = ticket.status == Status.CLOSED
    if action == "reopen":
        if not closed:
            return False
        return is_controller(user, ticket) or (
            is_requester and ticket.department.is_active and _requester_can_reopen(ticket)
        )
    if closed:
        return False
    if action == "reply":
        # Public replies: the requester, or the current assignee while they still handle the ticket.
        return is_requester or (
            ticket.status == Status.IN_PROGRESS and ticket.assignee_id == user.pk and is_staff_for(user, ticket)
        )
    if action == "note":
        return is_staff_for(user, ticket)
    if action == "claim":
        return ticket.status == Status.OPEN and is_controller(user, ticket)
    if action in CONTROLLER_ACTIONS:
        return is_controller(user, ticket)
    if action == "escalate":
        return is_requester and next_escalation_target(ticket) is not None
    if action == "close":
        return is_requester or is_controller(user, ticket)
    raise ValueError(f"unknown action: {action}")


def reply_hint(user, ticket):
    """Why a staff member cannot reply publicly, or "" if they can."""
    from django.utils.translation import pgettext

    from .utils import display_name

    if can_act(user, ticket, "reply") or ticket.status == Status.CLOSED or not is_staff_for(user, ticket):
        return ""
    if ticket.status == Status.IN_PROGRESS and ticket.assignee_id and ticket.assignee_id != user.pk:
        return pgettext("aa_ticket", "This ticket is handled by %(name)s. You can write an internal note.") % {
            "name": display_name(ticket.assignee)
        }
    return pgettext("aa_ticket", "Claim the ticket to reply to the requester.")


def visible_tickets(user):
    """All tickets the user can view, as one query (same rules as can_view)."""
    if not user.is_authenticated:
        return Ticket.objects.none()
    if has_view_all(user):
        return Ticket.objects.all()
    expanded = _with_descendants(staff_department_ids(user))
    query = Q(requester=user)
    if expanded:
        staff_q = Q(department_id__in=expanded) | Q(collaborating_departments__in=expanded)
        query |= staff_q & ~Q(requester=user)
    return Ticket.objects.filter(query).distinct()


def department_staff(department):
    """Active users who are staff of this department."""
    return User.objects.filter(is_active=True, groups__aa_ticket_departments=department).distinct()


def assignable_users(ticket):
    department_ids = Department.objects.filter(
        pk__in=controller_department_ids(ticket), is_active=True
    ).values_list("pk", flat=True)
    return (
        User.objects.filter(is_active=True, groups__aa_ticket_departments__in=department_ids)
        .exclude(pk=ticket.requester_id)
        .distinct()
        .order_by("username")
    )


def submittable_departments(user):
    qs = Department.objects.filter(is_active=True, accepts_submissions=True)
    state = getattr(getattr(user, "profile", None), "state", None)
    open_q = Q(submit_states__isnull=True) & Q(submit_groups__isnull=True)
    allowed_q = Q(submit_groups__in=user.groups.all())
    if state is not None:
        allowed_q |= Q(submit_states=state)
    allowed_ids = qs.filter(open_q | allowed_q).values_list("pk", flat=True)
    return qs.filter(pk__in=allowed_ids).order_by("order", "name")


def next_escalation_target(ticket):
    already = set(
        EscalationRequest.objects.filter(ticket=ticket, cycle=ticket.escalation_cycle).values_list(
            "to_department_id", flat=True
        )
    )
    for department in ticket.department.ancestors():
        if department.is_active and department.pk not in already:
            return department
    return None


def stats_department_ids(user):
    """None means all departments."""
    if has_view_all(user):
        return None
    return _with_descendants(staff_department_ids(user))
