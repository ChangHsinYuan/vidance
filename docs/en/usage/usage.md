> English | [简体中文](../../usage/usage.md)

# Vidance User Guide

## Quick Start by Tier (user manual, v21)

Not sure which tier to pick? Run `python core/vidance.py doctor` first — it probes GPU/ports/disk and recommends a tier directly. Install in one command: `bash deploy/install.sh` (probe → pick tier → start services → smoke test; see [docs/en/deploy/README.md](../deploy/README.md)).

| Tier | Your machine | What it can do | First command |
|------|--------------|----------------|---------------|
| `none` | GPU-less server/PC | svg animation + fast marketing line (image crawl), ppt, blender3d, all editing/compositing; LLM/topic selection via remote API, TTS = edge online | `python core/vidance.py svg --concept "a duckling riding a bike"` |
| `flux` | 1× image GPU (16G+) | + FLUX/SDXL image generation (better fast-line quality) | `python core/vidance.py fast "the story of a late-night lighthouse" -n 3` |
| `wan` | 1× video GPU (24G+) | + Wan T2V/I2V: real video generation for auto/quick + CosyVoice local dubbing | `python core/vidance.py auto "sunrise on the snowfield, a little fox" --character "a little red fox"` |
| `h3` | 1× large GPU (40G+) | + MiniMax-H3: custom/h3shot reference-image-injected generation | `python core/vidance.py custom --ref input/doubao.jpg --script input/prompt1.txt` |
| `full` | Multi-GPU | Full feature set (Hunyuan3D/STT/voice cloning, the whole suite) | `python core/vidance.py hot -n 5` |

First-time config: `python core/vidance.py init` (interactive wizard: LLM key/gateway, voice, output dir, cleanup policy; or non-interactive with `--llm-key X --voice cosy-default`). Version: `--version`; health self-check: `curl :8894/api/health`; failure diagnosis: task errors automatically attach 💡 hints (ports/VRAM/external network, naming the exact command), or `python core/diagnose.py "error text"`.

Frontend: `http://127.0.0.1:8894/ui` (or :9400/ui in the container) — three-pane canvas, `/` pops command completion, ⚙ manages models and system (version/disk/cleanup). When the tier is insufficient, CLI/API tell you outright to switch (`VIDANCE_TIER=none|flux|wan|h3|full`).

> Below is the developer-oriented reference for all subcommands.

## Unified Entry

> Unified entry: `python core/vidance.py <subcommand> [args]`
>
> Per-version docs: [usage-v0.md](../../usage/usage-v0.md) (narrated short MVP/T2V/TTS) · [usage-v1.md](../../usage/usage-v1.md) (character anchors/3DGS) · [usage-v2.md](../../usage/usage-v2.md) (RIFE/LUT/BGM/ffmpeg/STT) · [usage-v3.md](../../usage/usage-v3.md) (mesh/asset registry) · [usage-v4.md](../../usage/usage-v4.md) (crawler/queue/voice cloning/fast/hot) · [usage-v6.md](../../usage/usage-v6.md) (prompt multi-turn clarification) · [usage-v7.md](../../usage/usage-v7.md) (frontend WebUI) · [usage-v10.md](../../usage/usage-v10.md) (timeline compositing & effects) · [usage-v-svg.md](../../usage/usage-v-svg.md) (SVG→mp4 pipeline) · [usage-v11.md](../../usage/usage-v11.md) (multi-agent chain orchestration) · [usage-v16.md](../../usage/usage-v16.md) (SAM2 image/video editing + generative editing) · [usage-v17.md](../../usage/usage-v17.md) (session assets/checkpoint resume/RAG/five-dimension templates/embeddings/retry) · [usage-v19.md](../../usage/usage-v19.md) (video-link rework)
>
> Architecture: [hierarchy.md](../../design/hierarchy.md) (method map: video models/non-video models × directing styles) · [v12-modules.md](../../design/v12-modules.md) (three-row orthogonal unified entry) · [v11-design.md](../../design/v11-design.md) (multi-agent layering and agent chains) · [v-t2c.md](../../design/v-t2c.md) (natural language → command translation layer) · [v-svg-pipeline.md](../../design/v-svg-pipeline.md) (SVG pipeline design)

## Documentation Map

