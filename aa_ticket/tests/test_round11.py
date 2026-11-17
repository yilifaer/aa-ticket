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


def mpo(size, extra_size):
    """A phone photo with a hidden extra picture (HDR gain map / depth map)."""
    main = Image.new("RGB", size, (120, 80, 40))
    extra = Image.new("RGB", extra_size, (10, 10, 10))
    buf = io.BytesIO()
    main.save(buf, format="MPO", save_all=True, append_images=[extra])
    return SimpleUploadedFile("photo.jpg", buf.getvalue())


class TestPhonePhotosWithExtraPicture(TestCase):
    """Multi-picture JPEGs keep only the main picture, so they are not counted as animations."""

    def test_pillow_reads_it_as_two_pictures(self):
        upload = mpo((4080, 3072), (1020, 768))
        with Image.open(upload) as img:
            self.assertEqual((img.format, img.n_frames), ("MPO", 2))

    def test_12mp_phone_photo_is_accepted_and_saved_as_one_jpeg(self):
        prepared = attachments.prepare_images([mpo((4080, 3072), (1020, 768))])
        content_type, data = prepared[0][1], prepared[0][3]
        self.assertEqual(content_type, "image/jpeg")
        with Image.open(io.BytesIO(data)) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertEqual(getattr(img, "n_frames", 1), 1)
            self.assertEqual(img.size, (4080, 3072))

    def test_24mp_iphone_size_is_accepted_and_scaled(self):
        data = attachments.prepare_images([mpo((4284, 5712), (1071, 1428))])[0][3]
        with Image.open(io.BytesIO(data)) as img:
            self.assertEqual(img.size, (3072, 4096))

    def test_main_picture_above_25mp_is_still_refused_as_an_image(self):
        with translation.override("en"), self.assertRaises(ValidationError) as ctx:
            attachments.prepare_images([mpo((6000, 5000), (100, 100))])
        text = " ".join(ctx.exception.messages)
        self.assertIn("This image is too large (6000 × 5000 pixels)", text)
        self.assertNotIn("animation", text)


class TestAnimatedPng(TestCase):
    """Animated PNGs are saved as their first frame only, so only that frame counts."""

    def test_large_apng_is_accepted_as_still_image(self):
        frames = [Image.new("RGB", (3000, 3000), (i * 60, 0, 0)) for i in range(4)]
        buf = io.BytesIO()
        frames[0].save(buf, format="PNG", save_all=True, append_images=frames[1:])
        data = attachments.prepare_images([SimpleUploadedFile("a.png", buf.getvalue())])[0][3]
        with Image.open(io.BytesIO(data)) as img:
            self.assertEqual(getattr(img, "n_frames", 1), 1)
