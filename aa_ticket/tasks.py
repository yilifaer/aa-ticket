import requests
from celery import shared_task

from django.db import models
from django.utils import timezone

from allianceauth.services.hooks import get_extension_logger
from allianceauth.services.tasks import QueueOnce

from .app_settings import WEBHOOK_MAX_RETRIES
from .discord import webhook
from .models import Department, Ticket

logger = get_extension_logger(__name__)


def _record_webhook_result(department_id, error):
    if error:
        Department.objects.filter(pk=department_id).update(
            last_webhook_error=error[:255], last_webhook_error_at=timezone.now()
        )
    else:
        Department.objects.filter(pk=department_id).exclude(last_webhook_error="").update(
            last_webhook_error="", last_webhook_error_at=None
        )


@shared_task(bind=True, max_retries=WEBHOOK_MAX_RETRIES, ignore_result=True)
def send_webhook(self, department_id, ticket_id, event, mention):
    department = Department.objects.filter(pk=department_id).first()
    ticket = Ticket.objects.filter(pk=ticket_id).first()
    if department is None or ticket is None or not department.webhook_url:
        return
    payload = webhook.build_payload(ticket, event, mention, department)
    error = None
    countdown = None
    try:
        response = webhook.post_webhook(department.webhook_url, payload)
    except requests.RequestException as exc:
        error = type(exc).__name__
        countdown = 2**self.request.retries * 30
    else:
        if response.ok:
            _record_webhook_result(department_id, None)
            return
        error = f"HTTP {response.status_code}"
        if response.status_code == 429:
            countdown = webhook.retry_after_seconds(response)
        elif response.status_code >= 500:
            countdown = 2**self.request.retries * 30
    if countdown is not None and self.request.retries < self.max_retries:
        raise self.retry(countdown=countdown)
    _record_webhook_result(department_id, error)
    logger.warning(
        "Discord message for department %s (ticket %s) failed: %s", department.name, ticket.display_number, error
    )


@shared_task(ignore_result=True)
def send_dm(user_id, ticket_id, event, data=None):
    """Send one Discord DM. Never retries: an undeliverable DM is not an error."""
    from django.contrib.auth.models import User

    from .discord import dm
    from .links import ticket_url
    from .models import UserPreference
    from .notifications import personal_text, personal_title
    from .translation import user_language

    if not dm.is_available():
        return
    user = User.objects.filter(pk=user_id).first()
    ticket = Ticket.objects.filter(pk=ticket_id).first()
    if user is None or ticket is None:
        return
    if not UserPreference.for_user(user).discord_dm_enabled:
        return
    with user_language(user):
        text = personal_text(ticket, event, data or {}, recipient_id=user.pk)
    try:
        dm.send(user.pk, personal_title(ticket), text, ticket_url(ticket))
    except Exception as exc:  # noqa: BLE001 - any bot error must not break the app
        logger.info("Discord DM to user %s not sent: %s", user.pk, type(exc).__name__)


BATCH_SIZE = 500


def _now(now):
    if now:
        from django.utils.dateparse import parse_datetime

        return parse_datetime(now)
    return timezone.now()


def _mark_and_emit(ticket, field, now, event, extra_filter=None):
    """Set a reminder field only if still unset, then emit. Survives restarts and races."""
    from django.db import transaction

    from .services import _emit

    with transaction.atomic():
        filters = {"pk": ticket.pk, f"{field}__isnull": True}
        filters.update(extra_filter or {})
        if not Ticket.objects.filter(**filters).update(**{field: now}):
            return False
        _emit(Ticket.objects.get(pk=ticket.pk), event)
    return True


def _release_departed_assignees():
    """Tickets whose assignee is no longer staff of the responsible department go back to unclaimed."""
    from django.contrib.auth.models import User
    from django.db import transaction

    from . import access
    from .constants import Event, Status
    from .services import _emit

    tickets = list(
        Ticket.objects.filter(status=Status.IN_PROGRESS, assignee__isnull=False)
        .select_related("department")
        .order_by("pk")[:BATCH_SIZE]
    )
    users = {u.pk: u for u in User.objects.filter(pk__in={t.assignee_id for t in tickets})}
    for ticket in tickets:
        assignee = users.get(ticket.assignee_id)
        if assignee is not None and assignee.is_active and access.is_controller(assignee, ticket):
            continue
        with transaction.atomic():
            updated = Ticket.objects.filter(
                pk=ticket.pk, status=Status.IN_PROGRESS, assignee_id=ticket.assignee_id
            ).update(status=Status.OPEN, assignee=None, open_since=timezone.now(), reminded_at=None, escalated_at=None)
            if updated:
                _emit(Ticket.objects.get(pk=ticket.pk), Event.ASSIGNEE_LEFT)


