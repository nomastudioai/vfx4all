"""The HTTP API, through FastAPI's in-process client. Nothing here submits a generation."""

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from vfx4all.config import VIDEO_LIMITS
from vfx4all.server import app

from .helpers import make_clip, make_image


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def upload(self, path: Path):
        with path.open("rb") as fh:
            return self.client.post("/api/upload", files={"file": (path.name, fh)})

    def test_health_reports_the_video_limits(self):
        body = self.client.get("/api/health").json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["has_key"])
        self.assertEqual(body["video_limits"], VIDEO_LIMITS)

    def test_presets(self):
        cards = self.client.get("/api/presets").json()
        self.assertEqual(len(cards), 45)
        self.assertTrue(all(c["thumb"].startswith("/static/thumbs/") for c in cards))

    def test_index_and_static_files(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/static/app.js").status_code, 200)

    def test_upload_accepts_an_image_and_a_clip_inside_the_limits(self):
        image = self.upload(make_image(self.dir / "face.png"))
        self.assertEqual(image.status_code, 200, image.text)
        self.assertEqual(image.json()["kind"], "image")
        clip = self.upload(make_clip(self.dir / "ok.mp4", 3))
        self.assertEqual(clip.status_code, 200, clip.text)
        self.assertEqual(clip.json()["kind"], "video")

    def test_upload_refuses_a_clip_outside_the_limits(self):
        short = self.upload(make_clip(self.dir / "short.mp4", 1))
        self.assertEqual(short.status_code, 422)
        small = self.upload(make_clip(self.dir / "small.mp4", 3, size="640x360"))
        self.assertEqual(small.status_code, 422)
        self.assertIn("480p", small.json()["detail"])

    def test_upload_refuses_other_file_types(self):
        text = self.dir / "notes.txt"
        text.write_text("hello", encoding="utf-8")
        self.assertEqual(self.upload(text).status_code, 400)

    def test_generation_needs_a_key(self):
        # tests/__init__.py blanks COMFY_API_KEY, so without a user key the server refuses up front.
        response = self.client.post("/api/jobs/scene", json={"preset": "shockwave", "refs": ["x.png"]})
        self.assertEqual(response.status_code, 401)

    def test_bad_requests_stop_before_any_job(self):
        headers = {"X-Comfy-Key": "not-a-real-key"}
        bad_subject = self.client.post("/api/jobs/scene", headers=headers,
                                       json={"preset": "shockwave", "refs": ["x.png"], "subject": "cat"})
        self.assertEqual(bad_subject.status_code, 400)
        missing_upload = self.client.post("/api/jobs/scene", headers=headers,
                                          json={"preset": "shockwave", "refs": ["missing.png"]})
        self.assertEqual(missing_upload.status_code, 404)
        no_source = self.client.post("/api/jobs/effect", headers=headers, json={"preset": "shockwave"})
        self.assertEqual(no_source.status_code, 400)

    def test_unknown_job(self):
        self.assertEqual(self.client.get("/api/jobs/nope").status_code, 404)


if __name__ == "__main__":
    unittest.main()
