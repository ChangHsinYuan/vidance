# Vidance v10 设计文档 — 拼接与特效（OpenCut 思路，后端 CLI）

> 仓库版本号 v10（紧接 v9 之后）。
> 状态：🚧 开发中。目标：把"拼接/剪辑/特效"做成**后端可调用命令**（不做前端），
> 时间线数据模型参考 OpenCut，剪辑实现用 ffmpeg，方便 LLM 直接编排。

---

## 1. 概述

### 1.1 动机

- v5 已有效果库（8 种镜头内特效）+ xfade 转场（30+），但都是"单片段/顺序拼接"级别
- v2 的 `concat` 子命令只支持顺序硬切/RIFE/crossfade，无法表达多轨（画中画/文字/配乐轨）、裁剪、叠加
- 我们**不需要 OpenCut 的前端**（浏览器 CapCut），只需要它的**时间线剪辑模型**做成后端命令
- 做成 CLI + `/api/tool` 后，LLM（v13 多智能体、v9 API）可直接编排剪辑

### 1.2 参考 OpenCut 的核心模型

OpenCut（`opencut-app/opencut-classic`）的时间线数据模型（`apps/web/src/timeline/types.ts`）：

```
Timeline
└── Scenes[]（主场景 + 附加场景）
    ├── main: VideoTrack（主视频轨）
    ├── overlay: OverlayTrack[]（视频/文字/图形/特效叠加轨）
    └── audio: AudioTrack[]（音频轨）
```

轨道类型：`video | text | audio | graphic | effect`
元素类型：`video | image | audio | text | sticker | graphic | effect`

**基础元素字段**（关键，v10 直接对齐）：
```ts
BaseTimelineElement {
  id, name,
  startTime,        // 在时间轴上的起始时刻
  duration,         // 持续时长
  trimStart,        // 源素材入点
  trimEnd,          // 源素材出点
  sourceDuration,   // 源素材总时长（可选）
  params,           // 参数（缩放/位置/透明度/文字样式…）
  animations,       // 关键帧动画（可选）
}
```

**视频元素**额外：`mediaId`、`retime.rate`（变速）、`isSourceAudioEnabled`、`effects[]`、`masks[]`
**图片元素**：`mediaId` + effects/masks
**文字元素**：`params` 里带文字内容/字体/颜色/位置
**音频元素**：`sourceType: upload|library`、`retime`、`buffer`

### 1.3 v10 范围（只做后端）

- **不做**：前端时间线 UI、拖拽、预览播放器（这是 v8 前端的事，且非必须）
- **做**：
  1. 时间线 JSON 数据模型（对齐 OpenCut，简化为后端可执行子集）
  2. 剪辑原语：拼接 / 裁剪 / 分割 / 变速 / 静音
  3. 转场（复用 v5 `transition`/`concat_with_transitions`）
  4. 特效（复用 v5 `apply_effect` + 关键帧驱动）
  5. 叠加：画中画（overlay 视频轨）、文字/水印层、音频混音轨
  6. 导出：统一 yuv420p h264
  7. CLI 子命令 + `/api/tool` 暴露 + LLM 自然语言→时间线 JSON

---

## 2. 时间线 JSON 模型（v10 实现子集）

```jsonc
{
  "output": "out.mp4",
  "width": 1280, "height": 704, "fps": 24,
  "main": [                          // 主视频轨（顺序排列的片段）
    {
      "id": "c1",
      "type": "video",               // video | image
      "source": "/path/a.mp4",
      "trim_start": 1.0,             // 源入点（秒）
      "trim_end": 4.0,               // 源出点（秒），缺省=到片尾
      "start": 0.0,                  // 时间轴位置（缺省=顺序追加）
      "duration": 3.0,               // 缺省=duration=trim_end-trim_start（变速后）
      "rate": 1.0,                   // 变速倍率（retime.rate）
      "effects": [                   // v5 特效链
        {"name": "grain_vignette", "params": {"grain": 0.02}}
      ],
      "transition_in": {"kind": "fade", "duration": 0.4},  // 与上一个片段的转场
      "volume": 1.0                  // 原声音量（0=静音）
    }
  ],
  "overlay": [                       // 叠加轨（画中画/文字/贴纸）
    {
      "id": "pip1", "type": "video",
      "source": "/path/b.mp4",
      "start": 2.0, "duration": 3.0,
      "pos": {"x": "W-w-40", "y": "40"},   // 支持表达式
      "scale": 0.35,                        // 相对主画布宽度
      "opacity": 1.0
    },
    {
      "id": "t1", "type": "text",
      "text": "标题", "start": 0.5, "duration": 3.0,
      "fontsize": 48, "fontcolor": "white",
      "pos": {"x": "(W-tw)/2", "y": "80"}
    }
  ],
  "audio": [                         // 音频混音轨（BGM/旁白）
    {
      "id": "a1", "source": "/path/bgm.wav",
      "start": 0.0, "duration": 10.0,
      "trim_start": 0.0, "volume": 0.3,
      "ducking": true                // 与 main 原声做 sidechain ducking
    }
  ]
}
```

字段命名：为便于 JSON 手写/LLM 生成，用 `snake_case`（OpenCut 是 camelCase，语义对齐）。

---

## 3. 命令设计

### 3.1 CLI

```bash
# 从时间线 JSON 合成
python core/vidance.py compose timeline.json -o final.mp4

# 快捷拼接（无需手写 JSON）
python core/vidance.py compose a.mp4 b.mp4 c.mp4 --transition fade --transition-duration 0.4 -o out.mp4

# 生成时间线模板（供 LLM/人填充）
python core/vidance.py compose --init template.json
```

