# v19（原 v16）营销号 Plus：视频链接二创 — 设计

> 2026-11-01 规划。目标：用户给一个视频链接（B站/抖音/YouTube 等），一条命令产出一条**全新解说向二创视频**——画面引用原片（改写处理）+ 解说词 LLM 改写 + 重 TTS 配音 + 字幕/调色/BGM 全套后期。
> **不新增模型**：yt-dlp（voice_clone 已用）/ faster-whisper STT（v2 M5）/ qwen3.8 多模态（v0 审片）/ deepseek 编剧 / CosyVoice（cosy-jieshuo1 影视解说音色现成）/ v5 特效 + v10 compose + LUT/BGM——全部现成基建接线与约束。

## 0. 问题陈述

- 营销号链路（v4 fast/hot）只解决"图文→视频"；**已有视频素材的二创**（影视解说/事件盘点/混剪）是另一大流量品类，目前全靠人工剪辑
- 二创的核心工作流是固定的：**看片 → 写解说词 → 配音 → 引用原片画面 → 组装**——每一步都是现成基建，缺的只是编排
- 与搬运的区别：解说词必须**改写**（不复述原文），画面必须**改写处理**（变速/镜像/裁剪/调色/插帧），强度可调 + 人工审核出口

## 1. 借鉴映射（全部本项目已有）

| 二创环节 | 现成基建 | 来源 |
|---|---|---|
| 视频/音频下载 | `yt-dlp`（bestaudio 已验证，扩展 bestvideo+bestaudio） | v4 voice_clone |
| 旁白转写（带时间戳） | faster-whisper large-v3-turbo | v2 M5 `utils/stt.py` |
| 画面内容理解 | qwen3.8-chat 多模态（缩图 512px 惯例） | v0 审片 `utils/llm.py` |
| 解说词改写 | deepseek-v4-flash（流式 + max_tokens 16384 铁律） | v17 `utils/llm.py` |
| 重配音 | CosyVoice `cosy-jieshuo1`（影视解说克隆音色，黑名单机制外的已验证音色） | v4 M3 |
| 画面改写 | 变速/镜像/裁剪（ffmpeg）+ 6 种 LUT（v2 M3）+ RIFE 插帧（v2 M1） | 全已有 |
| 镜头内特效/转场 | 8 种特效 + xfade 30+ | v5 `utils/effects.py` |
| 时间线编排 | compose 时间线 JSON（split/变速/画中画/贴纸/混音） | v10 `utils/compose.py` |
| 字幕/BGM ducking | SRT 烧录 + sidechaincompress | v0/v2 |

## 2. 设计

### M1 下载 + 内容理解（source.json）

```
链接 → yt-dlp（bestvideo+bestaudio 合流 mp4）→ {video.mp4, audio.wav}
     ├→ ffmpeg 抽帧（每 ~5s 一帧，512px）→ qwen3.8 多模态 → 分镜要点[]
     └→ faster-whisper STT（带字级/段级时间戳）→ 原旁白段落[]
     → 合成 source.json：{url, duration, segments:[{t0,t1,text,visual,frames}]}
```

- `utils/rework.py` 新建；下载复用 voice_clone 的 yt-dlp 惯例（tag 隔离防同名跳过 / .part 过滤 / 100KB 下限）
- STT 与抽帧理解**并行**（ThreadPool，同 v2 M2 预取惯例）
- 多模态调用遵守审片铁律：512px + JPEG85 缩图、180s timeout + 2 retries、失败 safe fallback（visual 置空不阻塞，靠 STT 文本兜底）

### M2 解说词改写 + 重配音

- LLM 改写输入 = source.json（原旁白 + 分镜要点）+ `--style`（解说/盘点/吐槽，默认解说）+ `--duration` 目标时长
- **改写而非复述**：prompt 约束"不得连续 15 字与原文重复"；程序断言 Levenshtein 相似度 < 阈值（复用 subtitle_correct 的距离计算）
- 产出 `script.json`：`[{t0,t1,narration,ref_segments:[原片段引用],motion}]`——时间轴映射决定 M3 引用哪些原片画面
- TTS 逐段配音（cosy-jieshuo1）；SRT 与旁白同源（v0 口径）；**音色黑名单机制**生效（新音色先 A/B）

