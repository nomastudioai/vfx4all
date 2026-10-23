"""The static catalog site builds from web/ and the presets, with no server behind it."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from vfx4all.config import ROOT
from vfx4all.presets import load_presets

sys.path.insert(0, str(ROOT / "tools"))
import build_site  # noqa: E402


class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "site"
        demo = Path(cls.tmp.name) / "demo.mp4"
        demo.write_bytes(b"not really a video")
        cls.report = build_site.build(cls.out, demo)
        cls.html = (cls.out / "index.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_page_runs_in_static_mode(self):
        self.assertIn(build_site.STATIC_MODE, self.html)
        self.assertNotIn(build_site.APP_MODE, self.html)
        self.assertNotIn("{{v}}", self.html)
        self.assertTrue((self.out / "static" / "app.js").exists())

    def test_every_preset_is_listed_with_its_app_mode_status(self):
        presets = json.loads((self.out / "static" / "presets.json").read_text(encoding="utf-8"))
        self.assertEqual(len(presets), len(load_presets()))
        apps = {p.stem for p in (ROOT / "workflows" / "apps").glob("*.json")}
        for preset in presets:
            self.assertEqual(preset["app_mode"], preset["id"] in apps, preset["id"])
            self.assertTrue((self.out / preset["thumb"].lstrip("/")).exists(), preset["thumb"])
            self.assertTrue((self.out / preset["preview"].lstrip("/")).exists(), preset["preview"])
        self.assertEqual(self.report["app_mode"], len(apps))

    def test_app_links_are_public_share_links(self):
        # a #<uuid> record link only opens for members of the workspace
        for preset in load_presets():
            link = preset.get("comfy_app") or ""
            if link:
                self.assertTrue(link.startswith("https://cloud.comfy.org/?share="), preset["id"])

    def test_demo_replaces_the_marker(self):
        self.assertIn(build_site.DEMO_VIDEO, self.html)
        self.assertTrue((self.out / "static" / "media" / "demo.mp4").exists())

    def test_headers_match_the_server(self):
        from vfx4all.server import CSP
        vercel = json.loads((self.out / "vercel.json").read_text(encoding="utf-8"))
        sent = {h["key"]: h["value"] for h in vercel["headers"][0]["headers"]}
        self.assertEqual(sent["Content-Security-Policy"], CSP)


if __name__ == "__main__":
    unittest.main()
