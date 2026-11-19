from django.contrib.auth.decorators import login_required, permission_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from .. import access
from ..constants import MessageKind
from ..models import Attachment


@login_required
@permission_required("aa_ticket.basic_access", raise_exception=True)
def attachment(request, pk):
    att = get_object_or_404(Attachment.objects.select_related("message__ticket"), pk=pk)
    ticket = att.message.ticket
    if not access.can_view(request.user, ticket):
        raise Http404
    if att.message.kind == MessageKind.INTERNAL and not access.can_view_internal(request.user, ticket):
        raise Http404
    try:
        handle = att.file.open("rb")
    except (FileNotFoundError, ValueError) as exc:
        raise Http404 from exc
    response = FileResponse(handle, content_type=att.content_type, filename=att.original_name)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox"
    response["Cache-Control"] = "private, max-age=300"  # short, so removed staff lose access soon
    return response
