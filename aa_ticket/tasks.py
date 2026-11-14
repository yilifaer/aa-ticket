import requests
from celery import shared_task

from django.utils import timezone

from allianceauth.services.hooks import get_extension_logger

from .app_settings import WEBHOOK_MAX_RETRIES
from .discord import webhook
from .models import Department, Ticket

logger = get_extension_logger(__name__)


def _record_webhook_result(department_id, error):
    if error:
        Department.objects.filter(pk=department_id).update(
            last_webhook_error=error[:255], last_webhook_error_at=timezone.now()
        )
    else:
        Department.objects.filter(pk=department_id).exclude(last_webhook_error="").update(
            last_webhook_error="", last_webhook_error_at=None
        )


@shared_task(bind=True, max_retries=WEBHOOK_MAX_RETRIES, ignore_result=True)
def send_webhook(self, department_id, ticket_id, event, mention):
    department = Department.objects.filter(pk=department_id).first()
    ticket = Ticket.objects.filter(pk=ticket_id).first()
    if department is None or ticket is None or not department.webhook_url:
        return
    payload = webhook.build_payload(ticket, event, mention, department)
    error = None
    countdown = None
    try:
        response = webhook.post_webhook(department.webhook_url, payload)
    except requests.RequestException as exc:
        error = type(exc).__name__
        countdown = 2**self.request.retries * 30
    else:
        if response.ok:
            _record_webhook_result(department_id, None)
            return
        error = f"HTTP {response.status_code}"
        if response.status_code == 429:
            countdown = webhook.retry_after_seconds(response)
        elif response.status_code >= 500:
            countdown = 2**self.request.retries * 30
    if countdown is not None and self.request.retries < self.max_retries:
        raise self.retry(countdown=countdown)
    _record_webhook_result(department_id, error)
    logger.warning(
        "Discord message for department %s (ticket %s) failed: %s", department.name, ticket.display_number, error
    )
