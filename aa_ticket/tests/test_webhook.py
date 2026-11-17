import json
from unittest.mock import MagicMock, patch

import requests

from django.core.exceptions import ValidationError
from django.test import TestCase

from aa_ticket import services
from aa_ticket.constants import Event
from aa_ticket.discord.webhook import build_payload, send_test_message, validate_webhook_url
from aa_ticket.models import Department
from aa_ticket.tasks import send_webhook

from .factories import make_department, make_user, priority

URL = "https://discord.com/api/webhooks/123456789012345678/SECRETtokenVALUE_abc-XYZ"


def response(status, body=None):
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.ok = 200 <= status < 300
    r.json.return_value = body or {}
    return r


class TestValidation(TestCase):
    def test_url_validation(self):
        for good in (
            URL,
            "https://discordapp.com/api/webhooks/1/abc",
            "https://canary.discord.com/api/webhooks/1/abc",
            "https://ptb.discord.com/api/webhooks/1/abc",
        ):
            validate_webhook_url(good)
        for bad in (
            "http://discord.com/api/webhooks/1/abc",
            "https://evil.example.com/api/webhooks/1/abc",
            "https://discord.com.evil.example/api/webhooks/1/abc",
            URL + "/x",
            "",
        ):
            with self.assertRaises(ValidationError, msg=bad):
                validate_webhook_url(bad)


class WebhookFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = make_department(
            "Diplomacy", webhook_url=URL, mention_role_ids="111111111111111111, 222222222222222222"
        )
        cls.requester = make_user("Pilot A")
        cls.ticket = services.create_ticket(
            cls.requester, cls.dept, priority("urgent"), "@everyone help", "SECRET-BODY-TEXT"
        )


class TestPayload(WebhookFixture):
    def test_payload_mentions_only_in_content_with_allowed_roles(self):
        payload = build_payload(self.ticket, Event.SUBMITTED, True, self.dept)
        self.assertEqual(payload["content"], "<@&111111111111111111> <@&222222222222222222>")
        self.assertEqual(
            payload["allowed_mentions"], {"parse": [], "roles": ["111111111111111111", "222222222222222222"]}
        )
        embed = payload["embeds"][0]
        self.assertTrue(embed["title"].startswith(f"#{self.ticket.pk} "))
        self.assertEqual(embed["url"], f"https://auth.example.com/ticket/{self.ticket.pk}/")
        self.assertEqual(embed["color"], 0xDC3545)

    def test_payload_no_mention(self):
        payload = build_payload(self.ticket, Event.SUBMITTED, False, self.dept)
        self.assertEqual(payload["content"], "")
        self.assertEqual(payload["allowed_mentions"], {"parse": [], "roles": []})

    def test_title_with_everyone_cannot_ping(self):
        payload = build_payload(self.ticket, Event.SUBMITTED, True, self.dept)
        self.assertNotIn("@everyone", payload["content"])
        self.assertIn("@everyone", payload["embeds"][0]["title"])
        self.assertEqual(payload["allowed_mentions"]["parse"], [])

    def test_payload_has_no_body(self):
        for event in (Event.SUBMITTED, Event.ESCALATION_REQUESTED, Event.UNCLAIMED_REMINDER):
            payload = build_payload(self.ticket, event, True, self.dept)
            self.assertNotIn("SECRET-BODY-TEXT", json.dumps(payload))

    def test_long_title_truncated(self):
        self.ticket.title = "x" * 300
        payload = build_payload(self.ticket, Event.SUBMITTED, False, self.dept)
        self.assertLessEqual(len(payload["embeds"][0]["title"]), 256)


class TestDelivery(WebhookFixture):
    @patch("aa_ticket.discord.webhook.requests.post")
    def test_success_clears_error(self, post):
        Department.objects.filter(pk=self.dept.pk).update(last_webhook_error="HTTP 500")
        post.return_value = response(204)
        send_webhook.apply(args=[self.dept.pk, self.ticket.pk, Event.SUBMITTED, True])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["timeout"], 10)
        self.assertEqual(Department.objects.get(pk=self.dept.pk).last_webhook_error, "")

    @patch("aa_ticket.discord.webhook.requests.post")
    def test_429_retries_with_retry_after(self, post):
        post.side_effect = [response(429, {"retry_after": 2.5}), response(204)]
        with patch("aa_ticket.tasks.send_webhook.retry", wraps=send_webhook.retry) as retry:
            send_webhook.apply(args=[self.dept.pk, self.ticket.pk, Event.SUBMITTED, True])
        self.assertEqual(post.call_count, 2)
        self.assertEqual(retry.call_args.kwargs["countdown"], 3)
        self.assertEqual(Department.objects.get(pk=self.dept.pk).last_webhook_error, "")

    @patch("aa_ticket.discord.webhook.requests.post")
    def test_final_failure_records_error_without_url(self, post):
        post.side_effect = requests.ConnectionError(f"failed to reach {URL}")
        with self.assertLogs("extensions.aa_ticket", level="WARNING") as logs:
            send_webhook.apply(args=[self.dept.pk, self.ticket.pk, Event.SUBMITTED, True])
        self.assertEqual(post.call_count, 6)
        dept = Department.objects.get(pk=self.dept.pk)
        self.assertEqual(dept.last_webhook_error, "ConnectionError")
        self.assertIsNotNone(dept.last_webhook_error_at)
        self.assertEqual(len(logs.output), 1)
        self.assertNotIn("SECRETtoken", "".join(logs.output))

    @patch("aa_ticket.discord.webhook.requests.post")
    def test_404_not_retried(self, post):
        post.return_value = response(404)
        with self.assertLogs("extensions.aa_ticket", level="WARNING"):
            send_webhook.apply(args=[self.dept.pk, self.ticket.pk, Event.SUBMITTED, True])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(Department.objects.get(pk=self.dept.pk).last_webhook_error, "HTTP 404")

    @patch("aa_ticket.discord.webhook.requests.post")
    def test_no_webhook_configured_noop(self, post):
        other = make_department("Logistics")
        send_webhook.apply(args=[other.pk, self.ticket.pk, Event.SUBMITTED, True])
        post.assert_not_called()

    @patch("aa_ticket.discord.webhook.requests.post")
    def test_send_test_message(self, post):
        post.return_value = response(204)
        ok, text = send_test_message(self.dept)
        self.assertTrue(ok)
        self.assertEqual(post.call_args.kwargs["timeout"], 5)
        post.return_value = response(401)
        ok, text = send_test_message(self.dept)
        self.assertFalse(ok)
        self.assertIn("401", text)
        self.assertNotIn("SECRETtoken", text)
