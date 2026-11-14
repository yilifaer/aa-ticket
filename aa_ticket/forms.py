from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Category, Priority


class SubmitForm(forms.Form):
    category = forms.ModelChoiceField(
        label=_("Category"), queryset=Category.objects.none(), required=False, empty_label=_("Choose a category")
    )
    priority = forms.ModelChoiceField(label=_("Priority"), queryset=Priority.objects.none(), empty_label=None)
    title = forms.CharField(label=_("Title"), max_length=200)
    body = forms.CharField(label=_("Describe your request"), widget=forms.Textarea(attrs={"rows": 8}))

    def __init__(self, *args, department=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(department=department, is_active=True)
        priorities = Priority.objects.filter(is_active=True).order_by("order", "name")
        self.fields["priority"].queryset = priorities
        listed = list(priorities)
        if listed and not self.is_bound:
            self.initial.setdefault("priority", listed[len(listed) // 2].pk)
        if not self.fields["category"].queryset.exists():
            del self.fields["category"]


# ---------------------------------------------------------------------------
# Management forms
# ---------------------------------------------------------------------------

from .discord.webhook import validate_webhook_url  # noqa: E402
from .models import CannedReply, Department, TicketSettings  # noqa: E402


class DepartmentForm(forms.ModelForm):
    new_webhook_url = forms.CharField(
        label=_("Discord webhook"),
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
        help_text=_("Paste a new webhook URL to change it. Leave empty to keep the current one."),
    )
    clear_webhook = forms.BooleanField(label=_("Remove the webhook"), required=False)

    class Meta:
        model = Department
        fields = (
            "name",
            "description",
            "parent",
            "groups",
            "accepts_submissions",
            "submit_states",
            "submit_groups",
            "mention_role_ids",
            "order",
            "is_active",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "groups": forms.SelectMultiple(attrs={"size": 6}),
            "submit_states": forms.SelectMultiple(attrs={"size": 4}),
            "submit_groups": forms.SelectMultiple(attrs={"size": 6}),
        }
        help_texts = {
            "mention_role_ids": _(
                "In Discord, enable Developer Mode, right-click the role and choose 'Copy Role ID'. "
                "Separate several IDs with commas."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        parents = Department.objects.all()
        if self.instance.pk:
            parents = parents.exclude(pk__in={self.instance.pk} | self.instance.descendant_ids())
        self.fields["parent"].queryset = parents
        if self.instance.webhook_url:
            self.fields["new_webhook_url"].widget.attrs["placeholder"] = self.instance.masked_webhook()

    def clean_new_webhook_url(self):
        value = (self.cleaned_data.get("new_webhook_url") or "").strip()
        if value:
            validate_webhook_url(value)
        return value

    def save(self, commit=True):
        department = super().save(commit=False)
        if self.cleaned_data.get("clear_webhook"):
            department.webhook_url = ""
            department.last_webhook_error = ""
            department.last_webhook_error_at = None
        elif self.cleaned_data.get("new_webhook_url"):
            department.webhook_url = self.cleaned_data["new_webhook_url"]
            department.last_webhook_error = ""
            department.last_webhook_error_at = None
        if commit:
            department.save()
            self.save_m2m()
        return department


class PriorityForm(forms.ModelForm):
    class Meta:
        model = Priority
        fields = ("name", "color", "order", "mention_on_new", "remind_after_minutes", "escalate_after_minutes", "is_active")


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("department", "name", "template", "order", "is_active")
        widgets = {"template": forms.Textarea(attrs={"rows": 5})}


class CannedReplyForm(forms.ModelForm):
    class Meta:
        model = CannedReply
        fields = ("department", "title", "body")
        widgets = {"body": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, allowed_department_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        if allowed_department_ids is not None:
            self.fields["department"].queryset = Department.objects.filter(pk__in=allowed_department_ids)
            self.fields["department"].required = True
            self.fields["department"].empty_label = None


class TicketSettingsForm(forms.ModelForm):
    class Meta:
        model = TicketSettings
        fields = (
            "autoclose_days",
            "autoclose_warning_hours",
            "reopen_days",
            "max_open_tickets",
            "max_image_mb",
            "attachment_retention_days",
            "discord_dm_enabled",
        )
