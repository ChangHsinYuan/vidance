# Vidance v10 使用指南 — 时间线拼接与特效（后端 CLI）

> v10 是**纯后处理**：对**已生成素材**做剪辑合成，不调任何生成模型，秒级出片。
> 设计见 [v10-design.md](./v10-design.md)（时间线模型对齐 OpenCut）。

## 定位

- 输入：已有视频/图片/音频文件 + 一份时间线 JSON
- 输出：一条成片（统一 yuv420p h264）
- 引擎：ffmpeg（无 GPU、无模型）
- 可被 LLM/Agent 调用：CLI + `/api/tool/compose`

## 快速开始

```bash
# 1) 生成时间线模板，改吧改吧
python core/vidance.py compose --init timeline.json

# 2) 从时间线合成（-o 可选，缺省落 output_dir/<时间戳>/final.mp4）
python core/vidance.py compose timeline.json

# 3) 快捷顺序拼接（不写 JSON）
python core/vidance.py compose a.mp4 b.mp4 c.mp4 --transition fade -o out.mp4
```

单步 CLI（`utils/compose.py`）：

```bash
python utils/compose.py run timeline.json -o out.mp4   # 执行时间线
python utils/compose.py probe clip.mp4                  # 探测时长/分辨率/有无音轨
python utils/compose.py init -o timeline.json           # 生成模板
python utils/compose.py merge a.mp4 b.mp4 -o out.mp4     # 快捷顺序拼接
python utils/compose.py split clip.mp4 --at 2 5.5 -o part  # 按时码分割（--precise 帧级精确）
```

## 效果总表

v10 集成的所有剪辑能力（✅ = 已实测出片）：

| 类别 | 能力 | 参数 / 字段 | 状态 |
|------|------|-------------|:----:|
| **拼接** | 主轨顺序拼接 | `main[]` | ✅ |
| | xfade 转场（30+ 种） | `transition_in:{kind,duration}` | ✅ |
| | 硬切（无转场） | 省略 `transition_in` | ✅ |
| **裁剪** | 入点/出点裁剪 | `trim_start` / `trim_end` | ✅ |
| | 单段展示时长 | `duration` | ✅ |
| **变速** | 倍率变速（视频 setpts + 音频 atempo 链式） | `rate` | ✅ |
| | 静音 | `volume:0` | ✅ |
| **镜头内特效** | 闪白/闪黑 | `{"name":"flash"}` | ✅ |
| | 快速推进强调 | `{"name":"punch_in","strength":1.3}` | ✅ |
| | 数字故障噪点 | `{"name":"glitch"}` | ✅ |
| | 胶片颗粒+暗角 | `{"name":"grain_vignette","grain":0.02}` | ✅ |
| | 甩镜平移 | `{"name":"wipe","sweep":0.3}` | ✅ |
| | 整体推拉 | `{"name":"zoom","direction":"in"}` | ✅ |
| | 变速斜坡（前段1x后段快） | `{"name":"speed_ramp","factor":1.5}` | ✅ |
| | 定格放大 | `{"name":"freeze_zoom","hold":0.5}` | ✅ |
| **叠加** | 画中画（视频/图片） | `overlay[].type=video\|image` | ✅ |
| | 叠加缩放 | `overlay[].scale` | ✅ |
| | 叠加位置（表达式） | `overlay[].pos:{x,y}` | ✅ |
| | 叠加透明度 | `overlay[].opacity` | ✅ |
| | 文字层（drawtext） | `overlay[].type=text` | ✅ |
| | 文字字号/颜色 | `fontsize` / `fontcolor` | ✅ |
| | 文字时间轴显隐 | `start` / `duration` | ✅ |
| **音频** | 多音轨混音 | `audio[]` + `amix` | ✅ |
| | BGM 自动闪避（ducking） | `audio[].ducking:true` | ✅ |
| | 音轨音量/延迟 | `audio[].volume` / `start` | ✅ |
 | **探测** | 媒体信息 | `python utils/compose.py probe` | ✅ |
 | **关键帧** | x/y/scale/opacity/rotation 属性动画 | `keyframes:[{t,x,y,scale,opacity,rotation}]` | ✅ |
 | | 缓动 | `easing: linear\|ease-in-out`（默认 ease-in-out） | ✅ |
 | **掩码** | 圆形/圆角/矩形/自定义图 蒙版 | `mask:{kind:circle\|rounded\|rect\|image,...}` | ✅ |
 | | 羽化 | `mask.feather`（高斯模糊半径） | ✅ |
 | **贴纸轨** | PNG 静图循环/GIF 循环贴图 | `sticker[]`（同 overlay 字段） | ✅ |
 | **分割** | 按时码切成多段 | `python utils/compose.py split --at 2 --precise` | ✅ |

