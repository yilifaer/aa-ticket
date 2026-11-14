"""Management pages: departments, priorities, categories, canned replies, settings."""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db.models import ProtectedError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from .. import access
from ..discord.webhook import send_test_message
from ..forms import CannedReplyForm, CategoryForm, DepartmentForm, PriorityForm, TicketSettingsForm
from ..models import CannedReply, Category, Department, Priority, TicketSettings

basic = permission_required("aa_ticket.basic_access", raise_exception=True)
manage_perm = permission_required("aa_ticket.manage", raise_exception=True)

SECTIONS = (
    ("departments", gettext_lazy("Departments"), "aa_ticket:manage_departments"),
    ("priorities", gettext_lazy("Priorities"), "aa_ticket:manage_priorities"),
    ("categories", gettext_lazy("Categories"), "aa_ticket:manage_categories"),
    ("canned", gettext_lazy("Canned replies"), "aa_ticket:manage_canned"),
    ("settings", gettext_lazy("Settings"), "aa_ticket:manage_settings"),
)


def _ctx(request, section, **extra):
    can_manage = request.user.has_perm("aa_ticket.manage")
    sections = SECTIONS if can_manage else [s for s in SECTIONS if s[0] == "canned"]
    return {"sections": sections, "section": section, "nav_active": "manage", **extra}


def _get_or_new(model, pk):
    if pk == 0:
        return model()
    return get_object_or_404(model, pk=pk)


def _edit(request, pk, model, form_class, section, list_url, title_new, title_edit, template="aa_ticket/manage/form.html", form_kwargs=None):
    obj = _get_or_new(model, pk)
    form_kwargs = form_kwargs or {}
    if request.method == "POST":
        form = form_class(request.POST, instance=obj, **form_kwargs)
        if form.is_valid():
            form.save()
            messages.success(request, _("Saved."))
            return redirect(list_url)
    else:
        form = form_class(instance=obj, **form_kwargs)
    return render(
        request,
        template,
        _ctx(request, section, form=form, obj=obj, title=title_edit if obj.pk else title_new, list_url=list_url),
    )


def _delete(request, obj, list_url, refused_message):
    try:
        obj.delete()
    except ProtectedError:
        messages.error(request, refused_message)
    else:
        messages.success(request, _("Deleted."))
    return redirect(list_url)


# ----- departments ---------------------------------------------------------


def _department_rows():
    departments = list(Department.objects.prefetch_related("groups").order_by("order", "name"))
    by_parent = {}
    for d in departments:
        by_parent.setdefault(d.parent_id, []).append(d)
    rows, seen = [], set()

    def walk(parent_id, depth):
        for d in by_parent.get(parent_id, []):
            if d.pk in seen:
                continue
            seen.add(d.pk)
            rows.append({"department": d, "depth": depth, "indent": depth * 1.5})
            walk(d.pk, depth + 1)

    walk(None, 0)
    for d in departments:  # anything left over (broken tree) is still shown
        if d.pk not in seen:
            rows.append({"department": d, "depth": 0, "indent": 0})
    return rows


@login_required
@manage_perm
def departments(request):
    return render(request, "aa_ticket/manage/departments.html", _ctx(request, "departments", rows=_department_rows()))


@login_required
@manage_perm
def department_edit(request, pk):
    return _edit(
        request, pk, Department, DepartmentForm, "departments", "aa_ticket:manage_departments",
        _("New department"), _("Edit department"), template="aa_ticket/manage/department_form.html",
    )


@login_required
@manage_perm
@require_POST
def department_delete(request, pk):
    department = get_object_or_404(Department, pk=pk)
    if department.children.exists() or department.tickets.exists():
        messages.error(request, _("This department still has tickets or sub-departments. Deactivate it instead."))
        return redirect("aa_ticket:manage_departments")
    return _delete(
        request, department, "aa_ticket:manage_departments",
        _("This department still has tickets or sub-departments. Deactivate it instead."),
    )


@login_required
@manage_perm
@require_POST
def department_test(request, pk):
    department = get_object_or_404(Department, pk=pk)
    ok, text = send_test_message(department)
    (messages.success if ok else messages.error)(request, text)
    return redirect("aa_ticket:manage_department_edit", pk=pk)


# ----- priorities ----------------------------------------------------------


@login_required
@manage_perm
def priorities(request):
    return render(request, "aa_ticket/manage/priorities.html", _ctx(request, "priorities", items=Priority.objects.all()))


@login_required
@manage_perm
def priority_edit(request, pk):
    return _edit(request, pk, Priority, PriorityForm, "priorities", "aa_ticket:manage_priorities", _("New priority"), _("Edit priority"))


@login_required
@manage_perm
@require_POST
def priority_delete(request, pk):
    return _delete(
        request, get_object_or_404(Priority, pk=pk), "aa_ticket:manage_priorities",
        _("Tickets still use this priority. Deactivate it instead."),
    )


# ----- categories ----------------------------------------------------------


@login_required
@manage_perm
def categories(request):
    items = Category.objects.select_related("department").order_by("department__name", "order", "name")
    return render(request, "aa_ticket/manage/categories.html", _ctx(request, "categories", items=items))


@login_required
@manage_perm
def category_edit(request, pk):
    return _edit(request, pk, Category, CategoryForm, "categories", "aa_ticket:manage_categories", _("New category"), _("Edit category"))


@login_required
@manage_perm
@require_POST
def category_delete(request, pk):
    return _delete(request, get_object_or_404(Category, pk=pk), "aa_ticket:manage_categories", "")


# ----- canned replies ------------------------------------------------------


def _canned_scope(user):
    """None means every canned reply; otherwise the department IDs the user may edit."""
    if user.has_perm("aa_ticket.manage"):
        return None
    if not access.staff_department_ids(user):
        raise PermissionDenied
    return access.staff_department_ids(user)


@login_required
@basic
def canned(request):
    scope = _canned_scope(request.user)
    items = CannedReply.objects.select_related("department").order_by("department__name", "title")
    if scope is not None:
        items = items.filter(department_id__in=scope) | items.filter(department__isnull=True)
    return render(
        request,
        "aa_ticket/manage/canned.html",
        _ctx(request, "canned", items=items, editable_ids=None if scope is None else set(scope)),
    )


def _canned_object(request, pk):
    scope = _canned_scope(request.user)
    obj = _get_or_new(CannedReply, pk)
    if obj.pk and scope is not None and obj.department_id not in scope:
        raise Http404
    return obj, scope


@login_required
@basic
def canned_edit(request, pk):
    _obj, scope = _canned_object(request, pk)
    return _edit(
        request, pk, CannedReply, CannedReplyForm, "canned", "aa_ticket:manage_canned",
        _("New canned reply"), _("Edit canned reply"), form_kwargs={"allowed_department_ids": scope},
    )


@login_required
@basic
@require_POST
def canned_delete(request, pk):
    obj, _scope = _canned_object(request, pk)
    if not obj.pk:
        raise Http404
    return _delete(request, obj, "aa_ticket:manage_canned", "")


# ----- settings ------------------------------------------------------------


@login_required
@manage_perm
def settings_view(request):
    instance = TicketSettings.get_solo()
    if request.method == "POST":
        form = TicketSettingsForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, _("Settings saved."))
            return redirect("aa_ticket:manage_settings")
    else:
        form = TicketSettingsForm(instance=instance)
    return render(
        request,
        "aa_ticket/manage/form.html",
        _ctx(request, "settings", form=form, obj=instance, title=_("Settings"), list_url=None),
    )
