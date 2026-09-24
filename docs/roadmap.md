# Vidance 总览与路线图

> 视频生成 agent 系统：opencode 当"制片人"编排本地生图/生视频/生3D/语音引擎，从一句概念产出有声短片。
> 本文件结构对照 `roadmap_origin.md`；v0-v7 已实现，v8 起为规划版本。

## 1. 定位

不是 API 服务，是 **"agent 当导演"** 的视频生产系统：

| 角色 | 组件 | 说明 |
|------|------|------|
| 制片人 | opencode（director agent） | 全流程主控，关键决策点介入 |
| 编剧/策划 | LLM（deepseek-v4-flash） | 概念→分镜脚本→prompt 优化 |
| 摄影/演员 | 生图生视频模型 | SDXL / FLUX / Wan / HunyuanVideo / MiniMax-H3 |
| 角色锚 | 3D 重建 | TripoSplat(3DGS) / Hunyuan3D(mesh)，跨镜头不漂移 |
| 配音员 | TTS 双引擎 | edge-tts（自然在线）+ CosyVoice 2（本地克隆） |
| 审片员 | 多模态 LLM（qwen3.8-chat 主力） | 逐帧读图打分，闭环重做 |
| 剪辑师 | ffmpeg + moviepy + OpenCut 思路 | 拼接/字幕/配乐/调色/转场/特效 |

**核心创新**：3DGS 充当"角色锚"——每镜头起始帧由 RenderSplat 从同一 3DGS 按镜头角度渲染，喂 I2V 生成，避免跨镜头角色漂移。

---

## 2. 三层架构

```
┌──────────────────────────────────────────────────────────┐
│  产品层   v0 ✅ 有声短片 → v1 ✅ 角色一致性 → v2 ✅ 长视频       │
│         v3 ✅ 2D→3D→新视角 → v4 ✅ 营销号流水线                  │
│         v5 ✅ 剪辑特效 → v6 ✅ prompt 多轮核实 → v7 ✅ 前端 WebUI │
├──────────────────────────────────────────────────────────┤
│  编排层   opencode agent runtime                          │
│           director + subagents(reviewer/asset/scout) + skills │
│           core/ Python 流水线骨架（混合模式）              │
├──────────────────────────────────────────────────────────┤
│  引擎层   T2I: SDXL / FLUX                                │
│         T2V: Wan2.2 / HunyuanVideo / MiniMax-H3           │
│         3D:  TripoSplat(3DGS) / Hunyuan3D(mesh) / RenderSplat │
│         音频: edge-tts(在线自然) + CosyVoice 2(本地克隆, 9880) │
│              faster-whisper (STT兜底, large-v3-turbo, 9880)     │
│         后处理: ffmpeg + moviepy + RIFE(插帧) + LUT(调色) + BGM(配乐) │
│         LLM: USTC API (编剧 + 多模态审片)                  │
└──────────────────────────────────────────────────────────┘
```

**混合模式**：确定性流程（调引擎/拼接/后处理）硬编码在 `core/`，创意与判断决策（编剧/prompt 优化/审片/重做）交 agent。

---

## 3. 模型与引擎清单

### 3.1 视频生成模型（ComfyUI 实例）

| 模型 | 能力 | GPU | 端口 | 显存 | 状态 |
|------|------|-----|------|------|------|
| **Wan2.2-TI2V-5B** | T2V + I2V | GPU2 | 8189 | 18G | 运行中 |
| **MiniMax-H3 ref2va** | 参考图→视频+原生音频 | GPU0 | 8188 | 46G | 运行中（custom 主力） |
| **HunyuanVideo 13B** | T2V | GPU3 | 8190 | 20G | 运行中（备选） |
| **FLUX.1-dev fp8** | T2I | GPU3 | 8192 | 16G | 运行中（角色/场景图） |
| **TripoSplat** | 单图→3DGS | GPU3 | 8192 | ~4G | 随 FLUX |
| **Hunyuan3Dv2 turbo** | 图→mesh 重建 | GPU1 | 8193 | ~15G | 运行中（v3） |
| **SDXL Base 1.0** | T2I | — | 8191 | — | 已停（未接入） |