| Category | Files | Contents |
|----------|-------|----------|
| **Entry** | usage.md (this file) · [roadmap.md](../../roadmap.md) | Main usage entry · overview and version roadmap (the authoritative status source) |
| **Map/Architecture** | hierarchy.md · v12-modules.md · v11-design.md · [deployed-models.md](../instructions/deployed-models.md) | Method map and v12 pipeline · three-row orthogonal module contracts · deployed-models manifest |
| **Design** | v0 · v1 · v2 · [v2.5](../../design/v2.5-design.md) · v3 · v4 · v5 · v6 · v7 · v8 · v9 · v10 (each `-design.md`) | Per-version design docs (the planning-stage v8/v9 contain the original designs later absorbed by v16/v14 (formerly v14/v11)) |
| **Special designs** | v-t2c.md · v-svg-pipeline.md | Natural language → command · SVG pipeline |
| **Per-version usage** | usage-v0/v1/v2/v3/v4/v6/v7/v10 · usage-v11.md · usage-v-svg.md · [usage-v16.md](../../usage/usage-v16.md) · [usage-v17.md](../../usage/usage-v17.md) | Per-version small-tool quick reference |
| **Command library** | [instructions/commands.json](../../instructions/commands.json) (22 commands) · [instructions/compose-commands.md](../instructions/compose-commands.md) + .json (43 editing instructions) | Data source for the frontend `/help`, retraining data source for t2c |
| **Samples** | [example/](../../example/) | Timeline JSON examples (compose demo) |
| **History** | archive/roadmap_origin.md | Original planning draft (archived, reference only) |

## Subcommands

| Subcommand | Input | Engine | Role | Post | Use case |
|------------|-------|--------|------|------|----------|
| `auto` | One Chinese sentence | Wan T2V/I2V + FLUX | Text description → FLUX images | Optional | Quick films, automatic scriptwriting |
| `custom` | Reference images + pre-written script | H3 ref2va | Three-view images injected directly | Optional | Precise shot control, multiple characters |
| `quick` | One Chinese sentence | Wan T2V | None | None | Fastest film, no character |
| `concat` | Multiple video files | — | — | — | Concatenate existing clips |
| `fast` (v4) | One sentence | Skips video models | Image crawl/FLUX + zoompan camera moves | Common post | Quick marketing-line films, see usage-v4.md M6 |
| `hot` | None (crawls live trending topics) | Same as fast | Crawler auto-selects the topic | Common post | One-click trending film, see usage-v4.md M6 |
| `svg` (v13) | Concept or SVG file | No GPU (pure CPU) | LLM generates animated SVG | TTS/subtitles (S5) | Second-level turnaround, see usage-v-svg.md |
| `ppt` (v15) | Concept or deck.html | No GPU (pure CPU) | LLM plans pages/charts | TTS narration/subtitles/LUT/BGM | Slideshow films + PDF/PNG delivery |
| `blender3d` (v13) | Concept or scene.json | bpy EEVEE (host GPU/container CPU) | LLM plans the 3D scene | TTS narration/subtitles | 3D-look short film (templates title3d/shapes/bars3d) |
| `poster` (v22) | One sentence | FLUX images + SAM2 cutout (GPU tiers; auto-degrades to a gradient plate without FLUX) | LLM plans the poster JSON (title/tagline/creature zones) | PIL typographic composite (chromatic aberration/glow/rainy-night vibe) | 2:3 portrait promo poster jpg (terminal card/URL/QR optional) |
| `edit` (v16) | Image/video path | SAM2+YOLO+FLUX Fill/VACE/Qwen-Edit (GPU tiers) | SAM2 segmentation + inpaint/propagation/colorized multi-object/YOLO auto + generative inpaint/background swap/ref-to-video/instruction editing | — | Matting/background swap/mosaic/watermark removal/video bidirectional tracking/box prompts + generative editing (v16.x), see [v16-design.md](../../design/v16-design.md) |
| `vace` (v16.x) | Reference image + prompt | Wan2.1 VACE (wan 8189) | Reference image → subject-consistent video | — | Character reference image → 5s video (480×832@16fps) |
| `rework` (v19) | Video link | yt-dlp+STT+multimodal+LLM (no new models) | Download → understand → rewrite narration → re-dub | Visual rewrite 0-5/LUT/BGM/subtitles | Video-link rework (M1 promised Bilibili), see usage-v19.md |
| `compose` (v10) | Timeline JSON | — | — | Timeline compositing & effects | Backend CLI editing, see usage-v10.md |
| `h3shot` | Prompt + reference image | H3 ref2va | Whole-prompt single shot | Native audio direct | Whole-prompt single shot (`--ref` conditional injection) |
| `ask` (v6) | One sentence | — | LLM asks clarifying questions | — | Multi-turn completion of the concept, see usage-v6.md |
| `make` (v12) | Concept + director/generator choice | Any combination | By the director layer | Common post | **Unified entry**: --director llm/manual/scout × --generator wan/fast/svg/h3, see v12-modules.md |
| `agent` (v11) | Agent name or chain JSON | By chain step | Three-layer agent orchestration | — | Multi-agent list/run/chain, see usage-v11.md |

