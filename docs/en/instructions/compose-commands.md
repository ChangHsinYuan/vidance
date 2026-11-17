> English | [简体中文](../../instructions/compose-commands.md)

# Vidance Editing Instruction Pattern Library (v10 timeline compositing)

> Purpose: ① a human-browsable command/slash-fragment reference ② a data source for future SFT (instruction → command/timeline).
> Each entry = `id` + `natural-language instruction` (multiple phrasings) + `slash command` (for the frontend) + `CLI` + `timeline JSON fragment` + `parameters`.
> Generation method: reverse-written from existing timelines (`docs/example/compose_demo.json`, `output/tl_test.json`) into diverse natural-language instructions.
> Test material (use existing clips only, do not generate on the spot):
> - `A = output/custom/clips/01A.mp4`
> - `B = output/custom/clips/01B.mp4`
> - `F = output/custom/final.mp4`

Structure:
- `[CAT]` category: concat / transition / trim / speed / effects / overlay / audio / combo
- `id`: `fx-001` incrementing
- `tl`: a fragment that can be dropped straight into a timeline

---

## 1. Concatenation & transitions

### fx-001 Plain concatenation of two clips (hard cut)
- Natural language: *join A and B end to end, no transition* / *A followed by B, hard cut*
- Slash: `/compose A.mp4 B.mp4`
- CLI: `python core/vidance.py compose A.mp4 B.mp4 -o out.mp4`
- tl: `main: [{source:A}, {source:B}]`

### fx-002 Crossfade transition concat
- Natural language: *join A and B with a 0.5-second fade between them* / *fade transition between the two clips*
- Slash: `/compose A.mp4 B.mp4 --transition fade --transition-duration 0.5`
- CLI: `python core/vidance.py compose A.mp4 B.mp4 --transition fade --transition-duration 0.5 -o out.mp4`
- tl: `main: [{source:A}, {source:B, transition_in:{kind:"fade", duration:0.5}}]`

### fx-003 Slide-left transition concat
- Natural language: *switch from A to B with a slide to the left* / *slideleft transition*
- CLI: `python core/vidance.py compose A.mp4 B.mp4 --transition slideleft --transition-duration 0.4 -o out.mp4`
- tl: `{source:B, transition_in:{kind:"slideleft", duration:0.4}}`

### fx-004 Circle-open transition
- Natural language: *the second clip appears with a circular expansion* / *circleopen transition*
- tl: `{source:B, transition_in:{kind:"circleopen", duration:0.5}}`

### fx-005 Wipe transition
- Natural language: *switch from A to B with a left wipe* / *wipeleft*
- tl: `{source:B, transition_in:{kind:"wipeleft", duration:0.5}}`

### fx-006 Three clips chained with different transitions
- Natural language: *chain A, B, F together — slide between the first and second, circle-open between the second and third*
- tl:
```json
"main": [
  {"id":"c1","source":"A"},
  {"id":"c2","source":"B","transition_in":{"kind":"slideleft","duration":0.5}},
  {"id":"c3","source":"F","transition_in":{"kind":"circleopen","duration":0.5}}
]
```
- For the full set of transition kinds see `utils/effects.py:XFADE_KINDS` (fade/slideleft/slideright/slideup/slidedown/circleopen/circleclose/wipeleft/wiperight/wipeup/wipedown/pixelize/hblur/dissolve/radial/smoothleft/…30+)

---

## 2. Trimming

### fx-010 Extract a segment
- Natural language: *only from second 2 to second 5 of A* / *trim A to 2-5s*
- tl: `{source:"A", trim_start:2.0, trim_end:5.0}`
- CLI: `python utils/compose.py run timeline.json` (trims are written in the JSON)

### fx-011 Fixed display duration
- Natural language: *show only 3 seconds of A*
- tl: `{source:"A", trim_start:0, duration:3.0}`

### fx-012 Start at an offset with the default length
- Natural language: *from second 1.5 of A, show 2.5 seconds*
- tl: `{source:"A", trim_start:1.5, duration:2.5}`

