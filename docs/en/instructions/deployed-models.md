> English | [简体中文](../../instructions/deployed-models.md)

# Vidance Deployed-Models Manifest

> Last updated: 2026-10-16

All model files live under `/mnt/dataset/zxy/<Model>-ComfyUI/` (mergerFS HDD array), mapped in via ComfyUI's `extra_model_paths.yaml`. Code/config live on the fast sdb SSD; models/output live on the mergerFS HDDs.

---

## 1. Video generation models (ComfyUI instances)

| Model | Capability | Port | GPU | VRAM | Model files | Size | Status |
|-------|-----------|------|-----|------|-------------|------|--------|
| **Wan2.2-TI2V-5B** | T2V + I2V | 8189 | GPU2 | 18G | `wan2.2_ti2v_5B_fp16`(9.4G) + `umt5_xxl_fp8`(6.3G) + `wan2.2_vae`(1.4G) | 17G | Running |
| **MiniMax-H3 ref2va** | Reference image → video + native audio | 8188 | GPU0 | 46G | `minimax_h3_ref2va_int8`(20G) + `qwen3vl_32b_int8`(26G) + `video_vae_fp16`(4.9G) + `audio_vae_fp32`(578M) | 70G | **Running (custom mainstay)** |
| **MiniMax-H3 fl2va** | Pure text → video | 8188 | GPU0 | — | `minimax_h3_fl2va_pruned_int8`(20G) | 20G | Standby (same instance) |
| **HunyuanVideo 13B** | T2V | 8190 | GPU3 | 20G | `hunyuan_video_t2v_720p_bf16`(24G) + `llava_llama3_fp8`(8.5G) + `clip_l`(235M) + `vae`(471M) | 34G | Running (not wired into the pipeline) |
| **SDXL Base 1.0** | T2I | 8191 | — | — | `sd_xl_base_1.0.safetensors`(6.5G) | 6.5G | **Stopped** |
| **FLUX.1-dev fp8** | T2I | 8192 | GPU0 | — | `flux1-dev-fp8`(12G) + `t5xxl_fp8`(4.6G) + `ae`(320M) | 16G | **Stopped** |
| **TripoSplat** | Single image → 3DGS | 8192 | GPU0 | ~4G | `triposplat_fp16`(707M) + `dino_v3_vit_h`(1.6G) + `vae_decoder`(550M) + `flux2-vae`(321M) + `birefnet`(424M) | 3.6G | Shares the FLUX instance |
| **Hunyuan3Dv2 turbo** | Image → mesh reconstruction | 8193 | GPU1 | ~15G | `hunyuan3d-dit-v2-0-turbo.fp16`(4.6G) + `hunyuan3d-vae-v2-0.fp16`(409M) + `hunyuan3d_dinov2_giant`(2.27G) | 7.3G | **Running (v3 M1+M2 verified)** |

### What each model is for

- **Wan2.2-TI2V-5B**: mainstay of auto/quick. 1280×704@24fps, both T2V and I2V (ti2v = text+image to video). auto `--character-mode flux` uses the I2V path (`Wan22ImageToVideoLatent` node, 48ch latent + noise_mask inpainting, first-frame correlation 0.99+).
- **MiniMax-H3 ref2va**: mainstay of custom. 1344×768@24fps + native audio. Injects the reference image at every denoising step to lock character identity; up to 10 reference images, referenced via `<Picture i>` tags. The Qwen3-VL-32B text encoder natively understands Chinese — prompts pass through untranslated. `ref_image_size`: match (fast, ~6min/shot) / max (2048px hi-fi, 2-3x slower).
- **MiniMax-H3 fl2va**: pure text → video (no reference conditioning), shares the ComfyUI instance (8188) with ref2va; currently standby.
- **HunyuanVideo 13B**: backup T2V engine, 720p high quality, but slow and VRAM-hungry; not wired into the pipeline yet. The Chinese tokenizer bug is fixed (`LlamaTokenizerFast` → `PreTrainedTokenizerFast`).
- **SDXL Base 1.0**: T2I backup, planned in the v1 design as a FLUX fallback for character/scene images; not wired in.
- **FLUX.1-dev fp8**: character+scene image generator for auto `--character-mode flux` (1024×1024 character images, 832×480 scene images). **Port 8192 currently has no process; restart it manually to use flux mode**.
- **TripoSplat**: core of the character anchor for auto `--character-mode 3dgs/auto`, single image → 3DGS Gaussian cloud (262K gaussians). Shares the 8192 instance with FLUX (serial, no resource contention); starts/stops with FLUX.
- **Hunyuan3Dv2 turbo**: v3 3D reconstruction engine. Single image → mesh (4-step consistency distillation, ~61s) + multiview → mesh (3 views, ~22s warm), on its own GPU1:8193 instance. The DINOv2-giant image encoder is extracted from the DiT checkpoint (prefix `conditioner.main_image_encoder.model.` stripped). M1 verified: doubao.jpg → 257K-vert GLB; M2 verified: 3 views → 206K-vert GLB (aspect 1.69, main component 63%).