- 每镜随机 seed（防 ComfyUI 缓存命中）
- ⚠️ ComfyUI 启动不能加 `--cuda-device`，否则覆盖 `CUDA_VISIBLE_DEVICES`（main.py:87）
- 模型按需加载：启动只占几百 M，首次跑 workflow 才吃满显存

### 3.2 音频模型

| 模型 | 能力 | 端口 | GPU | 状态 |
|------|------|------|------|------|
| **CosyVoice 2 (0.5B)** | TTS + zero-shot 音色克隆 | 9880 | GPU2 | 运行中（默认音色改为 cosy-default） |
| **faster-whisper large-v3-turbo** | STT 语音转文字 | 内嵌 | 共享 | 按需（`--stt`） |
| **edge-tts** | 在线 TTS（微软神经语音） | 9880 | CPU | 运行中（需外网，偶发抖动） |

- TTS 双引擎统一封装（`utils/tts_server.py`）：edge-* 走 edge-tts，cosy-* 走 CosyVoice
- **默认音色已从 edge-moe 改为 cosy-default**（edge 在线偶发 Connection timeout，规避"有字幕没语音"）
- TTS 失败降级链：目标音色重试 3 次 → 本地 cosy-default 真声 → 静音兜底

### 3.3 插帧 / 后处理

| 组件 | 能力 | 位置 | 说明 |
|------|------|------|------|
| **RIFE v4.26** | 光流插帧（过渡 + slowmo） | ComfyUI | 运行中 |
| **3D LUT ×6** | 调色 | `utils/luts/` | cinematic/warm/cool/vintage/vivid/soft |
| **BGM** | 配乐 | `bgm/` | incompetech CC BY 真实素材（calm/uplifting/mysterious/dramatic/playful/epic）+ ducking |

### 3.4 LLM（远程 API，不本地部署）

| 模型 | 用途 |
|------|------|
| deepseek-v4-flash | 编剧、prompt 优化、LUT/BGM 选择、特效选择、完整度评估 |
| qwen3.8-chat | 多模态审片 + 图片相关性审核（主力，支持视觉） |

> USTC API：`https://api.llm.ustc.edu.cn/v1`，key 存 `config/config.json`

---

## 4. 版本路线

### v0 — 有声短片 MVP ✅ 已完成

**目标**：跑通"概念→有声短片"端到端。
**状态**：2026-09-07 端到端验证通过。概念"一只猫在月球上跳舞" → 13.3s 成片（3 镜，审片 7/7/7）。TTS 双引擎上线。

```
concept → [LLM 编剧→分镜] → [Wan T2V 每镜] → [TTS 配音] → [多模态审片+重做≤2]
        → [ffmpeg 拼接+字幕+转场] → final.mp4 + meta.json
```
**详细设计**：[v0-design.md](./v0-design.md)

### v1 — 角色一致性 ✅ 已完成（含 v1.1）

**目标**：同一角色跨镜头不漂移。
**状态**：2026-09-08 全链路通过。v1.1：character-mode 开关（auto/3dgs/flux），flux 模式绕过 3DGS 瓶颈（I2V 相关性 0.993-0.998）；3DGS 位姿修复（PCA 对齐 + 接地合成，review_character score 2→7）；Wan22ImageToVideoLatent（48ch + noise_mask）。
**瓶颈**：3DGS 一致性仍受限；flux 侧面/背面可能走样。
**详细设计**：[v1-design.md](./v1-design.md)

### v2 — 长视频 + 完整后期 ✅ 已完成（v2.1 backlog 已接线）

**目标**：超出单次生成上限的长片 + 完整后期。
**状态**：2026-09-09 M1-M5 完成。RIFE 过渡 + 并行预取 + LUT 调色 + BGM ducking + STT 字幕全通。v2.1：`--duration N`、`--slowmo N`、per-shot 过渡、`concat` 子命令。
**详细设计**：[v2-design.md](./v2-design.md)

### v2.5 — 多入口架构 + H3 引擎接入 ✅ 已完成