### 3.2 单步（`utils/compose.py` CLI）

```bash
python utils/compose.py run timeline.json -o out.mp4   # 执行时间线
python utils/compose.py probe clip.mp4                  # 探测时长/分辨率
python utils/compose.py init -o timeline.json           # 生成模板
python utils/compose.py merge a.mp4 b.mp4 -o out.mp4     # 快捷顺序拼接
```

### 3.3 API / `/` 命令（v7 集成）

```bash
# 提交时间线合成任务（复用 v4 队列）
curl -X POST http://127.0.0.1:8894/api/tool/compose \
  -H 'Content-Type: application/json' \
  -d '{"args":"timeline.json -o out.mp4"}'
```

前端 `/compose timeline.json`。

### 3.4 LLM 自然语言 → 时间线

`llm.timeline_from_text(text, media_hint)`：把 "把 a 和 b 拼起来，中间淡入淡出，右下角放个水印，配乐轻一点"
转成上面的 JSON（可用媒体清单作为上下文）。

---

## 4. 实现架构

```
utils/compose.py
├── Timeline 数据模型（dataclass/TypedDict，对齐 OpenCut 子集）
│   ├── TimelineElement / Track / Timeline
├── 探测：probe(path) → {duration, width, height, has_audio}
├── 原语（每个都是独立 ffmpeg 调用，可单测）
│   ├── trim_clip(src, in, out)        裁剪
│   ├── retime_clip(src, rate)         变速（setpts + atempo）
│   ├── apply_effect_chain(src, effects) 复用 v5 effects.apply_effect
│   └── silence_clip(src)              去音轨
├── 合成器
│   ├── build_main_track(clips, transitions)  单 filter_complex 链式
│   ├── build_overlay(...)                    画中画/文字叠加
│   └── mux_audio_tracks(...)                 多音频混音 + ducking
└── run(timeline) → final.mp4
```

**关键 ffmpeg 技术**：
- 多片段 + 转场：`filter_complex` 里 `xfade` 链式（复用 v5 `transition` 思路，但改为单次编码）
- 画中画：`overlay=x=...:y=...` + `scale`
- 文字：`drawtext`（需字体文件；无字体时报错兜底）
- 多音轨：`amix` + `sidechaincompress`（复用 v2 ducking）
- 变速：视频 `setpts=PTS/rate`，音频 `atempo`（0.5-2.0，超出用链式）
- 统一 `-pix_fmt yuv420p` + `libx264`

**设计取舍**：
- 中间步骤落临时文件（便于调试/断点），最终一次合成
- overlay/audio 的表达式直接透传给 ffmpeg（不重造 DSL）
- 先支持单层 overlay + 单层 audio 叠加，多层后续迭代

---

## 5. 里程碑

| 里程碑 | 内容 | 验证 |
|--------|------|------|
| M1 | 时间线 JSON 模型 + probe + 顺序拼接（含转场） | 3 片段带 fade 拼接出片 |
| M2 | 裁剪 / 分割 / 变速 / 静音 | trim+rate 单测 |
| M3 | 特效链 + 画中画 + 文字层 + 多音轨混音/ducking | 多轨时间线出片 |
| M4 | CLI `compose` 子命令 + `/api/tool/compose` + LLM 自然语言→时间线 | 端到端 + API 实测 |

---

## 6. 与既有能力的关系

| 既有 | v10 关系 |
|------|---------|
| v2 `concat` 子命令 | 保留；v10 `compose merge` 是其超集 |
| v5 `effects.py` | 直接复用（特效/转场），v10 增加时间线编排层 |
| v2 `ffmpeg_tools.compose` | 参考其 audio/srt 合成，v10 不替换 pipeline 内部 |
| v4 任务队列 | `/api/tool/compose` 走队列异步执行 |
| v3 资产库 | 时间线里的 source 可用资产库路径 |

---

## 7. 验证记录（2026-09-24）

- **M1 顺序拼接+转场** ✅：`output/compose_test.mp4`（2 段 1344x768 素材 → 1280x704 24fps h264，xfade fade 转场，7.55s，带音轨）
- **M2 裁剪/变速/静音** ✅：`trim_start/trim_end`/`rate=1.5`（setpts+atempo）/`volume=0` 实测通过
- **M3 特效+画中画+多文字+多音轨** ✅：`output/compose_fx_demo.mp4` 一条时间线 4 段主轨（flash+punch_in / glitch / grain_vignette+zoom / wipe+rate1.5）+ 3 段 xfade 不同转场（slideleft/circleopen/wipeleft）+ 3 个不同位置颜色文字层 + 1 个右下角画中画（scale 0.28 / opacity 0.9）+ 1 条 BGM ducking 混音，11.4MB 出片
- **M4 CLI + API** ✅：
  - `python core/vidance.py compose /tmp/tl_fx.json -o out.mp4` 出片
  - `python core/vidance.py compose --init tmpl.json` 生成模板
  - `python utils/compose.py run|probe|init|merge` 四子命令可用
  - `curl -X POST /api/tool/compose -d '{"args":"/tmp/tl_fx.json --output /tmp/x.mp4"}'` 出片

**已集成的 OpenCut 效果**：主轨拼接（xfade 30+）、trim 裁剪、retime 变速、8 种镜头内特效（flash/punch_in/glitch/grain_vignette/wipe/zoom/speed_ramp/freeze_zoom）、画中画 overlay（缩放/位置/透明度）、drawtext 文字层（位置/字号/颜色/时间轴 enable）、多音轨 amix+sidechain ducking。
**未实现**（留 OpenCut 字段未用）：关键帧 `animations`、掩码 `masks`、贴纸 sticker / graphic 图形轨、分割 split。