### Model file paths

```
/mnt/dataset/zxy/
├── Wan-ComfyUI/
│   ├── diffusion_models/wan2.2_ti2v_5B_fp16.safetensors    (9.4G)
│   ├── text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors (6.3G)
│   └── vae/wan2.2_vae.safetensors                            (1.4G)
├── MiniMax-H3-ComfyUI/
│   ├── diffusion_models/
│   │   ├── minimax_h3_ref2va_pruned_int8_convrot.safetensors (20G)
│   │   └── minimax_h3_fl2va_pruned_int8_convrot.safetensors  (20G)
│   ├── text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors (26G)
│   └── vae/
│       ├── minimax_h3_video_vae_fp16.safetensors  (4.9G)
│       └── minimax_h3_audio_vae_fp32.safetensors  (578M)
├── HunyuanVideo-ComfyUI/
│   ├── diffusion_models/hunyuan_video_t2v_720p_bf16.safetensors (24G)
│   ├── text_encoders/
│   │   ├── llava_llama3_fp8_scaled.safetensors (8.5G)
│   │   └── clip_l.safetensors                   (235M)
│   └── vae/hunyuan_video_vae_bf16.safetensors   (471M)
├── SDXL-ComfyUI/
│   └── checkpoints/sd_xl_base_1.0.safetensors   (6.5G)
├── FLUX-ComfyUI/
│   ├── diffusion_models/flux1-dev-fp8.safetensors (12G)
│   ├── text_encoders/t5xxl_fp8_e4m3fn.safetensors (4.6G)
│   └── vae/ae.safetensors                         (320M)
└── TripoSplat-ComfyUI/
    ├── diffusion_models/triposplat_fp16.safetensors      (707M)
    ├── clip_vision/dino_v3_vit_h.safetensors             (1.6G)
    ├── vae/
    │   ├── triposplat_vae_decoder_fp16.safetensors       (550M)
    │   └── flux2-vae.safetensors                         (321M)
    └── background_removal/birefnet.safetensors           (424M)

Hunyuan3Dv2 (shares ComfyUI/models/ with Wan):
  diffusion_models/hunyuan3d-dit-v2-0-turbo.fp16.safetensors  (4.6G)
  vae/hunyuan3d-vae-v2-0.fp16.safetensors                     (409M)
  clip_vision/hunyuan3d_dinov2_giant.safetensors              (2.27G, extracted from the DiT)
```

---

## 2. Audio models

| Model | Capability | Port | GPU | VRAM | Size | Status |
|-------|-----------|------|-----|------|------|--------|
| **CosyVoice 2 (0.5B)** | TTS + zero-shot voice cloning | 9880 | GPU2 | 2.5G | 4.4G | Running |
| **faster-whisper large-v3-turbo** | STT speech-to-text | embedded | shared | 1.5G | 1.6G | On demand (`--stt`) |
| **edge-tts** | Online TTS (Microsoft neural voices) | 9880 | CPU | 0 | 0 (online) | Running |

### What each is for