**目标**：重构入口与引擎层——统一 CLI 多子命令 + H3 ref2va 新引擎 + 后处理模块化。
**状态**：2026-09-11 通过（13 脚本 / 32 镜 / ~96s 成片，双角色跨镜一致）。
- 统一 CLI `vidance.py`（auto/custom/quick），PostProcessor 抽出共享
- H3 ref2va：`<Picture i>` 引用多角色，1344×768 + 原生音频，中文 prompt 直传
**详细设计**：[v2.5-design.md](./v2.5-design.md)

### v3 — 2D→3D→新视角 ✅ 已完成（M0-M7，M8 跳过）

**目标**：从 2D 内容重建 3D，生成原视角没有的新角度视频。
**进度**：M0 headless 渲染 ✅ / M1 Hunyuan3Dv2 mesh 重建 ✅ / M2 multiview ✅ / M3 mesh_render 封装 ✅ / M4 场景锚 ✅ / M5 角色双路径 ✅ / M6 资产库 ✅ / M7 端到端联调 ✅ / M8 跳过。
**详细设计**：[v3-design.md](./v3-design.md)

### v4 — 营销号流水线 ✅ 已完成（M1-M6；发布不做，人精选手动上传）

**目标**：批量自动化内容生产。
**进度**：M1 爬虫+选题 ✅ / M2 异步任务队列 ✅ / M3 声音克隆生产化 ✅ / M4 FunClip 智能裁剪 ✅ / M5 素材爬取 ✅ / M6 快速营销号链路（fast/hot）✅。
**详细设计**：[v4-design.md](./v4-design.md)

### v5 — 剪辑特效包 ✅ 已完成（M1-M4）

**目标**：丰富单镜头内/镜头间剪辑表现力。
**进度**：M1 特效库（8 种）✅ / M2 xfade 转场（30+ 种）✅ / M3 LLM 自动选 ✅ / M4 端到端 ✅。
**详细设计**：[v5-design.md](./v5-design.md)

### v6 — prompt 多轮核实 ✅ 已完成（M1-M4）

**目标**：prompt 信息不全时打回，多轮对话核实需求。
**进度**：M1 完整度评估（6 维）✅ / M2 对话状态机 ✅ / M3 CLI `ask` ✅ / M4 API 三端点 ✅。修复：全 6 维齐才 COMPLETE，每轮批量问完合并 reply。
**详细设计**：[v6-design.md](./v6-design.md)、[usage-v6.md](./usage-v6.md)

### v7 — 前端 agent WebUI ✅ 代码完成（浏览器渲染待确认）

**目标**：仿豆包对话式 agent WebUI——左功能边栏 + 顶部画布 + 下/右发框；`/` 斜杠命令调用既有 tool。
**进度**：M1 后端端点（video/options/tools/tool 分发/ui）✅ / M2 对话+`/`补全 ✅ / M3 画布（任务轮询+video 卡片）✅ / M4 ask+scout 接洽 ✅。
**15 命令**：auto/fast/hot/ask/clip/scout/voices/luts/moods/video/tasks/status/trends/clean/help。
**详细设计**：[v7-design.md](./v7-design.md)、[usage-v7.md](./usage-v7.md)

---

### v8 — 前端增强（已初步完成）

目标：做出更好用的UI

进度：
1、实现类似豆包或者智象未来的边栏-对话式简洁UI
2、实现comfyui跳转、日志输出、自定义配置

（目前感觉我的目标就做到这种程度，我们的思想是SaaS软件即服务，主界面就越简洁越好，想要专业一点的直接用comfyui跳转过去）

以下仅作参考

**目标**：把 v7 的单页聊天 UI 升级为完整的导演工作台（仍零 npm 自包含优先）。

**范围**：
- 资产库面板：角色/场景/道具可视化管理，拖拽引用（对接 v3 `asset_registry`）
- 分镜预览面板：九宫格候选视角 + 关键帧编辑
- 任务进度可视化：pipeline 各步骤实时状态（复用 v7 日志面板）
- 时间线编辑雏形：镜头排列、转场、音频轨道（**仅展示+提交命令，剪辑逻辑在后端**）
- ComfyUI 画布：直连跳转（已完成）或按实例选择菜单

**里程碑**：M1 资产库面板 → M2 分镜预览 → M3 进度可视化 → M4 时间线展示

**参考**：BigBanana 网格化导演工作台、Toonflow 分镜表、v7 现有三栏布局。

---

