"""The HTTP API, through FastAPI's in-process client. Nothing here submits a generation:
the few tests that need a job swap the pipeline step for a local stand-in."""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from vfx4all import config, server
from vfx4all.config import IMAGE_LIMITS, VIDEO_LIMITS
from vfx4all.jobs import Cancelled, Usage
from vfx4all.server import app

from .helpers import make_clip, make_image

KEY = {"X-Comfy-Key": "not-a-real-key"}


def finished(job_id: str, timeout: float = 5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = server.jobs.get(job_id)
        if job and job.status in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"{job_id} did not finish")


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.face = make_image(cls.dir / "face.png")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def upload(self, path: Path, client=None, consent="true", headers=None):
        with path.open("rb") as fh:
            return (client or self.client).post("/api/upload", files={"file": (path.name, fh)},
                                                data={"consent": consent}, headers=headers or {})

    def test_health_reports_the_limits_and_the_mode(self):
        body = self.client.get("/api/health").json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["has_key"])
        self.assertEqual(body["mode"], "local")
        self.assertFalse(body["access_required"])
        self.assertEqual(body["video_limits"], VIDEO_LIMITS)
        self.assertEqual(body["image_limits"], IMAGE_LIMITS)
        self.assertEqual(body["target"], {"kind": "cloud", "label": "Comfy Cloud"})

    def test_your_own_comfyui_needs_no_key(self):
        with mock.patch.dict(os.environ, {"COMFY_BASE_URL": "http://127.0.0.1:8189"}):
            body = self.client.get("/api/health").json()
        self.assertTrue(body["has_key"])
        self.assertEqual(body["target"], {"kind": "local", "label": "Your ComfyUI"})

    def test_a_job_for_your_own_comfyui_is_taken_without_a_key(self):
        upload = self.upload(make_clip(self.dir / "own-comfyui.mp4", 3)).json()
        body = {"preset": "disintegrate", "video": upload["id"], "seconds": 0.5, "seed": 7, "direction": "slow wind"}
        self.assertEqual(self.client.post("/api/jobs/splice", json=body).status_code, 401)
        with mock.patch.dict(os.environ, {"COMFY_BASE_URL": "http://127.0.0.1:8189"}), \
                mock.patch.object(server.pipeline, "run_splice") as run:
            res = self.client.post("/api/jobs/splice", json=body)
            self.assertEqual(res.status_code, 200, res.text)
            job = res.json()
            for _ in range(50):
                if run.called:
                    break
                time.sleep(0.05)
        self.assertEqual(job["params"]["direction"], "slow wind")
        self.assertEqual(job["params"]["seed"], 7)
        self.assertEqual(run.call_args.kwargs["direction"], "slow wind")

    def test_the_samples_are_served_and_nothing_else(self):
        photo = self.client.get("/samples/photos/front.jpg")
        self.assertEqual(photo.status_code, 200)
        self.assertEqual(photo.headers["content-type"], "image/jpeg")
        self.assertEqual(self.client.get("/samples/clips/street-walk-16x9.mp4").status_code, 200)
        for path in ("/samples/photos/../README.md", "/samples/photos/%2E%2E%2FREADME.md", "/samples/runs/front.jpg",
                     "/samples/photos/missing.jpg"):
            with self.subTest(path=path):
                self.assertIn(self.client.get(path).status_code, (404, 422))

    def test_a_long_direction_is_refused(self):
        res = self.client.post("/api/jobs/effect", json={"preset": "walk-of-fire", "image": "x" * 32,
                                                          "direction": "a" * 501})
        self.assertEqual(res.status_code, 422)

    def test_presets(self):
        cards = self.client.get("/api/presets").json()
        self.assertEqual(len(cards), 45)
        self.assertTrue(all(c["thumb"].startswith("/static/thumbs/") for c in cards))

    def test_index_gets_versioned_assets_and_security_headers(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn("{{v}}", page.text)
        self.assertIn("default-src 'self'", page.headers["content-security-policy"])
        self.assertEqual(page.headers["x-content-type-options"], "nosniff")
        self.assertIn(server.SESSION_COOKIE, self.client.cookies)
        self.assertEqual(self.client.get("/static/app.js").status_code, 200)

    def test_upload_accepts_an_image_and_a_clip_inside_the_limits(self):
        image = self.upload(self.face)
        self.assertEqual(image.status_code, 200, image.text)
        self.assertEqual(image.json()["kind"], "image")
        clip = self.upload(make_clip(self.dir / "ok.mp4", 3))
        self.assertEqual(clip.status_code, 200, clip.text)
        self.assertEqual(clip.json()["kind"], "video")
        self.assertEqual(self.client.get(clip.json()["url"]).status_code, 200)

    def test_upload_needs_consent(self):
        response = self.upload(self.face, consent="")
        self.assertEqual(response.status_code, 400)
        self.assertIn("agreed", response.json()["detail"])

    def test_upload_refuses_a_clip_outside_the_limits(self):
        short = self.upload(make_clip(self.dir / "short.mp4", 1))
        self.assertEqual(short.status_code, 422)
        small = self.upload(make_clip(self.dir / "small.mp4", 3, size="640x360"))
        self.assertEqual(small.status_code, 422)
        self.assertIn("480p", small.json()["detail"])

    def test_upload_refuses_photos_outside_the_limits(self):
        with mock.patch.dict(config.IMAGE_LIMITS, {"max_side": 100}):
            self.assertEqual(self.upload(self.face).status_code, 422)
        with mock.patch.dict(config.IMAGE_LIMITS, {"max_mb": 0}):
            self.assertEqual(self.upload(self.face).status_code, 413)

    def test_upload_refuses_other_file_types(self):
        text = self.dir / "notes.txt"
        text.write_text("hello", encoding="utf-8")
        self.assertEqual(self.upload(text).status_code, 400)
        heic = self.dir / "IMG_0001.HEIC"
        heic.write_bytes(b"not really a heic")
        response = self.upload(heic)
        self.assertEqual(response.status_code, 400)
        self.assertIn("HEIC", response.json()["detail"])

    def test_generation_needs_a_key(self):
        # tests/__init__.py blanks COMFY_API_KEY, so without a user key the server refuses up front.
        response = self.client.post("/api/jobs/scene", json={"preset": "shockwave", "refs": ["x.png"]})
        self.assertEqual(response.status_code, 401)

    def test_bad_requests_stop_before_any_job(self):
        face = self.upload(self.face).json()["id"]
        cases = {
            422: [("scene", {"preset": "shockwave", "refs": [face], "subject": "cat"}),
                  ("effect", {"preset": "shockwave", "image": face, "quality": "ultra"}),
                  ("splice", {"preset": "shockwave", "video": face, "audio": "loud"})],
            404: [("scene", {"preset": "no-such-effect", "refs": [face]}),
                  ("scene", {"preset": "shockwave", "refs": ["missing.png"]})],
            400: [("effect", {"preset": "shockwave"}),
                  ("effect", {"preset": "colossus", "image": face}),    # scene only
                  ("effect", {"preset": "ant-size", "image": face}),    # scene only, has a generic prompt
                  ("splice", {"preset": "frozen-rain", "video": face})],
        }
        for status, requests in cases.items():
            for kind, body in requests:
                with self.subTest(kind=kind, body=body):
                    self.assertEqual(self.client.post(f"/api/jobs/{kind}", headers=KEY, json=body).status_code, status)

    def test_unknown_job(self):
        self.assertEqual(self.client.get("/api/jobs/nope").status_code, 404)
        self.assertEqual(self.client.post("/api/jobs/nope/cancel").status_code, 404)

    def test_files_serves_outputs_only(self):
        def work(job):
            out = job.dir / "effect.mp4"
            out.write_bytes(b"video")
            job.add_output("video", out)

        job = finished(server.jobs.submit("effect", {}, work).id)
        self.assertEqual(self.client.get(job.outputs["video"]).content, b"video")
        for name in ("job.json", "error.txt", "../usage.json"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(f"/files/{job.id}/{name}").status_code, 404)

    def test_cancel_stops_a_running_job(self):
        started = threading.Event()

        def work(job):
            started.set()
            for _ in range(200):
                if job.cancel_requested:
                    raise Cancelled()
                time.sleep(0.01)

        job = server.jobs.submit("effect", {}, work)
        started.wait(2)
        self.assertEqual(self.client.post(f"/api/jobs/{job.id}/cancel").status_code, 200)
        done = finished(job.id)
        self.assertEqual(done.status, "cancelled")
        self.assertEqual(self.client.get(f"/api/jobs/{job.id}").json()["status"], "cancelled")


class HostedModeTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"VFX4ALL_MODE": "hosted"})
        self.env.start()
        self.alice, self.bob = TestClient(app), TestClient(app)
        self.alice.get("/")
        self.bob.get("/")
        self.tmp = tempfile.TemporaryDirectory()
        self.face = make_image(Path(self.tmp.name) / "face.png")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def upload(self, client, headers=None):
        with self.face.open("rb") as fh:
            return client.post("/api/upload", files={"file": ("face.png", fh)}, data={"consent": "true"},
                               headers=headers or {})

    def test_hosted_limits_are_lower(self):
        limits = self.alice.get("/api/health").json()["video_limits"]
        self.assertEqual(limits, config.HOSTED_VIDEO_LIMITS)
        self.assertLess(limits["max_mb"], VIDEO_LIMITS["max_mb"])

    def test_uploads_and_jobs_belong_to_their_session(self):
        upload = self.upload(self.alice).json()
        self.assertEqual(self.alice.get(upload["url"]).status_code, 200)
        self.assertEqual(self.bob.get(upload["url"]).status_code, 404)
        stolen = self.bob.post("/api/jobs/effect", headers=KEY, json={"preset": "shockwave", "image": upload["id"]})
        self.assertEqual(stolen.status_code, 404)

        owner = self.alice.cookies[server.SESSION_COOKIE]
        job = finished(server.jobs.submit("effect", {}, lambda j: None, owner=owner).id)
        self.assertEqual(self.alice.get(f"/api/jobs/{job.id}").status_code, 200)
        self.assertEqual(self.bob.get(f"/api/jobs/{job.id}").status_code, 404)

    def test_access_code(self):
        with mock.patch.dict(os.environ, {"VFX4ALL_ACCESS_CODE": "open-sesame"}):
            self.assertTrue(self.alice.get("/api/health").json()["access_required"])
            self.assertEqual(self.upload(self.alice).status_code, 403)
            self.assertEqual(self.upload(self.alice, {"X-Access-Code": "wrong"}).status_code, 403)
            self.assertEqual(self.upload(self.alice, {"X-Access-Code": "open-sesame"}).status_code, 200)

    def test_daily_cap(self):
        face = self.upload(self.alice).json()["id"]
        body = {"preset": "shockwave", "refs": [face]}
        usage = Usage(Path(self.tmp.name) / "usage.json")
        with mock.patch.dict(os.environ, {"VFX4ALL_DAILY_RUNS": "1"}), \
                mock.patch.object(server.jobs, "usage", usage), \
                mock.patch("vfx4all.pipeline.run_scene", lambda job, **kw: None):
            first = self.alice.post("/api/jobs/scene", headers=KEY, json=body)
            self.assertEqual(first.status_code, 200, first.text)
            finished(first.json()["id"])
            self.assertEqual(self.alice.post("/api/jobs/scene", headers=KEY, json=body).status_code, 429)


if __name__ == "__main__":
    unittest.main()
