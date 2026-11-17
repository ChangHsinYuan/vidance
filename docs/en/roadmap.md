> English | [简体中文](../roadmap.md)

# Vidance Overview & Roadmap

> A video-generation agent system: opencode acts as the "producer" orchestrating local image/video/3D/speech engines, turning a one-sentence concept into a narrated short film.
> The original planning draft is at `archive/roadmap_origin.md`. **Implemented**: v0-v10 + t2c + v11 multi-agent (formerly v13) + v12 three-row-orthogonal M1-M2 (formerly v17) + v13 lightweight model-free four lines: marketing/SVG/PPT/Blender 3D (formerly v15) + v15 LLM-generated PPT (formerly v20) + v16 video processing & editing (formerly v19) + v17 open-source integration closure (formerly v12) + v18 long-form quality closure (formerly v14, M1-M4 all green 2026-10-31) + v19 video-link rework closure (formerly v16, 2026-11-02) + v21 delivery-form closure 1.0.0 (formerly v18, M0-M4 all green 2026-11-05: doctor/five tiers/install.sh/init wizard/diagnostic hints/cleanup/VERSION+CHANGELOG+user manual+SKILL demos) + v14 social media ✅ (formerly v11, 🔗 delivered in a teammate's repo 2026-11-05, not merged into this repo); **To develop**: nothing (all milestones closed). (2026-09-26 renumbering: finished blocks moved forward, unfinished blocks moved back; 2026-09-30 added v19-v21; 2026-10-01 second renumbering: PPT/video editing moved forward after v14, live generation audit inserted before delivery form; 2026-10-01 evening third pass: v13/v15 closed ✅ (the v15 entry moved into the implemented area, to-develop entries moved forward), v14 handed to a teammate — numbers in parentheses are the originals, v12/v14/v16 refer to the earliest numbering, v18-v21 refer to the 2026-09-30 numbering, to make commit cross-referencing easier; 2026-10-30 fourth pass: v17 open-source integration closed ✅ (M1-M7 all green, entry marked in place); 2026-11-02 fifth pass: v19 rework closed ✅; 2026-11-04 sixth pass: v20 live generation audit closed ✅ (entry moved into the implemented area); 2026-11-05 seventh pass: v21 delivery form closed 1.0.0 ✅ (M0-M4 all green, entry moved into the implemented area); 2026-11-05 eighth pass: v14 social media delivered in the teammate's repo ✅ (not merged here, entry marked as closed))

## 1. Positioning

Not an API service — a video production system where **"the agent is the director"**:

| Role | Component | Notes |
|------|-----------|-------|
| Producer | opencode (director agent) | Runs the whole show, steps in at key decision points |
| Screenwriter/planner | LLM (deepseek-v4-flash) | Concept → shot script → prompt optimization |
| Camera/actors | Image & video generation models | SDXL / FLUX / Wan / HunyuanVideo / MiniMax-H3 |
| Character anchor | 3D reconstruction | TripoSplat(3DGS) / Hunyuan3D(mesh) — no cross-shot drift |
| Voice actor | Dual TTS engines | edge-tts (natural, online) + CosyVoice 2 (local cloning) |
| Reviewer | Multimodal LLM (qwen3.8-chat mainstay) | Scores frame by frame, closed-loop redo |
| Editor | ffmpeg + moviepy + the OpenCut approach | Concat/subtitles/scoring/color/transitions/effects |

**Core innovation**: 3DGS as the "character anchor" — each shot's starting frame is rendered by RenderSplat from the same 3DGS at the shot's angle, then fed to I2V, avoiding cross-shot character drift.

---

## 2. Three-layer architecture

```
┌──────────────────────────────────────────────────────────┐
│  Product    v0 ✅ narrated short → v1 ✅ character consistency → v2 ✅ long-form │
│             v3 ✅ 2D→3D→novel views → v4 ✅ marketing pipeline          │
│             v5 ✅ editing effects → v6 ✅ prompt clarification → v7 ✅ frontend WebUI │
├──────────────────────────────────────────────────────────┤
│  Orchestration  opencode agent runtime                    │
│           director + subagents(reviewer/asset/scout) + skills │
│           core/ Python pipeline skeleton (hybrid mode)    │
├──────────────────────────────────────────────────────────┤
│  Engines    T2I: SDXL / FLUX                              │
│             T2V: Wan2.2 / HunyuanVideo / MiniMax-H3       │
│             3D:  TripoSplat(3DGS) / Hunyuan3D(mesh) / RenderSplat │
│             Audio: edge-tts(online, natural) + CosyVoice 2(local clone, 9880) │
│                  faster-whisper (STT fallback, large-v3-turbo, 9880)     │
│             Post: ffmpeg + moviepy + RIFE(interpolation) + LUT(color) + BGM(score) │
│             LLM: USTC API (scriptwriting + multimodal review)             │
└──────────────────────────────────────────────────────────┘
```

**Hybrid mode**: deterministic flows (invoking engines/concat/post-processing) are hard-coded in `core/`; creative and judgment decisions (scriptwriting/prompt optimization/review/redo) go to the agent.

---

## 3. Model & engine manifest

### 3.1 Video generation models (ComfyUI instances)

| Model | Capability | GPU | Port | VRAM | Status |
|-------|-----------|-----|------|------|--------|
| **Wan2.2-TI2V-5B** | T2V + I2V | GPU2 | 8189 | 18G | Running |
| **MiniMax-H3 ref2va** | Reference image → video + native audio | GPU0 | 8188 | 46G | Running (custom mainstay) |
| **HunyuanVideo 13B** | T2V | GPU3 | 8190 | 20G | Running (backup) |
| **FLUX.1-dev fp8** | T2I | GPU3 | 8192 | 16G | Running (character/scene images) |
| **TripoSplat** | Single image → 3DGS | GPU3 | 8192 | ~4G | With FLUX |
| **Hunyuan3Dv2 turbo** | Image → mesh reconstruction | GPU1 | 8193 | ~15G | Running (v3) |
| **SDXL Base 1.0** | T2I | — | 8191 | — | Stopped (not wired in) |

- Random seed per shot (avoids ComfyUI cache hits)
- ⚠️ ComfyUI must NOT be started with `--cuda-device`, or it overrides `CUDA_VISIBLE_DEVICES` (main.py:87)
- Models load on demand: startup takes only a few hundred MB; the first workflow run fills VRAM

### 3.2 Audio models

| Model | Capability | Port | GPU | Status |
|-------|-----------|------|-----|--------|
| **CosyVoice 2 (0.5B)** | TTS + zero-shot voice cloning | 9880 | GPU2 | Running (default voice switched to cosy-default) |
| **faster-whisper large-v3-turbo** | STT speech-to-text | embedded | shared | On demand (`--stt`) |
| **edge-tts** | Online TTS (Microsoft neural voices) | 9880 | CPU | Running (needs external network, occasional jitter) |

