# Vidance 总览与路线图

> 视频生成 agent 系统：opencode 当"制片人"编排本地生图/生视频/生3D/语音引擎，从一句概念产出有声短片。
> 原始规划稿见 `archive/roadmap_origin.md`。**已实现**：v0-v7 + v10 时间线拼接（M1-M8）+ v15 SVG 流水线（S1-S5）+ t2c + v17（M1-M2）；其余（v8/v9/v11-v14/v16、v17 M3-M4）为规划版本。

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

### v10 — 拼接与特效（OpenCut 思路，后端 CLI）（✅ M1-M8 全部完成 2026-09-25）

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

**状态**：M1-M8 全部完成（M5-M8 2026-09-25）。`utils/compose.py`（时间线 JSON 模型 + 主轨 xfade 拼接 + trim/rate + 8 特效链 + 画中画/文字叠加 + 多音轨 amix/ducking）；`vidance.py compose` CLI + `/api/tool/compose`；实测 `output/compose_fx_demo.mp4`（4 段特效主轨 + 3 转场 + 3 文字 + 画中画 + BGM ducking）。**M5 关键帧**（x/y/scale/opacity/rotation 表达式动画 + linear/ease-in-out，三轨通用）、**M6 掩码**（circle/rounded/rect/image + feather，geq+alphamerge）、**M7 贴纸轨**（PNG 循环补帧/GIF 循环）、**M8 split**（`--at` 多切点，`--precise` 帧级）全部实测通过。另建**剪辑指令模式库** `docs/instructions/compose-commands.{md,json}`（36 条，前端 `/help` 展示，供 SFT）；完整效果演示视频 `output/output/20260924_compose_demo/v10_effects_demo.mp4`。LLM 自然语言→时间线 JSON（`llm.timeline_from_text`）待补。用法见 [usage-v10.md](./usage-v10.md)。

**参考**：OpenCut（时间线模型）、BigBanana CutOS（粗剪）、v5 effects.py、v2 `concat` 子命令。

---

### t2c — 自然语言 → 命令翻译层（✅ 已接入 2026-09-24）

**目标**：让用户用中文口语驱动 Vidance，而非记斜杠命令。总体是自建 **agent_loop**：tool = Vidance 自己的命令；text→command 翻译器 = **自训练的 mt5-small 微调模型**（非通用 LLM）。

**链路**：`/api/chat`（LLM 判意图：闲聊直接回 / 创作返回 `[[VIDEO:概念]]`）→ v6 dialog 多轮核实 → `POST /api/t2c`（`utils/t2c_server.py` 的 `translate(text)`）→ 得命令 → 前端展示 + ▶ 执行。

**范围**：
- 模型 `t2c/model`（mt5-small 微调，CPU 可跑）；推理封装 `utils/t2c_server.py`（进程内单例 + 可选 HTTP :9881）
- 后端 `POST /api/t2c`；前端 `t2cTranslate`/`runT2CCmd`（dialog COMPLETE 后出「→ 智能翻译成命令」）
- 网页端 `:8894/ui` 直接测；命令行 `python utils/t2c_server.py '帮我auto生成城市夜景'` → `python core/vidance.py auto "城市夜景"`

**已知局限**：现模型只覆盖训练时（旧）命令分布，对 fast/quick 等偶有偏差。**计划**：全部指令（含 v10 剪辑）齐全后，用 `docs/instructions/*.json` 作数据源**重训**覆盖全量。

**详细设计**：[v-t2c.md](./v-t2c.md)

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

### v13 — 多智能体系统（✅ M0-M4 全部完成，2026-09-26）

**目标（定稿口径）**：物理分层 D/G/P/V + 薄包装 Agent + 黑板 + chain 编排，不改既有业务逻辑。