---

## 3. Speed & muting

### fx-020 Speed up
- Natural language: *play this at 1.5x* / *speed up 1.5x*
- tl: `{source:"B", rate:1.5}`

### fx-021 Slow down
- Natural language: *slow it to half speed* / *0.5x speed*
- tl: `{source:"B", rate:0.5}`

### fx-022 Mute the original audio (for dubbing)
- Natural language: *remove this segment's original audio*
- tl: `{source:"B", volume:0}`

### fx-023 Lower the original audio
- Natural language: *turn the original audio down, keep 30%*
- tl: `{source:"B", volume:0.3}`

---

## 4. In-shot effects (8 kinds)

### fx-030 Flash-open
- Natural language: *start with a white flash* / *flash white at the head of the film*
- tl: `effects:[{"name":"flash"}]`
- Variant: flash black `{"name":"flash","kind":"black"}`

### fx-031 Punch-in emphasis
- Natural language: *punch in quickly for emphasis* / *punch in effect*
- tl: `effects:[{"name":"punch_in","strength":1.3}]`

### fx-032 Digital glitch
- Natural language: *add some glitch feel* / *cyber glitch noise*
- tl: `effects:[{"name":"glitch"}]`

### fx-033 Film grain + vignette
- Natural language: *add film grain and vignette* / *aged cinematic look*
- tl: `effects:[{"name":"grain_vignette","grain":0.02}]`

### fx-034 Whip-pan sweep
- Natural language: *do a whip pan* / *fast horizontal camera sweep*
- tl: `effects:[{"name":"wipe","sweep":0.3}]`

### fx-035 Overall push/pull
- Natural language: *slowly push in* / *zoom in*
- tl: `effects:[{"name":"zoom","direction":"in"}]`
- Variant: pull out `{"name":"zoom","direction":"out"}`

### fx-036 Speed ramp
- Natural language: *normal at first, then suddenly faster* / *speed ramp*
- tl: `effects:[{"name":"speed_ramp","factor":1.5,"cut":0.7}]`

### fx-037 Freeze & zoom
- Natural language: *freeze and zoom at the end* / *hold the last frame and magnify it*
- tl: `effects:[{"name":"freeze_zoom","hold":0.5,"strength":1.3}]`

### fx-038 Effect stacking (multi-effect chain)
- Natural language: *white flash then punch in* / *film grain plus a push-in*
- tl: `effects:[{"name":"flash"},{"name":"punch_in","strength":1.3}]`

---

## 5. Overlays (picture-in-picture / text)

### fx-040 Bottom-right PiP
- Natural language: *play F in a small window at the bottom right* / *picture-in-picture, bottom right, 30% wide*
- tl:
```json
{"overlay":[{"type":"video","source":"F","start":2.0,"duration":3.0,
  "scale":0.28,"pos":{"x":"W-w-30","y":"H-h-30"},"opacity":0.9}]}
```

### fx-041 Top-left PiP
- Natural language: *overlay a small video at the top left*
- tl: `"pos":{"x":"30","y":"30"}`

### fx-042 Centered title text
- Natural language: *put a big title "My Video" in the middle* / *centered title*
- tl:
```json
{"overlay":[{"type":"text","text":"我的视频","start":0.5,"duration":3,
  "fontsize":56,"fontcolor":"white","pos":{"x":"(W-tw)/2","y":"80"}}]}
```

### fx-043 Bottom-left caption
- Natural language: *write a line "shot in 2026" at the bottom left*
- tl: `{"pos":{"x":"40","y":"H-th-60"},"fontcolor":"white"}`

### fx-044 Top-right watermark (throughout)
- Natural language: *top-right watermark @myaccount for the whole video*
- tl:
```json
{"overlay":[{"type":"text","text":"@我的账号","start":0,"duration":9999,
  "fontsize":28,"fontcolor":"white","pos":{"x":"W-tw-30","y":"30"}}]}
```