def _unclaimed_candidates():
    """Unclaimed tickets that still have a reminder or escalation to send."""
    from .constants import Status

    return (
        Ticket.objects.filter(status=Status.OPEN)
        .select_related("priority", "department")
        .filter(
            models.Q(priority__remind_after_minutes__isnull=False, reminded_at__isnull=True)
            | models.Q(
                priority__escalate_after_minutes__isnull=False,
                escalated_at__isnull=True,
                department__parent__isnull=False,
            )
        )
        .order_by("open_since")
    )


@shared_task(base=QueueOnce, once={"graceful": True}, ignore_result=True)
def check_unclaimed(now=None):
    """Remind departments of unclaimed tickets and escalate to the parent."""
    from datetime import timedelta

    from .constants import Event, Status

    now = _now(now)
    _release_departed_assignees()
    for ticket in _unclaimed_candidates()[:BATCH_SIZE]:
        prio = ticket.priority
        waited = now - ticket.open_since
        if (
            prio.remind_after_minutes
            and ticket.reminded_at is None
            and waited >= timedelta(minutes=prio.remind_after_minutes)
        ):
            _mark_and_emit(ticket, "reminded_at", now, Event.UNCLAIMED_REMINDER, {"status": Status.OPEN})
        if (
            prio.escalate_after_minutes
            and ticket.escalated_at is None
            and ticket.department.parent_id
            and waited >= timedelta(minutes=prio.escalate_after_minutes)
        ):
            _mark_and_emit(ticket, "escalated_at", now, Event.ESCALATION_REMINDER, {"status": Status.OPEN})


@shared_task(base=QueueOnce, once={"graceful": True}, ignore_result=True)
def check_auto_close(now=None):
    """Warn before auto-close, auto-close tickets waiting for the requester,
    and remind staff about tickets waiting for staff."""
    from datetime import timedelta

    from .constants import ClosedReason, Event, Status
    from .models import TicketSettings
    from .services import close

    now = _now(now)
    s = TicketSettings.get_solo()
    close_after = timedelta(days=s.autoclose_days)
    warn_at = close_after - timedelta(hours=s.autoclose_warning_hours)
    oldest_due = now - min(warn_at, close_after)
    tickets = Ticket.objects.filter(
        models.Q(last_reply_by_staff=True) | models.Q(staff_reminded_at__isnull=True),
        status=Status.IN_PROGRESS,
        last_reply_at__lte=oldest_due,
    ).order_by(
        "last_reply_at"
    )[:BATCH_SIZE]
    for ticket in tickets:
        idle = now - ticket.last_reply_at
        if ticket.last_reply_by_staff:
            warning = timedelta(hours=s.autoclose_warning_hours)
            warned_long_enough = not s.autoclose_warning_hours or (
                ticket.autoclose_warned_at is not None and now >= ticket.autoclose_warned_at + warning
            )
            if idle >= close_after and warned_long_enough:
                close(None, ticket, ClosedReason.AUTO)
            elif s.autoclose_warning_hours and ticket.autoclose_warned_at is None and idle >= warn_at:
                _mark_and_emit(
                    ticket,
                    "autoclose_warned_at",
                    now,
                    Event.AUTOCLOSE_WARNING,
                    {"status": Status.IN_PROGRESS, "last_reply_at": ticket.last_reply_at},
                )
        elif ticket.staff_reminded_at is None and idle >= close_after:
            _mark_and_emit(
                ticket,
                "staff_reminded_at",
                now,
                Event.AWAITING_STAFF_REMINDER,
                {"status": Status.IN_PROGRESS, "last_reply_at": ticket.last_reply_at},
            )


@shared_task(base=QueueOnce, once={"graceful": True}, ignore_result=True)
def cleanup_attachments():
    """Delete image files of tickets closed longer than the retention period."""
    from datetime import timedelta

    from .attachments import delete_attachment
    from .constants import Status
    from .models import Attachment, TicketSettings

    days = TicketSettings.get_solo().attachment_retention_days
    if not days:
        return
    cutoff = timezone.now() - timedelta(days=days)
    old = Attachment.objects.filter(
        message__ticket__status=Status.CLOSED, message__ticket__closed_at__lt=cutoff
    )[:BATCH_SIZE]
    count = 0
    for attachment in old:
        delete_attachment(attachment)
        count += 1
    if count:
        logger.info("Deleted %d old ticket images.", count)