### M3 画面二创 + 组装

- 每个 script 段 → 引用原片 `ref_segments` → **改写强度档**（`--visual-rewrite 0-5`，默认 2）：
  - 0 原样引用（仅裁到目标时长）；1 +变速(0.9-1.2x)；2 +LUT 调色；3 +镜像/裁剪构图；4 +RIFE 插帧变速重排；5 +v5 特效叠加
  - 组合式：档位 N 含全部 <N 的处理；每档都是纯 ffmpeg/现成工具
- 组装走 v10 compose 时间线 JSON（复用其 split/变速/LUT/转场/混音能力，不新写拼接器）
- 终拼铁律：h264 + yuv420p + 烧字幕（Windows 播放）

### M4 一条命令端到端

```bash
python core/vidance.py rework "<视频链接>" \
    --style 解说 --voice cosy-jieshuo1 --duration 60 \
    --visual-rewrite 2 --lut cinematic --bgm dramatic
```

- `core/vidance.py` 加 `rework` 子命令（早退路由，同 oneshot 模式）；产物 `output/rework/rw-{ts}/`
- 产物：`final.mp4` + `source.json`（原片理解）+ `script.json`（二创脚本）+ `prompts.md`（改写 prompt 留痕）+ meta.json（**来源 URL 必录**）
- 人工审核出口：成片后打印建议人工过一遍再发布；**不做自动发布**（同 fast/hot 原则）
- agent 化：`generator.rework` agent + `/api/tool/rework`（同 v18 收尾三通道惯例）

## 3. 里程碑总表

| 里程碑 | 内容 | 验收断言 | 预估 |
|---|---|---|---|
| M1 下载+理解 | yt-dlp 合流下载 + STT/抽帧并行 → source.json | 音频时长=容器±0.5s；转写字符>0；抽帧数匹配时长；B站真实链接端到端 | 0.5-1 天 |
| M2 改写+配音 | LLM 解说词改写 + 时间轴映射 + TTS + SRT | 相似度断言（防复述）；TTS 时长匹配新词；script.json 时间轴单调 | 1 天 |
| M3 画面+组装 | 改写强度 0-5 档 + compose 时间线 + 终拼 | 每档 ffmpeg 参数程序断言；成片 yuv420p；字幕烧录 | 1-1.5 天 |
| M4 端到端 | rework 子命令 + meta + agent/API + 文档 | 一条命令 3-5min 原片 → 成片；全链路可复验 | 0.5 天 |

测试：`tests/test_rework.py`（纯逻辑不依赖 GPU：URL/tag 隔离/强度档→ffmpeg 参数生成/相似度断言/时间轴映射单调性）。

## 4. 风险与边界

| 风险 | 缓解 |
|---|---|
| yt-dlp 反爬（抖音/YouTube 需 cookie 或外网） | M1 只承诺 B站（voice_clone 已验证可达）；其他平台 best-effort 报错点名 |
| 嘈杂 BGM 视频转写质量差 | faster-whisper large-v3-turbo 已是主力；转写置信度低时段 visual 兜底 |
| 多模态描述延迟（30-120s/批） | 批量合并多帧一次调用；失败 safe fallback 不阻塞 |
| 版权/合规 | 二创强度改写 + meta 录来源 + 人工审核出口；不做自动发布 |
| 原片横竖屏/分辨率杂 | 统一套 1280x704 画布（scale+pad，同 M6 组装段惯例） |

**明确不做**：自动发布/账号矩阵（v14 社交已移交队友）、换脸/人声克隆原角色声音（合规边界）、无来源链接的纯文字二创（走 fast）。

**参考**：v4 voice_clone yt-dlp 惯例、v2 STT、v10 compose、v18 oneshot 早退路由模式；roadmap §v19 原始条目。
