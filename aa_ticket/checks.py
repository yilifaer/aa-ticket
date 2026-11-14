import os

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
    root = settings.MEDIA_ROOT
    if not os.path.isdir(root) or not os.access(root, os.W_OK):
        return [
            Warning(
                "MEDIA_ROOT does not exist or is not writable; image uploads are disabled.",
                hint=f"Create the folder and let the Alliance Auth user write to it: {root}",
                id="aa_ticket.W002",
            )
        ]
    return []