### v9 — API 接口标准化（已初步完成）

目前v8里面也说了，基本已经配置好了，主要是平时我们也不太需要这个，后面就整合到一起就好了，但是我感觉这个不是很硬核的功能，所以可以留到最后试试。

（目前感觉我的目标就做到这种程度）

以下仅作参考


**目标**：对外暴露标准化 RESTful API，第三方/LLM 可编程调用 Vidance 全部能力。

**范围**：
- 多 Vendor 适配层：统一 text/image/video/tts 四类接口协议，新增提供商只写适配器
- 生图/生视频独立切换：前端/API 分别选择 T2I 与 I2V/T2V 模型
- 模型能力自动发现：查询 `/v1/models` 自动标注 t2i/i2v/t2v
- 用量统计与限流：调用次数/花费记录 + 并发上限（Semaphore）
- API 端点标准化：tasks/tools/scout/clone/clip/dialog 统一 OpenAPI 文档

**里程碑**：M1 Vendor 适配层 → M2 能力自动发现 → M3 用量统计 → M4 OpenAPI 文档

**参考**：Toonflow `data/vendor/`、ViMax `tools/protocols.py` + Semaphore；v7 现有 `/api/tool/{name}` 统一分发。

---

### v10 — 拼接与特效（OpenCut 思路，后端 CLI）（✅ M1-M4 完成 2026-09-24）

**目标**：把"拼接/剪辑/特效"做成**后端可调用命令**（不做前端），方便 LLM 直接编排。

**参考 OpenCut**（开源 CapCut 替代）的核心时间线模型：**轨道(track) → 片段(clip) → 裁剪/分割 → 转场 → 特效/关键帧 → 导出**。我们只取其"后端剪辑原语"思想，用 ffmpeg 实现，不引入其前端。

**范围**（`utils/compose.py` 或扩展 `utils/effects.py`，CLI + `/api/tool`）：
- 时间线数据模型：JSON 描述 track/clip（源文件、入出点、时间轴位置、层级）
- 拼接命令：多片段顺序拼接（硬切/xfade/RIFE），支持视频+音频+图片混合轨
- 裁剪/分割：按时间码裁切、去段、变速、静音
- 转场：复用 v5 的 30+ xfade
- 特效：复用 v5 的 8 种镜头内特效 + 关键帧驱动（透明度/缩放/位置）
- 叠加：画中画、文字/水印层、音频混音轨
- 导出：统一 yuv420p h264

**里程碑**：M1 时间线 JSON 模型 + 拼接 → M2 裁剪/分割/变速 → M3 转场+特效集成 → M4 CLI/API 暴露 + LLM 自然语言→时间线 JSON

**状态**：M1-M4 全部完成。`utils/compose.py`（时间线 JSON 模型 + 主轨 xfade 拼接 + trim/rate + 8 特效链 + 画中画/文字叠加 + 多音轨 amix/ducking）；`vidance.py compose` CLI + `/api/tool/compose`；实测 `output/compose_fx_demo.mp4`（4 段特效主轨 + 3 转场 + 3 文字 + 画中画 + BGM ducking）。未做：关键帧 animations、掩码 masks、sticker/graphic 轨、分割 split。另建**剪辑指令模式库** `docs/instructions/compose-commands.{md,json}`（36 条，前端 `/help` 展示，供 SFT）；完整效果演示视频 `output/output/20260924_compose_demo/v10_effects_demo.mp4`。LLM 自然语言→时间线 JSON（`llm.timeline_from_text`）待补。用法见 [usage-v10.md](./usage-v10.md)。

**参考**：OpenCut（时间线模型）、BigBanana CutOS（粗剪）、v5 effects.py、v2 `concat` 子命令。

---

### v11 — 接入社交媒体（🎯 待开发）

**目标**：把成片一键分发到社交平台 / IM，任务完成可推送通知、可在 IM 里用 `/` 命令触发。

**范围**：
- 发布渠道适配：抖音/B站/视频号/小红书（人工审核后发布，或开放平台 API）
- IM 机器人网关：`utils/notify/`（`Notifier` 抽象 + 企业微信 / 飞书 / 钉钉 / Slack / Telegram + factory 多通道并发推送）
- 任务完成 post-hook 接入 v4 scheduler
- 回调网关 `POST /api/notify/{channel}/callback`（解密→文本→复用 v9 `/api/tool/{name}`）
- 富媒体卡片：IM 中展示视频预览卡片、进度条、候选方案选择
- config.json 加 `notify` 节；个人微信不做