---

## auto — Concept Auto-Generation

LLM auto-scriptwriting → character anchor generation → per-shot generation → review → post-processing composite.

```bash
# Basic (no character, pure T2V + dubbing + post)
python core/vidance.py auto "a cat dancing on the moon"

# With a character (default auto mode: tries 3DGS first, degrades to flux if the review fails)
python core/vidance.py auto "deep-sea adventure" --character "a blue jellyfish"

# flux mode (FLUX generates character+scene per shot; most stable quality)
python core/vidance.py auto "sunrise over snow mountains" --character "a little red fox" --character-mode flux

# Full features (RIFE transitions + LUT color + BGM + STT subtitles)
python core/vidance.py auto "sunrise over snow mountains: a little fox's adventure" \
    --character "a little red fox" --character-mode flux \
    --lut cool --bgm calm --stt

# Disable some post-processing
python core/vidance.py auto "concept" --character "character" --no-rife --no-color --no-bgm

# Long-form mode (--duration 60 → dynamic ~15 shots; defaults to 2-5 shots when unset)
python core/vidance.py auto "deep-sea adventure" --character "a blue jellyfish" --character-mode flux --duration 60

# Global slow motion (2x frame multiplication on every shot)
python core/vidance.py auto "concept" --character "character" --slowmo 2
```

### auto parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `concept` (positional) | Video concept (Chinese) | Required |
| `--character` | Character description (Chinese) | None (pure T2V) |
| `--character-mode` | `auto`/`3dgs`/`flux` | `auto` |
| `--voice` | TTS voice (e.g. `edge-moe`) | config default |
| `--duration` | Target total duration (seconds); adjusts shot count dynamically | None (default 2-5 shots) |
| `--slowmo` | Global slow-motion frame multiplier (2 = 2x slow) | None (LLM annotates) |

---

## custom — Reference Images + Script Generation

With a pre-written shot script + character three-view reference images, H3 ref2va generates video with native audio in one step.

```bash
# Basic (two-character story)
python core/vidance.py custom \
    --ref input/doubao.jpg --ref input/naiwa.jpg \
    --script input/prompt1.txt

# With post-processing
python core/vidance.py custom \
    --ref input/doubao.jpg --ref input/naiwa.jpg \
    --script input/prompt1.txt \
    --lut cinematic --bgm dramatic --stt

# High-fidelity mode (2048px reference images, better character identity, 2-3x slower)
python core/vidance.py custom \
    --ref input/doubao.jpg \
    --script input/prompt1.txt \
    --ref-image-size max

# Explicit output path
python core/vidance.py custom \
    --ref input/doubao.jpg --ref input/naiwa.jpg \
    --script input/prompt1.txt \
    -o my_video.mp4
```

### custom parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--ref` (repeatable) | Character reference image path | Required |
| `--script` | Shot script file path | Required |
| `--ref-image-size` | `match` (fast) / `max` (2048px hi-fi) | `match` |

### Shot script format

```
[global scene setting line]
[global character setting line]
【01A｜title｜~3s】
generation prompt:
[shot description (multi-line allowed)]
【01B｜title｜~2.5s】
generation prompt:
[shot description]
【editing & sound...】 (ignored)
```

- `约X秒` (~X seconds) supports decimals (e.g. `约2.5秒` = ~2.5s)
- Each H3 shot needs ≥5 frames; shorter durations are auto-aligned to the 17k+5 grid
- `<Picture i>` tags reference the i-th reference image automatically

---

## quick — Pure T2V

No character anchor, no post-processing — the fastest film.

```bash
python core/vidance.py quick "a cat dancing on the moon"

# Pick a voice
python core/vidance.py quick "concept" --voice edge-xiaoxiao
```

---

## concat — Multi-Video Concatenation

Joins several video files into one, with three transition modes.

