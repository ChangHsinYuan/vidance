> English | [简体中文](./CHANGELOG.md)

# Changelog

Semantic versioning (semver): `MAJOR.MINOR.PATCH` — MAJOR = capability generation (a set of v-series milestones), MINOR = a single v milestone, PATCH = fixes and touch-ups. The current version lives in the root `VERSION`; query it with `python core/vidance.py --version`.

## 1.1.0 (2026-11-17)

v22 promo poster generation (the poster line):

- **`poster` subcommand**: one concept → LLM plans a poster JSON (title/English subtitle/Chinese tagline/plate prompt/creature zones) → FLUX plate (2:3, multi-seed retry) + creature portraits → Grounded-SAM cutout (YOLO box prompts; falls back to luminance keying automatically) → parameterized PIL compositing → `output/poster*/poster.jpg`; when FLUX is entirely unavailable, degrades to a purple-night gradient plate and still produces a poster
- **Typography system** (ported from the README promo poster v8 field-tested parameters): title chromatic aberration + glow, five-zone creature anchors (back-center hologram / mid ghost-fade / front foreground), purple wash to kill the sticker look, bottom gradient mask, rain streaks, vignette + grain; optional terminal card command / dual URLs / QR
- **Four channels**: CLI `poster` (one-shot + `--plan` render mode) + `generator.poster` agent + `POST /api/tool/poster` (async job) + thin utils shells
- **Tests**: tests/test_poster.py, 31 items (no GPU) + GPU E2E, film in 116.7s, blind review 8/10

## 1.0.0 (2026-11-05)

First semantic version tag, corresponding to the v21 delivery-form closure. **The full v0→v21 capability generation is catalogued** (historical renumbering in parentheses; see docs/roadmap.md for details):

### Core generation
- **auto/quick/custom/h3shot** (v0-v3): Chinese concept → LLM scriptwriting → Wan T2V/I2V → dual-engine TTS → review → ffmpeg compositing; three character-anchor paths (3DGS/mesh/flux) + Hunyuan3Dv2 asset-library reuse
- **Long-form** (v2/v2.1): RIFE optical-flow transitions and slow motion, parallel prefetch, LUT/BGM/STT post-processing, `--duration` dynamic shot count
- **One-shot single take** (v18, formerly v14): chained I2V with last-frame feedback + LLM camera-move chain + seam MAE assertion; VACE first/last-frame-driven inter-shot transitions
- **Hierarchical consistency** (v18): scene anchors + wardrobe system + event-line world.json

### Lightweight model-free lines (run without a GPU)
- **fast/hot marketing line** (v4, formerly v13): image crawl + validation + Ken Burns + TTS, automatic trending-topic selection
- **SVG animation** (v13): LLM generates SVG → headless browser frame-by-frame → mp4
- **PPT** (v15): deck.html → mp4/PDF/PNG multi-format delivery
- **Blender 3D** (v13): bpy EEVEE template scenes → short film

### Editing & rework
- **SAM2 editing** (v16, formerly v19): segmentation/cutout/background swap/mosaic/inpaint/colorized multi-object/YOLO auto/video bidirectional tracking
- **Generative editing** (v16.x): FLUX Fill inpainting, ControlNet canny, VACE reference-image-to-video, Qwen-Image-Edit instruction-based editing
- **Video-link rework** (v19, formerly v16): download → understand → rewrite narration (anti-parroting assertion) → re-dub → visual rewrite; burned-subtitle removal (ProPainter)
- **Timeline compositing** (v10): keyframes/masks/sticker tracks, backend CLI editing

### Platform & orchestration
- **Multi-agent** (v11, formerly v13): D/G/P/V four layers, 28 agents + chain orchestration + blackboard ledger
- **Frontend WebUI** (v7): :8894/ui three-pane canvas, task cards, `/` command completion, ⚙ model/system settings
- **API** (v4/v9): FastAPI :8894 task queue (SQLite persistence), tool dispatch, OpenAPI
- **t2c natural language → command**: fine-tuned mt5-small translation layer
- **Session asset layer** (v17, formerly v12): buffer/@references/checkpoint resume with sha256/RAG/five-dimension templates/script breakdown novel2video

### Quality & honesty
- **Live generation audit** (v20, formerly v21): WS latent2rgb preview frames → qwen3.8 rough pass → interrupt on fail to cut losses and swap seed; real-time verdict cards in the UI (field data shows the rough pass only blocks major collapses, semantic detail is left to the final review — a proven division of labor)
- **Review system**: 5-dimension full review + light parallel review + review_ensemble multi-vote

### Delivery form (v21)
- **Resource-probing doctor**: `vidance doctor` + `/api/doctor` — GPU/ports/conda/disk/external network → five-tier recommendation (none/flux/wan/h3/full)
- **Tiered deployment**: same codebase + `VIDANCE_TIER` + config/tiers overrides; Docker five-tier compose profiles
- **One-line install** `deploy/install.sh`: probe → pick tier → start containers (or conda setup_env) → smoke self-test
- **User-facing details**: `vidance init` config wizard, failure self-diagnosis hints (ports/VRAM/external-network, naming the exact command), output-dir cleanup (protects running tasks), VERSION + `/api/version`

## 0.x (pre-2026-09 prologue)

v0 MVP (T2V+TTS+compositing) → v1 character anchor (3DGS) → renumbering, v11-v21 chartered. Original planning draft: `docs/archive/roadmap_origin.md`.