- **CosyVoice 2**: local TTS engine with zero-shot voice cloning. Dubbing mainstay for auto/quick (`cosy-*` voices). Shares GPU2 with Wan (serial, no contention).
- **faster-whisper large-v3-turbo**: STT, int8_float16. With `--stt`, transcribes the final audio into SRT subtitles (the fallback that overrides TTS timestamps). No separate service; loaded in-process at runtime.
- **edge-tts**: Microsoft online TTS, natural voices, zero GPU. Dubbing mainstay for auto/quick (`edge-*` voices, 8 built-in).
- **custom mode uses H3 native audio** — no TTS/STT.

### Model file paths

```
/mnt/dataset/zxy/CosyVoice2-0.5B/
├── llm.pt                              (1.9G)
├── flow.pt                             (430M)
├── flow.cache.pt                       (430M)
├── hift.pt                             (80M)
├── speech_tokenizer_v2.onnx            (474M)
├── speech_tokenizer_v2.batch.onnx      (474M)
├── flow.decoder.estimator.fp32.onnx    (274M)
├── flow.encoder.fp32.zip               (184M)
├── flow.encoder.fp16.zip               (112M)
├── campplus.onnx                       (27M)
└── cosyvoice2.yaml

/mnt/dataset/zxy/hf_cache/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/
└── snapshots/.../model.bin             (1.6G, int8_float16)
```

---

## 3. Frame-interpolation models

| Model | Capability | Location | GPU | Size | Status |
|-------|-----------|----------|-----|------|--------|
| **RIFE v4.26** | Optical-flow interpolation (inter-shot transitions) | ComfyUI `models/frame_interpolation/` | GPU2 | 11M | Running |
| **RIFE v4.26 heavy** | Optical-flow interpolation (high-quality variant) | Same | GPU2 | 11M | Standby |

### What each is for

- **RIFE v4.26**: optical-flow transitions between shots in auto/custom. Extracts first/last frames of adjacent shots → RIFE interpolation (multiplier=8) → 0.375s@24fps transition segment. Controlled by config `rife.enabled`; `--no-rife` disables.
- `rife_v4.26_heavy` is the high-quality variant, currently unused.
- The `slowmo()` per-shot slow-motion method in `rife.py` is implemented but not wired into the pipeline (v2.1 backlog).

```
/mnt/disk_sdb/zxy/ComfyUI/models/frame_interpolation/
├── rife_v4.26.safetensors       (11M)
└── rife_v4.26_heavy.safetensors (11M)
```

---

## 4. Image/video editing models (v16, deployed 2026-10)

| Model | Capability | Location | Size | Status |
|-------|-----------|----------|------|--------|
| **SAM2.1 Hiera** | Segmentation/cutout/background swap/mosaic/inpaint + video bidirectional tracking | `vidance/models/sam2/` (tiny+small) | 325M | On demand (`edit`) |
| **YOLOv8s** | Auto-detect → SAM box prompts (Grounded-SAM) | `vidance/models/yolo/yolov8s.pt` | 22M | On demand (`edit --yolo`) |
| **FLUX.1-Fill-dev fp8** | In-mask generative inpainting / generative background swap | FLUX-ComfyUI (shares 8192) | 12G | On demand (`edit --engine flux`) |
| **Wan2.1 VACE 1.3B fp16** | Reference-image-to-video + video-level generative removal/replacement | Wan-ComfyUI (shares 8189) | 4.1G | On demand (`vace`/`edit video`) |
| **Qwen-Image-Edit 2509 fp8** | Instruction-based image editing (Chinese instructions, no mask needed) | FLUX-ComfyUI (shares 8192) | 20G | On demand (`edit instruct`) |

### What each is for

- **SAM2.1**: the seven image modes of `vidance.py edit` (segment/cutout/replace_bg/mosaic/inpaint/visualize/instruct) + `edit video` bidirectional propagation tracking (colorized multi-object tracks each point independently). Weights in-repo at `models/sam2/` (gitignored); code source at `/mnt/disk_sdb/zxy/sam2-src` (pip -e). On full GPUs it probes card by card (same as v4 FunClip device='auto') and can fall back to CPU.
- **YOLOv8s**: `--yolo` auto-detects classes → SAM box prompts (Grounded-SAM; more accurate than point prompts for large objects), no manual clicking.
- **FLUX Fill**: `edit inpaint/replace_bg --engine flux --prompt "..."` — FLUX generative inpainting inside the mask (v16.x M5); can stack Union ControlNet canny for structure preservation (M6, `--controlnet canny`).
- **Wan2.1 VACE**: `vidance.py vace ref.png "prompt"` reference-image-to-video (480×832@16fps, M7); `edit video` SAM2 tracking + VACE generative video inpaint (op=remove/keep, object removal/background completion).
- **Qwen-Image-Edit 2509**: `edit instruct --prompt "swap the cat for a dog"` instruction-based editing (M8); Chinese instructions work natively; runs on 8192 sharing the FLUX instance.

