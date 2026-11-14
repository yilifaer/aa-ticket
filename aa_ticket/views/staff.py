import re
from datetime import timedelta

from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import pgettext_lazy

from .. import access
from ..constants import Status
from ..models import Category, Department, Priority
from ..stats import department_stats

basic = permission_required("aa_ticket.basic_access", raise_exception=True)

TABS = (
    ("unclaimed", pgettext_lazy("aa_ticket", "Unclaimed")),
    ("mine", pgettext_lazy("aa_ticket", "Assigned to me")),
    ("department", pgettext_lazy("aa_ticket", "My departments")),
    ("children", pgettext_lazy("aa_ticket", "Sub-departments")),
    ("collab", pgettext_lazy("aa_ticket", "Helping")),
    ("closed", pgettext_lazy("aa_ticket", "Closed")),
)
PAGE_SIZE = 50
STATS_RANGES = (7, 30, 90)


def _require_staff(user):
    if not access.is_department_staff(user):
        raise PermissionDenied


def _tab_queryset(user, tab):
    own = access.staff_department_ids(user)
    visible = access.visible_tickets(user).exclude(requester=user)
    if tab == "unclaimed":
        return visible.filter(status=Status.OPEN, department_id__in=own)
    if tab == "mine":
        return visible.filter(assignee=user).exclude(status=Status.CLOSED)
    if tab == "department":
        return visible.filter(department_id__in=own).exclude(status=Status.CLOSED)
    if tab == "children":
        if access.has_view_all(user):
            return visible.exclude(status=Status.CLOSED)
        children = access._with_descendants(own) - own
        return visible.filter(department_id__in=children).exclude(status=Status.CLOSED)
    if tab == "collab":
        return visible.filter(collaborating_departments__in=own).exclude(status=Status.CLOSED).distinct()
    return visible.filter(status=Status.CLOSED)


def _apply_filters(qs, params):
    for field, key in (("department_id", "department"), ("priority_id", "priority"), ("category_id", "category")):
        value = params.get(key)
        if value and value.isascii() and value.isdigit():
            qs = qs.filter(**{field: int(value)})
    status = params.get("status")
    if status in Status.values:
        qs = qs.filter(status=status)
    q = (params.get("q") or "").strip()
    if q:
        number = re.fullmatch(r"#?(\d+)", q)
        cond = Q(title__icontains=q) | Q(requester_character__character_name__icontains=q)
        if number:
            cond |= Q(pk=int(number.group(1)))
        qs = qs.filter(cond)
    return qs


@login_required
@basic
def workbench(request):
    _require_staff(request.user)
    tab = request.GET.get("tab", "unclaimed")
    if tab not in dict(TABS):
        tab = "unclaimed"
    qs = _apply_filters(_tab_queryset(request.user, tab), request.GET)
    qs = qs.select_related("department", "priority", "requester", "requester_character", "assignee")
    if tab == "closed":
        qs = qs.order_by("-closed_at")
    else:
        qs = qs.order_by("-priority__order", "created_at")
    page_number = request.GET.get("page") or "1"
    if not (page_number.isascii() and page_number.isdigit()) or int(page_number) < 1:
        page_number = "1"
    page = Paginator(qs, PAGE_SIZE).get_page(page_number)
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "aa_ticket/workbench.html",
        {
            "tabs": TABS,
            "tab": tab,
            "tickets": page.object_list,
            "page": page,
            "querystring": params.urlencode(),
            "departments": Department.objects.filter(is_active=True),
            "priorities": Priority.objects.all(),
            "categories": Category.objects.filter(is_active=True).select_related("department"),
            "statuses": Status.choices,
            "filters": request.GET,
            "nav_active": "workbench",
        },
    )


@login_required
@basic
def stats(request):
    _require_staff(request.user)
    try:
        days = int(request.GET.get("days", 30))
    except ValueError:
        days = 30
    if days not in STATS_RANGES:
        days = 30
    since = timezone.now() - timedelta(days=days)
    rows = department_stats(access.stats_department_ids(request.user), since)
    return render(
        request,
        "aa_ticket/stats.html",
        {"rows": rows, "days": days, "ranges": STATS_RANGES, "nav_active": "stats"},
    )
