"""0.4.7: decision from the 0.4.6 test report (section 7): animation total limited to 25 megapixels."""

import io

from PIL import Image

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import translation

from aa_ticket import attachments


def animation(size, frames, fmt="GIF"):
    images = [Image.new("RGB", size, (i * 40 % 256, 0, 0)) for i in range(frames)]
    buf = io.BytesIO()
    images[0].save(buf, format=fmt, save_all=True, append_images=images[1:], duration=100, loop=0)
    return SimpleUploadedFile(f"a.{fmt.lower()}", buf.getvalue())


class TestAnimationTotal(TestCase):
    def test_limit_is_25_megapixels(self):
        from aa_ticket.app_settings import MAX_ANIMATION_PIXELS

        self.assertEqual(MAX_ANIMATION_PIXELS, 25_000_000)

    def test_seven_large_frames_are_refused_with_frames_and_size(self):
        # 2000 x 2000 = 4 MP per frame; 7 frames = 28 MP, above the 25 MP total
        with translation.override("en"), self.assertRaises(ValidationError) as ctx:
            attachments.prepare_images([animation((2000, 2000), 7)])
        text = " ".join(ctx.exception.messages)
        self.assertIn("7 frames", text)
        self.assertIn("2000 × 2000", text)
        self.assertIn("25 megapixels", text)
        self.assertIn("fewer frames", text)

    def test_webp_animation_is_refused_too(self):
        with self.assertRaises(ValidationError):
            attachments.prepare_images([animation((2000, 2000), 7, "WEBP")])

    def test_chinese_message(self):
        with translation.override("zh-hans"), self.assertRaises(ValidationError) as ctx:
            attachments.prepare_images([animation((2000, 2000), 7)])
        text = " ".join(ctx.exception.messages)
        self.assertIn("7 帧", text)
        self.assertIn("2000 × 2000", text)

    def test_animation_within_total_is_accepted(self):
        data = attachments.prepare_images([animation((2000, 2000), 6)])[0][3]
        with Image.open(io.BytesIO(data)) as img:
            self.assertEqual(img.n_frames, 6)

    def test_common_small_animation_is_accepted(self):
        # 480 x 270, 100 frames = about 13 MP
        data = attachments.prepare_images([animation((480, 270), 100)])[0][3]
        with Image.open(io.BytesIO(data)) as img:
            self.assertEqual(img.n_frames, 100)

    def test_single_frame_over_limit_keeps_the_still_image_message(self):
        with translation.override("en"), self.assertRaises(ValidationError) as ctx:
            attachments.prepare_images([animation((6000, 5000), 1)])
        self.assertIn("6000 × 5000", " ".join(ctx.exception.messages))
        self.assertNotIn("frames", " ".join(ctx.exception.messages))
