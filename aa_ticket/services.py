"""All actions that change tickets.

Every function checks permissions through `access`, runs in a transaction,
writes a system event to the ticket's timeline and hands the event to
`notifications.dispatch` once the transaction has been committed.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from . import access
from .constants import ClosedReason, Event, MessageKind, Status
from .exceptions import TicketActionError
from .models import EscalationRequest, Ticket, TicketMessage, TicketSettings
from .notifications import dispatch
from .utils import display_name

TITLE_MAX = 200


def _require(user, ticket, action):
    if not access.can_act(user, ticket, action):
        raise PermissionDenied(action)


def _emit(ticket, event, actor=None, data=None):
    """Write a system event to the timeline and dispatch it after commit."""
    data = dict(data or {})
    message = TicketMessage.objects.create(
        ticket=ticket,
        author=actor,
        kind=MessageKind.EVENT,
        event_type=event,
        event_data=data,
    )
    ticket_id = ticket.pk
    actor_id = actor.pk if actor else None
    transaction.on_commit(lambda: dispatch(event, ticket_id, actor_id, data), robust=True)
    return message


def _save_images(message, images):
    if not images:
        return
    from .attachments import save_images

    save_images(message, images)


def _author_department(user, ticket):
    staff_ids = access.staff_department_ids(user)
    if not staff_ids:
        return None
    preferred = [ticket.department_id]
    preferred += [d.pk for d in ticket.collaborating_departments.all()]
    preferred += [d.pk for d in ticket.department.ancestors()]
    for pk in preferred:
        if pk in staff_ids:
            return type(ticket.department).objects.get(pk=pk)
    return type(ticket.department).objects.filter(pk__in=staff_ids).order_by("order", "name").first()


def _clean_text(text):
    return (text or "").strip()


def _validate_images(images):
    if not images:
        return
    from .attachments import uploads_enabled, validate_images

    if not uploads_enabled():
        raise TicketActionError(_("Image uploads are turned off on this server."))
    try:
        validate_images(list(images))
    except ValidationError as exc:
        raise TicketActionError(" ".join(exc.messages)) from exc


@transaction.atomic
def create_ticket(user, department, priority, title, body, category=None, images=()):
    if department not in access.submittable_departments(user):
        raise PermissionDenied("department")
    title = _clean_text(title)
    body = _clean_text(body)
    if not title:
        raise TicketActionError(_("Please enter a title."))
    if len(title) > TITLE_MAX:
        raise TicketActionError(_("Please keep the title under 200 characters."))
    if not body:
        raise TicketActionError(_("Please describe your request."))
    if not priority.is_active:
        raise TicketActionError(_("Please pick an available priority."))
    if category is not None and (category.department_id != department.pk or not category.is_active):
        raise TicketActionError(_("Please pick a category of the selected department."))
    limit = TicketSettings.get_solo().max_open_tickets
    open_count = Ticket.objects.filter(requester=user).exclude(status=Status.CLOSED).count()
    if open_count >= limit:
        raise TicketActionError(
            _(
                "You already have %(count)d open tickets. Please close resolved tickets "
                "before opening a new one."
            )
            % {"count": open_count}
        )
    _validate_images(images)
    now = timezone.now()
    ticket = Ticket.objects.create(
        title=title,
        requester=user,
        requester_character=getattr(user.profile, "main_character", None),
        department=department,
        category=category,
        priority=priority,
        status=Status.OPEN,
        open_since=now,
        last_reply_at=now,
        last_reply_by_staff=False,
    )
    message = TicketMessage.objects.create(ticket=ticket, author=user, kind=MessageKind.REPLY, body=body)
    _save_images(message, images)
    _emit(ticket, Event.SUBMITTED, user, {"department": department.name, "department_id": department.pk})
    return ticket


def _lock(ticket):
    return Ticket.objects.select_for_update().get(pk=ticket.pk)


@transaction.atomic
def add_reply(user, ticket, body, images=()):
    ticket = _lock(ticket)
    _require(user, ticket, "reply")
    body = _clean_text(body)
    if not body and not images:
        raise TicketActionError(_("Please write a message before sending."))
    _validate_images(images)
    by_staff = access.is_staff_for(user, ticket)
    message = TicketMessage.objects.create(
        ticket=ticket,
        author=user,
        kind=MessageKind.REPLY,
        body=body,
        author_department=_author_department(user, ticket) if by_staff else None,
    )
    _save_images(message, images)
    ticket.last_reply_at = message.created_at
    ticket.last_reply_by_staff = by_staff
    ticket.autoclose_warned_at = None
    ticket.staff_reminded_at = None
    ticket.save(update_fields=["last_reply_at", "last_reply_by_staff", "autoclose_warned_at", "staff_reminded_at"])
    ticket_id, actor_id, data = ticket.pk, user.pk, {"by_staff": by_staff, "message_id": message.pk}
    transaction.on_commit(lambda: dispatch(Event.REPLIED, ticket_id, actor_id, data), robust=True)
    return message


@transaction.atomic
def add_note(user, ticket, body, images=()):
    ticket = _lock(ticket)
    _require(user, ticket, "note")
    body = _clean_text(body)
    if not body and not images:
        raise TicketActionError(_("Please write a message before sending."))
    _validate_images(images)
    message = TicketMessage.objects.create(
        ticket=ticket,
        author=user,
        kind=MessageKind.INTERNAL,
        body=body,
        author_department=_author_department(user, ticket),
    )
    _save_images(message, images)
    return message


@transaction.atomic
def claim(user, ticket):
    if not access.is_controller(user, ticket):
        raise PermissionDenied("claim")
    updated = Ticket.objects.filter(pk=ticket.pk, status=Status.OPEN).update(
        status=Status.IN_PROGRESS, assignee=user, claimed_at=timezone.now()
    )
    if not updated:
        current = Ticket.objects.get(pk=ticket.pk)
        if current.assignee_id:
            raise TicketActionError(
                _("Already claimed by %(name)s.") % {"name": display_name(current.assignee)}
            )
        raise TicketActionError(_("This ticket can no longer be claimed."))
    ticket = Ticket.objects.get(pk=ticket.pk)
    _emit(ticket, Event.CLAIMED, user, {"assignee": display_name(user)})


@transaction.atomic
def assign(actor, ticket, assignee):
    ticket = _lock(ticket)
    _require(actor, ticket, "assign")
    if assignee is None or not access.assignable_users(ticket).filter(pk=assignee.pk).exists():
        raise TicketActionError(_("Pick someone from the responsible department."))
    ticket.assignee = assignee
    fields = ["assignee"]
    if ticket.status == Status.OPEN:
        ticket.status = Status.IN_PROGRESS
        ticket.claimed_at = timezone.now()
        fields += ["status", "claimed_at"]
    ticket.save(update_fields=fields)
    _emit(ticket, Event.ASSIGNED, actor, {"assignee": display_name(assignee), "assignee_id": assignee.pk})


@transaction.atomic
def invite(actor, ticket, department):
    ticket = _lock(ticket)
    _require(actor, ticket, "invite")
    if not department.is_active:
        raise TicketActionError(_("This department is not active."))
    if department.pk == ticket.department_id:
        raise TicketActionError(_("This department is already responsible for the ticket."))
    if ticket.collaborating_departments.filter(pk=department.pk).exists():
        raise TicketActionError(_("This department is already working on the ticket."))
    ticket.collaborating_departments.add(department)
    _emit(ticket, Event.INVITED, actor, {"department": department.name, "department_id": department.pk})


@transaction.atomic
def uninvite(actor, ticket, department):
    ticket = _lock(ticket)
    _require(actor, ticket, "uninvite")
    if not ticket.collaborating_departments.filter(pk=department.pk).exists():
        raise TicketActionError(_("This department is not working on the ticket."))
    ticket.collaborating_departments.remove(department)
    _emit(ticket, Event.UNINVITED, actor, {"department": department.name, "department_id": department.pk})


@transaction.atomic
def transfer(actor, ticket, department, keep_as_collaborator=True, reason=""):
    ticket = _lock(ticket)
    _require(actor, ticket, "transfer")
    if not department.is_active:
        raise TicketActionError(_("This department is not active."))
    if department.pk == ticket.department_id:
        raise TicketActionError(_("The ticket is already with this department."))
    old = ticket.department
    ticket.department = department
    ticket.status = Status.OPEN
    ticket.assignee = None
    ticket.open_since = timezone.now()
    ticket.reminded_at = None
    ticket.escalated_at = None
    ticket.escalation_cycle += 1
    ticket.save()
    ticket.collaborating_departments.remove(department)
    if keep_as_collaborator:
        ticket.collaborating_departments.add(old)
    _emit(
        ticket,
        Event.TRANSFERRED,
        actor,
        {
            "from": old.name,
            "to": department.name,
            "department_id": department.pk,
            "reason": _clean_text(reason),
        },
    )


@transaction.atomic
def request_escalation(user, ticket, reason=""):
    ticket = _lock(ticket)
    _require(user, ticket, "escalate")
    target = access.next_escalation_target(ticket)
    request = EscalationRequest.objects.create(
        ticket=ticket,
        to_department=target,
        requested_by=user,
        reason=_clean_text(reason),
        cycle=ticket.escalation_cycle,
    )
    ticket.collaborating_departments.add(target)
    _emit(
        ticket,
        Event.ESCALATION_REQUESTED,
        user,
        {"department": target.name, "department_id": target.pk, "reason": request.reason},
    )
    return request


@transaction.atomic
def change_priority(actor, ticket, priority):
    ticket = _lock(ticket)
    _require(actor, ticket, "priority")
    if not priority.is_active:
        raise TicketActionError(_("Please pick an available priority."))
    if priority.pk == ticket.priority_id:
        return
    old = ticket.priority
    ticket.priority = priority
    ticket.save(update_fields=["priority"])
    _emit(ticket, Event.PRIORITY_CHANGED, actor, {"from": old.name, "to": priority.name})


@transaction.atomic
def change_category(actor, ticket, category):
    ticket = _lock(ticket)
    _require(actor, ticket, "category")
    if category is not None and category.department_id != ticket.department_id:
        raise TicketActionError(_("Please pick a category of the responsible department."))
    if (category.pk if category else None) == ticket.category_id:
        return
    old = ticket.category
    ticket.category = category
    ticket.save(update_fields=["category"])
    _emit(
        ticket,
        Event.CATEGORY_CHANGED,
        actor,
        {"from": old.name if old else "", "to": category.name if category else ""},
    )


@transaction.atomic
def close(actor, ticket, reason, final_reply=""):
    ticket = _lock(ticket)
    if actor is not None:
        _require(actor, ticket, "close")
    elif ticket.status != Status.IN_PROGRESS or not ticket.last_reply_by_staff:
        return  # automatic close only while waiting for the requester (re-checked under lock)
    if _clean_text(final_reply):
        add_reply(actor, ticket, final_reply)
        ticket = _lock(ticket)
    ticket.status = Status.CLOSED
    ticket.closed_at = timezone.now()
    ticket.closed_by = actor
    ticket.closed_reason = reason if actor is not None else ClosedReason.AUTO
    ticket.save(update_fields=["status", "closed_at", "closed_by", "closed_reason"])
    _emit(ticket, Event.CLOSED, actor, {"reason": ticket.closed_reason})


@transaction.atomic
def reopen(actor, ticket):
    ticket = _lock(ticket)
    _require(actor, ticket, "reopen")
    now = timezone.now()
    if ticket.assignee_id:
        ticket.status = Status.IN_PROGRESS
    else:
        ticket.status = Status.OPEN
        ticket.open_since = now
        ticket.reminded_at = None
        ticket.escalated_at = None
    ticket.closed_at = None
    ticket.closed_by = None
    ticket.closed_reason = ""
    ticket.autoclose_warned_at = None
    ticket.staff_reminded_at = None
    ticket.last_reply_at = now
    ticket.save()
    _emit(ticket, Event.REOPENED, actor, {})
