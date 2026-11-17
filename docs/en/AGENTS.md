> English | [简体中文](../../AGENTS.md)

# Vidance — AI voiced short-video generation

> This file is read by opencode agents to learn the project conventions and commands.

## Project overview

Vidance is a local video-generation system orchestrated by opencode agents. Core flow: Chinese concept → LLM scriptwriter → Wan T2V generation → dual-engine TTS dubbing → multimodal review → ffmpeg compositing → voiced short video.

**Unified entry**: `python core/vidance.py make` (v12 (formerly v17): `--director llm|manual|scout × --generator wan|fast|svg|h3` permutations) or subcommands directly `{auto|custom|quick|fast|hot|svg|compose|concat|h3shot}` — auto mode does LLM scriptwriting + Wan/FLUX generation, custom mode uses reference images + a pre-written script + H3 ref2va generation, quick mode is pure T2V with no post-processing. Post-processing (RIFE/LUT/BGM/STT) is provided by the shared `core/postprocess.py` module.

**Current status: v0-v7 all implemented + v10 timeline compositing (M1-M8) + svg voiced pipeline (S1-S5) + t2c natural language→command + v12 make unified entry (M1-M2, formerly v17) + v11 multi-agent (M0-M4 + v11.1 frontend visualization, formerly v13, agents/ directory, docs/design/v11-design.md) + v15 PPT pipeline (M1-M4, formerly v20: ppt_llm plan_deck/templates/svg_chart + ppt_pipeline PptLine multi-format deck.html/PDF/PNG/mp4 + CLI ppt + generator.ppt agent + /api/tool/ppt) + v13 blender 3D simple version (blender_llm plan_scene/templates title3d+shapes+bars3d + blender_pipeline bpy EEVEE + BlenderLine + CLI blender3d + generator.blender3d agent + /api/tool/blender3d) + v13 lightweighting close-out (all four model-free lines in place: marketing-account/SVG/PPT/Blender) + **v22 promo poster ✅ (closed 2026-11-17: poster_llm concept→JSON planning (zone five-region whitelist + _norm_plan clamps) + poster_pipeline FLUX base plate → Grounded-SAM cutout (luminance-keying fallback) → PIL parameterized compositing (v8 field-tested params: chromatic aberration/glow/holographic fade/rainy night/terminal card/QR) → PosterLine + CLI poster + generator.poster agent + /api/tool/poster async job; tests/test_poster.py 31 items + GPU E2E 116.7s output, qwen blind review 8/10)** + v16 SAM2 editing + generative editing enhancements ✅ (sam_edit segment/cutout/replace_bg/mosaic/inpaint/visualize/instruct + YOLO auto Grounded-SAM/box prompts + video bidirectional propagation tracking + v16.x M5 FLUX Fill generative re-render/M6 Union ControlNet canny integration/M7 Wan2.1 VACE reference-image-to-video/M8 Qwen-Image-Edit 2509 instruction-based editing (Chinese works) + CLI edit --engine flux|vace|instruct + post.edit agent + /api/tool/edit|vace + the deploy environment-pinning trio; docs/design/v16-design.md) + **v17 open-source consolidation (formerly v12) ✅ (M1-M7 all green, closed 2026-10-30: M1-M3 buffer session asset layer/frontend attachments/@references (@N + @filename q search + cursor 410)/M4 checkpoint resume sha256 fingerprints + JSON tolerance/M5 five-dimension templates + RAG/M6 script breakdown novel2video (incl. wardrobe system)/M7 embeddings + retry; benchmark page docs/v17-benchmark.html; docs/usage/usage-v17.md)** + **v18 long-video quality (formerly v14) ✅ (M1-M4 all green, closed 2026-10-31, design doc docs/design/v18-design.md: M1 consistency asset foundation schema + scene anchors + wardrobe assembler + transition selection / M2 VACE flf2v first/last-frame driving (M6_FLF=1, inter-shot boundary MAE -87% clip level / -72.6% part level) / M3 one-shot utils/oneshot.py + auto --oneshot / M4 world.json + event-line close-out; v4/v5 same-topic comparison + 30s oneshot acceptance; docs/usage/usage-v18.md)** + **v19 video-link rework (formerly v16) ✅ (closed 2026-11-02, design doc docs/design/v19-design.md: M1 yt-dlp merge + STT/multimodal parallel understanding → source.json / M2 LLM narration rewrite (streaming + Levenshtein anti-paraphrase assertion <0.55) + re-dubbing / M3 visual rewrite 0-5 levels + v10 compose assembly / M4 rework subcommand four channels (CLI/utils/agent generator.rework/API async job); utils/rework.py + tests/test_rework.py 15 items; voice blacklist confirmed (jieshuo1 sentence-start leakage) → default cosy-default; docs/usage/usage-v19.md)** + **v19 burned-subtitle removal (completed 2026-11-02/03, reuses v16 ProPainter) ✅: rework --remove-sub off/auto/force; localization = unlimited-ocr multi-frame sampling ∪ white-text heuristic fallback (⚠ OCR outputs permille normalized coordinates 0-999, must map /1000; misjudging it as a 1080 space caused two rounds of rework; the heuristic fails on gray text on dark panels / night-scene highlights); part-level 704p removal, final acceptance zeroed text-line white-pixel peaks in 8 segments; four-channel wiring + 23 tests** + **v20 in-generation review (review while generating, formerly v21) ✅ (closed 2026-11-04: comfy_preview PreviewListener/WS latent2rgb preview frames + interrupt_if_running ownership check + live_audit_patch instance-level patch (zero changes to generation code) + live_auditor coarse-review throttling (qwen3.8 review, ≤3 times/shot) + Pipeline wrapper early-stop loss-cutting with seed swap + switch on three channels (config v20_live_audit.enabled default false / CLI --live-audit / API live_audit) + UI task card live preview frames + verdict (GET /api/tasks/{id}/preview); M2 same-topic comparison ON only +3.7% duration (coarse reviews hidden inside the generation window); M3 full-chain real run auto_20261104_153353 (3 shots × 3 coarse reviews all pass, verified via live UI cards); **follow-up verification 2026-11-05**: 15 natural coarse reviews all pass (latent2rgb cannot see semantic details, the coarse review only blocks catastrophic collapse; the final review caught a real score 2 error = one person with a Korean banner vs five people with a Chinese banner); light review runs in parallel with the next shot and doesn't retry on fail (design trade-off; retries only on the full-review path); container images must install all dependencies (8894/9401 share the DB and race for tasks; missing websockets once failed at shot1); docs/usage/usage-v20.md)** (v2 long video + v2.1 backlog + v3 M0-M7 + v4 M1-M6 + v5 M1-M4 + v6 M1-M4 + v7 frontend M1-M4 + v10 + t2c), **to develop**: nothing (v14 social media was delivered 2026-11-05 from a teammate's repo ✅, not merged here; all milestones closed). **v21 delivery form ✅ closed 2026-11-05 (formerly v18, 1.0.0)**: M0 doctor ✅ `core/doctor.py` + `vidance doctor` + `GET /api/doctor` (tests 13) / M1 deployment tiers ✅ (five-tier ladder + Docker compose) / M2 one-click install ✅ `deploy/install.sh` probe → tier selection → start containers → smoke test / M3 user-facing details ✅ `vidance init` wizard + `core/diagnose.py` failure self-diagnosis (hints attached to the tasks API + UI 💡) + `core/cleanup.py` (task dirs + protects running ones; the old clean missed task dirs, now fixed) + /api/version|settings|clean + ⚙ System section (tests 24) / M4 ✅ `--version` + CHANGELOG.md + usage.md tier-based user manual + SKILL demos ×6 (templates ×4 + healing + showcase, real runs placed next to the yamls) (2026-09-26 renumbering + 2026-09-30 added v19-v21 + 2026-10-01 second renumbering + v13/v15 closed, v14 handed to a teammate + 2026-10-02 v16 M0-M4 + 2026-10-30 v17 closed + 2026-10-31 v18 closed + 2026-11-02 v19 closed + 2026-11-04 v20 closed: numbers in parentheses are the original IDs).

**Version roadmap**: v4 marketing-account pipeline (fast/hot crawl-to-video) → v5 editing effects → v6 prompt multi-turn clarification (ask + dialog API) → v7 frontend agent WebUI (:8894/ui) → **v8 frontend enhancements** (asset library/storyboard preview/progress visualization/timeline display) → **v9 API standardization** (multi-vendor adapters/capability discovery/usage throttling/OpenAPI) → **v10 compositing & effects** (the OpenCut timeline approach, backend CLI callable by the LLM) → **v11 multi-agent** (three-layer Agent decoupling, formerly v13) → **v12 three-row orthogonal** (make unified entry, formerly v17) → **v13 lightweighting ✅** (four model-free lines: marketing-account/SVG/PPT/Blender 3D; model acceleration deferred as needed, formerly v15) → **v14 social media** (publishing channels + IM bot gateway, 🔗 handed to a teammate, formerly v11) → **v15 LLM-generated PPT ✅** (HTML slides → rendered mp4/PDF, formerly v20) → **v16 video processing & editing ✅** (SAM2 segmentation/cutout/mosaic/inpaint/colored multi-object/YOLO auto Grounded-SAM/box prompts + video bidirectional tracking + v16.x generative editing: M5 FLUX Fill re-render/M6 Union ControlNet canny/M7 Wan2.1 VACE reference-image-to-video/M8 Qwen-Image-Edit instruction editing, formerly v19) → **v17 open-source consolidation ✅** (buffer session asset layer/@references/checkpoint resume sha256 fingerprints/JSON tolerance/RAG/five-dimension prompts/script breakdown novel2video/embeddings/retry, formerly v12, closed 2026-10-30) → **v18 long-video quality** (keyframe-driven/one-shot/hierarchical consistency, formerly v14) → **v19 rework** (video-link rework: rewritten narration/re-dubbing/LUT/BGM + burned-subtitle removal + keyframe mode (still-frame subtitle removal + Ken Burns + RIFE morph) + first-person reversal, formerly v16) → **v20 in-generation review ✅** (tensor review while generating: latent preview coarse review + early-stop loss cutting, sidecar + switch default off, formerly v21, closed 2026-11-04) → **v21 delivery form** (deployment tiers/one-click install, formerly v18). See docs/roadmap.md for details.

