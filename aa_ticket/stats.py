"""Per-department ticket statistics, computed in a single query."""

from datetime import timedelta

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q

from .constants import ClosedReason, Status
from .models import Department


def _seconds(value):
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value.total_seconds()
    return float(value) / 1_000_000  # some backends return microseconds


def department_stats(department_ids, since):
    """Rows for each department; department_ids=None means all departments."""
    created_q = Q(tickets__created_at__gte=since)
    closed_q = Q(tickets__status=Status.CLOSED, tickets__closed_at__gte=since)
    qs = Department.objects.all()
    if department_ids is not None:
        qs = qs.filter(pk__in=department_ids)
    qs = qs.annotate(
        n_created=Count("tickets", filter=created_q, distinct=True),
        n_closed=Count("tickets", filter=closed_q, distinct=True),
        n_auto=Count("tickets", filter=closed_q & Q(tickets__closed_reason=ClosedReason.AUTO), distinct=True),
        n_open=Count("tickets", filter=Q(tickets__status=Status.OPEN), distinct=True),
        avg_claim=Avg(
            ExpressionWrapper(F("tickets__claimed_at") - F("tickets__created_at"), output_field=DurationField()),
            filter=created_q & Q(tickets__claimed_at__isnull=False),
        ),
        avg_resolve=Avg(
            ExpressionWrapper(F("tickets__closed_at") - F("tickets__created_at"), output_field=DurationField()),
            filter=closed_q,
        ),
    ).order_by("order", "name")
    rows = []
    for d in qs:
        rows.append(
            {
                "department": d,
                "created": d.n_created,
                "closed": d.n_closed,
                "open_now": d.n_open,
                "avg_claim_seconds": _seconds(d.avg_claim),
                "avg_resolve_seconds": _seconds(d.avg_resolve),
                "auto_closed_ratio": (d.n_auto / d.n_closed) if d.n_closed else None,
            }
        )
    return rows