**里程碑**：M1 Notifier 抽象+企微 → M2 飞书/钉钉+factory → M3 任务完成自动通知 → M4 回调网关 + 至少一个发布渠道

**参考**：`lark-oapi`（飞书官方 SDK）、wechaty；BigBanana 多候选决策点；原 v9-design.md。

---

### v12 — 整合已有开源仓库（🎯 待开发）

**目标**：吸收成熟开源项目的工程能力，不重复造轮子。

**范围**：
- 断点续跑机制：每步输出持久化，中断后可恢复（ViMax checkpoint/resume）
- JSON 容错解析：LLM 输出不稳定时容错（TrailingCommaTolerantParser）
- 结构化视频提示词模板：`[Visual]/[Motion]/[Camera]/[Audio]/[Narrative]` 五维
- RAG 管线：FAISS + BGE Reranker，长文本输入处理
- 结构化剧本拆解：非结构化文本→角色/场景/道具
- 本地语义嵌入 ONNX（all-MiniLM-L6-v2）：资产匹配/场景关联
- 重试标准化：tenacity 统一 API 重试
- 候选整合对象：MoneyPrinterTurbo（架构参考）、ViMax、Toonflow、BigBanana、OpenCut

**里程碑**：M1 断点续跑+JSON 容错 → M2 五维提示词模板+RAG → M3 剧本拆解 → M4 嵌入+重试标准化

**参考**：ViMax、Toonflow、BigBanana、MoneyPrinterTurbo（本机 `/mnt/disk_sdb/zxy/MoneyPrinterTurbo/`）。

---

### v13 — 多智能体系统（🎯 待开发）

**目标**：从单 pipeline 串行升级为三层 Agent 解耦架构。

**范围**：
- 三层架构：决策层（编排，对应 scheduler 升级）→ 执行层（各工具 Agent）→ 监督层（审核 Agent，只提问不改）
- **编剧 Agent**：故事生成/剧本拆解/分镜规划
- **审核 Agent**：多模态审核（画面质量/一致性/内容安全）
- **美术 Agent**：角色定妆照/场景概念图/道具设计
- **演员 Agent**：关键帧生成 + 视频生成
- **剪辑 Agent**：自动拼接+转场+节奏控制（对接 v10）
- **配音配乐 Agent**：TTS + BGM 选择 + 音效
- Agent 间通信协议 + 状态管理

**里程碑**：M1 角色定义+编排骨架 → M2 编剧+审核 Agent → M3 美术+演员 Agent → M4 剪辑+配音 Agent + 三层落地

**参考**：ViMax 14 Agent 分工、Toonflow 三层解耦、BigBanana 资产驱动。

---

### v14 — 长视频质量（🎯 待开发）

**目标**：提升长片（分钟级）的画面质量与跨镜一致性。

**范围**：
- 关键帧驱动生成：先生成首帧/尾帧，再插值生成中间视频
- 一镜到底：链式 I2V（段 N 末帧→段 N+1 首帧条件，拼缝隐形）+ LLM 连续运镜脚本 + 漂移控制（每段重注入角色锚）+ `--oneshot --duration N`（原 v8-design.md 能力并入）
- 分镜间一致性：上下文感知注入（当前场景/角色/服装参考）
- clip 间过渡管理：情绪/色调/节奏连贯性
- 层级角色一致性：Scene 级 → Event 级 → 全局角色注册表
- 长文本处理管线：小说压缩 → 事件提取 → RAG 检索 → 场景分解
- 世界观持久化：地图/区域/风格等全局上下文持续注入
- 衍生资产系统：角色变身/场景时间变体自动生成

**里程碑**：M1 关键帧驱动 → M2 一镜到底（末帧回灌+运镜脚本）→ M3 层级一致性 → M4 长文本管线+世界观

**参考**：ViMax Novel2Movie、BigBanana 关键帧驱动、Toonflow 导演规划五步；原 v8-design.md。

