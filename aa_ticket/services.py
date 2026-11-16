"""All actions that change tickets.

Every function checks permissions through `access`, runs in a transaction,
writes a system event to the ticket's timeline and hands the event to
`notifications.dispatch` once the transaction has been committed.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import pgettext

from . import access
from .constants import ClosedReason, Event, MessageKind, Status
from .exceptions import TicketActionError
from .models import EscalationRequest, Ticket, TicketMessage, TicketSettings
from .attachments import prepare_images, save_prepared, uploads_enabled
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


def _prepare(images):
    """Validate and re-encode uploads before any ticket row is locked."""
    if not images:
        return []
    if not uploads_enabled():
        raise TicketActionError(pgettext("aa_ticket", "Image uploads are turned off on this server."))
    try:
        return prepare_images(images)
    except ValidationError as exc:
        raise TicketActionError(" ".join(exc.messages)) from exc


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


# Characters that can reorder how text is displayed, plus NUL.
_STRIP_CHARS = dict.fromkeys(map(ord, "\x00\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"))
# Invisible characters that do not count as content.
_INVISIBLE = "\u200b\u200c\u200d\u2060\ufeff"
BODY_MAX = 10000
REASON_MAX = 1000


def _clean_text(text, max_length=None):
    text = (text or "").translate(_STRIP_CHARS).strip()
    if not text.strip(_INVISIBLE + " \t\r\n"):
        return ""
    if max_length and len(text) > max_length:
        raise TicketActionError(
            pgettext("aa_ticket", "Please keep the text under %(count)d characters.") % {"count": max_length}
        )
    return text


@transaction.atomic
def create_ticket(user, department, priority, title, body, category=None, images=()):
    if department not in access.submittable_departments(user):
        raise PermissionDenied("department")
    title = _clean_text(title)
    body = _clean_text(body, BODY_MAX)
    if not title:
        raise TicketActionError(pgettext("aa_ticket", "Please enter a title."))
    if len(title) > TITLE_MAX:
        raise TicketActionError(pgettext("aa_ticket", "Please keep the title under 200 characters."))
    if not body:
        raise TicketActionError(pgettext("aa_ticket", "Please describe your request."))
    if not priority.is_active:
        raise TicketActionError(pgettext("aa_ticket", "Please pick an available priority."))
    if category is not None and (category.department_id != department.pk or not category.is_active):
        raise TicketActionError(pgettext("aa_ticket", "Please pick a category of the selected department."))
    limit = TicketSettings.get_solo().max_open_tickets
    open_count = Ticket.objects.filter(requester=user).exclude(status=Status.CLOSED).count()
    if open_count >= limit:
        raise TicketActionError(
            pgettext("aa_ticket", 
                "You already have %(count)d open tickets. Please close resolved tickets "
                "before opening a new one."
            )
            % {"count": open_count}
        )
    prepared = _prepare(images)
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
    save_prepared(message, prepared)
    _emit(ticket, Event.SUBMITTED, user, {"department": department.name, "department_id": department.pk})
    return ticket


def _lock(ticket):
    return Ticket.objects.select_for_update().get(pk=ticket.pk)


@transaction.atomic
def add_reply(user, ticket, body, images=(), notify=True):
    _require(user, ticket, "reply")  # cheap pre-check; repeated below under the lock
    body = _clean_text(body, BODY_MAX)
    if not body and not images:
        raise TicketActionError(pgettext("aa_ticket", "Please write a message before sending."))
    prepared = _prepare(images)
    ticket = _lock(ticket)
    _require(user, ticket, "reply")
    by_staff = access.is_staff_for(user, ticket)
    message = TicketMessage.objects.create(
        ticket=ticket,
        author=user,
        kind=MessageKind.REPLY,
        body=body,
        author_department=_author_department(user, ticket) if by_staff else None,
    )
    save_prepared(message, prepared)
    ticket.last_reply_at = message.created_at
    ticket.last_reply_by_staff = by_staff
    ticket.autoclose_warned_at = None
    ticket.staff_reminded_at = None
    ticket.save(update_fields=["last_reply_at", "last_reply_by_staff", "autoclose_warned_at", "staff_reminded_at"])
    ticket_id, actor_id, data = ticket.pk, user.pk, {"by_staff": by_staff, "message_id": message.pk}
    if notify:
        transaction.on_commit(lambda: dispatch(Event.REPLIED, ticket_id, actor_id, data), robust=True)
    return message


@transaction.atomic
def add_note(user, ticket, body, images=()):
    _require(user, ticket, "note")  # cheap pre-check; repeated below under the lock
    body = _clean_text(body, BODY_MAX)
    if not body and not images:
        raise TicketActionError(pgettext("aa_ticket", "Please write a message before sending."))
    prepared = _prepare(images)
    ticket = _lock(ticket)
    _require(user, ticket, "note")
    message = TicketMessage.objects.create(
        ticket=ticket,
        author=user,
        kind=MessageKind.INTERNAL,
        body=body,
        author_department=_author_department(user, ticket),
    )
    save_prepared(message, prepared)
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
                pgettext("aa_ticket", "Already claimed by %(name)s.") % {"name": display_name(current.assignee)}
            )
        raise TicketActionError(pgettext("aa_ticket", "This ticket can no longer be claimed."))
    ticket = Ticket.objects.get(pk=ticket.pk)
    _emit(ticket, Event.CLAIMED, user, {"assignee": display_name(user)})


@transaction.atomic
def assign(actor, ticket, assignee):
    ticket = _lock(ticket)
    _require(actor, ticket, "assign")
    if assignee is None or not access.assignable_users(ticket).filter(pk=assignee.pk).exists():
        raise TicketActionError(pgettext("aa_ticket", "Pick someone from the responsible department."))
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
        raise TicketActionError(pgettext("aa_ticket", "This department is not active."))
    if department.pk == ticket.department_id:
        raise TicketActionError(pgettext("aa_ticket", "This department is already responsible for the ticket."))
    if ticket.collaborating_departments.filter(pk=department.pk).exists():
        raise TicketActionError(pgettext("aa_ticket", "This department is already working on the ticket."))
    ticket.collaborating_departments.add(department)
    _emit(ticket, Event.INVITED, actor, {"department": department.name, "department_id": department.pk})


@transaction.atomic
def uninvite(actor, ticket, department):
    ticket = _lock(ticket)
    _require(actor, ticket, "uninvite")
    if not ticket.collaborating_departments.filter(pk=department.pk).exists():
        raise TicketActionError(pgettext("aa_ticket", "This department is not working on the ticket."))
    ticket.collaborating_departments.remove(department)
    _emit(ticket, Event.UNINVITED, actor, {"department": department.name, "department_id": department.pk})


@transaction.atomic
def transfer(actor, ticket, department, keep_as_collaborator=True, reason=""):
    ticket = _lock(ticket)
    _require(actor, ticket, "transfer")
    if not department.is_active:
        raise TicketActionError(pgettext("aa_ticket", "This department is not active."))
    if department.pk == ticket.department_id:
        raise TicketActionError(pgettext("aa_ticket", "The ticket is already with this department."))
    old = ticket.department
    old_cycle = ticket.escalation_cycle
    ticket.department = department
    ticket.status = Status.OPEN
    ticket.assignee = None
    ticket.open_since = timezone.now()
    ticket.reminded_at = None
    ticket.escalated_at = None
    ticket.escalation_cycle += 1
    ticket.category = None
    ticket.last_reply_at = timezone.now()
    ticket.last_reply_by_staff = False
    ticket.autoclose_warned_at = None
    ticket.staff_reminded_at = None
    ticket.save()
    ticket.collaborating_departments.remove(department)
    if keep_as_collaborator:
        ticket.collaborating_departments.add(old)
    else:
        # departments that only joined through an escalation of the old department leave too
        escalated = EscalationRequest.objects.filter(ticket=ticket, cycle=old_cycle).values_list(
            "to_department_id", flat=True
        )
        ticket.collaborating_departments.remove(*escalated)
    _emit(
        ticket,
        Event.TRANSFERRED,
        actor,
        {
            "from": old.name,
            "to": department.name,
            "department_id": department.pk,
            "reason": _clean_text(reason, REASON_MAX),
        },
    )


@transaction.atomic
def request_escalation(user, ticket, reason="", expected_target=None):
    ticket = _lock(ticket)
    _require(user, ticket, "escalate")
    target = access.next_escalation_target(ticket)
    if expected_target is not None and target.pk != expected_target.pk:
        raise TicketActionError(
            pgettext("aa_ticket", "%(department)s has already been asked to step in.")
            % {"department": expected_target.name}
        )
    request = EscalationRequest.objects.create(
        ticket=ticket,
        to_department=target,
        requested_by=user,
        reason=_clean_text(reason, REASON_MAX),
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
        raise TicketActionError(pgettext("aa_ticket", "Please pick an available priority."))
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
    if category is not None and (category.department_id != ticket.department_id or not category.is_active):
        raise TicketActionError(pgettext("aa_ticket", "Please pick a category of the responsible department."))
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
def close(actor, ticket, reason, final_reply="", expected_last_reply_at=None):
    ticket = _lock(ticket)
    if actor is not None:
        _require(actor, ticket, "close")
        if _clean_text(final_reply) and not access.can_act(actor, ticket, "reply"):
            raise TicketActionError(
                pgettext("aa_ticket", "Only the requester and the assignee can add a final reply.")
            )
    elif ticket.status != Status.IN_PROGRESS or not ticket.last_reply_by_staff:
        return  # automatic close only while waiting for the requester (re-checked under lock)
    elif expected_last_reply_at is not None and ticket.last_reply_at != expected_last_reply_at:
        return  # someone replied after the task looked at this ticket
    if _clean_text(final_reply):
        add_reply(actor, ticket, final_reply, notify=False)
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
    ticket.last_reply_by_staff = False
    ticket.save()
    _emit(ticket, Event.REOPENED, actor, {})
