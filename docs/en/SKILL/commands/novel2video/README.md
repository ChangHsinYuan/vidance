> English | [简体中文](../../../../../SKILL/commands/novel2video/README.md)

# novel2video — Novel-to-Film Skill

Novel chapter → structured breakdown → keyframes → I2V → dubbing → subtitled final cut (the M6 prototype's finalized form; the manual pipeline before v17 made it official).

## Files

| File | Role |
|---|---|
| `novel2video.yaml` | Skill parameters (doc_key/style/camera moves/defaults) |
| `m6_breakdown_test.py` | Steps ①②: RAG character-card injection → LLM structured breakdown (characters/scenes/props/shot-list JSON; v18 schema: world/costumes/anchor_en/costume/transition_out) |
| `m6_upgrade_breakdown.py` | v18 migration: backfill v18 fields into old breakdown JSONs (dry-run/--apply, anti-tamper assertion + .v17.bak backup) |
| `m6_render_v3.py` | Steps ③④⑤⑥: English-prompt keyframes → I2V → dubbing → assembly with burned subtitles (`M6_ALL=1` renders all shots in the breakdown, default 8 key shots; v18: scene anchors + wardrobe assembler + transition selection; `M6_FLF=1` VACE first/last-frame-driven 832x480@16fps) |
| `m6_flf_smoke.py` | v18 M2 smoke: VACE flf2v single shot (control.mp4 concat → WanVaceToVideo; first/last-frame MAE 0.019/0.015) |
| `m6_archive_buffer.py` | Step ⑦: reference-style archival of artifacts into the buffer (idempotent, deduped by name+sha) |
| `m6_wardrobe_test.py` | Wardrobe system (BigBanana-inspired): Base Look locks the face across multiple outfit prompts (`--gen` FLUX image generation + collage) |
| `nahan.txt` | Gutenberg source text of *Call to Arms* (《呐喊》, for reproducing the sample; doc_key=454eb1f2…) |
| Process spec (six steps + pitfalls): `.opencode/skills/novel_to_video/SKILL.md` | |

## Usage

### A. Reproduce the sample (Kong Yiji; all materials included in this directory)

```bash
# Prereq ①: GPU services UP (h3/wan/flux/tts/api)
cd /mnt/disk_sdb/zxy/vidance && ./start_services.sh start && sleep 120

# Prereq ②: build the RAG index (nahan.txt in this directory → doc_key 454eb1f2…)
PY=/home/zxy/.conda/envs/comfyui/bin/python
$PY SKILL/commands/novel2video/m6_breakdown_test.py 孔乙己   # first run auto-builds the index + breakdown

# Render (idempotent and resumable; M6_ALL=1 renders every shot in the breakdown)
$PY SKILL/commands/novel2video/m6_render_v3.py
# M6_ALL=1 $PY SKILL/commands/novel2video/m6_render_v3.py   # all 36 shots (~2h; run in background)
# M6_FLF=1 M6_OUT=v5 $PY SKILL/commands/novel2video/m6_render_v3.py  # v18 M2: VACE first/last-frame-driven (inter-shot boundary -87% clip-level / -72.6% part-level)
# Migrate an old breakdown to the v18 schema: $PY SKILL/commands/novel2video/m6_upgrade_breakdown.py output/m6/breakdown_孔乙己.json --apply

# Archive artifacts into the buffer (reference-style, no copying; idempotent)
$PY SKILL/commands/novel2video/m6_archive_buffer.py m6_kongyiji_v3

# Wardrobe (optional): multiple outfits under one Base Look (new clothes, same face; default prompts only, --gen actually renders)
$PY SKILL/commands/novel2video/m6_wardrobe_test.py [--gen]
```

Artifacts land in `output/m6/v3/` (with the same doc_key they share the cache with historical samples, so reruns finish in seconds).

### B. Use a different novel

```bash
# 1. Upload & index (yields a new doc_key; the 8-char short prefix is enough)
$PY -c "
import sys; sys.path.insert(0,'.')
from utils.rag import RagIndex
print(RagIndex().add_novel('你的小说.txt')['key'])"
# or UI: /rag add /path/to/小说.txt --novel

# 2. Break down the target chapter (the chapter name must match the chapter list from /rag status)
$PY SKILL/commands/novel2video/m6_breakdown_test.py 章节名
#    ⚠ KEY/SRC in m6_breakdown_test.py are hardcoded to 《呐喊》; for a new book edit the first two lines:
#    KEY='new doc_key'; SRC=path to your novel

# 3. Render: point BD/SHOTS at the top of m6_render_v3.py to the new breakdown JSON path and shot subset
#    STYLE_EN/MOTION_EN live in the yaml (novel2video.yaml); rewrite them when switching genre
```

Artifacts (`output/m6/v3/`): `kongyiji_v3.mp4` final cut (yuv420p/burned subtitles, plays on Windows),
`subs.srt`, `prompts.md` (the full prompt manifest), `kf_contact.jpg` (keyframe contact sheet),
`kf/` (keyframes), `clips/` (shot videos + dubbing).
v18 also produces `output/m6/world_*.json` (worldview registry: style_en cache + forbidden rules on disk) +
`events_*.json/.md` (event-line summary cards; one card per arc at render time, auto-indexed into RAG via `RagIndex.add_chunks`).

## The six-step pipeline

```
novel ─① RAG index (chapter split + character cards)
    ─② LLM breakdown (shot.visual / narration as separate JSON columns)
    ─③ LLM zh→en prompt → FLUX keyframes (global STYLE for uniform look)
    ─④ Wan I2V (keyframe as first frame; bare T2V forbidden)
    ─⑤ CosyVoice dubbing (narration = same source as subtitles)
    ─⑥ slow-motion ≤2x + Ken Burns tail push + xfade concat + burned subtitles + yuv420p
```

## Hard constraints (distilled from failures — violate and it breaks)

1. **FLUX only eats English**: Chinese prompts → style drift / content wander; the LLM must translate zh→en (shot size first + this shot's character state prioritized)
2. **Always I2V**: bare T2V is the root cause of cross-shot style drift
3. **Voice blacklist**: a cloned voice's prompt_text gets zero-shot continued ("the street's street…" leaked at sentence starts with jieshuo1); A/B-test any new voice with a single sentence first; safe default is cosy-default
4. **Windows compatibility**: every ffmpeg output stage explicitly sets `-pix_fmt yuv420p` (RGB keyframes become 4:4:4 through the xfade chain → unplayable on Windows)
5. **No long dead frames**: absorb duration gaps with slow motion ≤2x; the remainder with a gentle Ken Burns push (zoompan 1.0→1.14)
6. **Long LLM tasks must stream**: non-streaming long reasoning returns zero bytes → guaranteed read timeout; chat_json max_tokens already raised to 16384 by default
7. **Split over-long chapters first**: breakdowns of >8000 chars time out / degrade (《藥》 = 36k chars, including the merged untitled "The True Story of Ah Q")
8. **Time budget**: breakdown 5-15min + keyframes 5min + I2V 3.5min/shot + assembly 2min; always run in the background
