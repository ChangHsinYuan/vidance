# Vidance 方法脉络图（Production Method Map）

> 2026-09-26。全文梳理系统的全部出片方法：**是否用视频模型** × **谁当导演**；下半部为 v12 流水线图（模块串行、模块内并行）与游离审计层。
> 相关：指令库 `instructions/commands.json`、路线 `roadmap.md`、t2c `v-t2c.md`、SVG `v-svg-pipeline.md`、三排正交 `v12-modules.md`。

## 总览

```
                         ┌─ A. 不用视频模型（纯 CPU / 轻量 GPU）
 出片方法 ──是否用视频模型─┤
                         └─ B. 用视频模型 ──驱动方式─┬─ B1 人给素材（人导演）
                                                    ├─ B2 LLM 导演（全自动）
                                                    └─ B3 T2C（自然语言入口，路由到 A/B1/B2）
 公共旁路：后处理(v2) · 特效(v5) · 拼接(v10) · 配音(TTS/克隆/FunClip) · 分发(v14 规划，原 v11)
```

## A. 不用视频模型的出片法

| 方法 | 命令 | 素材来源 | 画面动效 | 代码 | 状态 |
|------|------|---------|---------|------|------|
| **A1 营销号图文流** | `/fast` `/hot` | 爬图（Pexels/必应+多模态校验）→ 不足 FLUX 补图；或 `--images` 自供 | Ken Burns zoompan（pan/zoom）+ 可选 v5 特效 | `utils/fastline.py` | ✅ v4 M6 |
| **A2 SVG 动效流** | `/svg --concept … [--voice …]` | LLM 直接写自包含 SMIL/WAAPI SVG | 无头 Chromium 确定性逐帧渲染；S5 可配音+字幕+LUT/BGM | `utils/svg_llm.py` + `utils/svg_pipeline.py` | ✅ v15 S1-S5 |
| **A3 视频二创流** | `/rework`（规划） | yt-dlp 下他人视频 → 抽帧+STT | 改写解说+重 TTS+画面二创 | — | 🎯 v16 backlog |

- A1 特点：最快最稳，GPU 全挂也能降级出片（占位图+静音兜底）；热搜角标支持。
- A2 特点：零 GPU、图形/图表/扁平动画风格；`--fast` 外的另一条轻量线。
- A1/A2 共用后处理链（LUT/BGM/STT/字幕）。

## B. 用视频模型的出片法

### 可用模型（按卡）

| 模型 | 服务 | 能力 | 备注 |
|------|------|------|------|
| **MiniMax H3 ref2va** | ComfyUI :8188 / GPU0 | 参考图+prompt → 单镜，**原生音频** | 主力。慢（8-12s 镜头 20-25min），帧数超线性成本 |
| **Wan 2.2 T2V/I2V** | ComfyUI :8189 / GPU2 | 文/图 → ≤5s 镜（121帧） | auto/quick 主引擎，含 RIFE |
| **HunyuanVideo** | 8190 / GPU3 | T2V 备选 | 当前停，未接入流水线 |

（FLUX :8192 只生图，属于素材引擎，服务于 A1 补图和 B2 角色锚。）

### B1 人导演：素材和 prompt 都是人给的

| 方法 | 命令 | 输入 | 特点 |
|------|------|------|------|
| **H3 单镜直出** | `/h3shot prompt.txt --ref …` | 整段式 prompt + 参考图 | 《奶蛙徽商》13集批量走这条；`--fast` 档 steps14/1024×576；代码 `utils/h3_prompt_video.py` |
| **H3 多镜脚本** | `/custom --script …` | 分镜脚本【标题｜约N秒】+ 参考图 | 老格式，LLM 只改写不编故事 |

### B2 LLM 导演：给概念，LLM 编一切

| 方法 | 命令 | LLM 负责 | 链路 |
|------|------|---------|------|
| **auto 全自动** | `/auto "概念"` | 编剧分镜 → 每镜 prompt → 角色锚 → 审片重试 | `core/pipeline.py`；角色锚四模式 flux/3dgs/mesh/auto（v1/v3）→ Wan I2V |
| **quick 裸 T2V** | `/quick "概念"` | prompt 优化一步 | 单镜直出，无后处理 |
| （核实增强） | `/ask "概念"` | 6 维追问补全 prompt（v6） | 增强后的概念喂给上面任何一条 |

### B3 T2C：自然语言入口（不是生成法，是翻译层）

用户口语 → `/api/chat` 判意图 → v6 dialog 核实 → mt5 微调模型（`t2c/model`）翻译成上述任意命令 → ▶执行。见 `v-t2c.md`。待重训覆盖全量指令。

## 公共旁路（任何方法都能叠）

| 层 | 能力 | 代码 |
|----|------|------|
| 后处理 | RIFE 插帧/slowmo、LUT 6色、BGM ducking、STT 字幕 | `core/postprocess.py` |
| 特效 | 8 种镜内特效 + 30+ xfade 转场 + LLM 自动选 | `utils/effects.py` |
| 拼接 | 时间线 JSON（主轨/画中画/贴纸/文字/多音轨）+ 关键帧/掩码 + split + 快捷 concat | `utils/compose.py`、`vidance.py concat` |
| 声音 | edge-tts+CosyVoice 双引擎、B站克隆音色、FunClip 语义裁剪 | `utils/tts*.py`、`voice_clone.py`、`funclip.py` |
| 前端 | :8894/ui slash 分发（轮询 task/h3_job/compose_output 三类回执） | `ui/index.html` |

## 选型速查

