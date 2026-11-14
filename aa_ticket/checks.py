from django.conf import settings
from django.core.checks import Warning, register


@register()
def check_media_root(app_configs, **kwargs):
    if not getattr(settings, "MEDIA_ROOT", ""):
        return [
            Warning(
                "MEDIA_ROOT is not set; image uploads are disabled.",
                hint="Set MEDIA_ROOT in local.py to a writable folder, see the aa-ticket README.",
                id="aa_ticket.W001",
            )
        ]
    return []