---

### v15 — 轻量化（无 GPU 优先）（🎯 待开发）

**目标**：降低/消除本地 GPU 依赖，纯 API 也能跑。

**范围**：
- 纯 API 模式：所有生成任务可切云端 API（SiliconFlow 等），完全不依赖本地 GPU（对接 v9 模型提供商）
- Pipeline 轻量化：去除 GPU 依赖的预处理/后处理，或替换 CPU 版本
- 模型层面轻量化：小模型做预览/草稿，大模型做最终渲染
- 按需加载：各步骤按需初始化，不预加载所有模型
- Docker 轻量化部署：分离 CPU 服务（API/前端/调度）与 GPU 服务（生成）
- 本地 ONNX 小模型：语义嵌入/分类等替代大模型调用

**里程碑**：M1 纯 API 模式 → M2 按需加载+CPU 后处理 → M3 草稿/成片双档 → M4 Docker 分离部署

**参考**：BigBanana Docker Compose、Toonflow ONNX、v9 模型提供商系统。

---

## 5. GPU 与端口分配

| 服务 | 端口 | GPU | 环境 | 启动方式 |
|------|------|-----|------|---------|
| MiniMax-H3 ref2va (ComfyUI) | 8188 | GPU0 | comfyui | `./start_services.sh start h3` |
| Wan T2V/I2V + RIFE (ComfyUI) | 8189 | GPU2 | comfyui | `./start_services.sh start wan` |
| HunyuanVideo (ComfyUI) | 8190 | GPU3 | comfyui | `./start_services.sh start hunyuan` |
| FLUX + TripoSplat (ComfyUI) | 8192 | GPU3 | comfyui | `./start_services.sh start flux` |
| Hunyuan3Dv2 turbo (ComfyUI) | 8193 | GPU1 | comfyui | `./start_services.sh start h3d` |
| TTS 双引擎 (edge-tts + CosyVoice) | 9880 | GPU2 | cosyvoice | `./start_services.sh start tts` |
| Vidance API + WebUI | 8894 | — | comfyui | `./start_services.sh start api` |

- **一键脚本** `start_services.sh`（start/stop/restart/status/test/logs），服务↔端口↔GPU 映射见脚本注释
- ⚠️ ComfyUI 启动不能加 `--cuda-device`，会覆盖 `CUDA_VISIBLE_DEVICES`（main.py:87）
- FLUX(8192) 与 HunyuanVideo(8190) 共用 GPU3，互斥
- 模型按需加载；TTS 启动即加载 CosyVoice（约 28s）
- edge-tts 在线引擎不占 GPU（需外网，偶发抖动）

---

## 6. LLM 与 API

| 服务 | 用途 | 状态 |
|------|------|------|
| USTC deepseek-v4-flash | 编剧、prompt 优化、LUT/BGM/特效选择、完整度评估 | ✅ 免费 |
| USTC qwen3.8-chat | 多模态审片 + 图片相关性审核 | ✅ 免费 |

> USTC API：`https://api.llm.ustc.edu.cn/v1`，key 存 `config/config.json`（不入 git）

---

## 7. 关键技术决策

1. **混合模式编排**：确定性流程硬编码，创意/判断交 agent
2. **ComfyUI workflow JSON 模板 + 参数注入**：可视化调试
3. **director + reviewer/asset/scout subagents**：opencode 原生，职责隔离
4. **TTS 双引擎**：cosy-* 本地默认（规避 edge 外网抖动）+ edge-* 在线备选
5. **字幕用 TTS 时间戳**，STT 兜底（`--stt`）
6. **审片用 qwen3.8-chat**：支持视觉，180s timeout + 2 retries + safe fallback
7. **每镜随机 seed**：防 ComfyUI 缓存命中
8. **审片 3 次上限 + 最高分兜底**：防死循环
9. **存储分层**：代码/配置/小素材放 sdb，模型/视频/产出放机械盘，软链统一访问
10. **服务缺省兜底**：TTS 不可用→降级 cosy/default→静音；图源 crawl→FLUX→占位图，流程不崩
11. **拼接/特效后端化**（v10）：只做可被 LLM 调用的 CLI/API，不做前端，参考 OpenCut 时间线模型
12. **前端零 npm**：v7/v8 自包含 HTML+vanilla JS，FastAPI 静态服务

