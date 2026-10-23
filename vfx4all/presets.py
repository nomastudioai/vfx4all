"""Presets are plain JSON files in presets/. Anyone can copy one and make their own."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import PRESETS_DIR, SUBJECTS

REQUIRED = ("id", "name", "category", "description", "modes", "scene_prompt", "effect_prompt")

# Possessive and object pronoun per subject. Templates avoid subject pronouns
# so the verbs agree for "man", "woman" and "person" alike.
PRONOUNS = {"man": ("his", "him"), "woman": ("her", "her"), "person": ("their", "them")}


def load_presets(directory: Path = PRESETS_DIR) -> list[dict[str, Any]]:
    presets = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        missing = [field for field in REQUIRED if field not in data]
        if missing:
            raise ValueError(f"{path.name} is missing {', '.join(missing)}")
        presets.append(data)
    return sorted(presets, key=lambda p: (p.get("order", 99), p["id"]))


def get_preset(preset_id: str) -> dict[str, Any]:
    for preset in load_presets():
        if preset["id"] == preset_id:
            return preset
    raise KeyError(f"Unknown preset: {preset_id}")


def references_sentence(subject: str, count: int) -> str:
    """How a scene prompt introduces the photos. Qwen Image Edit 2511 reads its inputs as image 1,
    image 2..., and keeps identity best when each one is named with its role (round 7b, 22/10/2026)."""
    if count > 1:
        return f"Image 1 and image 2 are two photos of the same {subject}. Use them only as the identity reference."
    return f"Image 1 is a photo of the {subject}. Use it only as the identity reference."


def render(template: str, *, subject: str, aspect_words: str = "16:9 landscape",
           identity_notes: str = "", wardrobe: str = "", references: int = 1) -> str:
    if subject not in SUBJECTS:
        raise ValueError(f"subject must be one of {SUBJECTS}")
    their, them = PRONOUNS[subject]
    notes = identity_notes.strip().rstrip(".")
    values = {
        "subject": subject,
        "their": their,
        "Their": their.capitalize(),
        "them": them,
        "aspect_words": aspect_words,
        "identity_notes": f", including {notes}" if notes else "",
        "wardrobe": wardrobe,
        "references": references_sentence(subject, references),
        # Asking to keep the facial hair of a woman or of a neutral subject invites a beard.
        "facial_hair": ", facial hair" if subject == "man" else "",
    }
    return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), template)


def wardrobe_for(preset: dict[str, Any], subject: str) -> str:
    wardrobe = preset.get("wardrobe") or {}
    return wardrobe.get(subject) or wardrobe.get("person") or "simple dark clothes"


def public_view(preset: dict[str, Any]) -> dict[str, Any]:
    """What the web UI needs to draw a preset card."""
    pid = preset["id"]
    return {
        "id": pid,
        "name": preset["name"],
        "category": preset["category"],
        "icon": preset.get("icon", "sparkles"),
        "description": preset["description"],
        "modes": preset["modes"],
        "experimental": bool(preset.get("experimental")),
        "duration": preset.get("duration", 6),
        "thumb": f"/static/thumbs/{pid}.jpg",
        "preview": f"/static/previews/{pid}.mp4",
        # Optional Comfy Cloud App Mode link: visitors run the preset with their own Comfy account.
        "comfy_app": preset.get("comfy_app") or "",
    }