v1 character-anchor flow: FLUX generates the character image → TripoSplat rebuilds 3DGS → each shot's RenderSplat renders a reference frame by angle → Wan I2V generates.

**t2c natural language → command** (integrated 2026-09-24, see docs/design/v-t2c.md):
The "translation layer" of the self-built agent_loop — a user's spoken Chinese is converted into Vidance commands by a fine-tuned mt5-small model (`t2c/model`, runs on CPU). Chain: `/api/chat` (LLM judges intent; chitchat answered directly / creation returns `[[VIDEO:concept]]`) → v6 dialog multi-turn clarification → `POST /api/t2c` (`translate(text)` in `utils/t2c_server.py`) → command → frontend displays + ▶ executes. Test directly on the web at `:8894/ui`; CLI: `python utils/t2c_server.py '帮我auto生成城市夜景'` → `python core/vidance.py auto "城市夜景"`. Plan: once all commands (incl. v10 editing) are in place, retrain for full coverage.

**v2 long video** (M1-M5 all done):
- **M1 RIFE optical-flow interpolation**: inter-shot flow transitions (rife_v4.26, multiplier=8, 0.375s@24fps)
- **M2 per-shot parallel prefetch**: ThreadPool prefetches FLUX reference frames + TTS dubbing in parallel (no conflict with the serial Wan I2V)
- **M3 ffmpeg color grading**: 6 3D LUTs (cinematic/warm/cool/vintage/vivid/soft), pure numpy generation, LLM picks the style automatically
- **M4 BGM ducking**: 5 BGMs (calm/uplifting/mysterious/dramatic/playful), pure numpy synthesis, sidechaincompress ducking
- **M5 faster-whisper STT**: large-v3-turbo model, transcribes the final audio → SRT → re-burns subtitles

**v2.1 backlog** (all done):
- `--duration N` dynamic shot count + `--slowmo N` global slow motion + per-shot `transition_out` + `concat` subcommand

**v3 2D→3D→novel views** (M0+M1+M2+M3+M4+M5+M6+M7 done, M8 pending):
- **M0 headless rendering** ✅: trimesh 5.1.0 + pyrender 0.1.45 + EGL backend, 4×4090 headless GLB→IMAGE rendering works
- **M1 Hunyuan3Dv2 mesh reconstruction** ✅: DiT turbo (4 steps, ~61s) + VAE + DINOv2-giant, doubao.jpg→257K-vert GLB, pyrender 4-angle preview passed
- **M2 multiview** ✅: 3 views (front/left/back) cropped from doubao.jpg's tri-view → 206K-vert GLB (~22s warm), aspect 1.69 vs 1.02 single-image, main connected component 63% vs 38% — multiview clearly beats single image
- **M3 mesh_render wrapper** ✅: `utils/mesh_render.py` (260 lines), 3-layer API + 3-point lighting + depth-based alpha + background compositing, API aligned with splat_renderer, 8 tests all pass (832×480 renders at 0.79s each)
- **M4 scene anchors** ✅: FLUX→Hunyuan3Dv2→mesh_render full-chain verification, 2 scenes (isolated cabin 238K verts + snowfield environment 411K verts), 8-angle render consistency confirmed
- **M5 character dual path** ✅: `--character-mode mesh` wired into the pipeline, `utils/hunyuan3d.py` client (single + multiview → GLB), `_build_character_anchor` + `_generate_scene_ref` mesh branch, doubao.jpg→282K-vert GLB 28.8s + 4-angle preview + composited reference frame verified
- **M6 asset registry** ✅: `utils/asset_registry.py` (CRUD + fuzzy search + CLI), pipeline integration (look up the registry before character mesh/3dgs reconstruction, auto-register after), `--no-asset-reuse` flag, `.opencode/agents/asset.md` subagent, 14 tests all pass
- **M7 end-to-end integration** ✅: `auto --character-mode mesh` full chain works (FLUX tri-view → Hunyuan3Dv2 multiview → mesh_render → Wan I2V → RIFE slowmo → LUT → BGM → composite), 3 shots 12.8s output `output/20260912_183520/final.mp4`. **Fixes**: RIFE slowmo (4 frames→233 frames, concat demuxer→image2 demuxer), LLM review model (claude-haiku-4-5 delisted → qwen3.8-chat), review timeout (60s→180s + retries=2), multiview mesh (single-image Z=0.009 paper cutout → tri-view Z=1.56 real 3D). Review system effective: character score=3, Shot 2 score=3.2/4 (retry), Shot 3 score=6/5/5 (retry)

**v4 marketing-account pipeline** (M1-M6 done; ~~batch integration/unattended~~ confirmed skipped; no publishing — humans curate and upload manually):
- **M1 crawler + topic scouting** ✅: `utils/crawler.py` (Bilibili API + Weibo + Zhihu + Baidu + RSS + yt-dlp multi-source trending fetch) + `llm.scout_topics()` (trending → ranked concept candidates) + `.opencode/agents/scout.md` subagent + `.opencode/skills/topic_scouting/SKILL.md`. E2E verification: 45 trending items (15 each from Bilibili/Weibo/Zhihu) → 5 concept candidates (scores 9/8/8/7/7), concepts visually concrete with creative trending angles
- **M2 async task queue** ✅: `core/scheduler.py` (`TaskQueue` SQLite persistence + `Scheduler` thread polling + CLI) + `core/api_server.py` (FastAPI :8894, POST/GET/DELETE /api/tasks + /api/health + /api/scout + /api/dashboard) + `core/dashboard.py` (self-contained HTML dashboard, base64 thumbnails, 30s auto-refresh). `pipeline.py` + `vidance.py` gained `--task-id`. E2E verification: 3 tasks submitted → serial execution (max_concurrent=1) → 3 videos (shiba 12.7s / cyberpunk 11.4s / little chef 11.9s), visual artifacts `output/dashboard.html` + `output/m2_results.html`
- **M3 production voice cloning** ✅: `utils/voice_clone.py` (Bilibili search API with random buvid3 to beat anti-crawl → yt-dlp download isolated by bvid → faster-whisper VAD segmentation (skips pure ♪ instrumentals, takes 8s windows from long blocks, mean-quality gate -32dB) → 24kHz mono 16bit ffmpeg conversion → STT transcribes prompt_text → registered under voices/{name}/ as cosy-{name} → test synthesis stored in voice_samples/). TTS server gained `POST /voices/reload` hot reload (register new voices without restart). API server gained `POST /api/clone_voice` async clone endpoint + `GET /api/voices`. E2E verification: all 3 voice clones passed (xinwen1 news anchor / jieshuo1 film narration / jilupian1 documentary, 21-30s each), STT transcription re-verified content matches, registered voices callable by name
- **M4 FunClip smart clipping** ✅: `utils/funclip.py` (FunASR `speech_paraformer-large-vad-punc` transcription + character-level timestamps + character-level aggregation into sentences + ffmpeg time-range clipping/concat + LLM semantic keep/drop). Three-subcommand CLI (transcribe/clip/smart). **GPU fix**: on a saturated card (GPU0 fully occupied by H3) even the CUDA context can't be created (`cudaMemGetInfo` OOMs directly); `device='auto'` probes card by card, skips cards where a context can't be created, and picks the card with the most free VRAM. E2E verification: 4-sentence jellyfish script into 12.6s of audio, instruction "keep only the sentences about light" → LLM kept 2 sentences (incl. one semantically containing "点亮之光") and dropped 2 → 3.88s output, transcription re-verified content matches; after the CLI OOM fix all 14 chars correct
- **M5 material crawling** ✅: `utils/asset_crawler.py` (Bing Images async API search/download + magic-bytes validation + md5 dedup + LLM concept→keywords + incompetech BGM searched by feel, downloaded with loudnorm → bgm/{mood}.wav) + four-subcommand CLI (keywords/images/refs/bgm). **Corrections**: pieces.json's duration field is `length` (HH:MM:SS format), not duration; filename already carries the `.mp3` suffix, don't append again (double-append 404s); Baidu Images acjson needs a real cookie — deprecated; Bing `cn.bing.com/images/async` is directly reachable. E2E verification: concept "sunrise fox on a snowy mountain" → LLM 3 keywords → 6 reference images (19-129KB); `bgm epic --list` 5 candidates (58-62s) → crawled epic.wav (61.4s 10.8MB loudnorm); pieces.json persisted to bgm/pieces.json
- **M6 fast marketing-account pipeline** ✅: `utils/fastline.py` (`FastLine`) + `vidance.py fast/hot` subcommands — **skips video models**: LLM plans N narration segments + per-segment camera moves (pan/zoom-in/zoom-out) → images (`--images-source crawl` Bing crawl + **multimodal relevance check** auto-deletes irrelevant images, tops up with FLUX if short; or `flux` text-to-image per segment; or `--images` self-supplied) → ffmpeg zoompan (Ken Burns) → per-segment TTS → crossfade concat → LUT/BGM/STT reusing PostProcessor. **Trending-topic source**: `--source-topic` + `--trend-date` written into meta + a drawtext corner badge at the top of the video (independent of subtitles, no misalignment). `--slowmo N` additionally emits `final_slow.mp4` (RIFE, video-only); the original `final.mp4` is always kept. **`hot` subcommand**: crawl live trending → LLM scout auto-selects the topic → fast in one step. **FLUX image quality gate**: `optimize_fastline_prompt()` converts Chinese narration → English FLUX prompt (fixes "stuffing Chinese in generates unrelated images"); after generation `assess_image_relevance` checks fit to the narration, regenerates ≤2 times on failure (field-tested: backpack frog score=10 / programmer deletes 89TB 3 images 9/7/9). E2E verification: scout picked "Travel Frog shut down" at 9 points from 40 real trending items, crawl verification filtered 3 irrelevant images (hospital/charger/recycling sign all score=1.0) with FLUX topping up; trending badge + subtitles aligned at 0s. **Corrections**: ① added `epic` to `--bgm` choices; ② `_image_to_base64` supports RGBA/P/LA/PA→RGB (fixes `cannot write mode P as JPEG`); ③ RIFE slowmo carries no audio track (the helper re-encodes video only); ④ **service-default fallbacks (2026-09-15)**: TTS 9880 unavailable → silent-audio fallback + prints `⚠ [TTS 缺省]` (with a startup hint); crawler down → switch to FLUX, FLUX down → solid-gradient placeholder image (`_gen_placeholder_image`, watermarked with the concept) + `⚠ [图源/FLUX 缺省]`; plan_narration/select_lut/select_bgm fallbacks unchanged — **with all GPU services off, a fast task still completes via degradation without crashing** (verified: Pexels normal + silence + placeholder → 6.0s completed)

