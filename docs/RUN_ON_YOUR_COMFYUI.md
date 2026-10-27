# Run VFX 4 All on your own ComfyUI or on a Comfy deployment

VFX 4 All talks to the Comfy API v2 through `comfy-sdk`, so three places can run its graphs:

| Where | `COMFY_BASE_URL` in `.env` | `COMFY_API_KEY` | Who pays |
|---|---|---|---|
| Comfy Cloud (the default) | leave it out | your Comfy API key | your Comfy workspace, for the GPU time |
| Your own ComfyUI, through [comfy-api-proxy](https://github.com/Comfy-Org/comfy-api-proxy) | `http://127.0.0.1:8189` | leave it empty | nobody: it runs on your GPU |
| A Comfy Developer Platform deployment | `https://<your-deployment>.run.comfy.app` | the key of the workspace that owns the deployment | that workspace, while the deployment is up |

The top bar of the app says where it runs: "Comfy Cloud ready", "Your ComfyUI ready" or "Your Comfy
deployment ready". Every model is open weights, so the results are the same graphs wherever they run.

## What the graphs need

**ComfyUI:** a recent release. Every node the graphs use ships with ComfyUI itself, the LTX-2.5
keyframe nodes (`LTXV Add Generated Keyframes` and the rest) included, so no custom node pack is
needed. If your ComfyUI is older than the graphs, a job fails with the name of the missing node.

**Model files:** the graphs load them by the names below, so each file must sit in that folder of
`ComfyUI/models/` under exactly that name.

| File | Folder | Used by | Source (repository, file, revision) |
|---|---|---|---|
| `qwen_image_edit_2511_int8_convrot.safetensors` | `diffusion_models/` | scenes, last frames | `Comfy-Org/Qwen-Image-Edit_ComfyUI`, `split_files/diffusion_models/...`, `f68ace85e60b4a02a323e394253731947657b7d2` |
| `qwen_2.5_vl_7b_fp8_scaled.safetensors` | `text_encoders/` | scenes, last frames | `Comfy-Org/Qwen-Image_ComfyUI`, `split_files/text_encoders/...`, `1f12b17be14c89b026c51a91d67c32f84bb047bc` |
| `qwen_image_vae.safetensors` | `vae/` | scenes, last frames | `Comfy-Org/Qwen-Image_ComfyUI`, `split_files/vae/...`, `1f12b17be14c89b026c51a91d67c32f84bb047bc` |
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | `diffusion_models/` | every effect | `Lightricks/LTX-2.5`, `diffusion_models/...`, `49b093a39c19169a8a81721dcc541e07e945232f` |
| `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | `text_encoders/` | every effect | `Lightricks/LTX-2.5`, `text_encoders/...`, same revision |
| `ltx-2.5-video-vae-bf16.safetensors` | `vae/` | every effect | `Lightricks/LTX-2.5`, `vae/...`, same revision |
| `ltx-2.5-audio-vae-bf16.safetensors` | `vae/` | every effect | `Lightricks/LTX-2.5`, `vae/...`, same revision |
| `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` | `latent_upscale_models/` | every effect | `Lightricks/LTX-2.5`, `latent_upscale_models/...`, same revision |
| `ltx-2.5-latent-temporal-upscaler-x2-bf16-1.0.safetensors` | `latent_upscale_models/` | every effect | `Lightricks/LTX-2.5`, `latent_upscale_models/...`, same revision |
| `ltx-2.5-22b-ic-lora-refine-details-1.0.safetensors` | `loras/` | every effect | `Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details`, at the root, `4912c478b35dd96b6cdcc5f7c7ff9d72c2c57929` |
| `ltx-2.5-22b-distilled-transformer-bf16.safetensors` | `diffusion_models/` | only `VFX4ALL_EFFECT_PIPELINE=classic` | `Lightricks/LTX-2.5`, `diffusion_models/...`, same revision |

Five presets add a style LoRA. Their files have other names on Hugging Face, so they are renamed when
you download them:

| File the graph loads | Preset | Source (repository, file, revision) |
|---|---|---|
| `LTX_2.3_Cinematic_Sci-fi-Cyberpunk_Style.safetensors` | Hologram | `vrgamedevgirl84/LTX_2.3_Cinematic_Sci-fi-Cyberpunk_Style_LoRa`, `Cinematic_sci-fi-cyberpunk.safetensors`, `2d2e1796710c62882cba8cea4e51f5100e352c24` |
| `LTX_2.3_Clay_Mation_Style.safetensors` | Claymation | `vrgamedevgirl84/LTX_2.3_Clay_Mation_Style_LoRa`, `Claymation.safetensors`, `bbf7937db81244e7855adadc459ec7f1813b34ac` |
| `LTX2.3_Cozy_Felt_Style.safetensors` | Stop Motion | `vrgamedevgirl84/LTX2.3_Cozy_Felt_Style_LoRa`, `CozyFelt.safetensors`, `3a0b5ec60a63f039c24fc18daa388031a1ee30f4` |
| `LTX_2.3_Fantasy_Anime_Style.safetensors` | Anime Shift | `vrgamedevgirl84/LTX_2.3_Fantasy_Anime_Style_LoRa`, `Fantasy_Anime.safetensors`, `b4853b426fb37c7f4f0c28bf477c98a25aafeba3` |
| `LTX_2.3_Fantasy_Painterly_Style.safetensors` | Paint World | `vrgamedevgirl84/LTX_2.3_Fantasy_Painterly_Style_LoRa`, `Fantasy_Painterly.safetensors`, `a921cc65c53e3b46507165968801a1994f4f4803` |

The two LTX repositories are gated: accept their terms on Hugging Face and run `hf auth login` once.
Read the licenses in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) before you download, the
style LoRAs' in particular.

### Download them

Run this from the ComfyUI folder (the one that holds `models/`). The Comfy-Org repositories keep
their files under `split_files/`, so those land in a scratch folder first and move into place.

```bash
python -m pip install -U huggingface_hub
hf auth login

# LTX-2.5: the repository's folders match ComfyUI's
LTX=49b093a39c19169a8a81721dcc541e07e945232f
for f in diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors \
         text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors \
         vae/ltx-2.5-video-vae-bf16.safetensors vae/ltx-2.5-audio-vae-bf16.safetensors \
         latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors \
         latent_upscale_models/ltx-2.5-latent-temporal-upscaler-x2-bf16-1.0.safetensors; do
  hf download Lightricks/LTX-2.5 "$f" --revision $LTX --local-dir models
done
hf download Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details ltx-2.5-22b-ic-lora-refine-details-1.0.safetensors \
  --revision 4912c478b35dd96b6cdcc5f7c7ff9d72c2c57929 --local-dir models/loras

# Qwen Image Edit 2511 and its text encoder and VAE
hf download Comfy-Org/Qwen-Image-Edit_ComfyUI split_files/diffusion_models/qwen_image_edit_2511_int8_convrot.safetensors \
  --revision f68ace85e60b4a02a323e394253731947657b7d2 --local-dir hf_tmp
hf download Comfy-Org/Qwen-Image_ComfyUI split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors \
  split_files/vae/qwen_image_vae.safetensors --revision 1f12b17be14c89b026c51a91d67c32f84bb047bc --local-dir hf_tmp
mv hf_tmp/split_files/diffusion_models/* models/diffusion_models/
mv hf_tmp/split_files/text_encoders/* models/text_encoders/
mv hf_tmp/split_files/vae/* models/vae/

# The five style LoRAs, under the names the graphs load
hf download vrgamedevgirl84/LTX_2.3_Cinematic_Sci-fi-Cyberpunk_Style_LoRa Cinematic_sci-fi-cyberpunk.safetensors --revision 2d2e1796710c62882cba8cea4e51f5100e352c24 --local-dir hf_tmp
hf download vrgamedevgirl84/LTX_2.3_Clay_Mation_Style_LoRa Claymation.safetensors --revision bbf7937db81244e7855adadc459ec7f1813b34ac --local-dir hf_tmp
hf download vrgamedevgirl84/LTX2.3_Cozy_Felt_Style_LoRa CozyFelt.safetensors --revision 3a0b5ec60a63f039c24fc18daa388031a1ee30f4 --local-dir hf_tmp
hf download vrgamedevgirl84/LTX_2.3_Fantasy_Anime_Style_LoRa Fantasy_Anime.safetensors --revision b4853b426fb37c7f4f0c28bf477c98a25aafeba3 --local-dir hf_tmp
hf download vrgamedevgirl84/LTX_2.3_Fantasy_Painterly_Style_LoRa Fantasy_Painterly.safetensors --revision a921cc65c53e3b46507165968801a1994f4f4803 --local-dir hf_tmp
mv hf_tmp/Cinematic_sci-fi-cyberpunk.safetensors models/loras/LTX_2.3_Cinematic_Sci-fi-Cyberpunk_Style.safetensors
mv hf_tmp/Claymation.safetensors models/loras/LTX_2.3_Clay_Mation_Style.safetensors
mv hf_tmp/CozyFelt.safetensors models/loras/LTX2.3_Cozy_Felt_Style.safetensors
mv hf_tmp/Fantasy_Anime.safetensors models/loras/LTX_2.3_Fantasy_Anime_Style.safetensors
mv hf_tmp/Fantasy_Painterly.safetensors models/loras/LTX_2.3_Fantasy_Painterly_Style.safetensors
```

LTX-2.5 is a 22B model. We render on Comfy Cloud and have not measured how much GPU memory it needs on
one consumer card; start with Draft.

## Your own ComfyUI, through comfy-api-proxy

The proxy puts the Comfy API v2 in front of a ComfyUI you run, so the app needs no change.

1. Start ComfyUI as usual, on `127.0.0.1:8188`.
2. Start the proxy. `--max-upload-mb 500` matches the app's own limit for clips:

   ```bash
   pip install comfy-api-proxy
   comfy-api-proxy --comfyui http://127.0.0.1:8188 --port 8189 --max-upload-mb 500
   ```

3. In `.env`, set `COMFY_BASE_URL=http://127.0.0.1:8189` and leave `COMFY_API_KEY` empty. The proxy
   asks for no key while it stays on `127.0.0.1` without `--token`.
4. Start the app with `python run.py`. The top bar says "Your ComfyUI ready".

The first job loads the models into memory and takes longer than the ones after it. We have run the
app end to end on Comfy Cloud; this path follows the same API contract through the proxy, and we have
not yet timed it on a local GPU.

## A Comfy Developer Platform deployment

A deployment is a ComfyUI of your own on a dedicated cloud GPU. It also runs models and LoRAs that are
not in the Comfy Cloud catalog. Prepare a ComfyUI folder with the files above, then package it with the
Comfy CLI and publish a release:

```bash
pip install comfy-cli
comfy setup --where cloud
cd /path/to/ComfyUI
comfy build init --name vfx4all --models-dir ./models --custom-nodes-dir ./custom_nodes
comfy build status
comfy build push --release --target linux/nvidia
comfy deploy refs compute
```

Create a deployment from that release on the Developer Platform, then set `COMFY_BASE_URL` to its URL
and `COMFY_API_KEY` to the key of the workspace that owns it. A deployment bills for as long as it is
up, so stop or delete it when you finish.

## When a job says something is missing

The app reads ComfyUI's own validation error and names what is missing: "This Comfy server has no
X node" (update ComfyUI) or "This Comfy server does not have the model file X" (download it as above,
into the folder the tables give, then restart ComfyUI).
