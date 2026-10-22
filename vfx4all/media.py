"""ffmpeg helpers: probing, frame grabs, the black-take check and the splice.

ffmpeg comes from the imageio-ffmpeg wheel, so nothing has to be installed by
hand. Set VFX4ALL_FFMPEG to use another binary.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

FFMPEG = os.environ.get("VFX4ALL_FFMPEG") or get_ffmpeg_exe()


class MediaError(RuntimeError):
    pass


def _run(args: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run([FFMPEG, "-hide_banner", "-y", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-6:])
        raise MediaError(f"ffmpeg failed: {tail}")
    return proc


def probe(path: Path) -> dict:
    """Duration, size, frame rate and audio presence, read from `ffmpeg -i`."""
    proc = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    info = proc.stderr
    video = re.search(r"Stream #\S+.*?Video: .*?(\d{2,5})x(\d{2,5})", info)
    if not video:
        raise MediaError(f"No picture found in {path.name}")
    duration = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", info)
    seconds = (int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])) if duration else 0.0
    fps = re.search(r"(\d+(?:\.\d+)?) fps", info)
    is_image = path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    return {
        "kind": "image" if is_image else "video",
        "width": int(video[1]),
        "height": int(video[2]),
        "duration": 0.0 if is_image else round(seconds, 3),
        "fps": float(fps[1]) if fps else 24.0,
        "has_audio": "Audio:" in info,
    }


def extract_frame(video: Path, seconds: float, out_png: Path) -> Path:
    _run(["-ss", f"{seconds:.3f}", "-i", str(video), "-frames:v", "1", str(out_png)])
    return out_png


def mean_luma(video: Path) -> float:
    """Average brightness (0-255) sampled at 2 fps. A black take reads about 16."""
    proc = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", str(video), "-vf",
         "fps=2,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    values = [float(v) for v in re.findall(r"YAVG=([\d.]+)", proc.stdout)]
    return sum(values) / len(values) if values else 0.0


def mirror(image: Path, out_png: Path) -> Path:
    """Horizontal flip. For a subject seen side-on, the mirrored frame reads as the view from
    the opposite side, which is how Bullet Time gets its orbit."""
    _run(["-i", str(image), "-vf", "hflip", str(out_png)])
    return out_png


def reverse(video: Path, out: Path) -> Path:
    """Play a clip backward, picture and sound (Rewind renders forward, then flips time)."""
    _run(["-i", str(video), "-vf", "reverse", "-af", "areverse", "-c:v", "libx264", "-crf", "18",
          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    return out


def poster(video: Path, out_jpg: Path, seconds: float = 0.0) -> Path:
    _run(["-ss", f"{seconds:.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "3", str(out_jpg)])
    return out_jpg


def splice(source: Path, effect: Path, seconds: float, out: Path, *, audio_mode: str = "effect") -> Path:
    """Cut `source` at `seconds` and continue with `effect`, whose first frame is
    the frame grabbed at that instant. The effect is scaled to the source size and
    frame rate so the cut is invisible.

    audio_mode "effect": source sound up to the cut, then the effect's own sound.
    audio_mode "original": the source sound runs under the whole result.
    """
    src = probe(source)
    eff = probe(effect)
    width, height = src["width"] // 2 * 2, src["height"] // 2 * 2
    fps = src["fps"] or 24.0
    cut = max(0.0, min(seconds, src["duration"]))
    skip = 1.0 / (eff["fps"] or 24.0)  # drop the effect's first frame: it repeats the cut frame
    total = cut + max(eff["duration"] - skip, 0.0)

    fit = (f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
           f"crop={width}:{height},fps={fps},setsar=1,format=yuv420p")
    audio_fmt = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"

    inputs = ["-i", str(source), "-i", str(effect)]
    if not src["has_audio"]:
        inputs += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    src_audio = "[0:a]" if src["has_audio"] else "[2:a]"

    video_graph = (f"[0:v]trim=end={cut:.4f},setpts=PTS-STARTPTS,{fit}[va];"
                   f"[1:v]trim=start_frame=1,setpts=PTS-STARTPTS,{fit}[vb];")
    if audio_mode == "original":
        graph = (video_graph + "[va][vb]concat=n=2:v=1:a=0[v];"
                 f"{src_audio}{audio_fmt},apad,atrim=end={total:.4f}[a]")
    else:
        effect_audio = f"[1:a]atrim=start={skip:.4f},asetpts=PTS-STARTPTS,{audio_fmt}[ab];" if eff["has_audio"] \
            else f"anullsrc=r=48000:cl=stereo,atrim=end={total - cut:.4f}[ab];"
        graph = (video_graph +
                 f"{src_audio}atrim=end={cut:.4f},asetpts=PTS-STARTPTS,{audio_fmt},apad=whole_dur={cut:.4f}[aa];"
                 + effect_audio +
                 "[va][aa][vb][ab]concat=n=2:v=1:a=1[v][a]")
    _run([*inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
          "-r", f"{fps:g}", "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
          "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)])
    return out