**v5 editing effects** (M1-M4 done, 2026-09-14):
- **M1 effects library** ✅: `utils/effects.py` (8 in-shot effects: flash/punch_in/glitch/grain_vignette/speed_ramp/freeze_zoom/wipe/zoom, pure ffmpeg yuv420p) + single-clip CLI
- **M2 xfade transitions** ✅: `transition()` two-clip xfade + `concat_with_transitions()` single filter_complex chaining N clips (fade/slide/wipe/pixelize/circleopen etc., 30+ kinds)
- **M3 LLM auto-selection** ✅: `llm.select_effects()` picks effects by each shot's content/mood + inter-shot transitions (`fast/hot --effects auto`, applied by `apply_effects_to_clips` in the pipeline, falls back to the original clips on failure)
- **M4 end-to-end** ✅: `fast "夜色中城市霓虹与火光" --effects auto` 3 shots → LLM picked glitch/grain_vignette/freeze_zoom → 9.0s output; effects/transitions recorded in meta. xfade chained concat of 3 clips 5.2s verified
- **Corrections**: ① flash uses `fade=in` solid-color fade-in (fixes eq/drawbox syntax errors); ② glitch dropped rgbashift (this ffmpeg lacks the filter) in favor of noise+hue jitter; ③ wipe/zoom warp expressions use correct `t`/`on` usage

