from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from ..discord import dm
from ..models import UserPreference


@login_required
@permission_required("aa_ticket.basic_access", raise_exception=True)
def prefs(request):
    pref = UserPreference.for_user(request.user)
    available = dm.is_available()
    if request.method == "POST" and available:
        pref.discord_dm_enabled = bool(request.POST.get("discord_dm_enabled"))
        pref.save(update_fields=["discord_dm_enabled"])
        messages.success(request, _("Preferences saved."))
        return redirect("aa_ticket:prefs")
    return render(request, "aa_ticket/prefs.html", {"pref": pref, "available": available, "nav_active": "prefs"})
