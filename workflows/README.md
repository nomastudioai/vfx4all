# Workflows

Every file is a ComfyUI graph in API format, ready for `POST /api/v2/jobs` or the Comfy SDK.
They come from the official Comfy Cloud templates (`image_qwen_image_edit_2511_int8`,
`video_ltx2_5_dfr_i2v`, `video_ltx2_5_i2v` and `video_ltx2_5_flf2v`), flattened and trimmed: the
prompt enhancers and preview nodes were removed and the prompt is wired straight into the text
encoder. Only open-weights models run in them.

`apps/` holds one graph per preset for Comfy Cloud App Mode (photo, scene and effect in a single
graph, built by `tools/build_app_graph.py`).

## scene_qwen_image_edit_2511.json

Builds the first frame of a preset: a new cinematic still with the face of the person in the
reference photos. It is the Qwen Image Edit 2511 template with an empty latent at the scene size
instead of the encoded input, so the photos act as references (through the reference latents of
`TextEncodeQwenImageEditPlus`) and the frame is drawn new. Until 22/10/2026 scenes ran on Qwen
Image 2.1, whose license is non-commercial only; 2511 is Apache 2.0.

| Node | Input | What VFX 4 All sets |
|---|---|---|
| `1` | `image` | Reference photo 1 |
| `16` | `image` | Reference photo 2 (removed, with its scale node `17`, when there is only one) |
| `8` | `prompt` | The preset's `scene_prompt`, rendered |
| `12` | `width`, `height` | 1344x768 for 16:9, 768x1344 for 9:16 |
| `13` | `seed` | Random unless given |
| `15` | | Output image |

Models: `qwen_image_edit_2511_int8_convrot`, `qwen_2.5_vl_7b_fp8_scaled`, `qwen_image_vae`. Same
sampler settings as the template: 40 steps, CFG 4, Euler.

## effect_ltx_2_5_dfr_i2v.json (default)

LTX-2.5 DFR (Diffusion Fidelity Rendering): the production path of LTX. Stage 1 renders at half
resolution together with one detailing keyframe per second; stage 2 upsamples x2 and re-samples
3 steps with a detailing IC-LoRA, using the half-res latent as reference; stage 3 (temporal x2,
48 fps) is optional and off by default.

| Node | Input | What VFX 4 All sets |
|---|---|---|
| `2004` | `image` | The first frame |
| `5953:5508` | `value` | The rendered `effect_prompt` or `generic_prompt` |
| `5953:5509` | `value` | Negative prompt (wired in here; the template leaves it unconnected) |
| `5954` | `aspect_ratio`, `megapixels` | Format; 0.45 MP for Draft, 0.9 MP for HQ (multiple 32) |
| `5953:5918` | `value` | Duration in seconds |
| `5953:5808`, `5953:5843`, `5953:5878` | `noise_seed` | The same seed in the three stages |
| `5953:5729` | `resize_type.multiplier` | Scale of the conditioning image: 1.0 here, 0.25 in the template |
| `5953:5901` | `value` | Temporal x2 stage on or off |
| `4852` | | Output video |

Changes against the Comfy template, all measured in round 4 (16/10/2026, same frame, prompt and
seed):

- **Refine-Details IC-LoRA instead of Pixel-Spatial-Upscaler.** The template's
  `ltx-2.5-22b-ic-lora-pixel-spatial-upscaler-x2-1.0` is not on Comfy Cloud yet (the job fails
  validation; through the MCP it even ends "completed" with no output). Refine-Details is.
- **Conditioning image at full size (1.0) instead of a quarter.** At 0.25 the face inside the
  fire went soft; at 1.0 it stays sharp and recognisable, which the video splice also needs.
- **Prompt enhancer removed**, and the negative prompt connected.
- **Transformer and text encoder in int8, as the template ships them.** Our first version used the
  bf16 transformer (the classic graph is safer in bf16) and the bf16 encoder; with them, round 5
  (17/10/2026) had presets coming back black on all three seeds.