**v6 prompt multi-turn clarification** (M1-M4 done, 2026-09-14; 2026-09-15 fixed the multi-turn loop):
- **M1 completeness assessment** ✅: `llm.assess_completeness()` 6 dimensions (subject/scene/emotion/style/duration/cinematography) + missing list + follow-up suggestions (exceptions treated as complete as fallback). **Criteria**: subject/scene/emotion are required and need explicit description (noun-only implication doesn't count); style/duration/shot are also asked about — **COMPLETE only when all 6 dimensions are filled** (the prompt grows longer and more detailed through multi-turn probing); temperature=0.1
- **M2 dialog state machine** ✅: `utils/dialog.py` (DialogManager, OPEN/COLLECTING/COMPLETE/LOCKED, ≤3 rounds to prevent infinite loops, SQLite `output/tasks.sqlite` dialogs table)
- **M3 CLI `ask`** ✅: `vidance.py ask "concept"` interactive multi-turn probing → enhanced concept (`--out` saves to a file); **each round asks all current questions one by one and merges them into a single reply** (joined with `；`) → one re-assessment; piped answers verified; `dm.locked_concept` concatenates round answers ("whatever" skips)
- **M4 API three endpoints** ✅: `core/api_server.py` gained `POST /api/dialog/start` (returns missing/questions) + `GET /api/dialog/{dialog_id}` + `POST /api/dialog/{dialog_id}/reply` (each round returns the enhanced concept) for the v7 frontend; start/reply verified with curl
- **Fixes (2026-09-15)**: ① cmd_ask's idx accumulated across rounds so only one question was asked before exit → refactored to batch-ask all per round then reply; ② optional dimensions were judged as required → missing=[] stuck in COLLECTING → COMPLETE judged only on required dimensions; ③ criteria changed from "implied counts as present" to "only explicit descriptions count" (temperature 0.3→0.1); ④ stop condition was too loose (COMPLETE once the 3 required dimensions were filled, stopping after 2 questions so the prompt never grew) → changed to **COMPLETE only when all 6 dimensions are filled**, style/duration/shot also probed, the concept grows over 2-3 rounds
- No auto-completion (rather ask more); ≤3 rounds then LOCKED forces through

**v7 frontend agent WebUI** (M1-M4 code done, 2026-09-15; browser rendering + output E2E pending GPU restoration):
- **M1 backend endpoints** ✅: `core/api_server.py` gained `GET /api/video/{task_id}` (video stream FileResponse) + `GET /api/options` (voice/LUT/BGM/effects/camera enumerations) + `GET /api/tools` (**15 commands** + parameter schema) + `POST /api/tool/{name}` (unified dispatch, shlex parses `--key value`/`-n N`/positional args) + /ui StaticFiles; `scheduler.py _run_task` gained **mode dispatch** (auto/fast/hot mapped to vidance.py subcommand args); TaskSubmit gained mode/images_source/images_count/effects/top_each/account fields
- **M2 dialog + / command completion** ✅: `ui/index.html` (self-contained 21KB, zero npm) three-column layout (left tools/task sidebar + top canvas + bottom-right input box); `/` popup (↑↓/Tab/Enter selection, no popup in the args zone); natural language → v6 dialog
- **M3 canvas** ✅: task cards polled every 2s (progress bar + stage + error) + video cards (completed auto-embeds `<video controls src=/api/video/{id}>`) + left task list (click to replay/poll)
- **M4 ask + scout integration** ✅: /ask → questions rendered → keep chatting in the input box (/api/dialog/{id}/reply) → after COMPLETE, an enhanced-concept chip offers one-click `/fast`; scout candidates with scores displayed; voices/clip (async polling)/help dispatch
- **Verification**: backend curl tests (tools **15 commands** all dispatch / options / video stream 1.7MB / ask / voices / help / video dispatch); JS node --check passed; /ui 200 (21KB); the output chain untested during GPU downtime. New query/maintenance commands are all zero-GPU (luts/moods/tasks/status/trends (crawls trending without topic selection)/clean (default keep 10))

**v1.1 improvements**:
- **I2V fix**: `WanImageToVideo` → `Wan22ImageToVideoLatent` (Wan 2.2 native 48ch latent + noise_mask inpainting), first-frame vs reference correlation 0.99+
- **character-mode switch**: `auto` (default; auto-downgrades to flux if the 3DGS review fails) / `3dgs` / `mesh` (Hunyuan3Dv2→GLB→mesh_render) / `flux` (each shot's FLUX directly generates character+scene images, no 3D reconstruction)
- **3DGS pose fix**: PCA auto-aligns the character's main axis to vertical + crop-and-ground compositing (feet on the ground, not floating)
- **3DGS rendering optimization**: floater filtering + supersampled rendering + larger Gaussian params — smoother surfaces, less noise
- **Character pose fix**: FLUX character prompt emphasizes "standing upright on the ground"; review gained a pose dimension
- Without `--character`, falls back to v0 pure T2V

## Directory structure

```
vidance/
├── opencode.json              # opencode config (agents + permissions)
├── AGENTS.md                  # this file
├── config/config.json         # runtime config (API keys, engine addresses, model names, voices)
├── core/
│   ├── vidance.py             # unified CLI entry (auto/custom/quick/concat/compose/svg/make)
│   ├── pipeline.py            # auto-mode pipeline controller (internal module)
│   ├── custom_gen.py          # custom-mode H3 ref2va generation (internal module)
│   ├── postprocess.py         # shared post-processing (RIFE/LUT/BGM/STT)
│   ├── narration.py           # v12 (formerly v17) dubbing/subtitles single implementation (Narrator: TTS three-level fallback + silence backstop + SRT)
│   ├── preflight.py           # v17 (formerly v12) task preflight (hard-dependency interception / degradable warnings; 5 subcommands --no-preflight; 6/6 tests)
│   ├── scheduler.py           # v4 async task queue (TaskQueue SQLite + Scheduler thread polling)
│   ├── api_server.py          # v4 FastAPI service (:8894; task submit/query/dashboard/scouting/clone/clipping)
│   └── dashboard.py           # v4 HTML dashboard generation (queue stats + thumbnails + scout batches)
├── utils/
│   ├── comfy_api.py           # ComfyUI HTTP client (T2V/I2V/TripoSplat/FLUX T2I/H3 ref2va)
│   ├── llm.py                 # USTC LLM client (scriptwriting/prompt optimization/review, incl. image scaling + retries)
│   ├── tts.py                 # TTS client (dual engine: edge-tts + CosyVoice)
│   ├── tts_server.py          # TTS FastAPI service (dual engine, GPU2:9880)
│   ├── splat_renderer.py      # 3DGS PLY multi-angle renderer (render_splat_at_angle + composite_bg)
│   ├── ffmpeg_tools.py        # frame extraction/SRT/compositing (incl. LUT grading + BGM ducking)
│   ├── rife.py                # v2 RIFE interpolation client (inter-shot transitions + slowmo)
│   ├── gen_luts.py            # v2 3D LUT .cube generation (6 styles)
│   ├── music.py               # v2 ambient BGM generation (5 styles, numpy synthesis)
│   ├── stt.py                 # v2 faster-whisper STT transcription (subtitle fallback)
│   ├── mesh_render.py         # v3 headless mesh renderer (pyrender+EGL, wrapped in M3)
│   ├── hunyuan3d.py           # v3 Hunyuan3Dv2 reconstruction client (single + multiview → GLB, wrapped in M5)
│   ├── asset_registry.py      # v3 asset registry (CRUD + fuzzy search + CLI, wrapped in M6)
│   ├── crawler.py             # v4 trending crawler (Bilibili API + Weibo + Zhihu + Baidu + RSS + yt-dlp, wrapped in M1)
│   ├── voice_clone.py         # v4 production voice cloning (Bilibili search + VAD segmentation + STT transcription + voice registration, wrapped in M3)
│   ├── funclip.py             # v4 FunClip smart clipping (FunASR char-level timestamps + LLM semantic keep/drop, wrapped in M4)
│   ├── asset_crawler.py       # v4 material crawling (Pexels images first + Bing fallback + LLM keywords + incompetech BGM, wrapped in M5)
│   ├── fastline.py            # v4 M6 fast marketing-account pipeline (images + zoompan camera + RIFE, skips video models, wrapped in M6)
│   ├── effects.py             # v5 editing effects (8 in-shot effects + xfade chained transitions, M1-M4 implemented)
│   ├── dialog.py              # v6 prompt multi-turn clarification state machine (DialogManager, SQLite, M1-M4 implemented)
│   ├── compose.py             # v10 timeline compositing & effects (OpenCut approach, backend CLI; M1-M8 implemented: keyframes/masks/sticker track/split)
│   ├── buffer.py              # v17 (formerly v12) M1 session buffer BufferManager (sanitize/fencing/search cursor/TTL cleanup; 26/26)
│   ├── retry.py               # v17 (formerly v12) M7 tenacity retry, three strategies (llm/tts/comfy; 4xx raises directly; 13/13)
│   ├── embed_index.py         # v17 (formerly v12) M7 MiniLM ONNX local embedding EmbedIndex (brute-force cosine + npz persistence; 13/13)
│   ├── subtitle_correct.py    # v17 (formerly v12) MPT-inspired subtitle Levenshtein correction (hallucination discarding, wired into run_stt; 20/20)
│   ├── material_cache.py      # v17 (formerly v12) MPT-inspired material URL-md5 cache + 24h TTL search (wired into asset_crawler; 20/20)
│   ├── rag.py                 # v17 (formerly v12) M5b RAG indexing/retrieval (documents + novel chapters; v18 added add_chunks explicit chunking — one card per event arc)
│   ├── t2c_server.py          # t2c inference wrapper (translate(text)→command, in-process singleton/optional HTTP)
│   ├── svg_llm.py             # v13 (formerly v15) concept→LLM→animated SVG (S1)
│   ├── svg_pipeline.py        # v13 (formerly v15) SVG→mp4 (headless browser frame-by-frame, pure CPU; S2 single frame/S3 frame extraction/S4 video)
│   ├── sam_edit.py            # v16 (formerly v19) SAM2 editing: segment/cutout/re-bg/mosaic/inpaint/colored multi-object/YOLO auto/box prompts + video bidirectional tracking + qwen_edit instruction editing (GPU tier)
│   ├── ppt_llm.py             # v15 (formerly v20) concept→LLM plans deck JSON→HTML slides (template rendering + svg_chart bar/line/pie)
│   ├── ppt_pipeline.py        # v15 (formerly v20) deck→mp4/PDF/PNG (PptLine multi-format delivery, xfade between pages + TTS narration, pure CPU)
│   ├── blender_llm.py         # v13 blender simple version: concept→LLM plans 3D scene JSON (templates title3d/shapes/bars3d + colors + object/material/keyframe normalization)
│   ├── blender_pipeline.py    # v13 blender simple version: bpy 5.0 in-process scene build→EEVEE frame-by-frame render→ffmpeg stitch→TTS→mp4 (BlenderLine)
│   ├── poster_llm.py          # v22 poster line: concept→LLM plans poster JSON (title/tagline/plate prompt/creature zones, zone whitelist + normalization)
│   ├── poster_pipeline.py     # v22 poster line: FLUX plate→Grounded-SAM cutout (luminance-keying fallback)→PIL parameterized compositing→jpg (PosterLine)
│   ├── h3_prompt_video.py     # whole-prompt + reference image → single H3 ref2va shot (native audio direct out)
│   ├── oneshot.py             # v18 (formerly v14) one-shot (✅ chained I2V last-frame feedback + LLM camera chain + seam assertion; auto --oneshot --duration N)
│   ├── notify/                # v14 (formerly v11) social media/IM gateway (base/wecom/feishu/dingtalk/factory; 🎯 planned)
│   ├── luts/                  # v2 LUT file directory (cinematic/warm/cool/vintage/vivid/soft .cube)
│   └── workflows/
│       ├── wan_t2v.json       # Wan T2V workflow template
│       ├── wan_i2v.json       # Wan I2V workflow template (12 nodes, Wan22ImageToVideoLatent)
│       ├── triposplat.json    # TripoSplat single-image→PLY workflow (13 nodes)
│       ├── flux_t2i.json      # FLUX T2I workflow template (10 nodes)
│       ├── rife_transition.json  # v2 RIFE interpolation workflow (7 nodes)
│       ├── hunyuan3d_single.json  # v3 Hunyuan3Dv2 single-image→mesh workflow (M1 verified)
│       └── hunyuan3d_multiview.json  # v3 Hunyuan3Dv2 multiview→mesh workflow (M2 verified)
├── agents/                    # v11 multi-agent (formerly v13): D/G/P/V physical layering + thin wrappers (docs/design/v11-design.md)
│   ├── base.py                # TaskResult + @register registry + run_agent (timing/fallback/persistence)
│   ├── blackboard.py          # agent_runs blackboard (reuses output/tasks.sqlite)
│   ├── runtime.py             # load_all + run_chain (${ctx.key} artifact references)
│   ├── director/              # D: agents.py (scriptwrite/scout/pick-3) + tools/dialog.py
│   ├── generator/             # G: agents.py (svg/fast/wan_t2v) + tools/ (comfy_api/fastline/svg family/rife/3d family/vendor…)
│   ├── post/                  # P: agents.py (tts/compose/lut/bgm/subtitle burn/stt/fx/transition) + tools/ (effects/compose/…)
│   ├── audit/                 # V: agents.py (4 review agents + review_ensemble multi-vote) + tools/
│   └── common/                # shared: tools/ (llm/tts/config_loader/crawler/crawler family/voice_clone/t2c_server)
│   (all 27 original utils/ modules remain as thin-shell forwarders, zero breakage of old imports/CLIs; tts_server.py and the data directories are not migrated)
├── t2c/                       # t2c natural language→command (fine-tuned mt5-small model + inference scripts + README)
├── deploy/                    # v21 (formerly v18) deployment tiers (VIDANCE_TIER=none|flux|wan|h3|full; Dockerfile + Dockerfile.comfyui + docker-compose.yml five profiles + README; API defaults to 9400)
├── dist/images/               # offline delivery image bundles (docker save artifacts latest/rag/update.tar.gz, *.tar.gz gitignored; all five tiers share the single latest image)
├── ui/                        # v7 frontend (self-contained index.html, zero npm, at :8894/ui)
├── assets/                    # project images (v0-v9 evolution screenshots); defense PPT + ppt_media/ extracted assets gitignored (local staging only, select ones go into docs/)
├── docs/assets/               # README showcase assets (hero.gif + demo thumbnails + UI screenshots)
├── voices/                    # custom CosyVoice cloned-voice material directory
├── bgm/                       # v2 custom BGM material directory (drop in {mood}.wav to use automatically)
├── .opencode/
│   ├── agents/{director,reviewer,asset,scout}.md
│   └── skills/{scriptwriting,review,topic_scouting,novel_to_video}/SKILL.md
├── SKILL/                     # v17 (formerly v12) skill assets (one of two locations, command layer)
│   ├── templates/             # M5 five-dimension prompt templates (cinematic/documentary/anime90s/guofeng .yaml, discovered on disk immediately)
│   └── commands/novel2video/  # M6 novel→video pipeline scripts (m6_breakdown_test/m6_render_v3/m6_archive_buffer/m6_wardrobe_test + README)
├── docs/                      # docs (roadmap + reports; usage/ guides + design/ design docs + research/ surveys + instructions/ command library & deployment + example/ samples + archive/ historical drafts)
│   ├── usage/                 # usage guides (usage.md main entry + usage-v0/v1/v2/v3/v4/v6/v7/v10/v-svg.md per-version tools)
│   ├── design/                # design docs (v0-v18 design + v12-modules + hierarchy + v-t2c + v-svg-pipeline)
│   ├── research/              # research (mpt-research + bigbanana-research)
│   └── instructions/          # command library (commands.json + compose commands) + deployment (deploy-tiers/deployed-models)
├── voice_samples/ → /mnt/dataset/...  # voice audition samples (symlink)
└── output/                    # finished videos + metadata (real directory; task = output/{task_id}/, output final.mp4)
```

## Run commands

### Unified entry `core/vidance.py` (recommended)

Four subcommands: `auto` (LLM scriptwriting + generation + post), `custom` (reference images + script → H3 → post), `quick` (pure T2V), `concat` (multi-video stitching).

```bash
# ── auto: concept → LLM scriptwriter → Wan/FLUX generation → post ──
# v2 full features: RIFE transitions + parallel prefetch + LUT grading + BGM ducking + STT subtitles
python core/vidance.py auto "雪山日出：小狐狸的冒险" --character "红色小狐狸" --character-mode flux --stt

# auto mode (default 3DGS→flux downgrade)
python core/vidance.py auto "一只猫在月球上跳舞" --character "穿宇航服的白猫"

# Specify grading style and BGM mood
python core/vidance.py auto "深海探险" --character "蓝色水母" --character-mode flux --lut cool --bgm mysterious

# Long-form mode (dynamic shot count, target 60s → ~15 shots)
python core/vidance.py auto "深海探险" --character "蓝色水母" --character-mode flux --duration 60

# Global slow motion (all shots 2x slower)
python core/vidance.py auto "概念" --character "角色" --slowmo 2

# Disable some features
python core/vidance.py auto "概念" --character "角色" --no-rife --no-color --no-bgm

# ── custom: reference images + pre-written script → H3 ref2va → post ──
python core/vidance.py custom --ref input/doubao.jpg --ref input/naiwa.jpg --script input/prompt1.txt

# custom + post-processing
python core/vidance.py custom --ref input/doubao.jpg --ref input/naiwa.jpg --script input/prompt1.txt --lut cinematic --bgm dramatic --stt

# custom hi-fi mode (2048px reference images, 2-3x slower)
python core/vidance.py custom --ref input/doubao.jpg --script input/prompt1.txt --ref-image-size max

# ── quick: pure T2V, no character, no post ──
python core/vidance.py quick "一只猫在月球上跳舞"

# ── concat: multi-video stitching ──
# Hard-cut stitch (ffmpeg stream copy, fastest)
python core/vidance.py concat clip1.mp4 clip2.mp4 clip3.mp4 -o merged.mp4 --transition cut
# RIFE flow transitions (needs the GPU2 ComfyUI 8189 online)
python core/vidance.py concat clip1.mp4 clip2.mp4 clip3.mp4 -o merged.mp4 --transition rife
# Crossfade
python core/vidance.py concat clip1.mp4 clip2.mp4 -o merged.mp4 --transition crossfade --crossfade-duration 0.5
```

**Parameter quick reference**:

| Parameter | auto | custom | quick | concat | Description |
|------|:----:|:------:|:-----:|:------:|------|
| `concept` (positional) | ✓ | — | ✓ | — | Video concept (Chinese) |
| `videos` (positional) | — | — | — | ✓ | List of videos to stitch |
| `-o/--output` | ✓ | ✓ | ✓ | ✓ | Output path (relative → output_dir) |
| `--character` | ✓ | — | — | — | Character description (Chinese) |
| `--character-mode` | ✓ | — | — | — | auto/3dgs/mesh/flux |
| `--no-asset-reuse` | ✓ | — | — | — | Disable asset-registry reuse |
| `--voice` | ✓ | — | ✓ | — | TTS voice |
| `--duration` | ✓ | — | — | — | Target total duration (seconds), dynamic shot count |
| `--slowmo` | ✓ | — | — | — | Global slow-motion multiplier |
| `--ref` | — | ✓ (repeatable) | — | — | Character reference image |
| `--script` | — | ✓ | — | — | Storyboard script path |
| `--ref-image-size` | — | ✓ | — | — | match/max |
| `--transition` | — | — | — | ✓ | cut/rife/crossfade |
| `--crossfade-duration` | — | — | — | ✓ | Crossfade duration |
| `--lut` | ✓ | ✓ | — | — | LUT style |
| `--no-color` | ✓ | ✓ | — | — | Disable grading |
| `--bgm` | ✓ | ✓ | — | — | BGM mood |
| `--no-bgm` | ✓ | ✓ | — | — | Disable BGM |
| `--no-rife` | ✓ | ✓ | — | — | Disable RIFE transitions |
| `--stt` | ✓ | ✓ | — | — | STT subtitle alignment |

# ── svg: v13 (formerly v15) SVG pipeline (concept→LLM generates SVG→frame-by-frame render→mp4, pure CPU) ──
python core/vidance.py svg --concept "鹈鹕骑自行车"                    # one-click
python core/vidance.py svg --svg output/svg/pelican_bike.svg -o output/svg_demo/out.mp4 --duration 3
python core/vidance.py svg --svg scene.svg --still --at 1.5           # single-frame debugging
python core/vidance.py svg --svg scene.svg --frames                    # extract frames to a PNG sequence

# ── ppt: v15 (formerly v20) PPT pipeline (concept→LLM plans→HTML slides→rendered mp4/PDF/PNG, pure CPU) ──
python core/vidance.py ppt "Vidance 项目介绍" --video                  # one-click: deck.html + final.mp4 (TTS narration)
python core/vidance.py ppt "季度总结" --say "第一页旁白" --say "第二页旁白" --video -n 2  # manual outline with per-page narration
python core/vidance.py ppt --deck output/ppt_xxx/deck.html --video --pdf --pngs       # render mode: multi-format delivery
python core/vidance.py ppt "主题" --pdf -n 5 --transition wipe --voice cosy-default    # PDF 5 pages + specified transition/voice
python core/vidance.py blender3d "Vidance 3D 展示" --duration 6 --voice cosy-default   # one-click: LLM plans the 3D scene + bpy EEVEE render + TTS → final.mp4
python core/vidance.py blender3d --scene output/blender3d_xxx/scene.json              # render mode: rebuild from scene.json

# ── poster: v22 promo poster (concept→LLM plans→FLUX plate + SAM cutout→PIL compositing→jpg) ──
python core/vidance.py poster "紫色雨夜霓虹月亮下的红蓝猫" --title VIDANCE --tagline "从一句话，到一整部片"   # one-click: output/poster*/poster.jpg
python core/vidance.py poster "主题" --url github.com/x/vidance --qr-url https://github.com/x/vidance       # footer dual URLs + QR at bottom right
python core/vidance.py poster --plan output/poster_xxx/plan.json --bg bg.png --creatures c1.png,c2.png      # render mode: re-layout existing plate/creatures
python agents/generator/tools/poster_llm.py "主题" -o /tmp/plan.json                                       # single step: JSON plan only

# ── edit: v16 (formerly v19) SAM2 editing (image 7 modes / video bidirectional tracking; GPU tier) ──
python core/vidance.py edit cutout 图.jpg --point 311,175 -o out.png                  # cut out the subject → transparent PNG (omit --point for auto subject)
python core/vidance.py edit inpaint 图.jpg --point x,y -o out.png                     # watermark removal / partial replace (cv2 TELEA)
python core/vidance.py edit mosaic 图.jpg --point x,y --mode pixel                    # region mosaic (pixel/blur)
python core/vidance.py edit replace_bg 图.jpg --point x,y --bg blur                   # background replace (solid hex or blur)
python core/vidance.py edit visualize 图.jpg                                          # colored multi-object visualization (SAM demo style, omit --point for auto)
python core/vidance.py edit visualize 图.jpg --yolo --classes "cat,dog"               # YOLO auto-detect → SAM box prompts (Grounded-SAM, labels drawn)
python core/vidance.py edit visualize 图.jpg --box "x1,y1,x2,y2;x1,y1,x2,y2"          # box prompts, multi-object (boxes beat points on large objects: potted plant 17.5%→46%)
python core/vidance.py edit video in.mp4 --point x,y --op mosaic -o out.mp4           # video propagation: first-frame point prompt, per-frame mosaic/re-bg
python core/vidance.py edit video in.mp4 --point "x1,y1;x2,y2" --op color             # video colored multi-object (each point independently tracked with its own color)
python core/vidance.py edit video in.mp4 --point "x1,y1;x2,y2" --op color --frame 30  # propagate bidirectionally from prompt frame 30 (more accurate when both animals co-appear)
python core/vidance.py edit video in.mp4 --yolo --frame 30 --op color                 # YOLO detection frame → box prompts → bidirectional tracking
# ── edit generative enhancements (v16.x M5-M8; needs flux 8192 / wan 8189 online) ──
python core/vidance.py edit inpaint 图.jpg --box "x1,y1,x2,y2" --engine flux --prompt "a wooden table" -o out.png   # M5 Fill re-render inside the mask (--point/--box/--yolo all work)
python core/vidance.py edit replace_bg 图.jpg --box "x1,y1,x2,y2" --engine flux --prompt "a sunny beach" -o out.png # M5 generative re-bg (mask inverted)
python core/vidance.py edit inpaint 图.jpg --box "x1,y1,x2,y2" --engine flux --prompt "a golden retriever puppy" --controlnet canny --controlnet-strength 0.55 -o out.png  # M6 structure-preserving species change
python core/vidance.py vace ref.png "a dog running on grass" --length 81 -o out.mp4   # M7 VACE reference-image-to-video (480x832@16fps)
python core/vidance.py edit instruct 图.jpg --prompt "把猫换成狗" -o out.png           # M8 instruction-based editing (Qwen-Image-Edit, Chinese instructions, no mask needed)

> The old entries `python core/pipeline.py ...` and `python core/custom_gen.py ...` still work (backward compatible), but `vidance.py` is recommended.

### Starting model services (recommended: one-click script)

```bash
cd /mnt/disk_sdb/zxy/vidance && ./start_services.sh          # start the default set (h3/wan/flux/tts/api)
./start_services.sh start h3d        # additionally start Hunyuan3Dv2 (used by v3 mesh)
./start_services.sh stop             # stop everything
./start_services.sh restart          # restart
./start_services.sh status           # ports/processes/VRAM
./start_services.sh test             # per-service connectivity + LLM + TTS synthesis self-check
./start_services.sh logs tts         # follow logs
```
> The script header has full comments (service↔port↔GPU mapping, ComfyUI must not use `--cuda-device`, edge-tts external-network issues, etc.).
> Ports: h3 8188(GPU0) / wan 8189(GPU2) / flux 8192(GPU3) / hunyuan 8190(GPU3, mutually exclusive with flux) / h3d 8193(GPU1) / tts 9880(GPU2) / api 8894(CPU).
> Models load on demand; a ComfyUI start only takes a few hundred MB; TTS loads CosyVoice at startup (~28s).

### Starting the TTS service (manual, equivalent to the script)
```bash
conda activate cosyvoice
CUDA_VISIBLE_DEVICES=2 TTS_FP16=1 python utils/tts_server.py &
```

### Single smoke-test commands (verify services are healthy)
```bash
# ComfyUI instances (200/JSON means reachable)
curl -s -o /dev/null -w "8189 wan: %{http_code}\n" http://127.0.0.1:8189/
curl -s -o /dev/null -w "8192 flux: %{http_code}\n" http://127.0.0.1:8192/
curl -s -o /dev/null -w "8188 h3: %{http_code}\n" http://127.0.0.1:8188/

# TTS health + synthesis (returning {"audio":"<base64 wav>"} means success)
curl -s http://127.0.0.1:9880/health
curl -s -X POST http://127.0.0.1:9880/tts -H 'Content-Type: application/json' \
  -d '{"text":"测试一下声音是否正常","voice":"cosy-default"}' | head -c 120
# edge-* needs external network; if unreachable (Connection timeout to speech.platform.bing.com), switch to local cosy-* voices

# Vidance API + UI
curl -s http://127.0.0.1:8894/api/health
curl -s -o /dev/null -w "ui: %{http_code}\n" http://127.0.0.1:8894/ui

# End-to-end quick video (local voice, bypassing edge's external-network issue; -n ≤5; only with all services online do you get real voice/images)
python core/vidance.py fast "深夜灯塔的故事" -n 2 --voice cosy-jieshuo1
```

### Single-step operations
```bash
# Scriptwriting
python utils/llm.py --concept "概念"

# T2V generation
python utils/comfy_api.py "english prompt" -o output/clips/shot_1.mp4

# TTS dubbing (list all voices)
python utils/tts.py --list-voices

# TTS dubbing (specified voice, edge-* or cosy-*)
python utils/tts.py "中文旁白" -v edge-moe -o output/clips/shot_1.wav

# Frame extraction
python utils/ffmpeg_tools.py frames output/clips/shot_1.mp4 -n 4

# v4 trending crawler
python utils/crawler.py --top 20
python utils/crawler.py --source bilibili --top 10
python utils/crawler.py --top 20 -o output/hot_topics.json

# v4 Scout topic selection
python -c "
from utils.crawler import Crawler
from utils.llm import LLMClient
topics = Crawler().fetch_hot_topics(top_per_source=20)
candidates = LLMClient().scout_topics(topics, account_type='影视解说', n_candidates=5)
for c in candidates:
    print(f'[{c[\"predicted_score\"]}] {c[\"concept\"]}')
"

# v4 async task queue
# Start the API server (includes the scheduler, max_concurrent=1)
python core/api_server.py --port 8894

# Submit a task (CLI)
python core/scheduler.py submit "一只猫在月球上跳舞" --character "穿宇航服的白猫" --character-mode flux
# Submit a task (API)
curl -X POST http://127.0.0.1:8894/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"concept":"深海探险","character":"蓝色水母","character_mode":"flux"}'

# View the queue
python core/scheduler.py list
curl http://127.0.0.1:8894/api/tasks | python -m json.tool

# View task status
python core/scheduler.py status <task_id>
curl http://127.0.0.1:8894/api/tasks/<task_id>

# Generate the dashboard
python core/scheduler.py dashboard -o output/dashboard.html
# or visit http://127.0.0.1:8894/api/dashboard

# v4 production voice cloning
# Search for voice sources (Bilibili)
python utils/voice_clone.py search --keyword 新闻播报 --top 10
# Full clone pipeline (search → download → VAD segmentation → transcribe → register → test synthesis)
python utils/voice_clone.py clone --keyword 新闻播报 --name xinwen1 --desc "新闻播音-男声"
# Test a registered voice (samples stored in voice_samples/)
python utils/voice_clone.py test --name xinwen1
# List registered voices
python utils/voice_clone.py list
# Hot-reload new voices (no TTS server restart needed)
curl -X POST http://127.0.0.1:9880/voices/reload
# API async cloning (poll /api/clone_voice/{job_id} after submitting)
curl -X POST http://127.0.0.1:8894/api/clone_voice \
  -H 'Content-Type: application/json' \
  -d '{"keyword":"纪录片解说","name":"jilupian1","desc":"纪录片-男声"}'
```

## TTS voice conventions

Voices route to engines by prefix (service on 9880):

| Prefix | Engine | Examples |
|------|------|------|
| `edge-*` | edge-tts (Microsoft online, natural) | `edge-xiaoxiao` Xiaoxiao / `edge-moe` cute high-pitch / `edge-family` "family" style |
| `cosy-*` | CosyVoice (local GPU, clonable) | `cosy-default` / `cosy-cross` |
| `cosy-<custom>` | CosyVoice custom clone | `voices/<name>/prompt.wav` + `meta.json` (prompt_text/desc) auto-registers, or `utils/voice_clone.py clone` for fully automated crawl+clone; after adding, `POST /voices/reload` hot-reloads |

Audition samples: `vidance/voice_samples/` (17 wavs). Default voice `edge-moe` (config.json, cute high-pitch hakimi style).

## Service ports

| Service | Port | GPU | Env |
|------|------|-----|------|
| MiniMax-H3 ref2va (ComfyUI) | 8188 | GPU0 | comfyui |
| Hunyuan3Dv2 turbo (ComfyUI) | 8193 | GPU1 | comfyui |
| Wan T2V/I2V + RIFE (ComfyUI) | 8189 | GPU2 | comfyui |
| HunyuanVideo (ComfyUI) | 8190 | GPU3 | comfyui |
| FLUX + TripoSplat (ComfyUI) | 8192 | — | comfyui |
| SDXL (ComfyUI) | 8191 | — | comfyui |
| TTS dual engine (edge-tts + CosyVoice) | 9880 | GPU2 | cosyvoice |
| Vidance API (task queue + dashboard + v6/v7) | 8894 | — | comfyui |
| Vidance WebUI (v7 frontend) | 8894/ui | — | comfyui (browser) |

> H3 (8188) has GPU0 exclusively, used for custom-mode reference-image conditioned video generation. Models load on demand; the first workflow trigger takes ~46G.
> Hunyuan3Dv2 (8193) has GPU1 exclusively, the v3 3D reconstruction engine.
> Wan+RIFE (8189) has GPU2 exclusively, auto/quick video generation.
> HunyuanVideo (8190) has GPU3 exclusively, T2V alternative.
> FLUX (8192)/SDXL (8191) are **stopped**; restart when needed (FLUX needs a free card or is mutually exclusive with H3).
> ⚠️ ComfyUI must **not** be started with `--cuda-device`, otherwise it overrides the `CUDA_VISIBLE_DEVICES` env var (main.py:87 logic). Correct approach: `CUDA_VISIBLE_DEVICES=N python main.py --listen 127.0.0.1 --port XXXX`.

## Key conventions

0. **Unified output directory**: all outputs (videos/audio/GLB etc.) go under `output/{timestamp…}/` (tasks = `output/{task_id}/`, agent default = `output/agent_{ts}_{agent name}/`, svg = `output/svg{ts}/`; config `output_dir` is the single root). `/tmp` only for temporary intermediates. Agent default paths are implemented by `agents/base.py::default_out()`

1. **Random seed**: every T2V/I2V generation must use a random seed (ComfyUI cache-hit issue)
2. **Shots ≤5s**: Wan's per-call cap is 121 frames ≈ 5s@24fps
3. **Narration length**: duration × 4 chars (Chinese ≈ 4 chars/second)
4. **Review threshold**: composite score ≥7 passes, at most 2 retries, highest score kept as fallback
5. **Duration alignment**: the final video follows the dubbing duration; if visuals run short, freeze the last frame
6. **Complete metadata**: every task records meta.json (script/prompt/seed/review/timestamps)
7. **Character-anchor flow** (v1.1 + v3): pass `--character` with a character description → FLUX generates the character reference → branch by `--character-mode`:
   - `flux`: each shot's FLUX directly generates a full character+scene image → Wan I2V (no 3D reconstruction, most stable quality)
   - `3dgs`: FLUX image → TripoSplat→3DGS → each shot's RenderSplat renders by angle → composite bg → Wan I2V (all shots forced through 3DGS)
   - `mesh` (v3): FLUX image → Hunyuan3Dv2→GLB → each shot's mesh_render renders by angle → composite bg → Wan I2V (more accurate geometry, exportable)
   - `auto` (default): runs the 3DGS flow first + review_character; if it fails, auto-downgrades to flux
   - **Asset reuse** (v3 M6): mesh/3dgs modes check the asset registry before reconstruction (similarity ≥0.6 + score ≥7); on a hit, reconstruction is skipped and the preview rendered directly; after reconstruction, review ≥7 auto-registers. `--no-asset-reuse` disables
8. **Review's 5 dimensions** (v1): consistency/quality/motion/artifact/character_consistency, compared against the character reference image
9. **Review image scaling**: resize to 512px + JPEG 85% before upload (smaller payload, faster API responses)
10. **Review timeout handling**: 180s timeout + 2 retries; on failure, safe-fallback auto-pass (never blocks the pipeline)
11. **RIFE transitions** (v2): extract first/last frames between shots → RIFE flow interpolation (multiplier=8) → 0.375s transition clip, config `rife.enabled`
12. **Per-shot parallel prefetch** (v2): ThreadPool prefetches FLUX reference frames + TTS dubbing in parallel, no conflict with the serial Wan I2V
13. **LUT grading** (v2): 6 3D LUTs generated programmatically (`gen_luts.py`), LLM picks the style automatically, ffmpeg `lut3d` filter, config `color.enabled` — **default OFF since 2026-11-04** (user preference: preview frames should match the final look; keep the original generation colors; explicit `--lut warm|cool|...` still works when needed)
14. **BGM ducking** (v2): 5 BGMs synthesized programmatically (`music.py`), ffmpeg `sidechaincompress` auto-ducks BGM under narration, config `bgm.enabled`
15. **STT subtitle fallback** (v2): faster-whisper large-v3-turbo transcribes the final audio → SRT → re-burn; `--stt` switch, default off (TTS timestamps usually suffice)
16. **git belongs to the user** (user decision 2026-10-15): without the user's explicit instruction, the agent must not perform any git write operations (commit/mv/checkout/push etc.); when and what to commit is the user's call

## Python environments

- **Main env (comfyui)**: `/home/zxy/.conda/envs/comfyui/bin/python` (torch 2.13+cu130)
  - Used by: pipeline, comfy_api, llm, ffmpeg_tools, moviepy, rife, stt, music, gen_luts, **mesh_render (v3: trimesh+pyrender+EGL)**
- **TTS env (cosyvoice)**: `/home/zxy/.conda/envs/cosyvoice/bin/python` (torch 2.3.1+cu121)
  - Used by: tts_server (CosyVoice inference)
- **STT model**: `/mnt/dataset/zxy/hf_cache/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/` (int8_float16 GPU, HF_HOME points to hf_cache)
- **v3 headless rendering deps** (comfyui env): trimesh 5.1.0 + pyrender 0.1.45 + PyOpenGL 3.1.0, EGL backend (`PYOPENGL_PLATFORM=egl`)

## LLM models

| Model | Usage |
|------|------|
| deepseek-v4-flash | Scriptwriting, prompt optimization, LUT style selection, BGM mood selection |
| qwen3.8-chat | Multimodal review (main, ~30-120s/shot, supports vision) |
| deepseek-v4-flash | Scriptwriting, prompt optimization, LUT/BGM selection (text-only, no vision) |

## Known limitations (v2 + v3)

1. **3DGS character reconstruction quality remains the bottleneck** (character_consistency 2-4/10):
   - TripoSplat's 262K Gaussians render sparsely, pixel coverage 31-35% (improved after the v1.1 pose fix, was 13-26%)
   - 3DGS colors skew dark (mean 0.51 vs FLUX original 0.94), spacesuit details lost
   - **v1.1 pose fix**: `load_ply` PCA auto-aligns the character's main axis to vertical (replacing manual Y/Z swap), `composite_bg` crops the character bbox → scales to 55% of frame height → grounds at the 88% position (feet on the ground, not floating)
   - **v1.1 I2V fix**: Wan22ImageToVideoLatent (48ch + noise_mask), first-frame vs reference correlation 0.99+
   - **v1.1 mitigation**: `flux` mode skips 3D reconstruction; `auto` mode auto-downgrades to flux if the 3DGS review fails
   - **v1.1 rendering optimization**: `_filter_floaters` removes isolated Gaussians (distance >99th pct + opacity<0.03), render params min_px 3→5, gain 2→3, supersample=2 (2x render → LANCZOS downscale), LLM confirmed "noise notably reduced, surfaces smoother"
   - **Remaining issues**: 3DGS shot types are limited (full-body wide/medium only, no close-ups), reconstruction quality uneven across angles
   - **Follow-ups**: v2 explores multi-image 3D reconstruction / reference-image ControlNet / IP-Adapter character locking / surface smoothing
2. **flux-mode character consistency depends on the FLUX prompt**: side/back shots (yaw≠0) may distort the FLUX-generated character, no 3D constraint
3. **Multimodal review API latency fluctuates wildly** (12s-200s+):
   - USTC qwen3.8-chat multimodal calls take 30-120s/shot; added 180s timeout + 2 retries + safe fallback
   - Most reviews actually auto-pass (timeout degraded); only the first 2 successful calls return detailed feedback
4. **review_character timeouts**: 4× 512×512 preview images + 1 ref, large payload, usually times out to auto-pass
5. **BGM fixed to real music** (2026-09-13 fix): the original numpy program synthesis (music.py) had two problems — ① normalization bug `wave/max(1,np.max(...))*0.8` clamped the denominator with `max(1,...)` locking the peak at -18dB; ② calm/mysterious/dramatic were designed as ultra-low-frequency drones (55-82Hz), inaudible to human ears and ordinary speakers (louder volume doesn't help). **Fix**: ① music.py normalization changed to `wave/(np.max(np.abs(wave))+1e-9)*0.8`; ② downloaded 5 real instrumental tracks from incompetech.com (Kevin MacLeod, CC BY royalty-free, directly reachable), loudnorm-normalized to I≈-20 LUFS, stored as `bgm/{calm,uplifting,mysterious,dramatic,playful}.wav`; `select_bgm` automatically prefers custom_dir (no code change). Note `bgm/` holds real long tracks (59-261s); compose truncates to video length; to swap, just replace `bgm/{mood}.wav` (loudness recommended I≈-20 LUFS)
6. **LUTs are programmatically generated** (v2): numpy-generated 6 style 3D LUTs, inferior to professional LUT packs; `color.lut_dir` kept for custom paths
7. **STT off by default** (v2): TTS timestamps usually suffice; enable `--stt` only when re-alignment is needed (extra GPU VRAM + time)
8. **Video encoding uniformly yuv420p** (v2 fix): the LUT grading + STT burn ffmpeg commands all add `-pix_fmt yuv420p` for player compatibility (previously the lut3d filter produced yuv444p which some players can't play)
9. **~~Long form unverified~~ → implemented** (v2.1): `--duration N` CLI dynamically adjusts the LLM scriptwriter's shot count (`target_duration/4` shots), unlocking long-form capability
10. **~~Per-shot slow motion unwired~~ → implemented** (v2.1): `--slowmo N` global slow motion + LLM auto-annotates `shot.slowmo`, pipeline calls `RIFEClient.slowmo()` for frame multiplication
11. **~~Per-shot transition types unimplemented~~ → implemented** (v2.1): LLM annotates `shot.transition_out: "rife"|"crossfade"|"cut"`, the pipeline branches transitions by type, compose supports mixed transitions
12. **Post review 4 dimensions** (skipped in v2.1): unstable API, low ROI; per-shot review kept
13. **music subagent simplified** (v2 deviation): design §8.2 defined an independent music subagent; actually simplified to an inline LLM call in the pipeline (`llm.select_bgm_mood()`), functionally equivalent
14. **~~No `--duration` CLI~~ → implemented** (v2.1): `--duration` added to the auto subcommand
15. **concat subcommand** (v2.1 addition): `vidance.py concat` supports multi-video stitching (cut/rife/crossfade), reusable for merging existing material
16. **v3 M1 mesh is non-watertight** (v3): Hunyuan3Dv2 turbo's output mesh is non-watertight (a VoxelToMesh surface-net trait); doesn't affect rendering but affects later physics simulation/boolean ops. M2 multiview improved: main connected component 38%→63%, bbox proportions more natural (aspect 1.02→1.69)
17. **v3 pyrender material handling** (v3, ✅ handled in M3): GLB PBR materials may be partially lost in pyrender; the M3 wrapper added 3-point lighting (key+fill+ambient) and a `gray_fallback` option (override with gray material for review previews)
18. **~~v3 Hunyuan3Dv2 shares an instance with Wan~~ → separated** (v3): Hunyuan3Dv2 moved to GPU1:8193, no longer shares 8189 with Wan; 3D reconstruction and video generation can run in parallel

# v4 FunClip smart clipping (long-material semantic clipping, device='auto' picks the card)
# Transcription shows character-level timestamps
python utils/funclip.py transcribe output/clips/narration.wav
# LLM semantic clipping (one sentence describing what to keep)
python utils/funclip.py smart long.wav -i "只要讲龙的部分，去掉口误" -o dragon.wav
# API async clipping (poll /api/clip/{job_id} after submitting)
curl -X POST http://127.0.0.1:8894/api/clip \
  -H 'Content-Type: application/json' \
  -d '{"input":"/path/long.wav","instructions":"只要讲龙的部分","output":"dragon.wav"}'

# v4 M5 material crawling (reference images + BGM)
# LLM concept → image-search keywords
python utils/asset_crawler.py keywords "雪山上的日出小狐狸"
# concept → keywords → image download (one shot)
python utils/asset_crawler.py refs "雪山上的日出小狐狸" -o output/ref/ --top 2
# BGM: list candidates / download (→ bgm/{mood}.wav, --bgm epic takes effect directly)
python utils/asset_crawler.py bgm epic --list
python utils/asset_crawler.py bgm epic

# v4 M6 fast marketing-account pipeline (images+zoompan+RIFE, skips video models)
# concept → LLM narration → images → KenBurns pseudo-motion → TTS → crossfade → LUT/BGM/STT
python core/vidance.py fast "雪山日出小狐狸" -n 5                        # auto crawl + verify + auto BGM/LUT
python core/vidance.py fast "概念" --images-source flux -n 5              # FLUX text-to-image per segment
python core/vidance.py fast "概念" --bgm epic --lut warm --stt --slowmo 2 # specified BGM/LUT + STT + RIFE slow motion
python core/vidance.py fast "概念" --source-topic "热搜标题" --trend-date 2026-09-14  # trending badge + meta

# ✅ Fixed flow (one step): crawl live trending → LLM scout topic selection → video
python core/vidance.py hot -n 5 --top-each 10 --account "影视解说"

# v5 editing effects (--effects auto lets the LLM pick effects per segment)
python core/vidance.py fast "概念" --images dir/ --effects auto       # LLM picks glitch/grain/freeze etc.
python utils/effects.py apply in.mp4 --effect punch_in -o out.mp4     # single-clip effect
python utils/effects.py transition a.mp4 b.mp4 --kind slide -o out.mp4 # xfade two-clip stitch

# v11 multi-agent (formerly v13; thin-wrapper agents + chain + blackboard)
python core/vidance.py agent list                                          # 28 agents
python core/vidance.py agent run post.fx --with '{"video":"a.mp4","effect":"zoom"}'
curl http://127.0.0.1:8894/api/agents                                       # registry
curl http://127.0.0.1:8894/api/tasks/{id}/trace                             # chain trace (agent_runs)
# Queue a chain task: POST /api/tasks {"mode":"chain","chain":[{"agent":"post.lut","with":{...}}],"ctx":{},"concept":"label"}
# chain steps support ${ctx.key}/$ {as.artifact} references to previous artifacts; POST /api/agents/chain runs synchronously
# v11.1 frontend: /ui's /arch draws the layered architecture (lit at runtime), /agent list|run|chain, chain task cards embed a trace timeline

# v6 prompt multi-turn clarification (asks follow-ups when info is missing; the enhanced concept can feed auto/fast)
python core/vidance.py ask "深海探险"                 # interactive multi-turn probing (≤3 rounds), --out saves the enhanced concept
python core/vidance.py ask "深海探险" --out input/concept.txt
# dialog API (used by the v7 frontend)
curl -X POST http://127.0.0.1:8894/api/dialog/start -H 'Content-Type: application/json' -d '{"concept":"深夜灯塔"}'
curl -X POST http://127.0.0.1:8894/api/dialog/dlg_xxx/reply -H 'Content-Type: application/json' -d '{"text":"暴风雨夜，灯塔守护人独自值班"}'

# v7 frontend agent WebUI (visit http://127.0.0.1:8894/ui in a browser)
# left tools/task sidebar + top canvas + bottom-right input; / pops command completion
# /fast concept -n 3 --effects auto   → submit task → canvas polls → completed video card
# /hot /auto /ask /clip /scout /voices /video {id} /help likewise
# Backend counterparts:
curl http://127.0.0.1:8894/api/tools                     # 15 commands + parameter schema
curl http://127.0.0.1:8894/api/options                   # voice/LUT/BGM/effect enumerations
curl -X POST http://127.0.0.1:8894/api/tool/fast -H 'Content-Type: application/json' -d '{"args":"概念 -n 3 --effects auto"}'
curl http://127.0.0.1:8894/api/video/{task_id} -o final.mp4   # output video stream

# ── v17 open-source consolidation (formerly v12, ✅ closed 2026-10-30) — full commands in docs/usage/usage-v17.md ──
# buffer: POST /api/upload?session_id=s upload / GET /api/assets?session_id=s&q=keyword (@filename search, stale cursor 410)
#         POST /api/assets/archive archive / DELETE /api/session/{s} delete whole session
# checkpoint resume: python core/vidance.py auto --resume {task_id} (stage skipping + per-shot reuse + sha256 fingerprints blocking tampered artifacts)
# five-dimension templates: python core/vidance.py auto "概念" --template cinematic|documentary|anime90s|guofeng
# RAG: python core/vidance.py rag add 文档.md --novel / rag search "question" / rag ask "question"
# novel2video: SKILL/commands/novel2video/{m6_breakdown_test,m6_render_v3,m6_archive_buffer,m6_wardrobe_test}.py
# wardrobe: python input/rag_test/m6_wardrobe_test.py [--gen] (Base Look locks the face across multiple outfit prompts + FLUX renders)
# tests: python tests/test_{buffer,checkpoint_m4,retry,embed_index,subtitle_correct,material_cache,preflight}.py

# ── v18 long-video quality (formerly v14, ✅ closed 2026-10-31) — full log in docs/usage/usage-v18.md ──
# migrate a legacy breakdown to the v18 schema (dry-run preview / --apply writes back + .v17.bak backup)
python SKILL/commands/novel2video/m6_upgrade_breakdown.py output/m6/breakdown_孔乙己.json --apply
# M6 render (v18: scene anchors + wardrobe assembler + xfade transition selection; M6_ALL=1 full run ~2h, always background it)
M6_OUT=v4 python input/rag_test/m6_render_v3.py
# M6_FLF=1: VACE first/last-frame driving (first frame = this shot's keyframe, last frame = next shot's keyframe, 832x480@16fps; inter-shot boundaries -87% clip level / -72.6% part level)
M6_OUT=v5 M6_FLF=1 python input/rag_test/m6_render_v3.py
# one-shot (LLM camera chain + last-frame feedback chained I2V + anchor re-injection per segment; seam MAE assertion <0.10)
python core/vidance.py auto "穿越隧道的光" --oneshot --duration 30
python utils/oneshot.py "穿越隧道的光" --duration 30 --character "金色光流"   # direct-call equivalent

# ── v19 video-link rework (formerly v16, ✅ closed 2026-11-02) — full log in docs/usage/usage-v19.md ──
# one command: link → download + understand → LLM rewrites narration (anti-paraphrase assertion) → re-dub → visual rewrite → video
python core/vidance.py rework "https://www.bilibili.com/video/BVxxxx" --style 解说 --duration 60 --visual-rewrite 2 --lut cinematic --bgm dramatic
python utils/rework.py source "链接" --out output/rework/rw-x   # M1 single step (source.json)
# agent/API: generator.rework agent; POST /api/tool/rework (async job, polled at /api/h3shot/{job_id})
# ⚠ default voice cosy-safe (cosy-default); manual review before publishing (meta records the source URL)

# ── v20 in-generation review (review while generating, formerly v21, ✅ closed 2026-11-04) — full log in docs/usage/usage-v20.md ──
# on = during generation, WS latent2rgb preview frames go to qwen3.8 coarse review; a death verdict interrupts immediately to cut losses and swap seed; off = original path unchanged
python core/vidance.py auto "红狐狸雪原捕猎" --live-audit
# always on via config: config.json → v20_live_audit.enabled: true; API: POST /api/tasks {live_audit:true} / /api/tool/auto "概念" --live-audit
# frontend :8894/ui task card shows preview frames + verdict live (GET /api/tasks/{id}/preview)

# ── planned (🎯 to implement, see docs/roadmap.md §4) ──
# v14 social media (formerly v11)
# v21 delivery form (formerly v18)
# v10 compositing command example (planned):
# python core/vidance.py compose timeline.json -o final.mp4