---

## 8. 目录结构

```
vidance/
├── opencode.json              # opencode 配置：provider + agents + permissions
├── AGENTS.md                  # 项目约定 + 命令（供 agent 读）
├── start_services.sh          # 模型服务一键启停/自检脚本
├── .opencode/
│   ├── agents/                # director/reviewer/asset/scout.md
│   └── skills/                # scriptwriting/review/topic_scouting
├── config/config.json         # API key、引擎地址、模型名、音色配置
├── core/                      # 编排层
│   ├── vidance.py             # 统一 CLI（auto/custom/quick/concat/fast/hot/ask）
│   ├── pipeline.py            # auto 模式流水线主控
│   ├── custom_gen.py          # custom 模式 H3 ref2va 生成
│   ├── postprocess.py         # 共享后处理（RIFE/LUT/BGM/STT）
│   ├── scheduler.py           # 异步任务队列（TaskQueue SQLite + Scheduler）
│   ├── api_server.py          # FastAPI :8894（任务/dialog/tool/ui/…）
│   └── dashboard.py           # HTML 仪表盘
├── utils/                     # 工具层
│   ├── comfy_api.py           # ComfyUI 客户端（T2V/I2V/TripoSplat/FLUX/H3）
│   ├── llm.py                 # USTC LLM（文本+多模态）
│   ├── tts.py / tts_server.py # TTS 客户端 + 双引擎服务
│   ├── splat_renderer.py      # 3DGS 多角度渲染
│   ├── mesh_render.py         # headless mesh 渲染（pyrender+EGL）
│   ├── hunyuan3d.py           # Hunyuan3Dv2 重建客户端
│   ├── asset_registry.py      # 资产库管理
│   ├── crawler.py             # 热点爬虫
│   ├── voice_clone.py         # 声音克隆生产化
│   ├── funclip.py             # FunClip 智能裁剪
│   ├── asset_crawler.py       # 素材爬取（Pexels 图源 + BGM）
│   ├── fastline.py            # 快速营销号链路（图片+zoompan+TTS）
│   ├── effects.py             # 剪辑特效（v5）
│   ├── dialog.py              # prompt 多轮核实状态机（v6）
│   ├── ffmpeg_tools.py        # 抽帧/拼接/字幕/合成
│   ├── rife.py / gen_luts.py / music.py / stt.py
│   ├── compose.py             # v10 时间线拼接（🎯 待实现）
│   ├── oneshot.py             # v14 一镜到底（🎯 待实现）
│   ├── notify/                # v11 机器人网关（🎯 待实现）
│   ├── luts/  bgm/  workflows/  voices/
├── ui/                        # v7/v8 前端（index.html 自包含，:8894/ui）
├── docs/                      # roadmap + v0-v15 design + usage*.md
├── voice_samples/ → /mnt/dataset/...  # 音色试听样本（软链）
└── output/ → /mnt/dataset/zxy/vidance/output/  # 成片（软链）
```

---

## 9. 相关仓库与参考

| 仓库 | 用途 |
|------|------|
| ComfyUI (`/mnt/disk_sdb/zxy/ComfyUI/`) | 共用推理引擎，多实例 |
| CosyVoice (`/mnt/disk_sdb/zxy/CosyVoice/`) | TTS 引擎 |
| MoneyPrinterTurbo | 架构参考（字幕双模式/VideoParams/skill） |
| OpenCut | v10 拼接/时间线模型参考（仅后端思路） |
| ViMax / Toonflow / BigBanana | v12/v13/v14 多智能体与长视频参考 |

---

## 10. 部署记录

各模型部署细节见 `/mnt/disk_sdb/zxy/` 下：
- `MiniMax-H3-部署记录.md`、`Wan2.2-部署记录.md`、`HunyuanVideo-部署记录.md`、`SDXL-部署记录.md`、`FLUX-部署记录.md`
- Hunyuan3Dv2 见 v3-design.md §13

> 模型文件统一存 `/mnt/dataset/zxy/<Model>-ComfyUI/`，通过 `extra_model_paths.yaml` 映射到 ComfyUI。