```bash
# Hard cuts (ffmpeg stream copy, fastest)
python core/vidance.py concat clip1.mp4 clip2.mp4 clip3.mp4 -o merged.mp4 --transition cut

# RIFE optical-flow transitions (needs the GPU2 ComfyUI 8189 online)
python core/vidance.py concat clip1.mp4 clip2.mp4 clip3.mp4 -o merged.mp4 --transition rife

# Crossfade
python core/vidance.py concat clip1.mp4 clip2.mp4 -o merged.mp4 --transition crossfade --crossfade-duration 0.5
```

### concat parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `videos` (positional) | List of video files to join | Required |
| `--transition` | `cut`/`rife`/`crossfade` | `cut` |
| `--crossfade-duration` | Crossfade length (seconds) | `0.5` |
| `-o/--output` | Output path | `merged.mp4` |

---

## Shared Post-Processing Parameters (auto + custom)

| Parameter | Description |
|-----------|-------------|
| `--lut <style>` | LUT style: `cinematic`/`warm`/`cool`/`vintage`/`vivid`/`soft` |
| `--no-color` | Disable LUT color grading |
| `--bgm <mood>` | BGM mood: `calm`/`uplifting`/`mysterious`/`dramatic`/`playful` |
| `--no-bgm` | Disable background music |
| `--no-rife` | Disable RIFE inter-shot transitions |
| `--stt` | faster-whisper STT subtitle alignment |
| `-o/--output` | Output path (relative paths resolve into output_dir) |

Without `--lut`/`--bgm`, the LLM picks a style based on the concept. `--no-rife`/`--no-color`/`--no-bgm` override `enabled: true` in config.

---

## Output

- No `-o`: outputs automatically to `{output_dir}/{custom_}TIMESTAMP/final.mp4`
- `-o` relative: resolves automatically under `{output_dir}/`
- `-o` absolute: written exactly as given
- Every task writes `meta.json` (script/prompts/seeds/timestamps and other complete metadata)

---

## TTS Voices

| Prefix | Engine | Examples |
|--------|--------|----------|
| `edge-*` | edge-tts (Microsoft online) | `edge-moe` moe high voice / `edge-xiaoxiao` Xiaoxiao / `edge-yunjian` Yunjian |
| `cosy-*` | CosyVoice (local GPU) | `cosy-default` / `cosy-cross` |
| `cosy-<custom>` | CosyVoice clone | Drop material into `voices/<name>/prompt.wav` to auto-register |

> custom mode uses H3 native audio and does not use TTS. `--voice` only affects auto/quick.

---

## Service Dependencies

Before running, make sure the matching ComfyUI instance is up:

| Subcommand | Required services | Ports |
|------------|-------------------|-------|
| auto | Wan (T2V/I2V) + FLUX/TripoSplat | 8189 + 8192 |
| auto (3dgs/auto mode) | additionally TripoSplat | 8192 |
| custom | H3 ref2va | 8188 |
| quick | Wan T2V | 8189 |
| fast/hot | TTS 9880 (FLUX 8192 optional backfill; crawl/placeholder images have fallbacks) | 9880 |
| svg | None (pure CPU; TTS optional) | — |
| agent/make | Depends on chain steps (`GET /api/agents` shows GPU markers) | — |
| All (with `--voice`) | TTS service | 9880 |
| All (with `--stt`) | faster-whisper (GPU) | embedded |

---

## Backward Compatibility

The old entries still work but are not recommended:

```bash
python core/pipeline.py ...      # equivalent to auto
python core/custom_gen.py ...    # equivalent to custom (no post-processing params)
```

---

## Full Examples

### Example 1: auto fully automatic with a character

```bash
python core/vidance.py auto "a red-cloaked boy on the snowfield" \
    --character "a short-haired boy in a red cloak" \
    --character-mode flux \
    --voice edge-moe \
    --lut cool --bgm calm \
    --stt
```

Flow: LLM scriptwriting → FLUX character image → per-shot FLUX scene image + Wan I2V + TTS → review → RIFE transitions → LUT color → BGM ducking → STT subtitles

### Example 2: custom two-character story

```bash
python core/vidance.py custom \
    --ref input/doubao.jpg --ref input/naiwa.jpg \
    --script input/prompt1.txt \
    --ref-image-size match \
    --lut cinematic --bgm dramatic
```

Flow: parse script → LLM looks at reference images to describe characters → H3 ref2va per-shot generation (native audio) → RIFE transitions → LUT color → BGM ducking

### Example 3: quick lightning film

```bash
python core/vidance.py quick "a cat dancing on the moon"
```

Flow: LLM scriptwriting → Wan T2V → TTS dubbing → ffmpeg composite (no color, no BGM, no transitions)
