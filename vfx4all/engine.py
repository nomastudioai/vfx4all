"""The two Comfy Cloud calls VFX 4 All makes, through the official Comfy SDK.

1. scene(): Qwen Image 2.1 Edit builds a cinematic first frame with the face of
   the person in the reference photos.
2. effect(): LTX-2.5 image to video animates that frame into the VFX shot, with
   native audio. By default through the DFR graph (detailing keyframes and a
   spatial x2 pass with the Refine-Details IC-LoRA); the classic two pass graph
   stays as a fallback.

Both workflows are API-format graphs in workflows/. Only open-weights models run
in them, so no partner API credits are spent: Comfy Cloud bills GPU time only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from comfy_sdk import Comfy, Progress, StatusChange

from .config import (DFR_WORKFLOW, EDIT_WORKFLOW, EFFECT_WORKFLOW, FLF_WORKFLOW, SCENE_WORKFLOW, SIZE_MULTIPLE,
                     api_key, effect_pipeline)

ProgressFn = Callable[[float | None, str], None]

# Node ids inside the graphs. See workflows/README.md.
SCENE_REF_1, SCENE_REF_2 = "470", "475"
SCENE_TEXT, SCENE_LATENT, SCENE_SAMPLER, SCENE_SAVE = "459:474", "459:456", "459:458", "461"
EFFECT_IMAGE, EFFECT_PROMPT, EFFECT_SIZE = "395", "398:376", "403"
EFFECT_DURATION, EFFECT_SEED, EFFECT_SAVE = "398:362", "398:339", "75"
DFR_IMAGE, DFR_PROMPT, DFR_SIZE, DFR_DURATION, DFR_SAVE = "2004", "5953:5508", "5954", "5953:5918", "4852"
DFR_SEEDS = ("5953:5808", "5953:5843", "5953:5878")  # one noise per stage, same seed
DFR_TRANSFORMER, CLASSIC_TRANSFORMER, FLF_TRANSFORMER, STYLE_LORA = "5953:5742", "398:384", "251:230", "9001"


def with_style_lora(graph: dict, lora: dict | None, transformer: str = DFR_TRANSFORMER) -> dict:
    """Put a preset's own LoRA right after the transformer, so it acts on every stage
    (and under the detailing IC-LoRA of stage 2). Only LoRAs in the Comfy Cloud catalog."""
    if not lora or not lora.get("name"):
        return graph
    graph[STYLE_LORA] = {"class_type": "LoraLoaderModelOnly",
                         "inputs": {"model": [transformer, 0], "lora_name": lora["name"],
                                    "strength_model": float(lora.get("strength", 1.0))}}
    for node_id, node in graph.items():
        if node_id != STYLE_LORA and node["inputs"].get("model") == [transformer, 0]:
            node["inputs"]["model"] = [STYLE_LORA, 0]
    return graph


class MissingApiKey(RuntimeError):
    pass


def _graph(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def edit_graph(with_face: bool = False) -> dict:
    """Qwen Image Edit 2511 graph; with a face it takes a second reference image (node 16)."""
    graph = _graph(EDIT_WORKFLOW)
    if with_face:
        graph["16"] = {"class_type": "LoadImage", "inputs": {"image": "IMAGE_2"}}
        graph["17"] = {"class_type": "FluxKontextImageScale", "inputs": {"image": ["16", 0]}}
        for node in ("8", "9"):
            graph[node]["inputs"]["image2"] = ["17", 0]
    return graph


def mid_node(i: int) -> str:
    """LoadImage node id of the i-th middle guide in `flf_graph`."""
    return f"95{i}0"


def flf_graph(mid_frames: list[int] | None = None, lora: dict | None = None) -> dict:
    """First and last frame graph, with one extra LTXVAddGuide per middle frame index, chained
    between the first frame guide (251:206) and the last frame guide (251:204)."""
    graph = with_style_lora(_graph(FLF_WORKFLOW), lora, FLF_TRANSFORMER)
    previous = "251:206"
    for i, frame_idx in enumerate(mid_frames or []):
        load, resize, prep, guide = mid_node(i), f"95{i}1", f"95{i}2", f"95{i}3"
        graph[load] = {"class_type": "LoadImage", "inputs": {"image": f"MID_{i}"}}
        graph[resize] = {"class_type": "ResizeImageMaskNode", "inputs": {
            "input": [load, 0], "resize_type": "scale dimensions", "resize_type.crop": "center",
            "resize_type.height": ["251:216", 0], "resize_type.width": ["251:215", 0], "scale_method": "lanczos"}}
        graph[prep] = {"class_type": "LTXVPreprocess", "inputs": {"image": [resize, 0], "img_compression": 18}}
        graph[guide] = {"class_type": "LTXVAddGuide", "inputs": {
            "frame_idx": int(frame_idx), "image": [prep, 0], "latent": [previous, 2], "negative": [previous, 1],
            "positive": [previous, 0], "strength": 0.7, "vae": ["251:229", 0]}}
        previous = guide
    for key, slot in (("latent", 2), ("negative", 1), ("positive", 0)):
        graph["251:204"]["inputs"][key] = [previous, slot]
    return graph


class Engine:
    """One Engine per API key. Generations bill the Comfy Cloud workspace that
    owns the key: the server's own key from .env, or a key the user brings."""

    def __init__(self, key: str | None = None) -> None:
        self._key = (key or "").strip()
        self._client: Comfy | None = None

    @property
    def client(self) -> Comfy:
        if self._client is None:
            key = self._key or api_key()
            if not key:
                raise MissingApiKey("Add your Comfy API key in Settings, or set COMFY_API_KEY in .env.")
            self._client = Comfy(api_key=key)
        return self._client

    def scene(self, refs: list[Path], prompt: str, size: tuple[int, int], seed: int,
              dest: Path, progress: ProgressFn) -> Path:
        wf = self.client.workflows.from_json(_graph(SCENE_WORKFLOW))
        first = self.client.assets.from_file(refs[0])
        second = self.client.assets.from_file(refs[1]) if len(refs) > 1 else first
        wf.set_input(SCENE_REF_1, "image", first)
        wf.set_input(SCENE_REF_2, "image", second)
        wf.set_input(SCENE_TEXT, "prompt", prompt)
        wf.set_input(SCENE_LATENT, "width", size[0])
        wf.set_input(SCENE_LATENT, "height", size[1])
        wf.set_input(SCENE_SAMPLER, "seed", seed)
        return self._run(wf, SCENE_SAVE, dest, progress)

    def edit_frame(self, image: Path, prompt: str, seed: int, dest: Path, progress: ProgressFn,
                   face: Path | None = None) -> Path:
        """Qwen Image Edit 2511 over one frame; `face` is an optional second image for identity."""
        wf = self.client.workflows.from_json(edit_graph(face is not None))
        wf.set_input("1", "image", self.client.assets.from_file(image))
        if face is not None:
            wf.set_input("16", "image", self.client.assets.from_file(face))
        wf.set_input("8", "prompt", prompt)
        wf.set_input("13", "seed", seed)
        return self._run(wf, "15", dest, progress)

    def effect_flf(self, first: Path, last: Path, prompt: str, size: tuple[int, int], duration: int,
                   seed: int, dest: Path, progress: ProgressFn, mids: list[tuple[Path, int]] | None = None,
                   lora: dict | None = None, strengths: tuple[float, float] = (0.7, 0.7)) -> Path:
        """LTX-2.5 first and last frame (one pass, as the Comfy template). `mids` adds guide frames
        in between, as (image, frame index), for effects LTX would otherwise wander off in."""
        graph = flf_graph([frame_idx for _, frame_idx in mids or []], lora)
        wf = self.client.workflows.from_json(graph)
        wf.set_input("31", "image", self.client.assets.from_file(first))
        wf.set_input("39", "image", self.client.assets.from_file(last))
        for i, (image, _) in enumerate(mids or []):
            wf.set_input(mid_node(i), "image", self.client.assets.from_file(image))
        wf.set_input("251:252", "value", prompt)
        wf.set_input("251:215", "value", int(size[0]))
        wf.set_input("251:216", "value", int(size[1]))
        wf.set_input("251:198", "value", int(duration))
        wf.set_input("251:196", "noise_seed", seed)
        wf.set_input("251:206", "strength", float(strengths[0]))
        wf.set_input("251:204", "strength", float(strengths[1]))
        return self._run(wf, "68", dest, progress)

    def effect(self, image: Path, prompt: str, selector: str, megapixels: float, duration: int,
               seed: int, dest: Path, progress: ProgressFn, lora: dict | None = None,
               pipeline: str | None = None) -> Path:
        if (pipeline or effect_pipeline()) == "dfr":
            wf = self.client.workflows.from_json(with_style_lora(_graph(DFR_WORKFLOW), lora))
            wf.set_input(DFR_IMAGE, "image", self.client.assets.from_file(image))
            wf.set_input(DFR_PROMPT, "value", prompt)
            wf.set_input(DFR_SIZE, "aspect_ratio", selector)
            wf.set_input(DFR_SIZE, "megapixels", megapixels)
            wf.set_input(DFR_DURATION, "value", float(duration))
            for node in DFR_SEEDS:
                wf.set_input(node, "noise_seed", seed)
            return self._run(wf, DFR_SAVE, dest, progress)
        wf = self.client.workflows.from_json(with_style_lora(_graph(EFFECT_WORKFLOW), lora, CLASSIC_TRANSFORMER))
        wf.set_input(EFFECT_IMAGE, "image", self.client.assets.from_file(image))
        wf.set_input(EFFECT_PROMPT, "value", prompt)
        wf.set_input(EFFECT_SIZE, "aspect_ratio", selector)
        wf.set_input(EFFECT_SIZE, "megapixels", megapixels)
        wf.set_input(EFFECT_SIZE, "multiple", SIZE_MULTIPLE)
        wf.set_input(EFFECT_DURATION, "value", int(duration))
        wf.set_input(EFFECT_SEED, "noise_seed", seed)
        return self._run(wf, EFFECT_SAVE, dest, progress)

    def _run(self, wf, output_node: str, dest: Path, progress: ProgressFn) -> Path:
        progress(0.02, "Uploading inputs and queueing on Comfy Cloud")
        job = self.client.submit(wf)
        progress(0.05, "Queued on Comfy Cloud")
        try:
            for event in job.events():
                if isinstance(event, Progress):
                    progress(max(0.05, min(event.value, 0.98)), event.message or "Generating")
                elif isinstance(event, StatusChange):
                    progress(None, f"Comfy Cloud: {event.status}")
        except Exception:  # the live stream is best effort; polling below is authoritative
            pass
        job.result()
        outputs = job.get_outputs(output_node)
        if not outputs:
            raise RuntimeError(f"Job {job.id} finished without an output on node {output_node}")
        output = outputs[0]
        suffix = Path(output.name).suffix or ".bin"
        path = dest.with_suffix(suffix)
        output.to_file(path)
        progress(1.0, "Downloaded")
        return path