**未做**（OpenCut 有，v10 保留字段）：graphic 矢量图形轨（SVG 走 v15/svg 链路）、animations 独立字段（关键帧并入元素 `keyframes`）。

### 关键帧与掩码（M5-M8，2026-09-25 补完）

适用于 `main[]`、`overlay[]`、`sticker[]` 三种元素：

```jsonc
{
  "id": "s1", "source": "star.png", "start": 0.3, "duration": 4.6,
  "keyframes": [                    // t 为元素本地秒（相对 start）
    {"t": 0.0, "x": 780, "y": -130, "scale": 0.3, "opacity": 0.0, "rotation": -30},
    {"t": 1.2, "x": 420, "y": 60,  "scale": 0.5, "opacity": 1.0, "rotation": 15},
    {"t": 3.6, "x": 60,  "y": 250, "scale": 0.35,"opacity": 0.7, "rotation": -8}
  ],
  "easing": "ease-in-out",          // linear=直线；ease-in-out=cos S 曲线
  "mask": {"kind": "circle", "feather": 4}   // 白=显示；kind=image 时给 "source":"mask.png"
}
```

- 每个关键帧对象只写要动的属性即可，未写的保持顶层默认值
- x/y/scale/rotation 走 ffmpeg 表达式（旋转 `rotate`、位移 `overlay`、缩放 `scale eval=frame`）；opacity/mask 走 `geq + alphamerge`（掩码按源尺寸生成）
- 主轨也支持：scale 动画自动叠固定 W×H 黑底（防编码器尺寸抖动），mask 支持圆角片头效果
- 文字层增强：`borderw/bordercolor`（描边）、`shadowx/shadowy/shadowcolor`（阴影）、`box/boxcolor/boxborderw`（底框）
- GIF 贴纸自动循环（`-ignore_loop 0`）；PNG 静图自动补帧到 `duration`

## 时间线 JSON 格式

```jsonc
{
  "output": "out.mp4",              // 可被 CLI -o 覆盖；缺省落 output_dir/<ts>/final.mp4
  "width": 1280, "height": 704,     // 画布（缺省 1280x704，片酬统一 scale+pad 适配）
  "main": [                         // 主视频轨（顺序）
    {
      "id": "c1",
      "type": "video",              // video | image
      "source": "/path/a.mp4",
      "trim_start": 1.0,            // 源入点（秒）
      "trim_end": 4.0,              // 源出点（秒），缺省=到片尾
      "duration": 3.0,              // 展示时长，缺省=trim 段时长/rate
      "rate": 1.0,                  // 变速倍率
      "volume": 1.0,                // 原声音量（0=静音）
      "effects": [                  // 镜头内特效链（见上表）
        {"name": "grain_vignette", "grain": 0.02}
      ],
      "transition_in": {"kind": "fade", "duration": 0.4}  // 与上一段的转场
    }
  ],
  "overlay": [                      // 叠加轨（画中画/文字）
    {
      "id": "pip1", "type": "video",
      "source": "/path/b.mp4",
      "start": 2.0, "duration": 3.0,
      "scale": 0.35,                // 相对画布宽度
      "pos": {"x": "W-w-40", "y": "40"},   // ffmpeg 表达式
      "opacity": 1.0
    },
    {
      "id": "t1", "type": "text",
      "text": "标题", "start": 0.5, "duration": 3.0,
      "fontsize": 48, "fontcolor": "white",
      "pos": {"x": "(W-tw)/2", "y": "80"}
    }
  ],
  "audio": [                        // 音频混音轨
    {
      "id": "a1", "source": "/path/bgm.wav",
      "start": 0.0, "duration": 10.0,
      "trim_start": 0.0, "volume": 0.3,
      "ducking": true               // 与 main 原声做 sidechain 闪避
    }
  ]
}
```

- 命名用 `snake_case`（OpenCut 是 camelCase，语义对齐）
- `pos` 表达式直接透传 ffmpeg（`W/H` 画布宽高、`w/h` 叠加层宽高、`tw/th` 文字宽高）
- 转场 `kind` 见 `utils/effects.py` 的 `XFADE_KINDS`（fade/slideleft/circleopen/wipeleft/pixelize… 30+）

## API / 前端

```bash
# 提交时间线合成（复用 v4 队列风格，纯同步后处理）
curl -X POST http://127.0.0.1:8894/api/tool/compose \
  -H 'Content-Type: application/json' \
  -d '{"args":"/path/timeline.json --output /tmp/out.mp4"}'
```