**落地形态**（与最初"六 Agent 大重构"规划不同，按 2026-09-26 拍板的薄包装方案执行）：
- **物理分层**：`agents/{director,generator,post,audit,common}/`，各层 `tools/` 存放从 utils/ 迁入的 27 个实现模块（`utils/` 原路径全部保留薄壳转发，旧 import/CLI 零破坏）；`core/`（CLI+api+scheduler=决策层宿主）与 `core/tts_server 启动链路` 不动
- **Agent 契约（薄包装）**：`agents/base.py` — `@register(name, layer, desc, inputs, needs_gpu)` + `TaskResult{ok, artifacts, trace, score, error}` + `run_agent()`（计时/异常兜底/黑板落盘）；各层 `agents.py` 把既有能力包装成 28 个 Agent（D×6：scriptwrite/scout/select_lut/select_bgm/select_effects/**brain 智囊**；G×4：svg/fast/wan_t2v/**artist 美术师**；P×9：tts/compose/lut/bgm/subtitle_burn/stt/fx/transition/**voice 配音师**；V×5：review_shot/review_character/relevance/describe_character/review_ensemble）
- **黑板**：`agents/blackboard.py` `agent_runs` 表（task_id/agent/layer/ok/score/artifacts_json/error/耗时），复用 `output/tasks.sqlite`，dashboard/trace 统一数据源
- **chain 运行器**：`agents/runtime.py` `run_chain(steps, ctx)`，`${ctx.key}` 引用上一步产物（整体引用保类型/内嵌替换成字符串），产物双键回写（`as.artifact` + 裸 artifact），optional 步骤失败续跑
- **ensemble 审核**：`audit.review_ensemble` 多模型投票基础设施，默认单票 `models=['qwen3.8-chat']`，评分归一 0-1、全票 pass
- **统一入口**：CLI `python core/vidance.py agent {list|run|chain}`；API `GET /api/agents`、`POST /api/agents/{name}/run`、`POST /api/agents/chain`、`GET /api/agents/board`、`GET /api/tasks/{id}/trace`
- **scheduler 编排**：`TaskSubmit.mode='chain'` + `chain/ctx` 字段 → 进程内 `run_chain`，产物回写 task.output，trace 走 `/api/tasks/{id}/trace`

**验证**：27 模块旧/新路径 import 同一性 + core 7 模块 + 壳 CLI（compose/llm/stt）+ 端到端 split；三步 LLM 链（编剧→选LUT→审片 score=2）；scheduler chain 任务 completed+黑板落盘。

**v13.1 前端可视化（2026-09-26）**：`/arch` 命令（`tool_dispatch` + `ui renderArch()` 分层彩色卡片，运行时注册表点亮 24 Agent）；chain 任务卡片内嵌 trace 时间线（轮询 `/api/tasks/{id}/trace`，`#步骤 层`徽章+✓/✗+评分+耗时）；`/agent list|run|chain` 命令三端同源。

**v13.2 闭环（2026-09-26）**：pipeline 审片重试接入 `review_ensemble`（config `review.ensemble` 开关，默认关，失败回退单票）；GPU Agent 注册 `h3shot/splat/mesh` + `post.pip` 画中画（28 个，splat 实测出 PLY、pip 实测出片）；`run_agent` 自举 load_all。

**后续（v13.x backlog）**：/ui 链 DAG 视图、h3shot 实卡长测、v11 队友网关对接 agent API、chain 并联分支/断点续跑。

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
- Pipeline 轻量化：去除 GPU 依赖的处理。**无 GPU 出片两条线**（均已具备或已规划）：
  1. **营销号流水线（已有）**：v4/v5 的生图/爬图 → zoompan 运镜 → TTS → 剪辑，零视频模型，已可用
  2. **LLM 生成 SVG → 渲染成片（✅ S1-S5 已实现 2026-09-24/26）**：LLM 产出带 CSS/SMIL 动画的自包含 SVG → 无头浏览器逐帧渲染 → ffmpeg 拼帧 → mp4。**纯 CPU、秒级、矢量清晰**，适合信息图/文字动画/数据可视化/科普短片。已落 `utils/svg_llm.py`（S1 概念→SVG + S5 plan_narration 旁白规划）+ `utils/svg_pipeline.py`（S2 单帧/S3 抽帧/S4 拼 mp4/**S5 SvgLine 有声流水线**：LLM 旁白→逐段 TTS（edge→cosy→静音降级）→逐段 SVG 渲染→字幕烧录→crossfade 拼接→可选 LUT/BGM），CLI `vidance.py svg --concept "…" [--voice 音色 -n 3 | --say "句1" --say "句2"]`；`/api/tool/svg` 无声同步/有声异步（svg_* job 复用 h3shot 轮询）。实测 `output/svg_e2e/s1.mp4`（音视频双流）。依赖 Playwright+Chromium（已装）
     - 关键设计：**确定性逐帧**（用 Web Animations API 把动画 `currentTime=t` 后 pause 再截图，而非 wall-clock `wait_for_timeout`），保证帧率精确无抖动
     - 渲染后端：Playwright/Chromium（需装）或 `resvg`/`cairosvg`（仅静态帧）；`node` 已就绪可走 puppeteer
     - 可选：LLM 直接给 SVG 代码 + 时长/分辨率 → 一条命令出片；后续可接 v9 模型提供商
- 模型层面轻量化：小模型做预览/草稿，大模型做最终渲染
- 按需加载：各步骤按需初始化，不预加载所有模型
- Docker 轻量化部署：分离 CPU 服务（API/前端/调度）与 GPU 服务（生成）
- 本地 ONNX 小模型：语义嵌入/分类等替代大模型调用

**里程碑**：M1 纯 API 模式 → M2 按需加载+CPU 后处理 → M3 草稿/成片双档 → M4 Docker 分离部署

**参考**：BigBanana Docker Compose、Toonflow ONNX、v9 模型提供商系统。

---

### v16 — 营销号 Plus：视频链接二创（🎯 待开发，backlog）

**目标**：用户给一个**视频链接**（B站/抖音/YouTube 等），流水线自动二创出一条新视频，**保留原有全部功能**。

**范围**：
- **素材获取**：yt-dlp 下载原视频（复用 v4 voice_clone 的 yt-dlp 能力）→ 抽帧/切片
- **内容理解**：帧 → 多模态 LLM 描述 + STT（`utils/stt.py`）转写旁白 → 分镜/要点
- **二创剪辑**：画面二创（可选重排、变速、局部放大、v5 特效/转场）＋ **重新 TTS 配音**（改写解说词，`utils/tts.py`）＋ 字幕（STT）＋ LUT/BGM
- **去重/合规**：画面改写强度可调（翻转/裁剪/调色/插帧），避免直接搬运；保留人工审核出口
- **一条命令**：`python core/vidance.py rework "<视频链接>" --style 解说 --voice cosy-jieshuo1`

**依赖**：v4 下载/STT/TTS + v5 剪辑特效 + v10 时间线 compose（把二创素材编排成时间线）。

**里程碑**：M1 下载+抽帧+转写 → M2 改写解说词+重配音 → M3 画面二创（特效/转场）→ M4 一条命令端到端。

---

### v17 — 三排正交模块化（🔄 M1-M2 已完成 2026-09-26，详见 [v17-modules.md](./v17-modules.md)）

**目标**：导演层（人肉/LLM/热点/对话）× 生成层（H3/Wan/爬图生图/SVG/二创）× 后期层（配音/字幕/拼接/调色配乐/特效/时间线）三层彻底解耦，任意排列组合出一条完整链路，环节实现唯一无冗余。

**里程碑**：
- **M1 ✅**：`core/narration.py`（Narrator：say 含三级降级链 / silence / srt）；fastline `_tts_segment`/`_gen_silence`/`_build_srt`/`srt_time`/`_video_duration` 与 svg_pipeline `_tts_seg`/`_silence`/`_srt_time`/`_probe_duration` 全部改薄壳转发（删 ~80 行重复）；SVG S5 回归通过
- M2 `vidance.py make --director --generator` 统一入口（现有子命令变别名）
- M3 `utils/director.py` 合并三套编剧/旁白 prompt（pipeline/fastline/svg_llm）为统一 schema
- M4 生成器契约统一，v16 二创作为 G5 即插即用

---

### v18 — 面向最终用户的交付形态（🎯 规划，2026-09-26 立项）

**目标**：从"开发者本地系统"变成"用户可安装可运行的产品"——先探测本机资源，再按资源分发对应部署档，屏蔽底层细节。

**里程碑草案**：
- **M0 资源探测**：`core/doctor.py`（GPU 型号/显存/端口占用/conda 环境/磁盘/外网可达性）→ 输出 profile JSON，`vidance doctor` + `/api/doctor`；首次启动自动跑并推荐档
- **M1 部署分档**：lite（无 GPU：v15 纯 API 模式 + edge-tts + SVG/crawl 图源，pip 即装）/ std（单卡：T2V+CosyVoice，官方镜像）/ full（多卡全家桶：docker-compose 编排 ComfyUI×N+TTS+API），对应 `deploy/{lite,std,full}` Dockerfile/compose 模板
- **M2 一键安装**：`install.sh` 按 M0 探测选档 → 拉镜像/建环境 → start_services 接管 → 冒烟自检（复用 start_services.sh test）
- **M3 面向用户细节**：config 向导（首次填 LLM key/选端口）、失败自诊断提示（端口占用/显存不足/外网不通点名到人）、输出目录与清理策略 UI 化、版本更新通道
- **M4 交付包装**：版本号语义化 + `vidance --version`、CHANGELOG、docs/usage.md 按档重写成用户手册

**依赖**：v15 轻量化是 lite 档地基；v13 agent API 是网关/机器人接入面。

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
│   ├── vidance.py             # 统一 CLI（auto/custom/quick/concat/fast/hot/ask/compose）
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
│   ├── compose.py             # v10 时间线拼接（M1-M8 已实现）
│   ├── svg_pipeline.py        # v15 SVG→mp4（逐帧渲染 + S5 有声流水线，已实现 S1-S5）
│   ├── svg_llm.py             # v15 概念→LLM→动效 SVG
│   ├── t2c_server.py          # t2c 自然语言→命令（translate，进程内/可选 HTTP）
│   ├── h3_prompt_video.py     # 整段式 prompt + 参考图 → H3 ref2va 单镜（原生音频直出）
│   ├── oneshot.py             # v14 一镜到底（🎯 待实现）
│   ├── notify/                # v11 机器人网关（🎯 待实现）
│   ├── luts/  bgm/  workflows/  voices/
├── t2c/                       # t2c 模型（mt5-small 微调）+ 推理脚本 + README
├── ui/                        # v7/v8 前端（index.html 自包含，:8894/ui）
├── docs/                      # roadmap + v0-v15 design + usage*.md + instructions/ + v-t2c.md
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
- t2c（mt5-small 微调，自然语言→命令）见 v-t2c.md；模型与推理脚本随项目 `t2c/`
- Hunyuan3Dv2 见 v3-design.md §13

> 模型文件统一存 `/mnt/dataset/zxy/<Model>-ComfyUI/`，通过 `extra_model_paths.yaml` 映射到 ComfyUI。