### fx-045 Multiple text layers (different positions/colors)
- Natural language: *a yellow title at the start, a red "GLITCH" on the left after 3 seconds, a white caption at the bottom after 6 seconds*
- tl: see the overlay section of `docs/example/compose_demo.json`

---

## 6. Audio

### fx-050 Add BGM
- Natural language: *add background music* / *add a gentle score*
- tl: `audio:[{"source":"bgm/calm.wav","start":0,"volume":0.3}]`

### fx-051 BGM auto-ducking
- Natural language: *automatically lower the music when there's narration* / *BGM ducks under the voice*
- tl: `audio:[{"source":"bgm/calm.wav","start":0,"volume":0.3,"ducking":true}]`

### fx-052 Delayed BGM entry
- Natural language: *bring the music in after 3 seconds*
- tl: `audio:[{"source":"bgm/calm.wav","start":3.0,"volume":0.3,"ducking":true}]`

### fx-053 Multi-track mixing
- Natural language: *mix one narration track with one music track*
- tl: `audio:[{source:"voice.wav",volume:1.0},{source:"bgm/calm.wav",volume:0.25,ducking:true}]`

---

## 7. Combos (complex instructions)

### fx-060 Marketing-style title card
- Natural language: *white flash at the start, then title text, quiet music, push in on the picture*
- tl:
```json
{
  "main":[{"id":"c1","source":"A","trim_start":0,"duration":3,
    "effects":[{"name":"flash"},{"name":"zoom","direction":"in"}]}],
  "overlay":[{"type":"text","text":"标题","start":0.3,"duration":2.5,
    "fontsize":56,"fontcolor":"yellow"}],
  "audio":[{"source":"bgm/uplifting.wav","start":0,"volume":0.3,"ducking":true}]
}
```

### fx-061 Effect mashup
- Natural language: *A white flash + punch-in, B glitch, F film grain + push, different transitions between segments, bottom-right PiP, ducked music*
- tl: full version in `docs/example/compose_demo.json` (this entry is that sample)

### fx-062 Clip with end watermark
- Natural language: *bottom-right watermark over all of F, with light music*
- tl: see the overlay+audio structure in `docs/example/compose_demo.json`

### fx-063 Multi-segment speed cuts
- Natural language: *A normal, B 2x faster, F 0.5x slow motion, hard cuts*
- tl:
```json
"main":[
  {"source":"A"},
  {"source":"B","rate":2.0},
  {"source":"F","rate":0.5}
]
```

---
## 8. Keyframes / masks / stickers / split (v10 M5-M8)

### Keyframes (element-local seconds; unspecified properties keep defaults)
- **fx-064 Sticker float-in**: floats in top-left → center → bottom-left, scaling up and fading in as it flies (`easing:ease-in-out`)
- **fx-065 Main-track push-in**: `main[].keyframes [{t:0,scale:1.06},{t:1,scale:1.0}]`
- **fx-066 Main-track fade-in**: `main[].keyframes [{t:0,opacity:0},{t:0.8,opacity:1}]`

### Masks
- **fx-067 Shape mask**: `mask:{kind:"circle|rounded|rect", radius?, feather?}` (white = visible; applies to all three tracks)
- **fx-068 Image mask**: `mask:{kind:"image", source:"mask.png"}` (grayscale image, white shows, black hides)

### Sticker track (sticker[], PNG auto loop / GIF auto loop)
- **fx-069 Looping GIF sticker**: `sticker:[{source:"anim.gif", start, duration, scale, pos}]`

### Split (single-file CLI)
- **fx-070 Timecode splitting**: `python utils/compose.py split clip.mp4 --at 2 5 --precise -o part`


## Appendix: timeline JSON field quick reference

See the "timeline JSON format" and "effects master table" in [usage-v10.md](../../usage/usage-v10.md).

## Appendix: how this library was generated

This library was expanded by reverse-rewriting existing timeline samples (`docs/example/compose_demo.json`, `output/tl_test.json`); each entry keeps several colloquial phrasings as the SFT instruction side, while `tl` / CLI / slash commands are the output side.