- 追热点快出片、不要真动态 → **A1 fast/hot**
- 概念演示/图表/扁平动画、零 GPU → **A2 svg**
- 角色一致性短剧、有参考图、接受慢 → **B1 h3shot**
- 一句话到成片、多镜叙事 → **B2 auto**
- 单镜试水 → **quick**；网页里说人话 → **B3 t2c**
- 已有一堆成片要合并/加字幕特效 → **compose/concat**（不占生成资源）

## v12 流水线图：模块串行 · 模块内并行 · 审计游离

> `make` = 每一排各取其一（或开关）串成一条链。审计层 V 不占总线，挂在需要它的模块出口。

```
概念/热点
   │
   ▼
┌─ D 导演层（选一，串行第一站）────────────┐
│ D1 llm   LLM 编剧分镜（auto/quick）      │   产出契约：
│ D2 manual 人给 --say/--prompt/--script   │   segments[] =
│ D3 scout 爬虫+LLM 选题得概念             │   {text, visual, motion}
│ D4 = D2 特例：人写多镜脚本（custom/h3）   │
└──────────────┬───────────────────────┘
               ▼
┌─ G 生成层（选一，串行第二站）────────────┐     ┌─ V 审计层（游离，多模态 LLM，可插拔）──────┐
│ G1 wan  T2V/I2V ≤5s镜+RIFE（吃segments） │ ◀── │ V1 审片 review_shot：逐镜抽帧5维评分        │
│ G2 fast 爬图/FLUX+KenBurns（营销号）      │ ◀── │    → <7 分回写 prompt 重试 ≤2（pipeline）  │
│ G3 svg  LLM写SVG+无头Chromium逐帧        │ ◀── │ V2 审角色 review_character：预览vs参考图   │
│ G4 h3   参考图+整段prompt→原生音频单镜    │ ◀── │    → 不过降级 flux / 重重建（pipeline v1/v3）│
│    （G4 原生带声 → P0/P1 自动跳过）       │     │ V3 图相关性 assess_image_relevance：        │
└──────────────┬───────────────────────┘     │    爬图/FLUX 逐张校验 → 删图重生（fastline）  │
               ▼                             │ V4 角色描述 describe_character：图→锚文本      │
┌─ P 后期层（每项独立开关，串行第三站）─────┐     │    （custom_gen/api 角色锚）                │
│ P0 配音 Narrator.say：voice重试→cosy→静音│     │  ensemble 并行玩法（规划）：V1/V2/V3 可多   │
│ P1 字幕 Narrator.srt：TTS时间戳→SRT烧录  │     │  模型同时投票取均值/多数决，见下表模型池     │
│ P2 BGM  select_bgm + sidechain ducking   │     └─────────────────────────────────────────┘
│ P3 调色 LUT×6（LLM 自选或手给）           │
│ P4 STT  whisper 重转写对齐字幕（--stt）    │
│ P5 拼接 compose/concat：crossfade/时间线  │
│ P6 特效×8+xfade转场+关键帧/掩码/贴纸/split│
└──────────────┬───────────────────────┘
               ▼
          final.mp4 + meta.json
```

- **串行**：D→G→P 数据流不回环（重试闭环发生在模块内部：V1 打分不过 → G 内重生成同镜 ≤2 次）。
- **并行**：D3 的爬取多源（B站/微博/知乎/百度/RSS）并行同批；P0 逐段 TTS、G1 的 M2 并行预取（FLUX 参考帧+TTS 与 Wan 串行不冲突）属模块内并行。
- **V 游离在流水线之外**：任何 D×G 组合都能挂或不挂审计；全部走 USTC 网关多模态。

## V 审计层可用的 USTC 多模态模型池（2026-09-26 实测）

用 16×16 纯红 PNG 问颜色、max_tokens=2000 逐个探测 `/v1/chat/completions`：**20 个模型全部接受 image_url 输入**（此前部分"空响应"仅是 max_tokens 太小被 reasoning_content 吃光，非不支持视觉）。

| 模型 | 视觉 | 审计定位建议 |
|------|:---:|------|
| `qwen3.8-chat` | ✅ | **V1/V2 现役主力**（AGENTS 约定，~30-120s/镜） |
| `deepseek-v4-flash-ascend` | ✅ | 现役默认编剧模型，顺带可审（省切换） |
| `deepseek-flash` / `deepseek-flash-2` | ✅ | V3 快审候选（flash 系延迟低） |
| `claude-haiku-4-5(-20251001)` | ✅ | V1 异构投票成员（曾为 v3 前审查模型） |
| `qwen3.5` / `qwen3.5-thinking` / `qwen3.5-non-thinking` | ✅ | thinking 系须 max_tokens≥2000 |
| `qwen3.8-flash-next` / `-2` / `qwen-chat` | ✅ | 便宜快审档 |
| `qwen3.8-reasoner` / `qwen-reasoner` / `smart/reasoning` | ✅ | 深审档（慢，值得用于终版复审） |
| `glm-5.3-flash` | ✅ | 异构第三票 |
| `unlimited-ocr` | ⚠️ OCR 专用 | 不收"看图问答"，走 OCR 管线——可用作 V5 字幕/角标 OCR 校验（v12 backlog：P4 烧字幕后 OCR 回读比对 SRT） |
| `smart/default` | — | 网关自动路由，未单测 |

> ensemble 审计（多模型并行投票）是 V 层的"模块内并行"玩法：`review_shot_v2` 计划用 `qwen3.8-chat + deepseek-flash-2 + claude-haiku-4-5` 三路并发、多数决，压单模型抖动与 auto-pass 假通过。