- Dual TTS engines in one wrapper (`utils/tts_server.py`): edge-* goes to edge-tts, cosy-* to CosyVoice
- **The default voice was switched from edge-moe to cosy-default** (edge's online calls occasionally hit Connection timeouts, causing "subtitles without speech")
- TTS failure fallback chain: retry the target voice 3 times → real local cosy-default voice → silent audio

### 3.3 Interpolation / post-processing

| Component | Capability | Location | Notes |
|-----------|-----------|----------|-------|
| **RIFE v4.26** | Optical-flow interpolation (transitions + slowmo) | ComfyUI | Running |
| **3D LUT ×6** | Color grading | `utils/luts/` | cinematic/warm/cool/vintage/vivid/soft |
| **BGM** | Scoring | `bgm/` | incompetech CC BY real material (calm/uplifting/mysterious/dramatic/playful/epic) + ducking |

### 3.4 LLMs (remote API, not deployed locally)

| Model | Purpose |
|-------|---------|
| deepseek-v4-flash | Scriptwriting, prompt optimization, LUT/BGM selection, effect selection, completeness assessment |
| qwen3.8-chat | Multimodal review + image-relevance checks (mainstay, supports vision) |

> USTC API: `https://api.llm.ustc.edu.cn/v1`, key stored in `config/config.json`

---
## 4. Version roadmap

### v0 — Narrated short MVP ✅ Done

**Goal**: get "concept → narrated short" working end to end.
**Status**: end-to-end verified 2026-09-07. Concept "a cat dancing on the moon" → 13.3s film (3 shots, review 7/7/7). Dual TTS engines online.

```
concept → [LLM scriptwriting → shot list] → [Wan T2V per shot] → [TTS dubbing] → [multimodal review + redo ≤2]
        → [ffmpeg concat + subtitles + transitions] → final.mp4 + meta.json
```
**Detailed design**: [v0-design.md](../design/v0-design.md)

---

### v1 — Character consistency ✅ Done (incl. v1.1)

**Goal**: the same character does not drift across shots.
**Status**: full chain passed 2026-09-08. v1.1: character-mode switch (auto/3dgs/flux); flux mode bypasses the 3DGS bottleneck (I2V correlation 0.993-0.998); 3DGS pose fix (PCA alignment + grounded compositing, review_character score 2→7); Wan22ImageToVideoLatent (48ch + noise_mask).
**Bottleneck**: 3DGS consistency still limited; flux side/back views may distort.
**Detailed design**: [v1-design.md](../design/v1-design.md)

---

### v2 — Long-form + full post ✅ Done (v2.1 backlog wired in)

**Goal**: films longer than a single generation cap + complete post.
**Status**: 2026-09-09 M1-M5 done. RIFE transitions + parallel prefetch + LUT color + BGM ducking + STT subtitles all pass. v2.1: `--duration N`, `--slowmo N`, per-shot transitions, `concat` subcommand.
**Detailed design**: [v2-design.md](../design/v2-design.md)

---

### v2.5 — Multi-entry architecture + H3 engine ✅ Done

**Goal**: refactor the entry and engine layers — unified CLI with multiple subcommands + the new H3 ref2va engine + modular post-processing.
**Status**: passed 2026-09-11 (13 scripts / 32 shots / ~96s film, two characters consistent across shots).
- Unified CLI `vidance.py` (auto/custom/quick), PostProcessor extracted as shared
- H3 ref2va: `<Picture i>` references multiple characters, 1344×768 + native audio, Chinese prompts pass through untranslated
**Detailed design**: [v2.5-design.md](../design/v2.5-design.md)

---

### v3 — 2D→3D→novel views ✅ Done (M0-M7, M8 skipped)

**Goal**: reconstruct 3D from 2D content and generate video from angles that were never captured.
**Progress**: M0 headless rendering ✅ / M1 Hunyuan3Dv2 mesh reconstruction ✅ / M2 multiview ✅ / M3 mesh_render wrapper ✅ / M4 scene anchors ✅ / M5 dual character paths ✅ / M6 asset registry ✅ / M7 end-to-end integration ✅ / M8 skipped.
**Detailed design**: [v3-design.md](../design/v3-design.md)

---

### v4 — Marketing pipeline ✅ Done (M1-M6; no auto-publishing — humans pick and upload manually)

**Goal**: batch-automated content production.
**Progress**: M1 crawler + topic selection ✅ / M2 async task queue ✅ / M3 production-grade voice cloning ✅ / M4 FunClip smart clipping ✅ / M5 asset crawling ✅ / M6 fast marketing line (fast/hot) ✅.
**Detailed design**: [v4-design.md](../design/v4-design.md)

---

### v5 — Editing effects pack ✅ Done (M1-M4)

**Goal**: richer in-shot/inter-shot editing expressiveness.
**Progress**: M1 effects library (8 kinds) ✅ / M2 xfade transitions (30+) ✅ / M3 LLM auto-selection ✅ / M4 end-to-end ✅.
**Detailed design**: [v5-design.md](../design/v5-design.md)

---

### v6 — Prompt multi-turn clarification ✅ Done (M1-M4)

**Goal**: bounce incomplete prompts and clarify requirements through multi-turn dialogue.
**Progress**: M1 completeness assessment (6 dimensions) ✅ / M2 dialogue state machine ✅ / M3 CLI `ask` ✅ / M4 three API endpoints ✅. Fix: only COMPLETE when all 6 dimensions are present; each round asks everything in batch and merges into one reply.
**Detailed design**: [v6-design.md](../design/v6-design.md), [usage-v6.md](../usage/usage-v6.md)

---

### v7 — Frontend agent WebUI ✅ Code done (browser rendering unconfirmed)

**Goal**: a Doubao-style conversational agent WebUI — left function sidebar + top canvas + bottom/right send box; `/` slash commands invoke existing tools.
**Progress**: M1 backend endpoints (video/options/tools/tool dispatch/ui) ✅ / M2 chat + `/` completion ✅ / M3 canvas (task polling + video cards) ✅ / M4 ask+scout wiring ✅.
**15 commands**: auto/fast/hot/ask/clip/scout/voices/luts/moods/video/tasks/status/trends/clean/help.
**Detailed design**: [v7-design.md](../design/v7-design.md), [usage-v7.md](../usage/usage-v7.md)

---

### v8 — Frontend enhancements (initially done)

**Detailed design**: [v8-design.md](../design/v8-design.md)

Goal: a more usable UI.

Progress:
1. A Doubao/Zhixiang-style sidebar conversational minimalist UI
2. ComfyUI jump links, log output, custom configuration

(That's about as far as I want to take this goal — our philosophy is SaaS, software as a service: the main interface should be as minimal as possible; anyone wanting something pro can jump straight into ComfyUI.)

The following is reference only.

**Goal**: upgrade v7's single-page chat UI into a full director's workbench (still zero-npm self-contained first).

**Scope**:
- Asset library panel: visual management of characters/scenes/props with drag-in references (backed by v3 `asset_registry`)
- Storyboard preview panel: nine-up candidate angles + keyframe editing
- Task progress visualization: live status of each pipeline step (reusing the v7 log panel)
- Timeline editing sketch: shot arrangement, transitions, audio tracks (**display + command submission only; editing logic lives in the backend**)
- ComfyUI canvas: direct jump (done) or per-instance selection menu

**Milestones**: M1 asset library panel → M2 storyboard preview → M3 progress visualization → M4 timeline display

**References**: BigBanana's grid director workbench, Toonflow's storyboard sheet, v7's existing three-pane layout.

---

### v9 — API standardization (initially done)

**Detailed design**: [v9-design.md](../design/v9-design.md)

As noted in v8, this is mostly configured already; we rarely need it day to day, so it can be consolidated later. It doesn't feel like a core feature, so it can wait until the end.

(That's about as far as I want to take this goal.)

The following is reference only.

**Goal**: expose a standardized RESTful API so third parties/LLMs can programmatically call all of Vidance's capabilities.

**Scope**:
- Multi-vendor adapter layer: unified text/image/video/tts interface protocols; adding a provider means writing one adapter
- Independent image/video switching: frontend/API select T2I and I2V/T2V models separately
- Automatic model-capability discovery: query `/v1/models` and auto-tag t2i/i2v/t2v
- Usage stats & rate limiting: call count/cost tracking + concurrency cap (Semaphore)
- API endpoint standardization: tasks/tools/scout/clone/clip/dialog with unified OpenAPI docs

**Milestones**: M1 vendor adapter layer → M2 capability discovery → M3 usage stats → M4 OpenAPI docs

**References**: Toonflow `data/vendor/`, ViMax `tools/protocols.py` + Semaphore; v7's existing `/api/tool/{name}` unified dispatch.

---

### v10 — Compositing & effects (the OpenCut approach, backend CLI) (✅ M1-M8 all done 2026-09-25)

**Detailed design**: [v10-design.md](../design/v10-design.md)

**Goal**: make "concat/edit/effects" into **backend-callable commands** (no frontend) so an LLM can orchestrate them directly.

**Borrowing OpenCut's** (open-source CapCut alternative) core timeline model: **track → clip → trim/split → transition → effects/keyframes → export**. We only take its "backend editing primitives" idea, implemented with ffmpeg, without importing its frontend.

**Scope** (`utils/compose.py` or extending `utils/effects.py`, CLI + `/api/tool`):
- Timeline data model: JSON describing track/clip (source file, in/out points, timeline position, layer)
- Concat command: sequential multi-clip concat (hard cut/xfade/RIFE), mixed video+audio+image tracks
- Trim/split: cut by timecode, remove segments, speed change, muting
- Transitions: reuse v5's 30+ xfades
- Effects: reuse v5's 8 in-shot effects + keyframe-driven (opacity/scale/position)
- Overlays: picture-in-picture, text/watermark layers, audio mixing tracks
- Export: uniform yuv420p h264

**Milestones**: M1 timeline JSON model + concatenation → M2 trim/split/rate control → M3 transitions + effects integration → M4 CLI/API exposure + LLM natural language → timeline JSON

**Status**: M1-M8 all complete (M5-M8 on 2026-09-25). `utils/compose.py` (timeline JSON model + main-track xfade concatenation + trim/rate + 8-effect chain + picture-in-picture/text overlays + multi-audio-track amix/ducking); `vidance.py compose` CLI + `/api/tool/compose`; verified with `output/compose_fx_demo.mp4` (4-segment effects main track + 3 transitions + 3 text overlays + picture-in-picture + BGM ducking). **M5 keyframes** (x/y/scale/opacity/rotation expression animation + linear/ease-in-out, shared by all three tracks), **M6 masks** (circle/rounded/rect/image + feather, geq+alphamerge), **M7 sticker track** (PNG loop fill / GIF loop), **M8 split** (`--at` multiple cut points, `--precise` frame-level) all passed real-run verification. Also built the **compose command library** `docs/instructions/compose-commands.{md,json}` (36 entries, shown in the frontend `/help`, for SFT); full effects demo video `output/output/20260924_compose_demo/v10_effects_demo.mp4`. LLM natural language → timeline JSON (`llm.timeline_from_text`) still pending. See [usage-v10.md](../usage/usage-v10.md) for usage.

**Reference**: OpenCut (timeline model), BigBanana CutOS (rough cut), v5 effects.py, v2 `concat` subcommand.

---

### t2c — Natural Language → Command Translation Layer (✅ Integrated 2026-09-24)

**Goal**: Let users drive Vidance with spoken Chinese instead of memorizing slash commands. Overall it is a self-built **agent_loop**: tool = Vidance's own commands; the text→command translator = **a self-trained fine-tuned mt5-small model** (not a general-purpose LLM).

**Chain**: `/api/chat` (LLM judges intent: chitchat answered directly / creation returns `[[VIDEO:concept]]`) → v6 dialog multi-turn clarification → `POST /api/t2c` (`translate(text)` in `utils/t2c_server.py`) → command → frontend displays it + ▶ executes.

**Scope**:
- Model `t2c/model` (fine-tuned mt5-small, runs on CPU); inference wrapper `utils/t2c_server.py` (in-process singleton + optional HTTP :9881)
- Backend `POST /api/t2c`; frontend `t2cTranslate`/`runT2CCmd` (after dialog COMPLETE, shows "→ smart-translate into a command")
- Test directly on the web at `:8894/ui`; CLI: `python utils/t2c_server.py '帮我auto生成城市夜景'` → `python core/vidance.py auto "城市夜景"`

**Known limitations**: The current model only covers the (old) command distribution from its training data, occasionally drifting on fast/quick etc. **Plan**: once all commands (incl. v10 editing) are in place, **retrain** using `docs/instructions/*.json` as the data source for full coverage.

**Detailed design**: [v-t2c.md](../design/v-t2c.md)

---

### v11 — Multi-agent system (formerly v13) (✅ M0-M4 all done, 2026-09-26)

**Detailed design**: [v11-design.md](../design/v11-design.md) (formerly v13-design.md, kept via git mv for history)

(✅ M0-M4 all done, 2026-09-26)

**Goal (final wording)**: Physical layering D/G/P/V + thin-wrapper Agents + blackboard + chain orchestration, without changing existing business logic.

**Landed form** (different from the original "six-Agent big refactor" plan; executed per the thin-wrapper approach decided on 2026-09-26):
- **Physical layering**: `agents/{director,generator,post,audit,common}/`, each layer's `tools/` holds the 27 implementation modules migrated from utils/ (all original `utils/` paths kept as thin-shell forwarders, so old imports/CLIs are zero-breakage); `core/` (CLI+api+scheduler = decision-layer host) and the `core/tts_server startup chain` untouched
- **Agent contract (thin wrapper)**: `agents/base.py` — `@register(name, layer, desc, inputs, needs_gpu)` + `TaskResult{ok, artifacts, trace, score, error}` + `run_agent()` (timing/exception fallback/blackboard persistence); each layer's `agents.py` wraps existing capabilities into 28 Agents (D×6: scriptwrite/scout/select_lut/select_bgm/select_effects/**brain**; G×4: svg/fast/wan_t2v/**artist**; P×9: tts/compose/lut/bgm/subtitle_burn/stt/fx/transition/**voice**; V×5: review_shot/review_character/relevance/describe_character/review_ensemble)
- **Blackboard**: `agents/blackboard.py` `agent_runs` table (task_id/agent/layer/ok/score/artifacts_json/error/duration), reusing `output/tasks.sqlite`, the unified data source for dashboard/trace
- **chain runner**: `agents/runtime.py` `run_chain(steps, ctx)`, `${ctx.key}` references the previous step's artifacts (whole references keep types / inline substitution becomes strings); artifacts written back under dual keys (`as.artifact` + bare artifact); optional steps continue on failure
- **ensemble review**: `audit.review_ensemble` multi-model voting infrastructure, default single vote `models=['qwen3.8-chat']`, scores normalized 0-1, unanimous pass
- **Unified entry**: CLI `python core/vidance.py agent {list|run|chain}`; API `GET /api/agents`, `POST /api/agents/{name}/run`, `POST /api/agents/chain`, `GET /api/agents/board`, `GET /api/tasks/{id}/trace`
- **scheduler orchestration**: `TaskSubmit.mode='chain'` + `chain/ctx` fields → in-process `run_chain`, artifacts written back to task.output, trace via `/api/tasks/{id}/trace`

**Verification**: import identity of the 27 modules on old/new paths + 7 core modules + shell CLI (compose/llm/stt) + end-to-end split; a three-step LLM chain (scriptwriter → select LUT → review, score=2); scheduler chain task completed + blackboard persisted.

**v11.1 frontend visualization (2026-09-26)**: `/arch` command (`tool_dispatch` + `ui renderArch()` layered colored cards, 24 Agents lit up from the runtime registry); chain task cards embed a trace timeline (polling `/api/tasks/{id}/trace`, `#step layer` badge + ✓/✗ + score + duration); `/agent list|run|chain` commands identical across CLI/API/UI.

**v11.2 closing the loop (2026-09-26)**: pipeline review-retry wired into `review_ensemble` (config `review.ensemble` switch, default off, falls back to single vote on failure); GPU Agents registered `h3shot/splat/mesh` + `post.pip` picture-in-picture (28 total; splat verified producing PLY, pip verified producing video); `run_agent` bootstraps load_all.

**v11.3 consolidation (2026-09-26)**: output directories unified via `default_out()` (`output/agent_{ts}_{name}/`, eliminating stray writes to cwd/tmp); UI task tab bar (cumulative/persistent/detail overlay with logs and trace, board popup player unified with final-video cards); model-panel connectivity lights + custom API failover (health via `/api/model-providers/health`, candidate rotation via `POST /api/model/chat`).

**Follow-ups (v11.x backlog)**: /ui chain DAG view, h3shot long-run on real cards, social notification (formerly v11, now v14) gateway wired to the agent API, chain parallel branches / checkpoint resume.

---

### v12 — Three-row orthogonal modularization (formerly v17) (🔄 M1-M2 done 2026-09-26, see [v12-modules.md](../design/v12-modules.md))

**Goal**: Director layer (manual/LLM/trending/dialog) × generator layer (H3/Wan/crawled-img-to-img/SVG/rework) × post layer (dubbing/subtitles/compositing/color+music/effects/timeline) fully decoupled into three rows; any permutation composes a complete pipeline, with exactly one implementation per stage, no redundancy.

**Milestones**:
- **M1 ✅**: `core/narration.py` (Narrator: say with a three-level fallback chain / silence / srt); fastline `_tts_segment`/`_gen_silence`/`_build_srt`/`srt_time`/`_video_duration` and svg_pipeline `_tts_seg`/`_silence`/`_srt_time`/`_probe_duration` all converted to thin-shell forwarders (~80 duplicated lines removed); SVG S5 regression passed
- M2 `vidance.py make --director --generator` unified entry (existing subcommands become aliases)
- M3 `utils/director.py` merges the three scriptwriter/narration prompt sets (pipeline/fastline/svg_llm) into one schema
- M4 generator contract unified; v19 rework plugs in as G5

---

### v13 — Lightweight (GPU-free first) (formerly v15) (✅ all four model-free lines done; model acceleration deferred as needed)

**Detailed design**: [v-svg-pipeline.md](../design/v-svg-pipeline.md), [usage-v-svg.md](../usage/usage-v-svg.md)

**Goal**: Reduce/eliminate local GPU dependency; pure API should also be able to run.

**Scope**:
- Pure API mode: all generation tasks can switch to cloud APIs (SiliconFlow etc.), fully independent of local GPUs (hooks into the v9 model-provider system) (🎯 follow-up)
- Pipeline lightweighting: GPU-free processing. **Four model-free video lines (✅ all in place)**:
  1. **Marketing-account pipeline (existing)**: v4/v5 image gen/crawling → zoompan camera moves → TTS → editing, zero video models, already usable
  2. **LLM-generated SVG → rendered video (✅ S1-S5 implemented 2026-09-24/26)**: LLM produces self-contained SVG with CSS/SMIL animations → headless browser frame-by-frame rendering → ffmpeg stitches frames → mp4. **Pure CPU, seconds-level, crisp vector graphics**, suited to infographics/text animation/data visualization/explainer shorts. Landed in `utils/svg_llm.py` (S1 concept→SVG + S5 plan_narration) + `utils/svg_pipeline.py` (S2 single frame/S3 frame extraction/S4 stitch mp4/**S5 SvgLine voiced pipeline**: LLM narration → per-segment TTS (edge→cosy→silence fallback) → per-segment SVG render → subtitle burn-in → crossfade concat → optional LUT/BGM), CLI `vidance.py svg --concept "…" [--voice voice -n 3 | --say "line1" --say "line2"]`; `/api/tool/svg` silent-sync / voiced-async (svg_* jobs reuse h3shot polling). Verified with `output/svg_e2e/s1.mp4` (dual audio+video streams). Depends on Playwright+Chromium (installed)
     - Key design: **deterministic frame-by-frame** (uses the Web Animations API to set animation `currentTime=t` then pause before screenshot, instead of wall-clock `wait_for_timeout`), guaranteeing precise frame rates with no jitter
     - Rendering backends: Playwright/Chromium (needs install) or `resvg`/`cairosvg` (static frames only); `node` is ready for a puppeteer route
     - Optional: LLM directly outputs SVG code + duration/resolution → one command to video; can later hook into the v9 model-provider system
  3. **LLM-generated PPT → rendered video (✅ v15 implemented 2026-10-01, see §v15)**: LLM plans a structured deck JSON → Python template renders HTML slides → page-by-page rendering → xfade concat → mp4/PDF/PNG multi-format. Pure CPU, `ppt_llm.py` + `ppt_pipeline.py`
  4. **Blender 3D rendering (🔄 simple version implemented 2026-10-01)**: LLM plans a 3D scene JSON (templates title3d/shapes/bars3d + color scheme + objects text/cube/sphere/torus etc. + materials basic/metal/emission/glass + keyframes spin/pop + camera dolly/pan/orbit) → bpy in-process build (bpy 5.0.1 wheel, Python 3.11) → EEVEE frame-by-frame rendering (host GPU CUDA ~156ms/frame@720p, container CPU ~2.5s/frame) → ffmpeg stitches frames → TTS narration → mp4. Landed in `agents/generator/tools/blender_llm.py` (plan_scene/_norm_scene) + `blender_pipeline.py` (bpy_build/render_frames/BlenderLine), CLI `vidance.py blender3d "topic" --duration 6 --voice cosy-default`, agent `generator.blender3d`, API `/api/tool/blender3d` (b3d_* jobs reuse h3shot polling). Verified: host 5-6s clip in 38-58s end-to-end (blender3d_20261001_191116/191913/192947/193101), container 5s clip in ~6.5 min (blender3d_20261001_114559). Dependencies: pip bpy (374MB; container also needs apt libsm6/libxext6 etc. X libraries)
- Model-level lightweighting (with-model acceleration route, 🎯 deferred as needed, does not block the v13 close): small models for preview/drafts, large models for final rendering; large-model **quantization** (INT8/FP8/GPTQ/AWQ) / **distillation** into smaller models / **other inference acceleration** (vLLM, continuous batching, KV cache optimization) introduced as needed
- On-demand loading: each step initializes on demand, no preloading of all models
- Docker lightweight deployment: separate CPU services (API/frontend/scheduler) from GPU services (generation)
- Local ONNX small models: semantic embedding/classification etc. replacing large-model calls

**Milestones**: M1 pure API mode → M2 on-demand loading + CPU post-processing → M3 draft/final dual tier → M4 Docker split deployment

**Reference**: BigBanana Docker Compose, Toonflow ONNX, v9 model-provider system.

### v15 — LLM-generated PPT (lightweight extension: v13's sister piece) (formerly v20, 🔄 M1-M4 done 2026-10-01)

**Goal**: v13 already validated the pure-CPU route "LLM produces structured declarative artifacts (SVG) → headless browser deterministic rendering → mp4"; v15 extends it to **PPT/slides** — LLM generates HTML slides → rendered to images/video, zero GPU, seconds-level, crisp vectors.

**Scope**:
- **LLM-generated HTML slides**: concept/outline → LLM produces self-contained HTML slides with CSS animations (reusing v13 svg_llm's prompt-engineering experience: layout/color/typography/motion constraints + output code only); fixed 16:9 resolution, reveal.js or pure CSS (lighter)
- **Rendering pipeline**: reuses v13 svg_pipeline's Playwright/Chromium deterministic frame-by-frame (`currentTime=t` + pause screenshot) — inter-slide transitions (fade/slide) + in-slide motion rendered frame by frame → mp4 short video; or export PDF/images (PPT delivery form)
- **Data visualization**: common PPT charts (bar/line/pie/flow) → LLM directly generates SVG charts (data-driven, crisp vectors) — can pull data from trending topics/data sources (v4 crawler) to auto-generate "data explainer" shorts/PPTs
- **Two delivery forms**: `vidance.py ppt "<outline>" -o deck.html` (HTML slides, plays directly in browser) + `vidance.py ppt "<outline>" --video` (rendered into a voiced mp4, with TTS narration = same as v13 S5)
- **Agent-ization**: `generator.ppt` thin wrapper (needs_gpu=False), chainable: `{"agent":"generator.ppt","with":{"concept":"quarterly summary","n":5,"voice":"edge-moe"}}`
- **Template system**: common PPT layouts (title/TOC/text+image/data/closing) generated by LLM per layout, unified style (global color/font constraints)

**Milestones**: M1 LLM→HTML slides→render mp4 (single page) ✅ → M2 multi-page + transitions + TTS narration ✅ → M3 data-viz charts ✅ → M4 PDF/PNG export + agent-ization ✅ (all done 2026-10-01: `agents/generator/tools/ppt_llm.py` (plan_deck planning JSON + template rendering + svg_chart bar/line/pie) + `ppt_pipeline.py` (PptLine multi-format: deck.html/PDF/PNG/mp4 voiced, xfade transitions between pages, TTS narration + subtitles + LUT/BGM reusing v10/v12) + CLI `ppt` subcommand + `generator.ppt` agent + API `/api/tool/ppt` async job + config task_prefixes `ppt`; end-to-end verification: LLM planned 4 pages incl. a bar-chart page, 42.9s video (117.8s), CLI --say 19s, agent 8.96s, API host 75s, container 80s — all passed).

**Reference**: v13 svg_pipeline (same rendering pipeline), Marp (Markdown→slides), Slidev, reveal.js.

---

<!-- ═══ Everything below 🎯 planned ═══ -->

### v14 — Social media integration (formerly v11) (✅ delivered in a teammate's repo 2026-11-05, not merged into this repo)

**Goal**: One-click distribution of finished videos to social platforms / IM; push notifications on task completion; trigger via `/` commands inside IM.

**Scope**:
- Publishing channel adapters: Douyin/Bilibili/Channels/Xiaohongshu (publish after manual review, or via open-platform APIs)
- IM bot gateway: `utils/notify/` (`Notifier` abstraction + WeCom / Feishu / DingTalk / Slack / Telegram + factory multi-channel concurrent push)
- Task-completion post-hook wired into the v4 scheduler
- Callback gateway `POST /api/notify/{channel}/callback` (decrypt → text → reuse v9 `/api/tool/{name}`)
- Rich media cards: video preview cards, progress bars, candidate selection inside IM
- Add a `notify` section to config.json; personal WeChat not supported

**Milestones**: M1 Notifier abstraction + WeCom → M2 Feishu/DingTalk + factory → M3 auto-notification on task completion → M4 callback gateway + at least one publishing channel

> **🔗 Handover note (updated 2026-11-05)**: v14 (social media / IM gateway) was delivered ✅ (M1-M4) by a teammate in their own repo; per the user's decision it is not merged into this repo — this entry is closed as handed over. The `utils/notify/` directory skeleton remains reserved (base/factory interfaces); to integrate the teammate's gateway, just implement the Notifier interface.

**Reference**: `lark-oapi` (official Feishu SDK), wechaty; BigBanana multi-candidate decision points; original v9-design.md.

---

### v16 — Video processing & editing (SAM segmentation / YOLO auto / video tracking / partial replace / generative editing) (formerly v19, ✅ done 2026-10-02: M0-M4 + enhancements all green + v16.x M5-M8 generative editing; kick-off 2026-09-30)

**Goal**: Add **frame-level video editing capability** to the pipeline — segmentation, tracking, face swap, partial replacement — serving both rework (v19's visual rewrite) and post-production fine-tuning of custom/auto outputs.

**Scope**:
- **SAM segmentation**: Segment Anything (or SAM2, with video propagation) for object segmentation on frames/clips — subject cutout/background replacement/partial mosaic; `utils/sam_edit.py` (image/clip → mask → cutout/re-bg/blur), one-click `--segment subject`
- **Optical-flow tracking**: reuse the v2 RIFE flow model for **object trajectory tracking** (CoTracker/RIFE flow focus) — shot stabilization/motion-blur repair/tracked mosaic; RIFE (8189) already online, incremental changes (🎯 merged into M3 at the video-extension stage, tracking mosaic first)
- **AI face swap**: local open-source solutions (FaceFusion/inswapper, reference image → target video face swap) — combined with the v1 character anchor (character reference → face swap in the final video), **explicitly for authorized material / fictional characters only**; `utils/face_swap.py` (GPU; disabled on the v21 `none` tier)
- **Partial replacement (inpaint)**: in-frame region re-rendering (SDXL inpaint 8191 / FLUX fill) — watermark removal/object replacement/background change; masks come from SAM segmentation (SAM segment → inpaint fill, two capabilities chained)
- **ControlNet reference (🎯 2026-10-02 research: nodes supported, weights not downloaded)**: FLUX 8192 natively supports all editing nodes (ControlNetApply/DiffControlNetLoader/InpaintModelConditioning/SetUnionControlNetType/ControlNetInpaintingAliMamaApply verified present), but `ComfyUI/models/controlnet/` is empty — weights needed; see the v16.x backlog below for candidates
- **Agent-ization**: `audit.edit` or `post.edit` thin-wrapper Agent (mask/sam/inpaint/face tools), chainable: `{"agent":"post.edit","with":{"video":"${v.video}","op":"segment+inpaint","target":"background"}}`
- **Tier integration**: new capabilities join the v21 tier ladder (enabled on `full`; all editing is GPU-dependent, none/flux tiers get downgrade notices)

**Milestones** (planned 2026-10-01, starting like the blender line at M0; 2026-10-02 M0-M4 + enhancements all done ✅): M0 SAM2 environment spike ✅ (SAM-2 1.0 source install at /mnt/disk_sdb/zxy/sam2-src + weights models/sam2/ tiny+small + single-image verification: build 1.1s/predict 0.2s/VRAM 201MB) → M1 SAM segmentation ✅ (`agents/post/tools/sam_edit.py`: segment/cutout/replace_bg/mosaic/inpaint/visualize six modes (visualize = colored multi-object overlay, SAM demo style 8-color palette + boundary strokes + IoU dedup) + auto-subject 3x3 grid point union (coverage 66.8% vs 29% single point) + _pick_device per-card probing) → M2 partial replacement ✅ (cv2.inpaint TELEA + mask dilation to cover edges; the FLUX server has no Fill model, latent inpaint left optional) → M3 video extension ✅ (SAM2 video propagation build_sam2_video_predictor + point-prompt per-frame masks + mosaic/blur_bg/cutout/color (multi-object color, one obj_id per point) re-stitched into mp4; 144 frames @48it/s propagation ~3s) → M4 agent-ization ✅ (CLI `vidance.py edit` subcommand + `post.edit` agent + `/api/tool/edit` (image sync / video async edit_* jobs reusing h3shot polling) + utils thin shells + config task_prefixes edit). **Enhancements (2026-10-02 afternoon-evening, verified on all channels)** ✅: ① colored multi-object segment_multi/visualize (8-color palette + IoU 0.85 dedup + score<0.5 noise drop) + video_color (one obj_id per point); ② prompt_frame parameter (SAM2 prompt at any frame, CLI --frame); ③ **bidirectional propagation fix** (propagate_in_video is forward-only by default; added a reverse=True backward pass, pre-prompt-frame coloring 0%→30.9%); ④ **YOLO auto-detection → SAM box prompts** (Grounded-SAM flow, --yolo/--classes/--conf: cat coverage 39.7% (point) → 49.3% (box), scores 0.94-0.99, visualize draws class-name labels) + video --yolo (detection-frame prompts → bidirectional propagation); ⑤ box prompts (--box, one object per box, big improvement for large objects: potted plant 17.5%→46% coverage) + segment_from_boxes; ⑥ all channels CLI/agent/API kept in sync (agent --with yolo/classes/box/frame; API fl passthrough + detected boxes injected into the job). Verified: cat-dog image --yolo detected all 7 objects (v8s; the n variant missed them); cat-dog fight video Wan 121 frames → SAM2 bidirectional tracking (frame 30 prompt cat+dog, whole-video coloring 29-37%, stable across frames); API video yolo job passed 121/121 frames (verified via pixel stats). **Face swap** (within compliance bounds, FaceFusion/inswapper) + FLUX Fill/ControlNet/VACE/Kontext see the v16.x backlog, started as needed. **Container tiers**: editing is fully GPU-dependent (torch); the container (none tier) only syncs code without installing sam2 — editing stays on the host GPU tier; environment pinned via deploy/requirements-lock.txt + setup_env.sh + download_weights.sh (2026-10-02)

**v16.x generative editing enhancements** (2026-10-02 evening, M5-M8 all done ✅):
- **M5 FLUX.1 Fill generative re-rendering ✅**: flux1-fill-dev-fp8 (11.9G, dim mirror repo) → direct UNETLoader; `flux_fill.json` (InpaintModelConditioning noise_mask) + `ComfyClient.generate_flux_fill` + `sam_edit.inpaint_flux` (invert = background replace) + CLI `--engine flux`. Tests: remove cat (whole-box mask seed42) YOLO cat 0.92 → undetected, 0.42% retained outside the box; beach background replace 100% re-rendered
- **M6 Union ControlNet integration ✅**: Shakker-Labs union pro fp8 (3.3G, Kijai) → ControlNetApplyAdvanced (plain Apply errors with "needs a VAE"); canny edges (cv2.Canny 100,200) + strength 0.55; outside-mask collateral damage 5.19%→0.49% (10x improvement); species change (cat→golden retriever) while keeping structure
- **M7 Wan2.1 VACE reference-image-to-video ✅**: wan2.1_vace_1.3B_fp16 (4.3G, Comfy-Org official repackaged) + wan_2.1_vae (254MB) → `wan_vace.json` (WanVaceToVideo reference_image) + `generate_vace_video` + CLI `vidance.py vace` + API /api/tool/vace (async). Tests: dog reference → 81 frames@16fps, YOLO dog 0.92-0.95 present throughout
- **M8 Qwen-Image-Edit 2509 instruction-based editing ✅**: qwen_image_edit_2509_fp8 (20.4G) + qwen_2.5_vl_7b_fp8_scaled (9.4G) + qwen_image_vae (254MB) → `qwen_edit.json` (TextEncodeQwenImageEditPlus) + `generate_qwen_edit` + `sam_edit.qwen_edit` + CLI `edit instruct` + API edit dispatch. Tests: Chinese instruction "把猫换成金毛犬" took effect on all instances (right-side cat 0.64→dog 0.94); "改成夜晚" global mean 148,116,86→55,52,69 dark blue
- **VACE control_video/control_masks inpaint variant ✅** (2026-10-11, v16.x wrap-up): `sam_edit.video_masks` (SAM2 per-frame masks: ffmpeg frame extraction → propagate → frame/mask %06d, 4n+1 alignment ≤81 uniform oversampling) + `sam_edit.video_inpaint_vace` (op remove as-is / keep inverted) + `comfy_api.generate_vace_inpaint` (**programmatically builds the workflow, no template needed**: LoadImage×N + ImageBatch chain + ImageToMask + WanVaceToVideo(control_video/control_masks) + KSampler uni_pc + SaveVideo; upload_image gained a subfolder parameter) + CLI `edit video --engine vace --mask-op remove|keep --prompt` + API async `_run_vaceeditjob` (on_stage stage reporting SAM2→VACE) + post.edit agent vace branch. **Mask semantics (2026-10-11 erratum, confirmed by pixel-level testing)**: mask white (1) = re-render that region, black (0) = keep — remove uses the SAM mask as-is, only keep inverts (initial version had the polarity reversed: the dog was kept while the background got smeared, and YOLO re-check was fooled by background re-rendering into falsely reporting the dog gone; verification must include pixel-level region diffs). Tests: cat_dog_fight.mp4 (832x480 24fps 121 frames) --yolo remove dog → 81 frames@16fps output; after the fix dog-region diff 36-54 vs background only 12-22, YOLO re-check dog gone in 4/5 frames (ghosting-frame conf 0.26 vs 0.85/0.66/0.95 in the original); CLI + API dual channels passed. Lesson: queue_prompt takes a dict, not a json.dumps string (HTTP 500 'str' object has no attribute 'items')
- **VACE 14B + ProPainter + three-engine division of labor ✅** (2026-10-12, video editing close-out):
  - **VACE 14B**: wan2.1_vace_14B_fp16 (27G, Comfy-Org repackaged, ModelScope domestic mirror) → `--vace-model 14b` (passed through in vidance.py CLI + API `_run_vaceeditjob` + post.edit agent). Verified: GPU2 loads ~40-45GB without OOM, 81 frames ~20-25 min per run; pelican_bike remove pelican, swap in "a fluffy orange cat riding a bicycle" → bird gone in 3/3 frames, bicycle retained at 0.9, bird region becomes an orange cat (user accepted)
  - **ProPainter**: repo + three weights (ProPainter.pth 157MB @hf-mirror camenduru mirror / raft-things / recurrent_flow_completion) → `sam_edit.video_inpaint_propainter` (SAM2 mask → subprocess inference_propainter.py, fp16 + mask_dilation 8) + `edit video --engine propainter` (vidance.py + API `_run_propaintereditjob` async + post.edit agent). Non-generative flow propagation (RAFT bidirectional + completion + transformer), **will not grow new objects**; verified on two videos (easy_dog_grass remove dog / pelican_bike remove bird) with YOLO 0 detections on all frames
  - **Temporal-median background plate**: VACE control-frame pre-fill (unoccluded pixels take the temporal median ≈ real background, cov>0.05 threshold, TELEA fallback) — replaces TELEA smears that VACE would then paint into new objects
  - **Selection guide**: plate = fixed camera, free, zero hallucination / propainter = camera motion, pure removal / vace 14B = swap in new objects (prompt must be specific: "empty grass" grew a white duck, "a fluffy orange cat riding a bicycle" succeeded; negative "duck" can conversely summon one)
  - **Prompt frame/box lessons**: on frames where cat and dog co-appear, YOLO confidence ordering picked the wrong box target (cat 0.92 > dog 0.90 but the box prompt only yielded 13.6% half-body + fragments) → choose a prompt frame where the target is alone visible + `--classes` lock-in (after frame 0, mask 31.9% full-width single domain)
- **Face swap** (within compliance bounds, FaceFusion/inswapper) — **capability already covered by the v1 character anchor** (character reference → final video); no further development
- **Lessons**: ① SAM masks only partially cover large objects (first remove-cat test failed: mask coverage 3.8% vs cat box 8.3%) → for removal use a whole-box rectangular mask + **YOLO re-check that the target disappeared**; ② Fill content-aware residue (with a real dog nearby, wood-grain shadows were misread by YOLO at 0.39-0.86; model behavior); ③ SetUnionControlNetType type valid values are combination strings; ④ SAM set_image requires uint8
- Detailed verification data: docs/design/v16-design.md §4; report docs/reports-20261001.md §4-6

**Reference**: SAM2 (Meta, video segmentation), CoTracker (Meta, point tracking), FaceFusion, ProPainter (video inpainting), ControlNet (composition/pose conditioning), FLUX.1 Fill/Canny/Depth/Kontext (Black Forest Labs, inpaint/ControlNet/instruction editing), Wan2.2 VACE (all-in-one video editing), Qwen-Image-Edit (instruction editing), RVM (video matting).

---

### v17 — Consolidating proven open-source repos (formerly v12) (✅ all milestones done, closed 2026-10-30; capability comparison and evidence in [v17-benchmark.html](../v17-benchmark.html))

**M1-M3 session asset layer ✅ (done before 2026-10-30, verified live on 8894)**:
- **M1**: `utils/buffer.py` (BufferManager: uploads as real files + archive reference records + refs.json atomic writes + sha256 revision 409 ESTALE + basename sanitization + path fencing + 200MB cap + TTL 7-day guardian thread + orphan reclamation) + `/api/upload` `/api/assets` `/api/assets/{id}`(DELETE) `/api/assets/{id}/ref` `/api/assets/archive` `/api/session/{id}`(DELETE); unit tests `tests/test_buffer.py` 19/19
- **M2**: UI 📎 button + drag/paste upload → chips (thumbnail/✕/@N index); artifact cards get a "📥 archive to buffer (@ reference)" button (`archiveToBuffer`)
- **M3**: `@N` references (`_resolve_attachments`: @N in args → the Nth attachment's buffer absolute path, values taken server-side from refs.json to prevent injection); chat requests carry an attachments list injected into the LLM context (so it knows @1/@2 are available); chips stay grayed out after sending but remain reusable
- **End-to-end smoke**: upload PNG → final video archives a reference (no copying) → /api/tool/clip with `@1` substitution works → deleting the session really deletes uploads + cleans reference records + **output/ final videos remain untouched and safe**

**M4 checkpoint resume + JSON tolerance ✅ (2026-10-30)**:
- **checkpoint**: `core/pipeline.py` `_save_ckpt/_load_ckpt` (MPT-style atomic writes: fsync+os.replace; corrupt JSON/half files auto-rebuild) + `--resume {task_id}` (CLI `auto`; skips scriptwriting/prompt/character-cache stages; `done_clips` reuses shots one by one); artifact sha256 fingerprints (`_fingerprint_clip`: final_video+audio dual keys; on resume, mismatch/missing triggers a redo; old checkpoints without fingerprint fields stay backward compatible); terminal-state `done` marker persisted into the ckpt
- **Blackboard mount**: whenever a stage persists its ckpt it also writes an agent_runs step record (`_board_log` → v11 AgentBoard `m4:script/prompts/character/clip:N/done`; failures are silent and never block the pipeline)
- **JSON tolerance**: unified exit in `utils/llm.py` (markdown fence stripping/trailing commas/single-quote tolerance) + failure feedback re-ask + max_tokens 16384 (M6 pitfall fix)
- Unit tests `tests/test_checkpoint_m4.py` 18/18 (incl. replaced-shot regression guard)

**M5 five-dimension prompt templates + RAG ✅**:
- **Template assetization**: `SKILL/templates/{cinematic,documentary,anime90s,guofeng}.yaml` (five-dimension vocabulary constraints + style packs), `core/vidance.py auto --template` loads and injects them into the scriptwriter via SkillManager; `core/pipeline.py` carries five_dim_guide/style_pack through the whole chain (M6-S5 style-pack anchor override)
- **RAG**: `utils/rag.py` full chain (chapter splitting rules + character cards + bge-small-zh embeddings + FAISS) + `/rag` CLI/UI three-state rendering + `--rag-doc`/`--rag-novel` scriptwriting context injection; indexed the real "Call to Arms" (see below)

**M6 script breakdown + consistency assets ✅ (2026-10-29/30, "Kong Yiji" end-to-end, three iterations)**:
- **Breakdown** (tier 1 pure LLM): `input/rag_test/m6_breakdown_test.py` — RAG character-card injection (filtered by names appearing in the text) → chat_json (streaming) → characters 6/scenes 14/props 8/storyboard 36 (223s), schema validation all passed; artifact `output/m6/breakdown_孔乙己.json`; breakdown is idempotent (skips the LLM if JSON exists, --force re-breaks) + >8000-char fool-proof guard
- **Render v3 finalized** (tier 3 full chain): `input/rag_test/m6_render_v3.py` — LLM translates each shot's prompt zh→en (root-cause fix for FLUX's weak English understanding) → FLUX keyframes → Wan I2V (bare T2V forbidden) → cosy-default TTS (cloned-voice hallucination blacklist) → slow-mo ≤2x/Ken Burns/xfade assembly → SRT burn-in → **yuv420p Windows-compatible final stitch**; output `output/m6/v3/kongyiji_v3.mp4` (73.7s, ffprobe-verified High/yuv420p); prompts.md fully persisted for traceability
- **Skill consolidation**: `SKILL/commands/novel2video/` (yaml + scripts + nahan.txt + README's eight hard constraints + reproduction tiers A/B/C) + `.opencode/skills/novel_to_video/SKILL.md`
- **Buffer archiving + full render ✅ (2026-10-30)**: `m6_archive_buffer.py` reference-style artifact archiving (idempotent by name+sha dedup); `M6_ALL=1` full 36-shot render verified (incremental translation merge / contact-sheet dynamic grid rework), output 349.2s (h264 High/yuv420p/aac, ffprobe-verified), archived at `output/buffer/m6_kongyiji_v3/`

**Benchmark page gap close-out ✅ (2026-10-30 evening)**: v17-benchmark.html §5 five gaps checked one by one — ① @filename search completed (search_assets cursor pagination + /api/assets?q= + 410 Gone, 26/26); ② MPT subtitle Levenshtein correction and ③ material URL-md5 cache + 24h TTL were confirmed by inventory to be **long since implemented** (subtitle_correct 20/20 + material_cache 20/20 + wiring in place; the page had wrongly listed them as gaps); ④ BigBanana wardrobe system completed (`optimize_costume_prompts` Base Look locks the face; Kong Yiji's 3 looks share the first 120 chars of three prompts, program-asserted identical + FLUX renders in `output/m6/wardrobe/`; formalizing the breakdown schema is deferred to v18); ⑤ benchmark page §3/§4.5/§5/§6 fully updated (capability matrix MPT 3→5 rows, BigBanana 2→3 rows, test-base counts added for subtitle_correct/material_cache). Remaining: 2 "explicitly not adopting" items (keyframe interpolation/infinite canvas) + 1 "evaluated and declined" item (ViMax context compression), all with documented rationale.

**M7 embeddings + retry standardization ✅ (2026-10-30)**:
- **Retry**: tenacity 9.2.1 + `utils/retry.py` (`retry_net('llm'/'tts'/'comfy')` three strategies: exponential backoff ×3 / fixed 2s×3 / 10s×2; is_retryable = 5xx/429/network, 4xx raises directly); unit tests 13/13
- **Embeddings**: MiniLM-L6-v2 qint8 ONNX (23MB, direct hf-mirror download, reproducible offline) + `utils/embed_index.py` (EmbedIndex: ONNX CPU inference / mean-pool+L2 / brute-force cosine / npz persistence + incremental add; missing model errors lazily without blocking import); unit tests 13/13; Chinese semantics still go through bge/RagIndex, MiniLM targets buffer asset retrieval reuse

**Goal**: Absorb engineering capabilities from mature open-source projects without reinventing wheels; and fill the system's long-missing "session asset layer" — uploaded material/intermediate artifacts get a unified buffer (lifecycle follows the session), the frontend supports ChatGPT-like attachment interactions, and commands use @references instead of natural-language pointing.

**Scope**:

*Session asset layer (added 2026-10-12, M1-M3 first)*:
- **buffer session buffer**: `output/buffer/{session_id}/` manages session-related assets (user-uploaded images/videos/audio + task intermediate artifacts) — uploads go straight into the buffer, agent artifacts can be archived into it, session deletion cascades to the directory, TTL periodic cleanup as backstop
- **Frontend attachments**: ChatGPT-like interactions — drag/paste/attachment-button upload, messages carry attachment chips, attachments submitted along with the command on send; task-produced video/image cards get one-click "archive to buffer" for reuse
- **@ reference syntax**: `@1 @2` in commands/natural language reference attachments by order (backend substitutes buffer absolute paths before sending), replacing phrasing like "use the first image below"; the LLM intent layer normalizes "use the first image" into @1 (t2c SFT corpus adopts the same format)

*Original scope*:
- Checkpoint resume: every step's output persisted, resumable after interruption (ViMax checkpoint/resume)
- Tolerant JSON parsing: tolerates unstable LLM output (TrailingCommaTolerantParser)
- Structured video prompt template: `[Visual]/[Motion]/[Camera]/[Audio]/[Narrative]` five dimensions
- RAG pipeline: FAISS + BGE Reranker, long-text input handling (index source = document assets in the buffer)
- Structured script breakdown: unstructured text → characters/scenes/props
- Local semantic embedding ONNX (all-MiniLM-L6-v2): asset matching/scene association (reused for buffer asset retrieval)
- Retry standardization: tenacity unified API retries
- Candidate repos to absorb: **MoneyPrinterTurbo (deep-readable locally: task_dir consolidation/atomic JSON writes/TTL cache cleanup/upload safety), ViMax (session reuse + render checkpoint), Toonflow (@-mention asset system + path fencing + sha256 revision), BigBanana (Script-to-Asset-to-Keyframe + triple consistency guarantee)** — borrowing details in v17-design.md §1

**Milestones**: M1 buffer directory + upload API + session-cascade deletion + TTL cleanup ✅ → M2 frontend attachments (drag/paste/chip/artifact archiving) ✅ → M3 @ references (backend substitution + LLM intent normalization + t2c corpus) ✅ → M4 checkpoint resume + JSON tolerance ✅ → M5 five-dimension prompt templates + RAG ✅ → M6 script breakdown ✅ → M7 embeddings + retry standardization ✅ (all green, closed 2026-10-30)

**Reference**: MoneyPrinterTurbo (local at `/mnt/disk_sdb/zxy/MoneyPrinterTurbo/`, source-level), Toonflow (cloned, source-level), ViMax, BigBanana (README-level); the borrowing map for the four projects and the session-asset-layer design are in [v17-design.md](../design/v17-design.md).

---

**Dependencies**: The multi-agent system (v11, formerly v13) blackboard/chain is the mounting point for checkpoint resume; the session asset layer (M1-M3) is a prerequisite for RAG (M5 document indexing) and the t2c retrain (@ corpus).

---

### v18 — Long-video quality (formerly v14) (✅ closed 2026-10-31: M1-M4 all green, design doc docs/design/v18-design.md)

**Goal**: Improve picture quality and cross-shot consistency for long-form (minutes-level) videos.

**Scope**:
- Keyframe-driven generation: generate first/last frames first, then interpolate the intermediate video
- One-shot (single-take): chained I2V (segment N's last frame → segment N+1's first-frame condition, invisible seams) + LLM continuous camera-move script + drift control (re-inject the character anchor every segment) + `--oneshot --duration N` (capabilities from the original v8-design.md merged in)
- Inter-shot consistency: context-aware injection (current scene/character/costume references)
- Clip-to-clip transition management: emotional/palette/pacing continuity
- Hierarchical character consistency: Scene level → Event level → global character registry
- Long-text processing pipeline: novel compression → event extraction → RAG retrieval → scene decomposition
- World persistence: global context like maps/regions/style continuously injected
- Derivative asset system: character transformations/scene time variants auto-generated

**Milestones**: M1 keyframe-driven → M2 one-shot (last-frame feedback + camera-move script) → M3 hierarchical consistency → M4 long-text pipeline + worldview

**Implementation log (per docs/design/v18-design.md's four milestones, no new models, all wired onto existing infrastructure)**:

- **M1 consistency asset foundation ✅**: breakdown schema upgrade (world{era,region,style,taboos}/characters[].costumes[{name,desc,stages}]/scenes[].anchor_en/storyboard[].costume+transition_out, missing-field downgrade warnings without blocking); legacy breakdown migration tool `m6_upgrade_breakdown.py` (dry-run/--apply/no-change assertion/.v17.bak backup; Kong Yiji world=True costumes=8 anchor_en=14/14 transition_out=36/36); prompt assembler (SCENE_ANCHOR reuses the same scene's anchor verbatim + WARDROBE `costume_for` picks the narrowest interval hit + costume English-translation cache KF/costumes_en.json); 16 xfade transitions selected by `transition_out`. **Acceptance**: all 14 scenes' shot-anchor segments injected verbatim / shot 9 = worn long gown / shot 30 = worn padded jacket with bundle — program assertions all green; v4 comparison video in `output/m6/v4/` (8 shots, 73.7s)
- **M2 VACE flf2v first/last-frame driving ✅**: `m6_flf_smoke.py` single-shot smoke test (control.mp4 = first-frame freeze → xfade 1.2s → last-frame freeze → WanVaceToVideo control_video sequence port, zero new models; first/last-frame MAE 0.019/0.015 + own first-last difference 0.154 = real motion); `m6_render_v3.py` gained an `M6_FLF=1` mode (first frame = this shot's keyframe, last frame = next shot's keyframe, 832x480@16fps, assembly segments scale+pad auto-fit). **Acceptance (two levels)**: clip level (pure generation artifacts) inter-shot boundary MAE **0.198→0.026 (-87%, improved on all 5 pairs)**; part level (assembled segments) **0.199→0.054 (-72.6%)** — under FLF mode the Ken Burns slow-push range converged 1.14→1.06 (the last frame already aligns with the next shot, so large zooming breaks first/last-frame alignment; the first version's part level was only -20.6% with shots 21→24 slightly worse, attributed to zoompan assembly noise reaching 0.111 at v5#21, eliminated after convergence)
- **M3 one-shot ✅**: `utils/oneshot.py` (LLM camera-move chain, five-dimension motion domain continuous across segments + FLUX first frame + segment N's last frame extracted with ffmpeg and fed back as segment N+1's I2V first-frame condition + character/style anchors re-injected per segment against drift + concat stitching + seam assertion/spec assertion/prompts.md) + `core/vidance.py auto --oneshot --duration N` early-exit routing. **Acceptance**: "light through the tunnel" 30s target → 28.3s output (7 segments × 4.04s, 1280x704@24fps h264+yuv420p); camera chain push-in 0.8→1.5→decelerate 1.0 continuous; seam MAE (assembled segment k+1's first frame vs the fed-back condition image) [0.018, 0.016, 0.009, 0.028, 0.015, 0.009] all <0.10 (same magnitude as the FLF smoke test)
- **M4 worldview close-out ✅**: world registry `world_*.json` (breakdown world.style → LLM English-translation cache → STYLE_EN overlay injection + taboos printed/persisted to prompts.md); event line `events_*.json` (storyboard sequence → LLM groups into arc summary cards; Kong Yiji's 10 arcs cover 36/36 shots) + readable `events_*.md` + RAG indexing hook (`utils/rag.py` gained `add_chunks()` explicit chunking — one card per arc, avoiding `add_document`'s chunk_text aggregation merging 10 arcs into 3 chunks and diluting retrieval; key=32b60cbc 10 cards, program assertion: 4 queries hit 3/4, the broken-leg card's top-2 margin 0.60 vs 0.61 = MiniLM's fine-grained Chinese limit); SKILL/roadmap/benchmark page/usage formalization kept in sync

**Explicitly not adopting** (design doc §not-adopting list): model capability routing matrix, nine-grid turnaround (depends on grid compliance), vector worldview DB (a JSON registry suffices). **Honest boundaries**: FLUX has no image conditioning, so scene/character anchors are prompt-level in v1; image-level compositing depends on inpaint/Fill combos, marked as enhancement items.

**Reference**: ViMax Novel2Movie, BigBanana keyframe driving, Toonflow's five-step director planning; original v8-design.md.

---

### v19 — Marketing-account Plus: video-link rework (formerly v16) ✅ Done (closed 2026-11-02, [v19-design.md](../design/v19-design.md), [usage-v19.md](../usage/usage-v19.md))

**Goal**: The user gives a **video link** (Bilibili/Douyin/YouTube etc.) and the pipeline automatically reworks it into a new video, **keeping all existing features**.

**Scope**:
- **Material acquisition**: yt-dlp downloads the original video (reusing v4 voice_clone's yt-dlp capability) → frame extraction/clipping
- **Content understanding**: frames → multimodal LLM descriptions + STT (`utils/stt.py`) transcribing the narration → storyboard/key points
- **Rework editing**: visual rework (optional reordering, speed changes, partial zoom, v5 effects/transitions) + **re-dubbed TTS** (rewritten narration, `utils/tts.py`) + subtitles (STT) + LUT/BGM
- **Dedup/compliance**: adjustable visual-rewrite strength (flip/crop/regrade/frame interpolation) to avoid straight reuploads; human-review exit preserved
- **One command**: `python core/vidance.py rework "<video link>" --style narration --voice cosy-jieshuo1`

**Dependencies**: v4 download/STT/TTS + v5 editing effects + v10 timeline compose (arranging rework material into a timeline).

**Milestones** (design finalized 2026-11-01 → all done 2026-11-02 ✅, no new models, all wired): M1 download + frame extraction + transcription ✅ (yt-dlp merge + STT/multimodal parallel → source.json; verified on a 533s Bilibili original: 203 transcript segments / 1743 chars + 107 frames visually understood 107/107 non-empty, 140.9s) → M2 rewrite narration + re-dub ✅ (streaming JSON + Levenshtein anti-paraphrase assertion <0.55, measured max=0.195 + timeline mapping script.json) → M3 visual rework ✅ (rewrite strength 0-5: speed/LUT/mirror/flow interpolation/effects, assembly via v10 compose; final 70.6s h264+yuv420p + burned-subtitle program assertion) → M4 one-command end-to-end ✅ (`rework` subcommand + meta records the source + human-review exit; four channels CLI/utils/agent(generator.rework)/API(/api/tool/rework async job)). Tests `tests/test_rework.py` 15 pure-logic assertions all pass. **Pitfall log**: ① cosy-jieshuo1 leaked "街道…" hallucination at sentence starts (voice blacklist confirmed) → default voice switched to cosy-default + blacklist warning; ② chat_json non-streaming long-reasoning read timeout (SKILL iron rule #1) → switched to chat_stream 1800s, stable; ③ v10 compose boundary bug: xfade main-track concat dropped the audio track → mux_audio `amix duration=first` degraded to the first narration's length and the output got cut by -shortest (rw-smoke1/rw-api1 both hit) → switched to `duration=longest` when there is no main-track audio, both outputs re-stitched and fixed (64.3s/82.0s matching narr_total). **M1 only promises Bilibili** (yt-dlp verified reachable); other platforms best-effort.

**Burned-subtitle removal (completed 2026-11-02/03, reuses v16 ProPainter)**: `--remove-sub off/auto/force` three levels. Localization = `unlimited-ocr` (USTC endpoint, multi-frame sampling) **∪ pixel-heuristic fallback** (white-text line clustering confirmed across ≥2 frames; the OCR endpoint's queueing fluctuates wildly — measured 7s to 7min+ to first byte — so it never hard-blocks); detection results land in `subtitle.json` (normalized coordinates) and are reused by every part with zero repeated OCR. **Coordinate-space pitfall (two reworks)**: unlimited-ocr outputs permille normalized coordinates (0-999, independent of input resolution — same values for 704p/1080p inputs); it was once misjudged as a "1080-pixel-high space", making 704p normalization off by 1.53x and masks covering the gradient bar above the subtitles while the subtitles stayed intact; and the white-pixel/MAE verification was polluted for two rounds by the false sense that "what got removed was the gradient bar"; the case was closed on the structural disappearance of text-line white-pixel peaks (raw peak 313 → part 0) plus OCR failing to read the original subtitles on crops. **Heuristic limits**: only effective for white text on bright fields; gray text on dark panels / night-scene highlights (white marble) are missed/false-flagged; OCR is the primary localizer. Removal = part granularity (after preclip, 1280x704, ProPainter fp16 ~20G VRAM; running 1080p whole-video directly OOMs) RAFT bidirectional flow completion; final acceptance: 8 segments' text-line peaks 7 zeroed + 1 segment smooth scene reconstruction (edge density 0.000). Tests grew to 23.

**Keyframe mode (2026-11-03, `--keyframes` + `--style first-person`)**: a fast tier replacing ProPainter's per-segment flow completion — each part extracts 1 keyframe (t=ref_start+ref_dur*0.45), still-frame cv2.INPAINT_TELEA subtitle removal (seconds-level, ~100x faster than ProPainter) → zoompan Ken Burns slow push (2560 upsample anti-jitter, zoom 1.08 → 1280x704@24fps) → RIFE v4.26 flow morph transitions between segments (ComfyUI 8189, multiplier 8, falls back to 0.0 hard cut on failure). Duration accounting unchanged (morph baked into the front segment's tail: hold×(narr+0.2-morph)+morph), compose/narration untouched; kf parts carry anullsrc silent tracks for amix. `first-person` style = character self-narration + person-reversal iron rule (third→first person, measured 6/6 segments ✓, similarity 0.121). **Pitfall log**: ① pre-concat tpad cloning the tail frame pushed the morph out of the -t window (frames 66-76 all 0.0 diff) → moved tpad after concat, morph progressive diff 18.6→64.3 ✓; ② kf mode accidentally triggered ProPainter (duplicate remove_sub block) → skip when force and keyframes; ③ JPEG full range made zoompan output carry pc markers and the output pix_fmt was reported by ffprobe as yuvj420p → hold chain tail `scale=in_range=pc:out_range=tv` normalization, final back to yuv420p/tv ✓. First full-chain run 61.7s (BV1jTxC6mExW, cool LUT + first-person + original-subtitle removal + own subtitles voiced, program assertions all green). Tests grew to 24.

---

### v20 — In-generation review (tensor export + multimodal review while generating) (formerly v21, ✅ done 2026-11-04: M0-M3, approach = sidecar + switch)

**Goal**: Showcase **the advantage of local deployment** — while generating video, tokens/latents are flowing; export the intermediate states **directly into reviewable images** and feed them to a multimodal LLM for real-time review, **reviewing while generating** (instead of waiting for the whole video then reviewing frame by frame), saving pipeline time (review is currently one of the biggest time bottlenecks, 30-200s/shot).

**Approach finalized (2026-11-03, user decision)**: **No rewrite of existing code — sidecar + switch** — `config.json` gains a `v20_live_audit` section (`enabled: false` default off) + CLI `--live-audit` override; **off = original path byte-identical, on = generation calls wrapped in a wrapper**. Existing review (light/full) is kept as final review; the coarse review is just an extra loss-cutting gate in front (parallel, not a replacement). Research evidence (2026-11-03 explore): ComfyClient is pure HTTP polling with no WS/interrupt code, but the **ComfyUI server natively supports** WS-streamed latent preview frames during sampling (`--preview-method` launch flag, latent2rgb needs no model install) + `POST /interrupt` for immediate termination — early stopping requires no in-house work; far less invasive than the original draft's "modify the workflow to split KSampler" route.

**Milestones** (2026-11-04 M0-M3 all green): M0 spike ✅ (start_services.sh wan gains `--preview-method latent2rgb`; WS verified 8 preview frames, step 8/20 interrupt takes effect immediately saving ~60%, qwen3.8 can judge subject/scene from preview frames) → M1 tooling ✅ (`agents/generator/tools/comfy_preview.py` PreviewListener/`interrupt_if_running` (checks /queue to verify ownership, avoids killing RIFE by mistake)/`live_audit_patch` instance-level patch (generate_i2v's internal self.queue_prompt hits the instance attribute, zero changes to generation code) + `agents/audit/tools/live_auditor.py` LiveAuditor (throttle ≤3 times/shot, only calls the API when step≥4 and frame std≥40, exceptions pass through without blocking) + 24 unit tests; pitfall: the coarse review defaulted to `models['script']` (a 400 for no multimodal after switching to deepseek-v4-flash-ascend1) → explicitly `models['review']`) → M2 pipeline wiring ✅ (EarlyStop→continue regenerate with a new seed; same-topic 3-shot comparison OFF 895.8s vs ON 929.2s (**+3.7%**, all 9 coarse reviews hidden inside the generation window); meta records live_audit per shot) → M3 frontend ✅ (coarse-review events persisted into task_dir → `GET /api/tasks/{id}/preview` → UI task card shows preview frames + verdict in real time; switch passed through on the API channel via scheduler/TOOLS/flags; full-chain real-run verification: task auto_20261104_153353 snowy-night old town 12s/3 shots, 3 shots × 3 coarse reviews all pass score 8, UI refreshed preview frames + review comments live during generation ✓). **Follow-up verification (2026-11-05)**: 3 tasks, 15 natural coarse reviews all pass — latent2rgb previews cannot judge semantic details (text language/number of people), the coarse review only blocks catastrophic collapse; the same batch's final review caught a real score 2 (one person with a Korean banner ≠ five people with a Chinese banner), empirically demonstrating the coarse/final division of labor; light review not retrying is pre-existing design (parallelism-for-speed trade-off).

**Honest gaps**: no natural trigger of early loss-cutting across the full chain was observed (all experiment topics passed); fail→interrupt→regenerate is covered by combining the spike (interrupt verified live) + unit tests (judgment/wiring).

**Dependencies**: Wan/ComfyUI local instance (8189, `--preview-method latent2rgb`) + multimodal LLM (qwen3.8-chat) + frontend task-card polling.

**Reference**: ComfyUI native `--preview-method auto|latent2rgb|taesd` (latent2rgb needs no model), `POST /interrupt`, WS `executing/progress/execution_cached` message protocol; LCM (low-step fast rendering idea). See docs/usage/usage-v20.md for details.

---

### v21 — End-user delivery form (formerly v18, ✅ done 2026-11-05: M0-M4 all green, version 1.0.0)

**Goal**: Go from "developer local system" to "a product users can install and run" — probe local resources first, then distribute the matching deployment tier per resources, hiding low-level details.

**Milestone draft**:
- **M0 resource probing** ✅ (2026-11-05): `core/doctor.py` (GPU model/VRAM/port occupancy/conda envs/disk/external reachability — HTTPError 4xx counts as reachable) → profile JSON, `vidance doctor [--json]` + `GET /api/doctor`; `recommend_tier()` recommends a tier by VRAM/card-count ladder (none<flux 16G<wan 24G<h3 40G<full 4 cards); tests/test_doctor.py 13 items all green
- **M1 deployment tiers** ✅ (five-tier landed 2026-09-26, see [deploy-tiers.md](../instructions/deploy-tiers.md) and deploy/README.md): five-tier ladder `none` (no GPU: svg + fast crawled images, LLM/edge-tts all remote) / `flux` (+SDXL/FLUX image gen) / `wan` (+Wan T2V/I2V+RIFE+auto/quick) / `h3` (+MiniMax-H3 ref2va+custom/h3shot) / `full` (everything) — same codebase + `VIDANCE_TIER` env var + `config/tiers/{tier}.json` overlay (`agents/common/tools/config_loader.py` deep merge, default full, zero change on the host); guard points `/api/health` reports the tier / `/api/tools` filters by tier / tool dispatch 400 / CLI require() exits with a tier-switch hint; Docker: `deploy/Dockerfile` (API layer ~2GB: ffmpeg+Noto CJK+playwright/Chromium) + `deploy/Dockerfile.comfyui` (GPU template, model volumes can't bake into the image) + `deploy/docker-compose.yml` (profiles five tiers, API defaults to port 9400, host networking reaches host services) — local full-tier demo: `VIDANCE_TIER=full VIDANCE_PORT=9401 docker compose -f deploy/docker-compose.yml up -d vidance`
- **M2 one-click install** ✅ (2026-11-05): `deploy/install.sh [--tier T] [--port N] [--mode docker|conda] [--gpu] [--no-smoke]` — `core/doctor.py --json` probing (GPU/disk/recommended tier) → port occupancy precheck (ss) → docker path (build if the image is missing + compose up, tier/port env injected; `--gpu` appends the compose gpu-* profile to start GPU services) / conda path (setup_env.sh + backgrounded api_server) → smoke self-check (/api/health polled 60s + tier/capability listing printed + WebUI/diagnostics entry hints); two local runs verified (`--tier none --port 9402` downgraded tier and `--tier full --port 9402` full tier, whole flow green; default-tier path doctor recommended full ✓; after testing the 9401 container was restored)
- **M3 user-facing details** ✅ (2026-11-05): **config wizard** `vidance init` (interactively asks LLM key/gateway/voice/output dir/cleanup retention one by one, Enter keeps current values; non-interactive `--llm-url/--llm-key/--voice/--output-dir/--cleanup-keep`; `--show` masks keys; writes config.local.json if present else config.json — config_loader gained `save_config`/`user_config_path`) + `/api/tool/init` dispatch; **failure self-diagnosis** `core/diagnose.py` (11 rules: connection refused → names the service by port + start command / OOM / 401 → init / edge-tts external network → cosy / disk full → clean / port occupied / websockets missing dependency / ffmpeg / missing model / 7200s timeout / non-zero exit → scheduler.log; `python core/diagnose.py "error text"` for direct CLI testing) — GET /api/tasks and /api/tasks/{id} auto-attach `hints` to failed tasks (error text untouched, also applies to old failed tasks), UI failure messages and task-detail overlay show 💡 hints; **output dir & cleanup** `core/cleanup.py` (task-directory detection = contains meta.json/scheduler.log or `2*` timestamp naming — fixes the old clean scanning only `2*` and missing task dirs like auto_/fast_; keeps N newest by mtime; protects queued/running task directories from deletion; `--dry-run`/`--keep/--output-dir` CLI) + `/api/clean` + `/api/settings` GET (output_dir/disk free/task-dir count/cleanup_keep/version) / POST (cleanup_keep 1-200 persisted); UI ⚙ overlay gains a "System" section (version/disk/task count/retention input/run cleanup); **version channel** root `VERSION` (1.0.0 semver) + `GET /api/version` (version/python/tier) + shown in the UI System section (update channel = manual git pull, see M4 CHANGELOG); tests/test_m3_ux.py **24/24** (diagnose rules 10 + cleanup 5 + version/config writeback 5 + endpoint layer 4)
- **M4 delivery packaging** ✅ (2026-11-05): `vidance --version` (reads root VERSION, 1.0.0 semver) + `CHANGELOG.md` (v0→v21 capability generations fully recorded) + `docs/usage/usage.md` gains a top "quick start by tier" user-manual section (five tiers × your machine/what it can do/first command + init wizard/diagnostics/frontend entry, developer reference kept below); **SKILL demos included** — `SKILL/templates/{tpl}.demo.mp4` ×4 (cinematic/documentary/anime90s/guofeng, each a real auto --template --duration 4 run copied next to its yaml) + `SKILL/commands/auto/healing.demo.mp4` (--skill healing 12s) + `SKILL/commands/blender3d/showcase.demo.mp4` (--skill showcase), aligned with the existing fast/{marketing,narrative}.demo.mp4 convention

**Dependencies**: v13 lightweighting (formerly v15) is the foundation of the lite tier; v11 multi-agent (formerly v13) agent API is the gateway/bot integration surface.

---

### v22 — Promotional poster generation (poster line, ✅ done 2026-11-17: M1-M4 all green)

**Goal**: Turn the open-source promo poster (README hero image, manually iterated v1-v8) into a formal feature — one concept sentence in, one 2:3 portrait promo poster out (LLM planning + FLUX base plate + SAM cutout + PIL typography compositing).

**Milestones**:
- **M1 poster planning** ✅: `agents/generator/tools/poster_llm.py` (PLAN_SYS: concept → JSON `{title, subtitle, tagline, bg_prompt, creatures[{name, prompt, zone, height}]}`, LLM outputs structured JSON only, copying the v13 blender architecture); `_norm_plan` normalization (title≤12/tagline≤14 char clamps, zone five-region whitelist back-center/mid-left/mid-right/front-left/front-right, height 0.15-0.45, region-conflict dedup, ≤3 creatures); LLM failure falls back to default_plan (pure landscape + typography)
- **M2/M3 pipeline** ✅: `agents/generator/tools/poster_pipeline.py` (effect functions all ported from the promo poster's v8 field-tested parameters: refine_alpha luminance keying / ghost_fade holographic fade / title chromatic aberration ±5px + purple glow / purple wash against sticker look / bottom 480px gradient mask / 140 rain streaks / vignette + grain). `generate_plates()` FLUX base plate (2:3 1024×1536, multi-seed retries) + creature standing art (pure black background 1024²); `cutout_creatures()` Grounded-SAM (YOLO box prompt takes the largest box, class guessed from the creature name), per-creature failure falls back to luminance keying (noted in notes); `compose_poster()` data-driven compositing (zone anchor table ZONE_LAYOUT, all constants scaled by canvas ratio); if FLUX is entirely unavailable → `gradient_bg()` purple-night gradient fallback (no GPU dependency). `PosterLine` one-click → `output/poster_{ts}/` (poster.jpg q90 + plan.json + plates/ + cutouts/ + meta.json)
- **M3 four-channel wiring** ✅: CLI `vidance poster "topic" [--title/--tagline/--command/--url×2/--qr-url/--no-terminal/--no-rain/--seeds/-o]` (render mode `--plan plan.json [--bg --creatures]` skips FLUX for iterative re-layout) + agent `generator.poster` (33rd) + API `POST /api/tool/poster` (async job, reuses the h3shot polling channel, receipt image_url) + utils/poster_{llm,pipeline}.py thin shells
- **M4 tests & E2E** ✅: tests/test_poster.py **31/31** (normalization/zone math/anchors don't exit bounds/compositing canvas/effect functions/fallback plate, no GPU); GPU E2E first run 116.7s to output (LLM planned 3 creatures → FLUX 4 plates → SAM 1/3 + luminance keying 2/3 → composite 1200×1800), qwen blind review **8/10** (terminal-card command/dual URLs/QR OCR'd verbatim all correct, no tofu blocks in Chinese)

**Known trade-offs**: the bottom info area (terminal card + dual URLs + QR) is slightly crowded when stacked (same trait as the manual v8; automatic layout doesn't yet fine-tune per element); absolute scores fluctuate (6.5↔8.5), comparative review is more reliable.

---

## 5. GPU & port allocation

| Service | Port | GPU | Env | Start |
|------|------|-----|------|---------|
| MiniMax-H3 ref2va (ComfyUI) | 8188 | GPU0 | comfyui | `./start_services.sh start h3` |
| Wan T2V/I2V + RIFE (ComfyUI) | 8189 | GPU2 | comfyui | `./start_services.sh start wan` |
| HunyuanVideo (ComfyUI) | 8190 | GPU3 | comfyui | `./start_services.sh start hunyuan` |
| FLUX + TripoSplat (ComfyUI) | 8192 | GPU3 | comfyui | `./start_services.sh start flux` |
| Hunyuan3Dv2 turbo (ComfyUI) | 8193 | GPU1 | comfyui | `./start_services.sh start h3d` |
| TTS dual engine (edge-tts + CosyVoice) | 9880 | GPU2 | cosyvoice | `./start_services.sh start tts` |
| Vidance API + WebUI | 8894 | — | comfyui | `./start_services.sh start api` |

- **One-click script** `start_services.sh` (start/stop/restart/status/test/logs); the service↔port↔GPU mapping is in the script comments
- ⚠️ Do not add `--cuda-device` when starting ComfyUI — it overrides `CUDA_VISIBLE_DEVICES` (main.py:87)

- FLUX (8192) and HunyuanVideo (8190) share GPU3, mutually exclusive
- Models load on demand; TTS loads CosyVoice at startup (~28s)
- The edge-tts online engine uses no GPU (needs external network, occasionally flaky)

---

## 6. LLM & APIs

| Service | Usage | Status |
|------|------|------|
| USTC deepseek-v4-flash | Scriptwriting, prompt optimization, LUT/BGM/effects selection, completeness assessment | ✅ Free |
| USTC qwen3.8-chat | Multimodal review + image-relevance auditing | ✅ Free |

> USTC API: `https://api.llm.ustc.edu.cn/v1`, key stored in `config/config.json` (not committed to git)

---

## 7. Key technical decisions

1. **Hybrid-mode orchestration**: deterministic flows hard-coded, creativity/judgment delegated to agents
2. **ComfyUI workflow JSON templates + parameter injection**: visual debugging
3. **director + reviewer/asset/scout subagents**: opencode-native, responsibility isolation
4. **Dual TTS engines**: cosy-* local default (avoids edge's external-network flakiness) + edge-* online backup
5. **Subtitles use TTS timestamps**, STT as fallback (`--stt`)
6. **Review uses qwen3.8-chat**: supports vision, 180s timeout + 2 retries + safe fallback
7. **Random seed per shot**: prevents ComfyUI cache hits
8. **Review capped at 3 attempts + highest-score fallback**: prevents infinite loops
9. **Storage tiering**: code/config/small assets on sdb, models/videos/outputs on the HDD, unified access via symlinks
10. **Service-default fallbacks**: TTS unavailable → degrade to cosy/default → silence; image source crawl → FLUX → placeholder image; the flow never crashes
11. **Compositing/effects stay backend** (v10): only CLI/API callable by the LLM, no frontend; follows the OpenCut timeline model
12. **Frontend zero-npm**: v7/v8 self-contained HTML + vanilla JS, served statically by FastAPI

---

## 8. Directory structure

```
vidance/
├── opencode.json              # opencode config: provider + agents + permissions
├── AGENTS.md                  # project conventions + commands (for agents)
├── start_services.sh          # one-click model-service start/stop/self-check script
├── .opencode/
│   ├── agents/                # director/reviewer/asset/scout.md
│   └── skills/                # scriptwriting/review/topic_scouting
├── config/config.json         # API keys, engine addresses, model names, voice config
├── core/                      # orchestration layer
│   ├── vidance.py             # unified CLI (auto/custom/quick/concat/fast/hot/ask/compose/svg/make/agent)
│   ├── pipeline.py            # auto-mode pipeline controller
│   ├── custom_gen.py          # custom-mode H3 ref2va generation
│   ├── postprocess.py         # shared post-processing (RIFE/LUT/BGM/STT)
│   ├── scheduler.py           # async task queue (TaskQueue SQLite + Scheduler)
│   ├── api_server.py          # FastAPI :8894 (tasks/dialog/tool/ui/…)
│   └── dashboard.py           # HTML dashboard
├── utils/                     # tooling layer
│   ├── comfy_api.py           # ComfyUI client (T2V/I2V/TripoSplat/FLUX/H3)
│   ├── llm.py                 # USTC LLM (text + multimodal)
│   ├── tts.py / tts_server.py # TTS client + dual-engine service
│   ├── splat_renderer.py      # 3DGS multi-angle rendering
│   ├── mesh_render.py         # headless mesh rendering (pyrender+EGL)
│   ├── hunyuan3d.py           # Hunyuan3Dv2 reconstruction client
│   ├── asset_registry.py      # asset registry management
│   ├── crawler.py             # trending-topic crawler
│   ├── voice_clone.py         # production voice cloning
│   ├── funclip.py             # FunClip smart clipping
│   ├── asset_crawler.py       # material crawling (Pexels images + BGM)
│   ├── fastline.py            # fast marketing-account pipeline (images+zoompan+TTS)
│   ├── effects.py             # editing effects (v5)
│   ├── dialog.py              # prompt multi-turn clarification state machine (v6)
│   ├── ffmpeg_tools.py        # frame extraction/concat/subtitles/compositing
│   ├── rife.py / gen_luts.py / music.py / stt.py
│   ├── compose.py             # v10 timeline compositing (M1-M8 implemented)
│   ├── svg_pipeline.py        # v13 (formerly v15) SVG→mp4 (frame-by-frame rendering + S5 voiced pipeline, S1-S5 implemented)
│   ├── svg_llm.py             # v13 (formerly v15) concept→LLM→animated SVG
│   ├── t2c_server.py          # t2c natural language→command (translate, in-process/optional HTTP)
│   ├── h3_prompt_video.py     # whole-prompt + reference image → single H3 ref2va shot (native audio)
│   ├── oneshot.py             # v18 (formerly v14) one-shot (✅ chained I2V last-frame feedback + LLM camera chain + seam assertion; auto --oneshot)
│   ├── notify/                # v14 (formerly v11) bot gateway (🎯 planned)
│   ├── luts/  bgm/  workflows/  voices/
├── agents/                    # v11 multi-agent (formerly v13): D/G/P/V physical layering + thin wrappers (docs/design/v11-design.md)
├── t2c/                       # t2c model (fine-tuned mt5-small) + inference scripts + README
├── ui/                        # v7/v8 frontend (self-contained index.html, :8894/ui)
├── docs/                      # roadmap + reports + usage/ + design/ + research/ + instructions/
├── voice_samples/ → /mnt/dataset/...  # voice audition samples (symlink)
└── output/ → /mnt/dataset/zxy/vidance/output/  # finished videos (symlink)
```

---

## 9. Related repos & references

| Repo | Usage |
|------|------|
| ComfyUI (`/mnt/disk_sdb/zxy/ComfyUI/`) | shared inference engine, multi-instance |
| CosyVoice (`/mnt/disk_sdb/zxy/CosyVoice/`) | TTS engine |
| MoneyPrinterTurbo | architecture reference (dual subtitle modes/VideoParams/skills) |
| OpenCut | v10 compositing/timeline model reference (backend thinking only) |
| ViMax / Toonflow / BigBanana | v11 multi-agent / v18 long video (formerly v14) / v17 open-source consolidation (formerly v12) references |
| SAM2 / CoTracker / FaceFusion / ProPainter | v16 video processing & editing (formerly v19; segmentation/tracking/face swap/inpainting) references |
| Marp / Slidev / reveal.js | v15 LLM-generated PPT (formerly v20; Markdown/code→slides) references |
| ComfyUI PreviewLatent / TAESD / LCM | v20 in-generation review (formerly v21; mid-generation latent decoding/fast decoding) references |

---

## 10. Deployment records

Deployment details for each model live under `/mnt/disk_sdb/zxy/`:
- `MiniMax-H3-部署记录.md`, `Wan2.2-部署记录.md`, `HunyuanVideo-部署记录.md`, `SDXL-部署记录.md`, `FLUX-部署记录.md`
- t2c (fine-tuned mt5-small, natural language→command) in v-t2c.md; the model and inference scripts ship with the project in `t2c/`
- Hunyuan3Dv2 in v3-design.md §13

> Model weights are stored under `/mnt/dataset/zxy/<Model>-ComfyUI/` and mapped into ComfyUI via `extra_model_paths.yaml`.