### Model file paths

```
/mnt/disk_sdb/zxy/vidance/models/
├── sam2/sam2.1_hiera_tiny.pt    (149M)
├── sam2/sam2.1_hiera_small.pt   (176M)
└── yolo/yolov8s.pt              (22M)

/mnt/dataset/zxy/FLUX-ComfyUI/diffusion_models/
├── flux1-fill-dev-fp8.safetensors              (12G)
└── qwen_image_edit_2509_fp8_e4m3fn.safetensors (20G)

/mnt/dataset/zxy/Wan-ComfyUI/diffusion_models/
└── wan2.1_vace_1.3B_fp16.safetensors           (4.1G)
```

---

## 5. RAG embedding models (M5b + M6-R-N)

| Model | Capability | Location | Size | Status |
|-------|-----------|----------|------|--------|
| **BAAI/bge-small-zh-v1.5** | Chinese text embeddings (FAISS vector search) | `/mnt/dataset/zxy/hf_cache/bge-small-zh-v1.5/` | 92M | On demand (runs on CPU) |

### What it's for

- **bge-small-zh-v1.5**: the RAG retrieval foundation. Shared by the standalone `/rag` command and `auto --rag-doc/--rag-novel`. Loaded directly via transformers (CLS pooling + L2 normalization), runs on CPU without a GPU.
- **Plain-document route**: add_document chunked indexing → FAISS retrieval injected into scriptwriting.
- **Novel route** (M6-R-N): split_novel_chapters chapter indexing + character cards extracted from the first 3 chapters (`novel-cards-{md5}.json`); the character card is the single source of appearance injected into scriptwriting.
- Download note: when hf-mirror returns 401 for the new Xet CAS, download directly with `curl ... /resolve/main/...`.

---

## 6. LLM models (remote API, not deployed locally)

| Model | Purpose | Latency | Status |
|-------|---------|---------|--------|
| **deepseek-v4-flash** | Scriptwriting, prompt optimization, LUT style selection, BGM mood selection | Fast | ✅ Free |
| **claude-haiku-4-5** | Multimodal review (per-shot frame extraction + image scoring) | 4s/shot | ✅ Free |
| **claude-sonnet-4-6** | Strict review backup (review_strict) | 534s/shot (too slow) | ✅ Free |

> LLM API: OpenAI-compatible gateway (`llm.base_url`); the key lives in `config/config.local.json` (machine-local override, not in git; `config.json` keeps only the placeholder template)

---

## 7. Procedurally generated assets (non-model)

| Asset | Location | Size | Notes |
|-------|----------|------|-------|
| 3D LUT ×6 | `utils/luts/` | 948K×6 | cinematic/warm/cool/vintage/vivid/soft (numpy-generated by `gen_luts.py`) |
| BGM | Generated at runtime | 0 | numpy synthesis of 5 moods (`music.py`); the `bgm/` custom dir holds real material |

---

## 8. Downloaded but unused

| Model | Location | Size | Notes |
|-------|----------|------|-------|
| Qwen3.6-35B-A3B | `/mnt/dataset/zxy/Qwen3.6-35B-A3B/` | 67G | 26 safetensors shards; not wired into any flow |
| MiniMax-H3 original weights | `/mnt/dataset/zxy/MiniMax-H3/` | 465G | Already converted to int8 ComfyUI format (70G in `MiniMax-H3-ComfyUI/`); originals can be deleted |

---

## 9. GPU & port allocation

