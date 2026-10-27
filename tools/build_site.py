"""Build the static catalog site: the web interface without the server. Every effect shows its preview
and links to its Comfy Cloud App Mode app (the preset's `comfy_app`), so visitors run it with their own
Comfy account. The output goes to Vercel or any static host.

    python tools/build_site.py                          # writes site/
    python tools/build_site.py --demo path/to/demo.mp4  # with the demo video
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vfx4all import __version__  # noqa: E402
from vfx4all.config import WORKFLOWS_DIR  # noqa: E402
from vfx4all.presets import load_presets, public_view  # noqa: E402

WEB = ROOT / "web"
APP_MODE = '<meta name="vfx4all-mode" content="app">'
STATIC_MODE = '<meta name="vfx4all-mode" content="static">'
DEMO_MARKER = "<!-- demo -->"
DEMO_VIDEO = '<video class="demo-video bevel reveal" src="/static/media/demo.mp4" controls playsinline preload="metadata"></video>'

# The same headers the server sends (vfx4all/server.py), so the site runs under the same rules.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data: blob:; "
       "media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
       "frame-ancestors 'none'")
VERCEL = {
    "cleanUrls": True,
    "headers": [
        {"source": "/(.*)", "headers": [
            {"key": "Content-Security-Policy", "value": CSP},
            {"key": "X-Content-Type-Options", "value": "nosniff"},
            {"key": "Referrer-Policy", "value": "strict-origin-when-cross-origin"},
            {"key": "Permissions-Policy", "value": "camera=(), microphone=(), geolocation=()"},
        ]},
        {"source": "/static/(.*)", "headers": [{"key": "Cache-Control", "value": "public, max-age=3600"}]},
    ],
}


def asset_version() -> str:
    """Same cache-busting tag as the server: the version plus the bytes of app.js and app.css."""
    digest = hashlib.sha256(__version__.encode())
    for name in ("app.js", "app.css"):
        digest.update((WEB / name).read_bytes())
    return digest.hexdigest()[:10]


def site_presets() -> list[dict]:
    """The cards, plus whether the preset can run as a single App Mode graph at all."""
    out = []
    for preset in load_presets():
        view = public_view(preset)
        view["app_mode"] = (WORKFLOWS_DIR / "apps" / f"{preset['id']}.json").exists()
        out.append(view)
    return out


def build(out: Path, demo: Path | None = None) -> dict:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(WEB, out / "static", ignore=shutil.ignore_patterns("index.html"))

    html = (WEB / "index.html").read_text(encoding="utf-8")
    if APP_MODE not in html:
        raise RuntimeError("web/index.html lost its vfx4all-mode meta tag")
    html = html.replace(APP_MODE, STATIC_MODE).replace("{{v}}", asset_version())
    if demo:
        shutil.copyfile(demo, out / "static" / "media" / "demo.mp4")
        html = html.replace(DEMO_MARKER, DEMO_VIDEO)
    (out / "index.html").write_text(html, encoding="utf-8")

    presets = site_presets()
    (out / "static" / "presets.json").write_text(json.dumps(presets, ensure_ascii=False), encoding="utf-8")
    (out / "vercel.json").write_text(json.dumps(VERCEL, indent=2), encoding="utf-8")
    return {"presets": len(presets), "apps": sum(bool(p["comfy_app"]) for p in presets),
            "app_mode": sum(p["app_mode"] for p in presets), "demo": bool(demo)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "site")
    parser.add_argument("--demo", type=Path, help="demo video, copied to static/media/demo.mp4")
    args = parser.parse_args()
    report = build(args.out, args.demo)
    print(f"{args.out}: {report['presets']} effects, {report['apps']} with a Comfy Cloud app link "
          f"({report['app_mode']} can run in App Mode), demo {'yes' if report['demo'] else 'no'}")


if __name__ == "__main__":
    main()