- **Text encoder in int8, not bf16.** With the Refine-Details IC-LoRA, the template's
  `gemma4-12b-with-proj-ltx-2.5-bf16` encoder made some prompts come back fully black on every
  seed (5 presets out of 9 in round 5, 17/10/2026; even the first frame black, audio intact). The
  same takes with `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot`, the encoder of the classic
  graph, came back right on the first seed. An occasional black take on one seed still happens
  (Stone Statue, seed 20261016) and the retry with the next seed covers it.

Against the classic graph below, DFR gives a clearly sharper face, flames with texture on the
clothes and a more real street. It also comes back black now and then, like the classic graph
(1 of 5 takes in round 4), so the black take check and retry stay on. In round 5 failed takes
came in waves that hit the classic graph too, and the same inputs worked an hour later: the
failures look tied to the moment and the cloud machine more than to the graph. The app makes two
DFR attempts and then a third with the classic graph. GPU time per clip:
[PENDING: measure once Comfy Cloud posts the round 4 jobs to the billing feed].

## effect_ltx_2_5_i2v.json (classic, `VFX4ALL_EFFECT_PIPELINE=classic`)

Animates a first frame into the effect shot, with native audio. Faster, softer.

| Node | Input | What VFX 4 All sets |
|---|---|---|
| `395` | `image` | The first frame (scene, user image, or the frame grabbed from a video) |
| `398:376` | `value` | The preset's `effect_prompt` or `generic_prompt`, rendered |
| `403` | `aspect_ratio`, `megapixels`, `multiple` | Format; 0.45 MP (896x512) for Draft, 0.9 MP (1280x704) for HQ, multiple 64 |
| `398:362` | `value` | Duration in seconds (6 for presets, 5 for video splices) |
| `398:339` | `noise_seed` | Random unless given; a black take is retried with the next seed |
| `75` | | Output video |

Models: `ltx-2.5-22b-distilled-transformer-bf16`, `gemma4-12b-with-proj-ltx-2.5`,
`ltx-2.5-video-vae-bf16`, `ltx-2.5-audio-vae-bf16`, `ltx-2.5-latent-spatial-upscaler-x2`.

LTX-2.5 renders in two passes: half resolution first, then a x2 latent upscale. That is why every
output size is a multiple of 64.

Why bf16 and not the int8 build the template ships with: through the Comfy API v2, the int8
transformer came back as a fully black video in 4 of 5 test runs on 16/10/2026, while the bf16
build gave 3 good takes out of 3 with the same image and prompt. The app still checks every take
and retries a black one with the next seed.

## effect_ltx_2_5_flf2v.json (first and last frame)

The Comfy template `video_ltx2_5_flf2v` flattened: one pass at the output size, a guide on the first
frame (`frame_idx` 0) and one on the last (`frame_idx` -1), Euler Ancestral, int8 transformer and
encoder. The prompt enhancer is gone and the negative prompt is ours (the template ships a list
written for another clip). `Engine.effect_flf` can chain extra guides in between and sets the two
guide strengths; Ant Size and Bullet Time run 4 s with the last frame at 1.0.

| Node | Input | What VFX 4 All sets |
|---|---|---|
| `31`, `39` | `image` | First frame, last frame |
| `251:252` | `value` | The rendered `effect_prompt` |
| `251:215`, `251:216` | `value` | Width and height (896x512 Draft, 1280x704 HQ) |
| `251:198` | `value` | Duration in seconds |
| `251:206`, `251:204` | `strength` | First and last frame guide strength |
| `251:196` | `noise_seed` | Seed |
| `68` | | Output video |

## edit_qwen_image_edit_2511.json (last frames)

Qwen Image Edit 2511 int8 at full quality (40 steps, CFG 4, no turbo LoRA), as in the template
`image_qwen_image_edit_2511_int8`. It builds the last frame of first-and-last-frame presets from the
first frame. Qwen Image 2.1 Edit was tried first and kept re-drawing the first frame: asked to make
the person tiny it added a second, small person; asked for a comic it gave an HDR look.

| Node | Input | What VFX 4 All sets |
|---|---|---|
| `1` | `image` | The first frame |
| `8` | `prompt` | The preset's `last_frame_prompt`, rendered |
| `13` | `seed` | Seed |
| `15` | | Output image |
