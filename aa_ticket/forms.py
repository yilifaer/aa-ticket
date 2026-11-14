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
