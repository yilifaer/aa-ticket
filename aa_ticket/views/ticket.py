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
        context["assignable_users"] = access.assignable_users(ticket).select_related("profile__main_character")
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
    return render(request, "aa_ticket/detail.html", detail_context(request.user, ticket))


def _run(request, ticket, func, *args, success=None, **kwargs):
    try:
        func(*args, **kwargs)
    except TicketActionError as exc:
        messages.error(request, exc.message)
    else:
        if success:
            messages.success(request, success)
    return redirect("aa_ticket:detail", pk=ticket.pk)


@login_required
@basic
@require_POST
def reply(request, pk):
    ticket = get_visible_ticket(request.user, pk)
    kind = request.POST.get("kind", "reply")
    body = request.POST.get("body", "")
    images = request.FILES.getlist("images")
    if kind == "internal":
        return _run(request, ticket, services.add_note, request.user, ticket, body, images=images)
    return _run(request, ticket, services.add_reply, request.user, ticket, body, images=images)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@login_required
@basic
@require_POST
def action(request, pk, action):
    if action not in ACTIONS:
        raise Http404
    ticket = get_visible_ticket(request.user, pk)
    user = request.user
    post = request.POST
    if action == "claim":
        return _run(request, ticket, services.claim, user, ticket, success=pgettext("aa_ticket", "You are now handling this ticket."))
    if action == "assign":
        assignee = User.objects.filter(pk=_int(post.get("user_id"))).first()
        return _run(request, ticket, services.assign, user, ticket, assignee, success=pgettext("aa_ticket", "Ticket assigned."))
    if action in ("invite", "uninvite", "transfer"):
        department = Department.objects.filter(pk=_int(post.get("department_id"))).first()
        if department is None:
            messages.error(request, pgettext("aa_ticket", "Please pick a department."))
            return redirect("aa_ticket:detail", pk=ticket.pk)
        if action == "invite":
            return _run(request, ticket, services.invite, user, ticket, department, success=pgettext("aa_ticket", "Department invited."))
        if action == "uninvite":
            return _run(request, ticket, services.uninvite, user, ticket, department, success=pgettext("aa_ticket", "Department removed."))
        keep = bool(post.get("keep")) if post.get("keep_present") else True
        return _run(
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
        if target is not None and target.webhook_url:
            success = pgettext("aa_ticket", "Escalation requested. %(department)s has been notified in Discord.")
        elif target is not None and access.department_staff(target).exists():
            success = pgettext("aa_ticket", "Escalation requested. Staff of %(department)s have been notified in Alliance Auth.")
        else:
            success = pgettext(
                "aa_ticket",
                "Escalation requested, but %(department)s has no Discord channel or staff to notify. "
                "Please contact them directly.",
            )
        return _run(
            request,
            ticket,
            services.request_escalation,
            user,
            ticket,
            reason=post.get("reason", ""),
            success=success % {"department": target.name if target else ""},
        )
    if action == "priority":
        prio = Priority.objects.filter(pk=_int(post.get("priority_id"))).first()
        if prio is None:
            messages.error(request, pgettext("aa_ticket", "Please pick a priority."))
            return redirect("aa_ticket:detail", pk=ticket.pk)
        return _run(request, ticket, services.change_priority, user, ticket, prio)
    if action == "category":
        raw = (post.get("category_id") or "").strip()
        category = None
        if raw:
            category = Category.objects.filter(pk=_int(raw)).first()
            if category is None:
                messages.error(request, pgettext("aa_ticket", "Please pick a category."))
                return redirect("aa_ticket:detail", pk=ticket.pk)
        return _run(request, ticket, services.change_category, user, ticket, category)
    if action == "close":
        reason = ClosedReason.REQUESTER if user.pk == ticket.requester_id else ClosedReason.STAFF
        return _run(
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
        return _run(request, ticket, services.reopen, user, ticket, success=pgettext("aa_ticket", "Ticket reopened."))
    raise PermissionDenied


__all__ = ["detail", "reply", "action", "TicketMessage"]
