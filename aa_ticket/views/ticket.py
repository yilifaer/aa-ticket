from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import pgettext
from django.views.decorators.http import require_POST

from .. import access, services
from ..attachments import uploads_enabled
from ..constants import ClosedReason, MessageKind, Status
from ..exceptions import TicketActionError
from ..models import Attachment, CannedReply, Category, Department, Priority, Ticket, TicketMessage, TicketSettings

basic = permission_required("aa_ticket.basic_access", raise_exception=True)

ACTIONS = ("claim", "assign", "invite", "uninvite", "transfer", "escalate", "priority", "category", "close", "reopen")


def get_visible_ticket(user, pk):
    ticket = get_object_or_404(
        Ticket.objects.select_related("department", "priority", "category", "requester", "assignee"), pk=pk
    )
    if not access.can_view(user, ticket):
        raise Http404
    return ticket


def _autoclose_eta(ticket):
    if ticket.status != Status.IN_PROGRESS or not ticket.last_reply_by_staff:
        return None
    return ticket.last_reply_at + timedelta(days=TicketSettings.get_solo().autoclose_days)


def detail_context(user, ticket):
    is_staff = access.can_view_internal(user, ticket)
    msgs = ticket.messages.select_related("author__profile__main_character", "author_department").prefetch_related(
        Prefetch("attachments", queryset=Attachment.objects.order_by("pk"))
    )
    if not is_staff:
        msgs = msgs.exclude(kind=MessageKind.INTERNAL)
    can = {action: access.can_act(user, ticket, action) for action in ACTIONS + ("reply", "note")}
    context = {
        "ticket": ticket,
        "timeline": msgs,
        "is_staff": is_staff,
        "can": can,
        "collaborators": ticket.collaborating_departments.all(),
        "escalation_target": access.next_escalation_target(ticket) if can["escalate"] else None,
        "reply_hint": access.reply_hint(user, ticket),
        "nav_active": "workbench" if is_staff else "mine",
        "autoclose_eta": _autoclose_eta(ticket),
        "uploads_enabled": uploads_enabled(),
        "statuses": Status,
    }
    if is_staff:
        staff_ids = access.staff_department_ids(user) | {ticket.department_id}
        context["canned_replies"] = CannedReply.objects.filter(
            Q(department__isnull=True) | Q(department_id__in=staff_ids)
        ).order_by("title")
    if can["assign"]:
        context["assignable_users"] = access.assignable_users(ticket)
    if can["invite"] or can["transfer"]:
        context["other_departments"] = Department.objects.filter(is_active=True).exclude(pk=ticket.department_id)
    if can["priority"]:
        context["priorities"] = Priority.objects.filter(is_active=True)
    if can["category"]:
        context["categories"] = Category.objects.filter(department=ticket.department, is_active=True)
    return context


@login_required
@basic
def detail(request, pk):
    ticket = get_visible_ticket(request.user, pk)
    context = detail_context(request.user, ticket)
    context["draft"] = request.session.pop(_draft_key(pk), None)
    return render(request, "aa_ticket/detail.html", context)


REQUESTER_ACTIONS = {"reply", "escalate", "close", "reopen"}


def _after(request, ticket):
    """Where to go after an action: the ticket, or a list if the user can no longer open it."""
    current = Ticket.objects.select_related("department").filter(pk=ticket.pk).first()
    if current is not None and access.can_view(request.user, current):
        return redirect("aa_ticket:detail", pk=ticket.pk)
    if access.is_department_staff(request.user):
        return redirect("aa_ticket:workbench")
    return redirect("aa_ticket:my_tickets")


def _stale(request, ticket, action):
    """A permission error on something the page offered means the ticket changed meanwhile."""
    user = request.user
    offered = access.is_staff_for(user, ticket) or (user.pk == ticket.requester_id and action in REQUESTER_ACTIONS)
    if not offered:
        raise PermissionDenied
    messages.error(
        request,
        pgettext("aa_ticket", "That is no longer possible because the ticket has changed. Please check its current state."),
    )
    return _after(request, ticket)


def _run(request, ticket, func, *args, success=None, action="", **kwargs):
    try:
        func(*args, **kwargs)
    except TicketActionError as exc:
        messages.error(request, exc.message)
        return False, redirect("aa_ticket:detail", pk=ticket.pk)
    except PermissionDenied:
        return False, _stale(request, ticket, action)
    if success:
        messages.success(request, success)
    return True, _after(request, ticket)


def _draft_key(pk):
    return f"aa_ticket_draft_{pk}"


@login_required
@basic
@require_POST
def reply(request, pk):
    ticket = get_visible_ticket(request.user, pk)
    kind = "internal" if request.POST.get("kind") == "internal" else "reply"
    body = request.POST.get("body", "")
    images = request.FILES.getlist("images")
    if kind == "internal":
        ok, response = _run(request, ticket, services.add_note, request.user, ticket, body, images=images, action="note")
    else:
        hint = access.reply_hint(request.user, ticket)
        if hint:
            messages.error(request, hint)
            ok, response = False, redirect("aa_ticket:detail", pk=ticket.pk)
        else:
            try:
                ok, response = _run(
                    request, ticket, services.add_reply, request.user, ticket, body, images=images, action="reply"
                )
            except PermissionDenied:
                raise
            if not ok:
                # The ticket may have changed after the page was loaded (for example reassigned).
                fresh_ticket = Ticket.objects.select_related("assignee", "department").filter(pk=pk).first()
                fresh_hint = access.reply_hint(request.user, fresh_ticket) if fresh_ticket else ""
                if fresh_hint:
                    messages.error(request, fresh_hint)
    if not ok and body.strip():
        # keep what the person typed so a rejected image or a changed ticket does not lose it
        request.session[_draft_key(pk)] = {"body": body[: services.BODY_MAX], "kind": kind}
    return response