前端：`/compose timeline.json [--output out]`（`/api/tools` 已列该命令）。

## 示例

### 示例 1：特效大集合（实测产物）

一条时间线 4 段主轨（各带不同特效）+ 3 段不同转场 + 3 个文字层 + 画中画 + BGM ducking：

```bash
python core/vidance.py compose docs/example/compose_demo.json
# → output/output/20260924_compose_demo/compose_fx_demo.mp4（7.55s / 11.4MB）
```

时间线内容：
- c1：`flash` + `punch_in`，无转场入场
- c2：`glitch`，`slideleft` 转场
- c3：`grain_vignette` + `zoom`，`circleopen` 转场
- c4：`wipe` + `rate:1.5`，`wipeleft` 转场
- overlay：3 个不同位置/颜色文字 + 右下角 0.28x 画中画（opacity 0.9）
- audio：BGM `volume:0.35` + `ducking`

### 示例 1b：完整效果演示视频（一条时间线串起所有效果）

`docs/example/v10_effects_demo.json` → 9 段主轨，每段演示一个效果并配分段字幕：

| 段 | 效果 | 转场入 |
|----|------|--------|
| 1 | `flash` + `zoom`（推近） | — |
| 2 | `punch_in` | fade |
| 3 | `glitch` | slideleft |
| 4 | `grain_vignette` | circleopen |
| 5 | `wipe` | wipeleft |
| 6 | `zoom`（拉远） | pixelize |
| 7 | `speed_ramp` | 硬切 |
| 8 | `freeze_zoom` | 硬切 |
| 9 | 画中画 + 文字 + BGM ducking | hblur |

```bash
python core/vidance.py compose docs/example/v10_effects_demo.json
# → output/output/20260924_compose_demo/v10_effects_demo.mp4（13.7s / 12MB）
```

> 注：`speed_ramp` / `freeze_zoom` 会改变片段时长，compose 在特效后**强制归一回元素 `duration`**（不足克隆末帧、超出截断），保证时间轴可精确预测。

### 指令库

`docs/instructions/` 下有两份：

1. **命令指令库** `commands.json`（v0-v10 全部 `/` 命令），供前端两级 `/help`：
   - `/help` → 每命令一句概览（可点击展开）
   - `/help 命令名` → 该命令版本/说明/参数/示例
2. **剪辑指令模式库** `compose-commands.md` + `compose-commands.json`（36 条 v10 剪辑效果组合）：
   - 覆盖拼接/转场/裁剪/变速/8 特效/画中画/文字/音频/组合
   - 每条 = 自然语言指令（多说法）+ 斜杠命令 + CLI + 时间线 JSON 片段
   - 后端 `GET /api/instructions` 提供

### 示例 2：把现有成片加水印+配乐

```jsonc
{
  "output": "out.mp4", "width": 1280, "height": 704,
  "main": [{"id":"m","type":"video","source":"final.mp4"}],
  "overlay": [{"id":"wm","type":"text","text":"@我的账号",
               "start":0,"duration":999,"fontsize":28,"fontcolor":"white",
               "pos":{"x":"W-tw-30","y":"H-th-30"}}],
  "audio": [{"id":"bgm","source":"bgm/calm.wav","start":0,"volume":0.25,"ducking":true}]
}
```

### 示例 3：多段素材带转场拼接

```bash
python core/vidance.py compose clip1.mp4 clip2.mp4 clip3.mp4 \
  --transition slideleft --transition-duration 0.5 -o merged.mp4
```

## 与既有能力的关系

| 既有 | v10 关系 |
|------|---------|
| `vidance.py concat`（v2） | 保留；`compose` 是其超集（支持裁剪/特效/多轨） |
| `utils/effects.py`（v5） | 直接复用：8 种特效 + xfade 30+ 种 |
| `utils/ffmpeg_tools.py`（v2） | 参考其 ducking，v10 独立实现多音轨 |
| `/api/tool/*`（v7） | compose 作为一条命令接入 |

## 常见问题

- **输出在哪？** 缺省 `config.output_dir/<时间戳>/final.mp4`（即 `/mnt/dataset/zxy/vidance/output/<ts>/`），可用 `-o` 覆盖
- **没声音？** 主轨素材无音轨时，xfade/overlay 仍会保留静音占位；需 BGM 请加 `audio[]`
- **画中画位置不对？** `pos` 用 ffmpeg 表达式，常见写法 `W-w-40`（右下角留 40px）、`(W-w)/2`（水平居中）
- **特效失败？** 单个特效失败会打印警告并跳过，不中断整条链
- **中间文件？** 落在输出同级 `_compose_tmp_<hash>/`，调试用；正常无需清理（可手动删）
