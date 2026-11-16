from django.core.cache import cache
from django.utils.translation import pgettext_lazy

from allianceauth import hooks
from allianceauth.services.hooks import MenuItemHook, UrlHook

from . import urls
from .app_settings import BADGE_CACHE_SECONDS


def badge_cache_key(user):
    return f"aa_ticket:badge:{user.pk}"


def unclaimed_count(user):
    """Unclaimed tickets the user's own departments are directly responsible for."""
    from . import access
    from .constants import Status
    from .models import Ticket

    department_ids = access.staff_department_ids(user)
    if not department_ids:
        return 0
    return (
        Ticket.objects.filter(status=Status.OPEN, department_id__in=department_ids)
        .exclude(requester=user)
        .count()
    )


class TicketMenuItem(MenuItemHook):
    def __init__(self):
        super().__init__(
            pgettext_lazy("aa_ticket", "Tickets"),
            "fas fa-ticket",
            "aa_ticket:index",
            navactive=["aa_ticket:"],
        )

    def render(self, request):
        user = request.user
        if not user.is_authenticated or not user.has_perm("aa_ticket.basic_access"):
            return ""
        key = badge_cache_key(user)
        count = cache.get(key)
        if count is None:
            count = unclaimed_count(user)
            cache.set(key, count, BADGE_CACHE_SECONDS)
        self.count = count or None
        return MenuItemHook.render(self, request)


def dashboard_card(request):
    from django.template.loader import render_to_string

    from .overview import dashboard_summary

    user = request.user
    if not user.is_authenticated or not user.has_perm("aa_ticket.basic_access"):
        return ""
    summary = dashboard_summary(user)
    if summary is None:
        return ""
    return render_to_string("aa_ticket/dashboard_card.html", {"summary": summary}, request=request)


class TicketDashboardHook(hooks.DashboardItemHook):
    def __init__(self):
        super().__init__(dashboard_card, 5)


@hooks.register("dashboard_hook")
def register_dashboard():
    return TicketDashboardHook()


@hooks.register("menu_item_hook")
def register_menu():
    return TicketMenuItem()


@hooks.register("url_hook")
def register_urls():
    return UrlHook(urls, "aa_ticket", r"^ticket/")