def _int(value):
    value = str(value or "").strip()
    if not (value.isascii() and value.isdigit()) or len(value) > 18:
        return None
    return int(value)


@login_required
@basic
@require_POST
def action(request, pk, action):
    if action not in ACTIONS:
        raise Http404
    ticket = get_visible_ticket(request.user, pk)
    user = request.user
    post = request.POST
    def _act(*args, **kwargs):
        return _run(*args, action=action, **kwargs)[1]

    if action == "claim":
        return _act(request, ticket, services.claim, user, ticket, success=pgettext("aa_ticket", "You are now handling this ticket."))
    if action == "assign":
        assignee = User.objects.filter(pk=_int(post.get("user_id"))).first()
        return _act(request, ticket, services.assign, user, ticket, assignee, success=pgettext("aa_ticket", "Ticket assigned."))
    if action in ("invite", "uninvite", "transfer"):
        department = Department.objects.filter(pk=_int(post.get("department_id"))).first()
        if department is None:
            messages.error(request, pgettext("aa_ticket", "Please pick a department."))
            return redirect("aa_ticket:detail", pk=ticket.pk)
        if action == "invite":
            return _act(request, ticket, services.invite, user, ticket, department, success=pgettext("aa_ticket", "Department invited."))
        if action == "uninvite":
            return _act(request, ticket, services.uninvite, user, ticket, department, success=pgettext("aa_ticket", "Department removed."))
        keep = bool(post.get("keep")) if post.get("keep_present") else True
        return _act(
            request,
            ticket,
            services.transfer,
            user,
            ticket,
            department,
            keep_as_collaborator=keep,
            reason=post.get("reason", ""),
            success=pgettext("aa_ticket", "Ticket transferred."),
        )
    if action == "escalate":
        target = access.next_escalation_target(ticket)
        asked = {
            r.to_department_id: r.to_department.name
            for r in ticket.escalations.filter(cycle=ticket.escalation_cycle).select_related("to_department")
        }
        requested = _int(post.get("target_department_id"))
        is_requester = user.pk == ticket.requester_id and ticket.status != Status.CLOSED
        if is_requester and asked and (requested in asked or (requested is None and target is None)):
            # a second click, or a page that was open for a while
            name = asked.get(requested) or list(asked.values())[-1]
            messages.error(
                request, pgettext("aa_ticket", "%(department)s has already been asked to step in.") % {"department": name}
            )
            return redirect("aa_ticket:detail", pk=ticket.pk)
        if target is None or (requested is not None and requested != target.pk):
            # not the department this ticket would escalate to: say nothing about other departments
            return _stale(request, ticket, action)
        if target.webhook_url:
            success = pgettext("aa_ticket", "Escalation requested. %(department)s has been notified in Discord.")
        elif access.department_staff(target).exists():
            success = pgettext("aa_ticket", "Escalation requested. Staff of %(department)s have been notified in Alliance Auth.")
        else:
            success = pgettext(
                "aa_ticket",
                "Escalation requested, but %(department)s has no Discord channel or staff to notify. "
                "Please contact them directly.",
            )
        return _act(
            request,
            ticket,
            services.request_escalation,
            user,
            ticket,
            reason=post.get("reason", ""),
            expected_target=target,
            success=success % {"department": target.name},
        )
    if action == "priority":
        prio = Priority.objects.filter(pk=_int(post.get("priority_id"))).first()
        if prio is None:
            messages.error(request, pgettext("aa_ticket", "Please pick a priority."))
            return redirect("aa_ticket:detail", pk=ticket.pk)
        return _act(request, ticket, services.change_priority, user, ticket, prio)
    if action == "category":
        raw = (post.get("category_id") or "").strip()
        category = None
        if raw:
            category = Category.objects.filter(pk=_int(raw)).first()
            if category is None:
                messages.error(request, pgettext("aa_ticket", "Please pick a category."))
                return redirect("aa_ticket:detail", pk=ticket.pk)
        return _act(request, ticket, services.change_category, user, ticket, category)
    if action == "close":
        reason = ClosedReason.REQUESTER if user.pk == ticket.requester_id else ClosedReason.STAFF
        return _act(
            request,
            ticket,
            services.close,
            user,
            ticket,
            reason,
            final_reply=post.get("final_reply", ""),
            success=pgettext("aa_ticket", "Ticket closed."),
        )
    if action == "reopen":
        return _act(request, ticket, services.reopen, user, ticket, success=pgettext("aa_ticket", "Ticket reopened."))
    raise PermissionDenied


__all__ = ["detail", "reply", "action", "TicketMessage"]
