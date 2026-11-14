"""Image attachments: validation, storage and clean-up.

Files are stored under MEDIA_ROOT/aa_ticket/ with random names and are only
served through the permission-checked view in views/files.py.
"""

import os
import uuid

from PIL import Image

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.translation import gettext as _

from .app_settings import MAX_IMAGES_PER_MESSAGE
from .models import Attachment, TicketSettings

ALLOWED_FORMATS = {
    "PNG": ("image/png", ".png"),
    "JPEG": ("image/jpeg", ".jpg"),
    "GIF": ("image/gif", ".gif"),
    "WEBP": ("image/webp", ".webp"),
}


def uploads_enabled():
    root = getattr(settings, "MEDIA_ROOT", "")
    if not root:
        return False
    return os.path.isdir(root) and os.access(root, os.W_OK)


def _format_error():
    return ValidationError(_("Only PNG, JPG, GIF and WEBP images are allowed."))


def _detect_format(upload):
    upload.seek(0)
    try:
        with Image.open(upload) as img:
            fmt = img.format
            img.verify()
    except Exception as exc:  # noqa: BLE001 - Pillow raises many types, incl. DecompressionBombError
        raise _format_error() from exc
    finally:
        upload.seek(0)
    if fmt not in ALLOWED_FORMATS:
        raise _format_error()
    return fmt


def validate_images(files):
    if len(files) > MAX_IMAGES_PER_MESSAGE:
        raise ValidationError(
            _("You can attach at most %(count)d images per message.") % {"count": MAX_IMAGES_PER_MESSAGE}
        )
    max_mb = TicketSettings.get_solo().max_image_mb
    for upload in files:
        if upload.size > max_mb * 1024 * 1024:
            raise ValidationError(_("Each image must be smaller than %(size)d MB.") % {"size": max_mb})
        _detect_format(upload)


def save_image(message, upload):
    fmt = _detect_format(upload)
    content_type, ext = ALLOWED_FORMATS[fmt]
    attachment = Attachment(
        message=message,
        original_name=os.path.basename(upload.name or "image")[:255],
        size=upload.size,
        content_type=content_type,
    )
    upload.seek(0)
    attachment.file.save(uuid.uuid4().hex + ext, ContentFile(upload.read()), save=True)
    return attachment


def save_images(message, uploads):
    return [save_image(message, upload) for upload in uploads]


def delete_attachment(attachment):
    """Delete the file from storage and the database row."""
    if attachment.file:
        attachment.file.delete(save=False)
    attachment.delete()