| GPU | VRAM | Instances | Ports | Status |
|-----|------|-----------|-------|--------|
| GPU0 | 48G | MiniMax-H3 ref2va | 8188 | Running (custom mainstay, 46G loaded on demand) |
| GPU1 | 48G | Hunyuan3Dv2 turbo | 8193 | Running (~15G on demand + local training jobs) |
| GPU2 | 48G | Wan2.2-5B + RIFE + CosyVoice 2 | 8189 / 9880 | Running (18G + 2.5G + local training jobs) |
| GPU3 | 48G | HunyuanVideo 13B | 8190 | Running (20G on demand + local training jobs) |

- **FLUX.1-dev fp8 (8192) stopped**: auto `--character-mode flux/3dgs/auto` requires restarting 8192 first (TripoSplat shares the FLUX instance)
- **SDXL (8191) stopped**: not wired into the pipeline; restart when needed
- **Hunyuan3Dv2 on its own GPU1:8193**: no longer shares an instance with Wan; 3D reconstruction and video generation can run in parallel
- faster-whisper STT loads on demand, sharing GPU VRAM (no dedicated resident process)
- Training jobs occupy GPU1/2/3 — do not touch
- ⚠️ ComfyUI must NOT be started with `--cuda-device`, or it overrides `CUDA_VISIBLE_DEVICES` (main.py:87)

---

## 10. Subcommand ↔ service dependencies

| Subcommand | Required services | Ports |
|------------|-------------------|-------|
| `auto` (no character) | Wan T2V + TTS | 8189 + 9880 |
| `auto --character-mode flux` | Wan I2V + FLUX + TTS | 8189 + 8192 + 9880 |
| `auto --character-mode 3dgs/auto` | Wan I2V + FLUX + TripoSplat + TTS | 8189 + 8192 + 9880 |
| `auto --rag-doc / --rag-novel` | + bge embedding (CPU) | embedded |
| `custom` | H3 ref2va | 8188 |
| `quick` | Wan T2V + TTS | 8189 + 9880 |
| Any `--stt` | + faster-whisper (GPU) | embedded |
| `edit` (segmentation family) | SAM2.1 (+ YOLOv8s with `--yolo`) | local weights (CPU possible) |
| `edit --engine flux` | FLUX Fill (+ ControlNet) | 8192 |
| `edit instruct` | Qwen-Image-Edit 2509 | 8192 |
| `vace` / `edit video` | Wan2.1 VACE | 8189 |
| `rag` (standalone) | bge embedding (CPU, generates no video) | embedded |
| v3 mesh reconstruction | Hunyuan3Dv2 (ComfyUI 8193) | 8193 |

---

## 11. Deployment logs

Deployment details for each model live under `/mnt/disk_sdb/zxy/`:

| File | Contents |
|------|----------|
| `MiniMax-H3-部署记录.md` | H3 ref2va/fl2va + Qwen3-VL-32B + dual VAE, int8 quantization & conversion |
| `Wan2.2-部署记录.md` | Wan2.2-TI2V-5B + UMT5-XXL + VAE |
| `HunyuanVideo-部署记录.md` | HunyuanVideo 13B + LLaVA-Llama3 + CLIP-L + VAE |
| `SDXL-部署记录.md` | SDXL Base 1.0 |
| `FLUX-部署记录.md` | FLUX.1-dev fp8 + T5-XXL + VAE (incl. TripoSplat co-instance config) |

> Hunyuan3Dv2 turbo has no standalone deployment log; the M1+M2 verification process is in v3-design.md §13. Models were downloaded from the `tencent/Hunyuan3D-2` HuggingFace repo (hf-mirror); DINOv2-giant was extracted from the DiT checkpoint.

> The v16 editing models (SAM2/YOLO/FLUX Fill/VACE/Qwen-Image-Edit) have no standalone deployment logs; deployment & verification are in v16-design.md (weight downloads / environment-pinning trio). The SAM2 code source is installed at `/mnt/disk_sdb/zxy/sam2-src` (pip -e).

> Model files live uniformly under `/mnt/dataset/zxy/<Model>-ComfyUI/` (mergerFS HDDs), mapped into ComfyUI via `extra_model_paths.yaml`.
