"""Small media files made with the ffmpeg that ships in imageio-ffmpeg."""

from __future__ import annotations

import subprocess
from pathlib import Path

from vfx4all.media import FFMPEG


def make_clip(path: Path, seconds: float, size: str = "854x480", fps: int = 24, source: str = "testsrc2",
              audio: bool = True) -> Path:
    spec = f"{source}:" if "=" in source else f"{source}="  # "testsrc2" or "color=c=black"
    args = [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"{spec}size={size}:rate={fps}:duration={seconds}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast"]
    if audio:
        args += ["-c:a", "aac", "-shortest"]
    subprocess.run([*args, str(path)], check=True)
    return path


def make_rotated(source: Path, path: Path, degrees: int) -> Path:
    """The same clip with a display rotation, the way a phone saves a vertical video."""
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-display_rotation", str(degrees),
                    "-i", str(source), "-c", "copy", str(path)], check=True)
    return path


def make_image(path: Path, size: str = "320x180") -> Path:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
                    "-i", f"testsrc2=size={size}:rate=1", "-frames:v", "1", str(path)], check=True)
    return path
