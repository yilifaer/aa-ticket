import io
from unittest.mock import patch

from PIL import Image

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from aa_ticket import attachments, services
from aa_ticket.constants import Event
from aa_ticket.exceptions import TicketActionError
from aa_ticket.notifications import _channel_targets

from .factories import make_department, make_group, make_user, priority


def gif(frames, size=(8, 8), durations=None):
    imgs = [Image.new("RGB", size, (i % 255, 0, 0)) for i in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, format="GIF", save_all=True, append_images=imgs[1:], duration=durations or 100, loop=0)
    return SimpleUploadedFile("a.gif", buf.getvalue())


class TestFrameBomb(TestCase):
    def test_too_many_frames_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            attachments.validate_images([gif(150, size=(4, 4))])
        self.assertIn("too many frames", " ".join(ctx.exception.messages))

    def test_large_canvas_animation_rejected(self):
        with patch("aa_ticket.attachments.MAX_ANIMATION_PIXELS", 1000):
            with self.assertRaises(ValidationError):
                attachments.validate_images([gif(20, size=(20, 20))])

    def test_frame_durations_kept(self):
        g = make_group("Diplomats")
        dept = make_department("Diplomacy", groups=[g])
        t = services.create_ticket(make_user("Pilot A"), dept, priority("normal"), "Help", "Body",
                                   images=[gif(3, durations=[100, 500, 1000])])
        with t.messages.get(kind="reply").attachments.get().file.open("rb") as fh:
            with Image.open(io.BytesIO(fh.read())) as saved:
                got = []
                for i in range(saved.n_frames):
                    saved.seek(i)
                    got.append(saved.info.get("duration"))
        self.assertEqual(got, [100, 500, 1000])


class TestTruncated(TestCase):
    def test_truncated_jpeg_gives_error_not_500(self):
        buf = io.BytesIO()
        Image.new("RGB", (200, 200), (1, 2, 3)).save(buf, format="JPEG")
        data = buf.getvalue()[:-400]
        g = make_group("Diplomats")
        dept = make_department("Diplomacy", groups=[g])
        with self.assertRaises(TicketActionError):
            services.create_ticket(make_user("Pilot A"), dept, priority("normal"), "Help", "Body",
                                   images=[SimpleUploadedFile("a.jpg", data)])


class TestAssigneeLeftNoPing(TestCase):
    def test_assignee_left_does_not_mention(self):
        dept = make_department("Diplomacy")
        t = services.create_ticket(make_user("Pilot A"), dept, priority("urgent"), "Help", "Body")
        self.assertEqual(_channel_targets(t, Event.ASSIGNEE_LEFT, {}), [(dept.pk, False)])


class TestDepartmentEdit404(TestCase):
    def test_missing_department_404(self):
        admin = make_user("Admin A", perms=("basic_access", "manage"))
        self.client.force_login(admin)
        self.assertEqual(self.client.get("/ticket/manage/departments/999999/").status_code, 404)
