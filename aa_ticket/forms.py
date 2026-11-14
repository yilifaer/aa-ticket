from django import forms
from django.utils.translation import pgettext_lazy

from .models import Category, Priority


class SubmitForm(forms.Form):
    category = forms.ModelChoiceField(
        label=pgettext_lazy("aa_ticket", "Category"), queryset=Category.objects.none(), required=False, empty_label=pgettext_lazy("aa_ticket", "Choose a category")
    )
    priority = forms.ModelChoiceField(label=pgettext_lazy("aa_ticket", "Priority"), queryset=Priority.objects.none(), empty_label=None)
    title = forms.CharField(label=pgettext_lazy("aa_ticket", "Title"), max_length=200)
    body = forms.CharField(label=pgettext_lazy("aa_ticket", "Describe your request"), widget=forms.Textarea(attrs={"rows": 8}))

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
        label=pgettext_lazy("aa_ticket", "Discord webhook"),
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
        help_text=pgettext_lazy("aa_ticket", "Paste a new webhook URL to change it. Leave empty to keep the current one."),
    )
    clear_webhook = forms.BooleanField(label=pgettext_lazy("aa_ticket", "Remove the webhook"), required=False)

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
            "mention_role_ids": pgettext_lazy("aa_ticket", 
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

    def clean_is_active(self):
        is_active = self.cleaned_data.get("is_active")
        if self.instance.pk and self.instance.is_active and not is_active:
            from .constants import Status

            if self.instance.children.filter(is_active=True).exists():
                raise forms.ValidationError(
                    pgettext_lazy("aa_ticket", "This department still has active sub-departments. Deactivate or move them first.")
                )
            open_count = self.instance.tickets.exclude(status=Status.CLOSED).count()
            if open_count:
                raise forms.ValidationError(
                    pgettext_lazy("aa_ticket", 
                        "This department still has %(count)d open tickets. "
                        "Transfer or close them before deactivating it."
                    )
                    % {"count": open_count}
                )
        return is_active

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
            "channel_language",
            "dm_language_mode",
        )

    def clean(self):
        cleaned = super().clean()
        days = cleaned.get("autoclose_days")
        hours = cleaned.get("autoclose_warning_hours")
        if days and hours is not None and hours >= days * 24:
            self.add_error(
                "autoclose_warning_hours",
                pgettext_lazy("aa_ticket", "The warning time must be shorter than the auto-close time (%(hours)d hours).")
                % {"hours": days * 24},
            )
        return cleaned
