from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import pgettext

from .. import access, services
from ..app_settings import LIST_PAGE_SIZE
from ..attachments import uploads_enabled
from ..constants import Status
from ..exceptions import TicketActionError
from ..forms import SubmitForm
from ..models import Department, Ticket

basic = permission_required("aa_ticket.basic_access", raise_exception=True)


@login_required
@basic
def index(request):
    from ..overview import sections_for

    return render(
        request,
        "aa_ticket/overview.html",
        {"sections": sections_for(request.user), "nav_active": "overview"},
    )


@login_required
@basic
def my_tickets(request):
    tab = "closed" if request.GET.get("tab") == "closed" else "active"
    qs = Ticket.objects.filter(requester=request.user).select_related("department", "priority", "assignee")
    if tab == "closed":
        qs = qs.filter(status=Status.CLOSED).order_by("-closed_at", "-pk")
    else:
        qs = qs.exclude(status=Status.CLOSED).order_by("-last_reply_at", "-pk")
    counts = {
        "active": Ticket.objects.filter(requester=request.user).exclude(status=Status.CLOSED).count(),
    }
    page_number = request.GET.get("page") or "1"
    if not (page_number.isascii() and page_number.isdigit()) or len(page_number) > 9 or int(page_number) < 1:
        page_number = "1"
    page = Paginator(qs, LIST_PAGE_SIZE).get_page(page_number)
    return render(
        request,
        "aa_ticket/my_tickets.html",
        {"tickets": page.object_list, "page": page, "tab": tab, "counts": counts, "nav_active": "mine"},
    )


@login_required
@basic
def submit_choose_department(request):
    departments = access.submittable_departments(request.user)
    return render(
        request, "aa_ticket/submit_choose_department.html", {"departments": departments, "nav_active": "mine"}
    )


@login_required
@basic
def submit(request, department_id):
    department = get_object_or_404(Department, pk=department_id)
    if department not in access.submittable_departments(request.user):
        raise Http404
    if request.method == "POST":
        form = SubmitForm(request.POST, department=department)
        if form.is_valid():
            try:
                ticket = services.create_ticket(
                    request.user,
                    department,
                    form.cleaned_data["priority"],
                    form.cleaned_data["title"],
                    form.cleaned_data["body"],
                    category=form.cleaned_data.get("category"),
                    images=request.FILES.getlist("images"),
                )
            except TicketActionError as exc:
                form.add_error(None, exc.message)
            except PermissionDenied as exc:
                raise Http404 from exc
            else:
                messages.success(request, pgettext("aa_ticket", "Ticket %(number)s submitted.") % {"number": ticket.display_number})
                return redirect("aa_ticket:detail", pk=ticket.pk)
    else:
        form = SubmitForm(department=department)
    return render(
        request,
        "aa_ticket/submit.html",
        {"form": form, "department": department, "uploads_enabled": uploads_enabled(), "nav_active": "mine"},
    )
