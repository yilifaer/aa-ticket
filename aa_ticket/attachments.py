"""Image attachments: validation, storage and clean-up.

Files are stored under MEDIA_ROOT/aa_ticket/ with random names and are only
served through the permission-checked view in views/files.py.
"""

import io
import os
import uuid
import warnings

from PIL import Image, ImageOps, ImageSequence

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.translation import pgettext

from .app_settings import MAX_ANIMATION_PIXELS, MAX_FRAMES, MAX_IMAGE_EDGE, MAX_IMAGE_PIXELS, MAX_IMAGES_PER_MESSAGE
from .models import Attachment, TicketSettings

ALLOWED_FORMATS = {
    "PNG": ("image/png", ".png"),
    "JPEG": ("image/jpeg", ".jpg"),
    "GIF": ("image/gif", ".gif"),
    "WEBP": ("image/webp", ".webp"),
}


# Formats saved with all their frames. Everything else is saved as its first picture only.
ANIMATED_FORMATS = ("GIF", "WEBP")


def uploads_enabled():
    root = getattr(settings, "MEDIA_ROOT", "")
    if not root:
        return False
    return os.path.isdir(root) and os.access(root, os.W_OK)


def _format_error():
    return ValidationError(pgettext("aa_ticket", "Only PNG, JPG, GIF and WEBP images are allowed."))


