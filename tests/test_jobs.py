"""The job queue: friendly errors, the daily cap, the per-session cap, restarts and cleanup."""

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import httpx
from comfy_sdk.exceptions import InvalidWorkflow, JobFailed

from vfx4all.config import RUNS_DIR, UPLOADS_DIR
from vfx4all.jobs import Cancelled, JobManager, LimitReached, Usage, friendly_error


class FriendlyErrorTests(unittest.TestCase):
    def test_each_failure_reads_as_a_sentence(self):
        cases = {
            "Cancelled.": Cancelled(),
            "render failed": JobFailed("job failed"),
            "did not answer": httpx.ReadTimeout("timed out"),
            "Ant Size needs its own scene": ValueError("Ant Size needs its own scene"),
            "Reference: job-1": ZeroDivisionError("division by zero"),
        }
        for phrase, exc in cases.items():
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, friendly_error(exc, "job-1"))

    def test_a_missing_node_or_model_is_named(self):
        # how ComfyUI words them, directly or behind comfy-api-proxy
        node = InvalidWorkflow("Cannot execute because node LTXVAddGeneratedKeyframes does not exist.",
                               code="invalid_workflow")
        model = InvalidWorkflow("Prompt outputs failed validation", code="invalid_workflow", details={
            "node_errors": {"4": {"errors": [{"type": "value_not_in_list", "message": "Value not in list",
                                              "details": "unet_name: 'qwen_image_edit_2511_int8_convrot.safetensors' not in []"}]}}})
        self.assertIn("no LTXVAddGeneratedKeyframes node", friendly_error(node, "job-1"))
        said = friendly_error(model, "job-1")
        self.assertIn("model file qwen_image_edit_2511_int8_convrot.safetensors", said)
        self.assertIn("docs/RUN_ON_YOUR_COMFYUI.md", said)
        other = InvalidWorkflow("Prompt outputs failed validation", code="invalid_workflow")
        self.assertIn("renamed in its catalog", friendly_error(other, "job-1"))

    def test_the_messages_name_where_the_graph_runs(self):
        with mock.patch.dict(os.environ, {"COMFY_BASE_URL": "http://127.0.0.1:8189"}):
            down = friendly_error(httpx.ConnectError("refused"), "job-1")
            self.assertIn("Check that ComfyUI and comfy-api-proxy are running", down)
            self.assertIn("The render failed on your ComfyUI", friendly_error(JobFailed("job failed"), "job-1"))
        self.assertIn("The render failed on Comfy Cloud", friendly_error(JobFailed("job failed"), "job-1"))


class UsageTests(unittest.TestCase):
    def test_the_cap_holds_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage.json"
            Usage(path).take(2)
            Usage(path).take(2)
            with self.assertRaises(LimitReached):
                Usage(path).take(2)
            self.assertEqual(Usage(path).today(), 2)
            Usage(path).take(0)  # 0 means no cap
            self.assertEqual(Usage(path).today(), 3)


class JobManagerTests(unittest.TestCase):
    def setUp(self):
        self.manager = JobManager(workers=2)
        self.tmp = tempfile.TemporaryDirectory()
        self.manager.usage = Usage(Path(self.tmp.name) / "usage.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_session_runs_a_limited_number_of_jobs_in_hosted_mode(self):
        release = threading.Event()
        with mock.patch.dict(os.environ, {"VFX4ALL_MODE": "hosted", "VFX4ALL_SESSION_JOBS": "1"}):
            first = self.manager.submit("effect", {}, lambda j: release.wait(5), owner="alice")
            with self.assertRaises(LimitReached):
                self.manager.submit("effect", {}, lambda j: None, owner="alice")
            self.manager.submit("effect", {}, lambda j: None, owner="bob")
        release.set()
        self._wait(first.id)

    def test_one_network_runs_a_limited_number_of_jobs_in_hosted_mode(self):
        release = threading.Event()
        env = {"VFX4ALL_MODE": "hosted", "VFX4ALL_SESSION_JOBS": "5", "VFX4ALL_IP_JOBS": "1"}
        with mock.patch.dict(os.environ, env):
            first = self.manager.submit("effect", {}, lambda j: release.wait(5), owner="alice", ip="10.0.0.1")
            with self.assertRaises(LimitReached):
                self.manager.submit("effect", {}, lambda j: None, owner="carol", ip="10.0.0.1")
            self.manager.submit("effect", {}, lambda j: None, owner="dave", ip="10.0.0.2")
        release.set()
        self._wait(first.id)

    def test_a_restart_marks_running_jobs_failed_and_names_their_comfy_jobs(self):
        job_dir = RUNS_DIR / "effect-restarted1"
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "job.json").write_text(json.dumps({
            "id": "effect-restarted1", "kind": "effect", "status": "running", "comfy_jobs": ["abc-123"]}),
            encoding="utf-8")
        self.assertGreaterEqual(self.manager.recover(), 1)
        job = self.manager.get("effect-restarted1")
        self.assertEqual(job.status, "failed")
        self.assertIn("abc-123", job.error)

    def test_cleanup_deletes_old_runs_and_uploads_only(self):
        old = self._wait(self.manager.submit("effect", {}, lambda j: None).id)
        new = self._wait(self.manager.submit("effect", {}, lambda j: None).id)
        old.finished = time.time() - 72 * 3600
        old.save()
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        stale = UPLOADS_DIR / "stale.png"
        stale.write_bytes(b"x")
        os.utime(stale, (time.time() - 72 * 3600,) * 2)
        self.manager.cleanup(48)
        self.assertFalse(old.dir.exists())
        self.assertTrue(new.dir.exists())
        self.assertFalse(stale.exists())
        self.assertEqual(self.manager.cleanup(0), 0)

    def _wait(self, job_id):
        deadline = time.time() + 5
        while time.time() < deadline:
            job = self.manager.get(job_id)
            if job.status in ("succeeded", "failed", "cancelled"):
                return job
            time.sleep(0.02)
        raise AssertionError(f"{job_id} did not finish")


if __name__ == "__main__":
    unittest.main()
