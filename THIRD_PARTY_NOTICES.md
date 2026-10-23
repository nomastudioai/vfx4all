# Third party notices

The code in this repository is MIT licensed (see [LICENSE](LICENSE)). Everything listed here keeps its
own license or ownership, and the MIT license does not cover it.

## Models

The workflows in `workflows/` do not include any model weights. They load models by name from the
Comfy Cloud catalog (or from your own ComfyUI), and each model is used under its publisher's license.
Read those licenses before you use what VFX 4 All makes for commercial work.

Checked on 19/10/2026 against each model's own card and license text. Licenses change: the
links below are the source of truth, and this summary is not legal advice.

| Used for | Model files | Publisher | License |
|---|---|---|---|
| Effect (every preset) | LTX-2.5 22B distilled transformer (bf16 and int8), video VAE, audio VAE, spatial and temporal x2 latent upscalers ([Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5)) | Lightricks | [LTX-2.x Community License Agreement](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x), with the [LTX Acceptable Use Policy](https://static.lightricks.com/legal/ltx-acceptable-use-policy.pdf) |
| Effect detail pass (DFR) | LTX-2.5 22B IC-LoRA Refine-Details ([Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details)) | Lightricks | LTX-2.x Community License Agreement |
| Effect text encoder | Gemma 4 12B with LTX-2.5 projections, int8 (inside Lightricks/LTX-2.5) | Google DeepMind (Gemma 4), modified and distributed by Lightricks | Gemma 4 is [Apache 2.0](https://ai.google.dev/gemma/docs/gemma_4_license). The model card does not give this modified file a license of its own, so treat it as covered by the LTX-2.x license too |
| Scene from a photo, and the last frames of Ant Size and Comic Panel | Qwen Image Edit 2511, int8 ([Qwen/Qwen-Image-Edit-2511](https://huggingface.co/Qwen/Qwen-Image-Edit-2511), ComfyUI files by Comfy-Org) | Qwen team | Apache 2.0 |
| Scenes and last frames | Qwen Image VAE ([Qwen/Qwen-Image](https://huggingface.co/Qwen/Qwen-Image)) | Qwen team | Apache 2.0 |
| Scene and last frame text encoder | Qwen2.5-VL 7B Instruct, fp8 ([Qwen/Qwen2.5-VL-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct)) | Qwen team | Apache 2.0 |
| Stop Motion, Claymation, Paint World, Anime Shift | LTX 2.3 style LoRAs Cozy Felt, Clay Mation, Fantasy Painterly and Fantasy Anime (Hugging Face user vrgamedevgirl84; the same files on Civitai: [2525862](https://civitai.com/models/2525862), [2526420](https://civitai.com/models/2526420), [2528481](https://civitai.com/models/2528481), [2552450](https://civitai.com/models/2552450)) | vrgamedevgirl | No license file. Civitai permissions: images may be sold and the LoRA may run on paid services; the LoRA and merges of it may not be sold or shared. Base model LTX-2.3 is under the [LTX-2 Community License Agreement](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2) |
| Hologram | LTX 2.3 Cinematic Sci-fi Cyberpunk style LoRA (Hugging Face user vrgamedevgirl84) | vrgamedevgirl | **No license found** on Hugging Face or Civitai |

What this means in practice:

* **The image models are Apache 2.0.** Photo scenes and last frames come from Qwen Image Edit 2511.
  Until 22/10/2026 scenes came from Qwen Image 2.1, whose license allows non-commercial research
  only; results made with versions before 0.2.0 carry that limit.
* **LTX-2.5 is free for entities under USD 10,000,000 in annual revenue**, counted together with
  affiliates. Above that, Lightricks requires a paid Commercial Use Agreement. If you host VFX 4 All
  as a service for other people, the LTX license asks you to put its Section 4 and the Acceptable Use
  Policy into your own terms and to pass on a copy of the license. Keep watermarks, metadata,
  provenance and AI disclosure features in what you publish, and follow the AI labelling laws that
  apply to you.
* **The Hologram LoRA has no published license.** Check with its author before you use Hologram
  results commercially.

## ComfyUI workflow templates

The graphs in `workflows/` (and the App Mode graphs built from them in `workflows/apps/`) are
derived from these templates of [Comfy-Org/workflow_templates](https://github.com/Comfy-Org/workflow_templates):
`image_qwen_image_edit_2511_int8` (scenes and last frames), `video_ltx2_5_dfr_i2v`, `video_ltx2_5_i2v`
and `video_ltx2_5_flf2v`. They are used under this license:

```
MIT License

Copyright (c) 2023-present Comfy Org

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Python packages

Installed by `pip install -r requirements.txt`, not included in this repository. Versions are the
ones pinned in `requirements.txt`; their own dependencies keep their own licenses.

| Package | Version | License |
|---|---|---|
| comfy-sdk | 0.5.0 | MIT |
| fastapi | 0.143.3 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| imageio-ffmpeg | 0.6.0 | BSD-2-Clause |
| starlette (through fastapi) | 1.8.0 | BSD-3-Clause |
| pydantic (through fastapi) | 2.14.1 | MIT |
| httpx (through comfy-sdk, also used by the tests) | 0.28.1 | BSD-3-Clause |

## ffmpeg

All video work (frame grabs, splicing, reversing, the black take check) runs through the ffmpeg
executable that the `imageio-ffmpeg` wheel installs. It is not included in this repository and VFX 4
All only calls it as a separate program. The build the wheel installs on Windows is the gyan.dev
"essentials" build of ffmpeg 7.1, configured with `--enable-gpl --enable-version3`, so that
executable is licensed under the GNU GPL version 3 or later. Other platforms get their own build from
the wheel. Set `VFX4ALL_FFMPEG` to use any other ffmpeg.

## Fonts

The web app serves [Montserrat](https://fonts.google.com/specimen/Montserrat) itself, so pages make no
request to Google: `web/fonts/montserrat-latin.woff2` and `web/fonts/montserrat-latin-ext.woff2`, the
variable font files Google Fonts serves (v31). Montserrat is Copyright 2024 The Montserrat.Git Project
Authors and licensed under the SIL Open Font License 1.1, included as `web/fonts/OFL.txt`. The OFL,
not MIT, covers those files.

## NoMa Studio AI brand

The NoMa Studio AI name, logo (`web/brand/logo-noma.png`, `web/brand/favicon.svg`) and the brand
graphics in `web/brand/` are owned by NoMa Studio AI and are not licensed under MIT. If you fork VFX
4 All, replace them with your own.

## Social network icons

The X, Discord, Instagram, LinkedIn, TikTok, YouTube, Skool and Facebook icons in `web/index.html`
are trademarks of their owners. They are used only to link to NoMa Studio AI's own profiles and are
not licensed under MIT.

## Demo media

The thumbnails in `web/thumbs/`, the preview loops in `web/previews/` and the hero image and video in
`web/media/` were made with VFX 4 All from photos of members of the NoMa Studio AI team. They show
real people, so they are not licensed under MIT: do not reuse them outside this project. Use your
own media when you fork it.