def _too_large_error(size=None):
    if size:
        return ValidationError(
            pgettext(
                "aa_ticket",
                "This image is too large (%(width)d × %(height)d pixels). Images up to %(max)d megapixels are "
                "accepted. Please use a smaller image.",
            )
            % {"width": size[0], "height": size[1], "max": MAX_IMAGE_PIXELS // 1_000_000}
        )
    return ValidationError(pgettext("aa_ticket", "This image is too large. Please make it smaller and try again."))


def _animation_too_large_error(frames, size):
    return ValidationError(
        pgettext(
            "aa_ticket",
            "This animation is too large in total (%(count)d frames of %(width)d × %(height)d pixels). "
            "All frames together may have up to %(max)d megapixels. Use fewer frames or a smaller size.",
        )
        % {"count": frames, "width": size[0], "height": size[1], "max": MAX_ANIMATION_PIXELS // 1_000_000}
    )


def _decode_small(img):
    """For JPEG, let the decoder skip detail we would throw away when scaling down. Saves memory."""
    if img.format in ("JPEG", "MPO"):
        img.draft("RGB", (MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))


def _fit(image):
    """Scale down so the longer edge is at most MAX_IMAGE_EDGE. Smaller images are not touched."""
    if max(image.size) > MAX_IMAGE_EDGE:
        image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
    return image


def _detect_format(upload):
    upload.seek(0)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(upload) as img:
                fmt = img.format
                size = img.size
                if size[0] * size[1] > MAX_IMAGE_PIXELS:
                    raise _too_large_error(size)
                # Only GIF and WEBP keep their frames when saved (see _reencode_unchecked). A phone
                # photo with a hidden extra picture (MPO) or an animated PNG keeps just the first
                # picture, so only that one counts, and it was checked above.
                frames = getattr(img, "n_frames", 1) if fmt in ANIMATED_FORMATS else 1
                if frames > MAX_FRAMES:
                    raise ValidationError(
                        pgettext("aa_ticket", "This animation has too many frames (%(count)d). Up to %(max)d frames are allowed.")
                        % {"count": frames, "max": MAX_FRAMES}
                    )
                if frames * size[0] * size[1] > MAX_ANIMATION_PIXELS:
                    raise _animation_too_large_error(frames, size)
                img.verify()
            # verify() does not decode pixel data; load once to catch truncated files.
            upload.seek(0)
            with Image.open(upload) as img:
                _decode_small(img)
                img.load()
    except ValidationError:
        raise
    except Image.DecompressionBombError as exc:
        raise _too_large_error() from exc
    except Exception as exc:  # noqa: BLE001 - Pillow raises many types
        raise _format_error() from exc
    finally:
        upload.seek(0)
    if fmt == "MPO":  # multi-picture JPEG from phone cameras: keep the main picture
        fmt = "JPEG"
    if fmt not in ALLOWED_FORMATS:
        raise _format_error()
    return fmt


def validate_images(files):
    if len(files) > MAX_IMAGES_PER_MESSAGE:
        raise ValidationError(
            pgettext("aa_ticket", "You can attach at most %(count)d images per message.") % {"count": MAX_IMAGES_PER_MESSAGE}
        )
    max_mb = TicketSettings.get_solo().max_image_mb
    for upload in files:
        if upload.size > max_mb * 1024 * 1024:
            raise ValidationError(pgettext("aa_ticket", "Each image must be smaller than %(size)d MB.") % {"size": max_mb})
        _detect_format(upload)


def _reencode(upload, fmt):
    """Re-encode the image so metadata (EXIF, GPS, comments) and trailing bytes are dropped."""
    try:
        return _reencode_unchecked(upload, fmt)
    except ValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - corrupt data must become a user-facing error
        raise _format_error() from exc


def _reencode_unchecked(upload, fmt):
    upload.seek(0)
    out = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        with Image.open(upload) as img:
            frames = getattr(img, "n_frames", 1)
            if frames > 1 and fmt in ANIMATED_FORMATS:
                _save_animation(img, out, fmt)
            else:
                icc = img.info.get("icc_profile")
                _decode_small(img)
                image = _fit(ImageOps.exif_transpose(img))
                image.info.pop("comment", None)
                options = {"icc_profile": icc} if icc and fmt in ("JPEG", "PNG", "WEBP") else {}
                if fmt == "JPEG":
                    if image.mode not in ("RGB", "L"):
                        image = image.convert("RGB")
                        options = {}
                    image.save(out, format="JPEG", quality=90, comment=b"", **options)
                else:
                    if fmt == "GIF":
                        options["comment"] = b""
                    image.save(out, format=fmt, **options)
    return out.getvalue()


def _save_animation(img, out, fmt):
    extra = {"comment": b""} if fmt == "GIF" else {}
    if max(img.size) <= MAX_IMAGE_EDGE:
        # Without a duration option Pillow keeps each frame's own delay.
        img.save(out, format=fmt, save_all=True, loop=img.info.get("loop", 0), **extra)
        return
    frames, durations = [], []
    for frame in ImageSequence.Iterator(img):
        durations.append(frame.info.get("duration", 100))
        frames.append(_fit(frame.convert("RGBA")))
    frames[0].save(
        out,
        format=fmt,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=img.info.get("loop", 0),
        **extra,
    )


def prepare_images(files):
    """Check and re-encode uploads in memory. Nothing is written to storage here.

    Returns a list of (original_name, content_type, extension, data). Raises ValidationError.
    This is the slow part (decoding), so callers run it before they lock a ticket.
    """
    files = list(files)
    if len(files) > MAX_IMAGES_PER_MESSAGE:
        raise ValidationError(
            pgettext("aa_ticket", "You can attach at most %(count)d images per message.") % {"count": MAX_IMAGES_PER_MESSAGE}
        )
    max_mb = TicketSettings.get_solo().max_image_mb
    prepared = []
    for upload in files:
        if upload.size > max_mb * 1024 * 1024:
            raise ValidationError(pgettext("aa_ticket", "Each image must be smaller than %(size)d MB.") % {"size": max_mb})
        fmt = _detect_format(upload)
        content_type, ext = ALLOWED_FORMATS[fmt]
        data = _reencode(upload, fmt)
        prepared.append((os.path.basename(upload.name or "image")[:255], content_type, ext, data))
    return prepared


def save_prepared(message, prepared):
    """Store prepared images. If one write fails, files already written are removed again."""
    saved = []
    try:
        for original_name, content_type, ext, data in prepared:
            attachment = Attachment(
                message=message, original_name=original_name, size=len(data), content_type=content_type
            )
            attachment.file.save(uuid.uuid4().hex + ext, ContentFile(data), save=True)
            saved.append(attachment)
    except Exception:
        for attachment in saved:
            attachment.file.delete(save=False)
        raise
    return saved


def save_images(message, uploads):
    return save_prepared(message, prepare_images(uploads))


def delete_attachment(attachment):
    """Delete the file from storage and the database row."""
    if attachment.file:
        attachment.file.delete(save=False)
    attachment.delete()
