# Vidance 总览与路线图

> 视频生成 agent 系统：opencode 当"制片人"编排本地生图/生视频/生3D/语音引擎，从一句概念产出有声短片。
> 原始规划稿见 `archive/roadmap_origin.md`。**已实现**：v0-v10 + t2c + v11 多智能体（原 v13）+ v12 三排正交 M1-M2（原 v17）+ v13 轻量化无模型四线：营销号/SVG/PPT/Blender 3D（原 v15）+ v15 LLM 生成 PPT（原 v20）；**待开发**：v14 社交媒体（原 v11，🔗 已移交队友）/ v16 视频处理编辑（原 v19）/ v17 开源整合（原 v12）/ v18 长视频质量（原 v14）/ v19 二创（原 v16）/ v20 生成中审核（原 v21）/ v21 交付形态（原 v18）。（2026-09-26 重排：已完成块前移，未完成块后移；2026-09-30 新增 v19-v21；2026-10-01 二次重排：PPT/视频编辑前移至 v14 后、生成中审核插至交付形态前；2026-10-01 晚三调：v13/v15 关版 ✅（v15 条目移入已实现区，待开发条目前移）、v14 移交队友——括号内为原号，v12/v14/v16 指最初编号，v18-v21 指 2026-09-30 编号，方便对照 commit）

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

---

### v1 — 角色一致性 ✅ 已完成（含 v1.1）

**目标**：同一角色跨镜头不漂移。
**状态**：2026-09-08 全链路通过。v1.1：character-mode 开关（auto/3dgs/flux），flux 模式绕过 3DGS 瓶颈（I2V 相关性 0.993-0.998）；3DGS 位姿修复（PCA 对齐 + 接地合成，review_character score 2→7）；Wan22ImageToVideoLatent（48ch + noise_mask）。
**瓶颈**：3DGS 一致性仍受限；flux 侧面/背面可能走样。
**详细设计**：[v1-design.md](./v1-design.md)

---

### v2 — 长视频 + 完整后期 ✅ 已完成（v2.1 backlog 已接线）

**目标**：超出单次生成上限的长片 + 完整后期。
**状态**：2026-09-09 M1-M5 完成。RIFE 过渡 + 并行预取 + LUT 调色 + BGM ducking + STT 字幕全通。v2.1：`--duration N`、`--slowmo N`、per-shot 过渡、`concat` 子命令。
**详细设计**：[v2-design.md](./v2-design.md)

---

### v2.5 — 多入口架构 + H3 引擎接入 ✅ 已完成

**目标**：重构入口与引擎层——统一 CLI 多子命令 + H3 ref2va 新引擎 + 后处理模块化。
**状态**：2026-09-11 通过（13 脚本 / 32 镜 / ~96s 成片，双角色跨镜一致）。
- 统一 CLI `vidance.py`（auto/custom/quick），PostProcessor 抽出共享
- H3 ref2va：`<Picture i>` 引用多角色，1344×768 + 原生音频，中文 prompt 直传
**详细设计**：[v2.5-design.md](./v2.5-design.md)

---

### v3 — 2D→3D→新视角 ✅ 已完成（M0-M7，M8 跳过）

**目标**：从 2D 内容重建 3D，生成原视角没有的新角度视频。
**进度**：M0 headless 渲染 ✅ / M1 Hunyuan3Dv2 mesh 重建 ✅ / M2 multiview ✅ / M3 mesh_render 封装 ✅ / M4 场景锚 ✅ / M5 角色双路径 ✅ / M6 资产库 ✅ / M7 端到端联调 ✅ / M8 跳过。
**详细设计**：[v3-design.md](./v3-design.md)

---

### v4 — 营销号流水线 ✅ 已完成（M1-M6；发布不做，人精选手动上传）

**目标**：批量自动化内容生产。
**进度**：M1 爬虫+选题 ✅ / M2 异步任务队列 ✅ / M3 声音克隆生产化 ✅ / M4 FunClip 智能裁剪 ✅ / M5 素材爬取 ✅ / M6 快速营销号链路（fast/hot）✅。
**详细设计**：[v4-design.md](./v4-design.md)

---

### v5 — 剪辑特效包 ✅ 已完成（M1-M4）

**目标**：丰富单镜头内/镜头间剪辑表现力。
**进度**：M1 特效库（8 种）✅ / M2 xfade 转场（30+ 种）✅ / M3 LLM 自动选 ✅ / M4 端到端 ✅。
**详细设计**：[v5-design.md](./v5-design.md)

---

### v6 — prompt 多轮核实 ✅ 已完成（M1-M4）

**目标**：prompt 信息不全时打回，多轮对话核实需求。
**进度**：M1 完整度评估（6 维）✅ / M2 对话状态机 ✅ / M3 CLI `ask` ✅ / M4 API 三端点 ✅。修复：全 6 维齐才 COMPLETE，每轮批量问完合并 reply。
**详细设计**：[v6-design.md](./v6-design.md)、[usage-v6.md](./usage-v6.md)

---

### v7 — 前端 agent WebUI ✅ 代码完成（浏览器渲染待确认）

**目标**：仿豆包对话式 agent WebUI——左功能边栏 + 顶部画布 + 下/右发框；`/` 斜杠命令调用既有 tool。
**进度**：M1 后端端点（video/options/tools/tool 分发/ui）✅ / M2 对话+`/`补全 ✅ / M3 画布（任务轮询+video 卡片）✅ / M4 ask+scout 接洽 ✅。
**15 命令**：auto/fast/hot/ask/clip/scout/voices/luts/moods/video/tasks/status/trends/clean/help。
**详细设计**：[v7-design.md](./v7-design.md)、[usage-v7.md](./usage-v7.md)

---

### v8 — 前端增强（已初步完成）

**详细设计**：[v8-design.md](./v8-design.md)

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

**详细设计**：[v9-design.md](./v9-design.md)

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

**详细设计**：[v10-design.md](./v10-design.md)

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

### v11 — 多智能体系统（原 v13）（✅ M0-M4 全部完成，2026-09-26）

**详细设计**：[v11-design.md](./v11-design.md)（原 v13-design.md，git mv 留史）

（✅ M0-M4 全部完成，2026-09-26）

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

**v11.1 前端可视化（2026-09-26）**：`/arch` 命令（`tool_dispatch` + `ui renderArch()` 分层彩色卡片，运行时注册表点亮 24 Agent）；chain 任务卡片内嵌 trace 时间线（轮询 `/api/tasks/{id}/trace`，`#步骤 层`徽章+✓/✗+评分+耗时）；`/agent list|run|chain` 命令三端同源。

**v11.2 闭环（2026-09-26）**：pipeline 审片重试接入 `review_ensemble`（config `review.ensemble` 开关，默认关，失败回退单票）；GPU Agent 注册 `h3shot/splat/mesh` + `post.pip` 画中画（28 个，splat 实测出 PLY、pip 实测出片）；`run_agent` 自举 load_all。

**v11.3 归仓（2026-09-26）**：产出目录统一 `default_out()`（`output/agent_{ts}_{name}/`，杜绝 cwd/tmp 散写）；UI 任务 tab 条（累加/持久化/详情浮层含日志与 trace，board 弹层播放器与成片卡片统一）；模型面板连通灯 + 自定义 API 故障互切（`/api/model-providers/health`、`POST /api/model/chat` 候选轮换）。

**后续（v11.x backlog）**：/ui 链 DAG 视图、h3shot 实卡长测、社交通知（原 v11，现 v14）网关对接 agent API、chain 并联分支/断点续跑。

---

### v12 — 三排正交模块化（原 v17）（🔄 M1-M2 已完成 2026-09-26，详见 [v12-modules.md](./v12-modules.md)）

**目标**：导演层（人肉/LLM/热点/对话）× 生成层（H3/Wan/爬图生图/SVG/二创）× 后期层（配音/字幕/拼接/调色配乐/特效/时间线）三层彻底解耦，任意排列组合出一条完整链路，环节实现唯一无冗余。

**里程碑**：
- **M1 ✅**：`core/narration.py`（Narrator：say 含三级降级链 / silence / srt）；fastline `_tts_segment`/`_gen_silence`/`_build_srt`/`srt_time`/`_video_duration` 与 svg_pipeline `_tts_seg`/`_silence`/`_srt_time`/`_probe_duration` 全部改薄壳转发（删 ~80 行重复）；SVG S5 回归通过
- M2 `vidance.py make --director --generator` 统一入口（现有子命令变别名）
- M3 `utils/director.py` 合并三套编剧/旁白 prompt（pipeline/fastline/svg_llm）为统一 schema
- M4 生成器契约统一，v19 二创作为 G5 即插即用

---

### v13 — 轻量化（无 GPU 优先）（原 v15）（✅ 无模型四线全部完成；模型加速按需后续）

**详细设计**：[v-svg-pipeline.md](./v-svg-pipeline.md)、[usage-v-svg.md](./usage-v-svg.md)

**目标**：降低/消除本地 GPU 依赖，纯 API 也能跑。

**范围**：
- 纯 API 模式：所有生成任务可切云端 API（SiliconFlow 等），完全不依赖本地 GPU（对接 v9 模型提供商）（🎯 后续项）
- Pipeline 轻量化：去除 GPU 依赖的处理。**无模型出片四线（✅ 全部已具备）**：
  1. **营销号流水线（已有）**：v4/v5 的生图/爬图 → zoompan 运镜 → TTS → 剪辑，零视频模型，已可用
  2. **LLM 生成 SVG → 渲染成片（✅ S1-S5 已实现 2026-09-24/26）**：LLM 产出带 CSS/SMIL 动画的自包含 SVG → 无头浏览器逐帧渲染 → ffmpeg 拼帧 → mp4。**纯 CPU、秒级、矢量清晰**，适合信息图/文字动画/数据可视化/科普短片。已落 `utils/svg_llm.py`（S1 概念→SVG + S5 plan_narration 旁白规划）+ `utils/svg_pipeline.py`（S2 单帧/S3 抽帧/S4 拼 mp4/**S5 SvgLine 有声流水线**：LLM 旁白→逐段 TTS（edge→cosy→静音降级）→逐段 SVG 渲染→字幕烧录→crossfade 拼接→可选 LUT/BGM），CLI `vidance.py svg --concept "…" [--voice 音色 -n 3 | --say "句1" --say "句2"]`；`/api/tool/svg` 无声同步/有声异步（svg_* job 复用 h3shot 轮询）。实测 `output/svg_e2e/s1.mp4`（音视频双流）。依赖 Playwright+Chromium（已装）
     - 关键设计：**确定性逐帧**（用 Web Animations API 把动画 `currentTime=t` 后 pause 再截图，而非 wall-clock `wait_for_timeout`），保证帧率精确无抖动
     - 渲染后端：Playwright/Chromium（需装）或 `resvg`/`cairosvg`（仅静态帧）；`node` 已就绪可走 puppeteer
     - 可选：LLM 直接给 SVG 代码 + 时长/分辨率 → 一条命令出片；后续可接 v9 模型提供商
  3. **LLM 生成 PPT → 渲染成片（✅ v15 已实现 2026-10-01，详见 §v15）**：LLM 规划 deck 结构化 JSON → Python 模板渲染 HTML 幻灯片 → 逐页渲染 → xfade 拼接 → mp4/PDF/PNG 多形态。纯 CPU，`ppt_llm.py` + `ppt_pipeline.py`
  4. **Blender 3D 渲染（🔄 简单版已实现 2026-10-01）**：LLM 规划 3D 场景 JSON（模板 title3d/shapes/bars3d + 配色 scheme + 物体 text/cube/sphere/torus 等 + 材质 basic/metal/emission/glass + 关键帧 spin/pop + 运镜 dolly/pan/orbit）→ bpy 进程内构建（bpy 5.0.1 wheel，Python 3.11）→ EEVEE 逐帧渲染（宿主 GPU CUDA ~156ms/帧@720p，容器 CPU ~2.5s/帧）→ ffmpeg 拼帧 → TTS 旁白 → mp4。已落 `agents/generator/tools/blender_llm.py`（plan_scene/_norm_scene）+ `blender_pipeline.py`（bpy_build/render_frames/BlenderLine），CLI `vidance.py blender3d "主题" --duration 6 --voice cosy-default`，agent `generator.blender3d`，API `/api/tool/blender3d`（b3d_* job 复用 h3shot 轮询）。实测：宿主 5-6s 片段 38-58s 端到端（blender3d_20261001_191116/191913/192947/193101），容器 5s 片段约 6.5 分钟（blender3d_20261001_114559）。依赖：pip bpy（374MB，容器另需 apt libsm6/libxext6 等 X 库）
- 模型层面轻量化（有模型加速路线，🎯 按需后续，不阻塞 v13 关版）：小模型做预览/草稿、大模型做最终渲染；大模型**量化**（INT8/FP8/GPTQ/AWQ）/**蒸馏**小模型/**其他推理加速**（vLLM、连续批处理、KV cache 优化）按需引入
- 按需加载：各步骤按需初始化，不预加载所有模型
- Docker 轻量化部署：分离 CPU 服务（API/前端/调度）与 GPU 服务（生成）
- 本地 ONNX 小模型：语义嵌入/分类等替代大模型调用

**里程碑**：M1 纯 API 模式 → M2 按需加载+CPU 后处理 → M3 草稿/成片双档 → M4 Docker 分离部署

**参考**：BigBanana Docker Compose、Toonflow ONNX、v9 模型提供商系统。

### v15 — LLM 生成 PPT（轻量化延伸：v13 姊妹篇）（原 v20，🔄 M1-M4 已完成 2026-10-01）

**目标**：v13 已验证"LLM 产出结构化声明式产物（SVG）→ 无头浏览器确定性渲染 → mp4"这条纯 CPU 路线；v15 把它延伸到 **PPT/幻灯片**——LLM 生成 HTML 幻灯片 → 渲染成图/成片，零 GPU、秒级、矢量清晰。

**范围**：
- **LLM 生成 HTML 幻灯片**：概念/大纲 → LLM 产出带 CSS 动画的自包含 HTML 幻灯片（复用 v13 svg_llm 的提示词工程经验：布局/配色/字体/动效约束 + 只输出代码）；16:9 固定分辨率，reveal.js 或纯 CSS（更轻）
- **渲染管线**：复用 v13 svg_pipeline 的 Playwright/Chromium 确定性逐帧（`currentTime=t` + pause 截图）——幻灯片页间转场（fade/slide）+ 页内动效逐帧渲染 → mp4 短片；或导出 PDF/图片（PPT 交付形态）
- **数据可视化**：PPT 常见图表（柱状/折线/饼图/流程图）→ LLM 直接生成 SVG 图表（数据驱动，矢量清晰）——可从热点/数据源（v4 crawler）取数自动生成"数据解读"短片/PPT
- **两条交付形态**：`vidance.py ppt "<大纲>" -o deck.html`（HTML 幻灯片，浏览器直接放映）+ `vidance.py ppt "<大纲>" --video`（渲染成 mp4 有声短片，接 TTS 旁白 = v13 S5 同款）
- **agent 化**：`generator.ppt` 薄包装（needs_gpu=False），链式：`{"agent":"generator.ppt","with":{"concept":"季度总结","n":5,"voice":"edge-moe"}}`
- **模板系统**：常用 PPT 版式（标题页/目录/图文页/数据页/结尾页）LLM 按版式生成，风格统一（配色/字体全局约束）

**里程碑**：M1 LLM→HTML 幻灯片→渲染 mp4（单页）✅ → M2 多页+页间转场+TTS 旁白 ✅ → M3 数据可视化图表 ✅ → M4 PDF/PNG 导出 + agent 化 ✅（2026-10-01 全部完成：`agents/generator/tools/ppt_llm.py`（plan_deck 规划 JSON + 模板渲染 + svg_chart bar/line/pie）+ `ppt_pipeline.py`（PptLine 多形态：deck.html/PDF/PNG/mp4 有声，页间 xfade 转场，TTS 旁白+字幕+LUT/BGM 复用 v10/v12）+ CLI `ppt` 子命令 + `generator.ppt` agent + API `/api/tool/ppt` 异步 job + config task_prefixes `ppt`；端到端验证：LLM 规划 4 页含 bar 图表页 42.9s 成片（117.8s），CLI --say 19s，agent 8.96s，API 宿主 75s，容器 80s 全通过）。

**参考**：v13 svg_pipeline（同一渲染管线）、Marp（Markdown→幻灯片）、Slidev、reveal.js。

---

<!-- ═══ 以下 🎯 待开发 ═══ -->

### v14 — 接入社交媒体（原 v11）（🔗 移交队友，暂不在本仓排期）

**目标**：把成片一键分发到社交平台 / IM，任务完成可推送通知、可在 IM 里用 `/` 命令触发。

**范围**：
- 发布渠道适配：抖音/B站/视频号/小红书（人工审核后发布，或开放平台 API）
- IM 机器人网关：`utils/notify/`（`Notifier` 抽象 + 企业微信 / 飞书 / 钉钉 / Slack / Telegram + factory 多通道并发推送）
- 任务完成 post-hook 接入 v4 scheduler
- 回调网关 `POST /api/notify/{channel}/callback`（解密→文本→复用 v9 `/api/tool/{name}`）
- 富媒体卡片：IM 中展示视频预览卡片、进度条、候选方案选择
- config.json 加 `notify` 节；个人微信不做

**里程碑**：M1 Notifier 抽象+企微 → M2 飞书/钉钉+factory → M3 任务完成自动通知 → M4 回调网关 + 至少一个发布渠道

> **🔗 移交说明**：v14（社交媒体/IM 网关）已移交队友负责，本仓暂停排期；`utils/notify/` 目录骨架已预留（base/factory 接口），队友接手时按上述里程碑推进即可。本仓后续聚焦 v16 视频处理与编辑。

**参考**：`lark-oapi`（飞书官方 SDK）、wechaty；BigBanana 多候选决策点；原 v9-design.md。

---

### v16 — 视频处理与编辑（SAM 分割 / YOLO 自动 / 视频追踪 / 局部替换 / 生成式编辑）（原 v19，✅ 已完成 2026-10-02：M0-M4 + 增强全绿 + v16.x M5-M8 生成式编辑，2026-09-30 立项）

**目标**：给流水线补上**帧级视频编辑能力**——分割、追踪、换脸、局部替换，既服务二创（v19 的画面改写），也让 custom/auto 的成片可后期精修。

**范围**：
- **SAM 分割**：Segment Anything（或 SAM2，带视频传播）对帧/片段做目标分割——抠主体/换背景/局部打码；`utils/sam_edit.py`（image/clip → mask → 抠图/换底/模糊），`--segment 主体` 一键
- **光流追踪**：复用 v2 RIFE 光流模型做**目标轨迹追踪**（CoTracker/RIFE flow 聚焦）——镜头稳定/运动模糊修复/追踪局部打码；RIFE(8189) 已在线，增量改造（🎯 视频扩展阶段并入 M3，追踪打码优先）
- **AI 换脸**：本地开源方案（FaceFusion/inswapper，参考图→目标视频换脸）——与 v1 角色锚结合（角色参考图→成片换脸），**明确仅用于已授权素材/虚构角色**；`utils/face_swap.py`（GPU，接 v21 档位 none 档禁用）
- **局部替换（inpaint）**：帧内区域重绘（SDXL inpaint 8191 / FLUX fill）——去水印/替换物件/改背景；mask 来自 SAM 分割（SAM 分割 → inpaint 补全，两能力串联）
- **ControlNet 参考（🎯 2026-10-02 调研：节点已支持、权重未下载）**：FLUX 8192 原生支持全部编辑类节点（ControlNetApply/DiffControlNetLoader/InpaintModelConditioning/SetUnionControlNetType/ControlNetInpaintingAliMamaApply 实测在列），但 `ComfyUI/models/controlnet/` 为空——需下权重；具体候选见下方 v16.x backlog
- **agent 化**：`audit.edit` 或 `post.edit` 薄包装 Agent（mask/sam/inpaint/face 四工具），链式调用：`{"agent":"post.edit","with":{"video":"${v.video}","op":"segment+inpaint","target":"背景"}}`
- **档位接入**：新增能力进 v21 档位阶梯（`full` 档启用，编辑类全 GPU 依赖，none/flux 档降级提示）

**里程碑**（2026-10-01 规划，仿 blender 线 M0 起步；2026-10-02 M0-M4 + 增强全部完成 ✅）：M0 SAM2 环境 spike ✅（SAM-2 1.0 源码装 /mnt/disk_sdb/zxy/sam2-src + 权重 models/sam2/ tiny+small + 单图验证：build 1.1s/预测 0.2s/显存 201MB）→ M1 SAM 分割 ✅（`agents/post/tools/sam_edit.py`：segment/cutout/replace_bg/mosaic/inpaint/visualize 六模式（visualize=彩色多物体叠加，SAM demo 风格 8 色调色板+边界描边+IoU 去重）+ 自动主体 3x3 网格打点并集（coverage 66.8% vs 单点 29%）+ _pick_device 逐卡探测）→ M2 局部替换 ✅（cv2.inpaint TELEA + mask 膨胀盖边缘；FLUX 服务器无 Fill 模型，latent inpaint 留可选）→ M3 视频扩展 ✅（SAM2 视频传播 build_sam2_video_predictor + 点提示逐帧 mask + mosaic/blur_bg/cutout/color（彩色多物体，每点独立 obj_id）重拼 mp4，144 帧 @48it/s 传播 ~3s）→ M4 agent 化 ✅（CLI `vidance.py edit` 子命令 + `post.edit` agent + `/api/tool/edit`（图同步/视频异步 edit_* job 复用 h3shot 轮询）+ utils 薄壳 + config task_prefixes edit）。**增强（2026-10-02 下午-傍晚，全通道验证）**✅：①彩色多物体 segment_multi/visualize（8 色调色板+IoU 0.85 去重+score<0.5 噪声丢弃）+ video_color（每点独立 obj_id）；②prompt_frame 参数（SAM2 任意帧提示，CLI --frame）；③**双向传播修复**（propagate_in_video 默认只向前，补 reverse=True 反向 pass，提示帧前帧着色 0%→30.9%）；④**YOLO 自动检测→SAM 框提示**（Grounded-SAM 流程，--yolo/--classes/--conf：猫覆盖 39.7%（点）→49.3%（框），scores 0.94-0.99， visualize 标签绘制类别名）+ video --yolo（检测帧提示→双向传播）；⑤box 提示（--box，每框一物体，大物体显著改善：盆栽 17.5%→46% 覆盖）+ segment_from_boxes；⑥全通道 CLI/agent/API 同步（agent --with yolo/classes/box/frame；API fl 透传 + 检出框注入 job）。实测：猫狗图 --yolo 7 物体全检（v8s，n 版检不出）；猫狗打斗视频 Wan 121 帧 → SAM2 双向追踪（帧 30 提示猫+狗，全片着色 29-37% 帧间稳定）；API 视频 yolo job 121/121 帧通过（像素统计验证）。**换脸**（合规边界内，FaceFusion/inswapper）+ FLUX Fill/ControlNet/VACE/Kontext 见 v16.x backlog 按需启动。**容器档位**：编辑类全 GPU 依赖（torch），容器（none 档）仅同步代码不装 sam2——编辑能力留宿主 GPU 档；环境固化 deploy/requirements-lock.txt + setup_env.sh + download_weights.sh（2026-10-02）

**v16.x 生成式编辑增强**（2026-10-02 晚，M5-M8 全部完成 ✅）：
- **M5 FLUX.1 Fill 生成式重绘 ✅**：flux1-fill-dev-fp8（11.9G，dim 镜像仓）→ UNETLoader 直连；`flux_fill.json`（InpaintModelConditioning noise_mask）+ `ComfyClient.generate_flux_fill` + `sam_edit.inpaint_flux`（invert=换底）+ CLI `--engine flux`。测试：去猫（整框 mask seed42）YOLO cat 0.92→无检出、框外 0.42% 保留；换底 beach 背景 100% 重绘
- **M6 Union ControlNet 联动 ✅**：Shakker-Labs union pro fp8（3.3G，Kijai）→ ControlNetApplyAdvanced（普通 Apply 报 needs a VAE）；canny 边缘（cv2.Canny 100,200）+ strength 0.55；mask 外误伤 5.19%→0.49%（10 倍提升）；改物种（猫→金毛）保持结构
- **M7 Wan2.1 VACE 参考图生视频 ✅**：wan2.1_vace_1.3B_fp16（4.3G，Comfy-Org 官方 repackaged）+ wan_2.1_vae（254MB）→ `wan_vace.json`（WanVaceToVideo reference_image）+ `generate_vace_video` + CLI `vidance.py vace` + API /api/tool/vace（异步）。测试：狗参考图→81 帧@16fps，YOLO dog 0.92-0.95 全程在场
- **M8 Qwen-Image-Edit 2509 指令式编辑 ✅**：qwen_image_edit_2509_fp8（20.4G）+ qwen_2.5_vl_7b_fp8_scaled（9.4G）+ qwen_image_vae（254MB）→ `qwen_edit.json`（TextEncodeQwenImageEditPlus）+ `generate_qwen_edit` + `sam_edit.qwen_edit` + CLI `edit instruct` + API edit 分发。测试：中文指令"把猫换成金毛犬"全实例生效（右侧 cat 0.64→dog 0.94）；"改成夜晚"全局均值 148,116,86→55,52,69 暗蓝
- **VACE control_video/control_masks inpaint 变体 ✅**（2026-10-11，v16.x 收尾）：`sam_edit.video_masks`（SAM2 逐帧 mask：ffmpeg 抽帧→propagate→frame/mask %06d，4n+1 对齐 ≤81 超量均匀采样）+ `sam_edit.video_inpaint_vace`（op remove 原样/keep 反转）+ `comfy_api.generate_vace_inpaint`（**程序化构建 workflow 无需模板**：LoadImage×N+ImageBatch 链+ImageToMask+WanVaceToVideo(control_video/control_masks)+KSampler uni_pc+SaveVideo，upload_image 加 subfolder 参数）+ CLI `edit video --engine vace --mask-op remove|keep --prompt` + API 异步 `_run_vaceeditjob`（on_stage 阶段上报 SAM2→VACE）+ post.edit agent vace 分支。**mask 语义（2026-10-11 勘误，像素级实测确认）**：mask 白(1)=重绘该区、黑(0)=保留——remove 用 SAM mask 原样、keep 才反转（初版极性搞反：狗被保留背景被糊，且 YOLO 复检被背景重绘干扰误报狗消失，验证必须加像素级分区差异）。测试：cat_dog_fight.mp4（832x480 24fps 121 帧）--yolo 移除狗 → 81 帧@16fps 成片，修正后狗区差异 36-54/背景仅 12-22，YOLO 复检 4/5 帧 dog 消失（残影帧 conf 0.26，原图 0.85/0.66/0.95）；CLI+API 双通道通过。教训：queue_prompt 收 dict 非 json.dumps 字符串（HTTP 500 'str' object has no attribute 'items'）
- **VACE 14B + ProPainter + 三引擎分工 ✅**（2026-10-12，视频编辑收官）：
  - **VACE 14B**：wan2.1_vace_14B_fp16（27G，Comfy-Org repackaged，ModelScope 国内源）→ `--vace-model 14b`（vidance.py CLI + API `_run_vaceeditjob` + post.edit agent 全透传）。实测：GPU2 加载 ~40-45GB 无 OOM，81 帧 ~20-25 分钟/次；pelican_bike 移除鹈鹕换"a fluffy orange cat riding a bicycle"→ 鸟 3/3 帧消失、自行车 0.9 保留、鸟区变橙猫（用户验收通过）
  - **ProPainter**：仓库 + 三权重（ProPainter.pth 157MB @hf-mirror camenduru 镜像 / raft-things / recurrent_flow_completion）→ `sam_edit.video_inpaint_propainter`（SAM2 mask → 子进程 inference_propainter.py，fp16 + mask_dilation 8）+ `edit video --engine propainter`（vidance.py + API `_run_propaintereditjob` 异步 + post.edit agent）。非生成式光流传播（RAFT 双向+补全+transformer），**不会长新物体**；双视频验证（easy_dog_grass 移除狗 / pelican_bike 移除鸟）YOLO 全帧 0 检出
  - **时序中位背景板**（plate）：VACE 控制帧预填充（物体未遮挡像素取时序中位≈真实背景，cov>0.05 门限，TELEA 回退）——替代 TELEA 糊斑被 VACE 顺势画成新物体
  - **选型**：plate=固定机位免费零幻觉 / propainter=相机运动纯移除 / vace 14B=换新物体（prompt 必须具体："empty grass" 长白鸭，"a fluffy orange cat riding a bicycle" 成功；negative 写 duck 反而可能召唤）
  - **prompt 帧/框教训**：猫狗同框帧 YOLO 置信度顺序框错目标（cat 0.92>dog 0.90 但框提示只出 13.6% 半身+碎片）→ 提示帧选目标单独可见帧 + `--classes` 锁定（帧 0 后 mask 31.9% 全宽单域）
- **换脸**（合规边界内，FaceFusion/inswapper）——**能力已被 v1 角色锚覆盖**（角色参考图→成片），不再开发
- **教训**：①SAM mask 对大物体只盖部分（首测 18 去猫失败：mask coverage 3.8% vs 猫框 8.3%）→ 移除类用整框矩形 mask + **YOLO 复检目标物消失**；②Fill 内容感知残留（旁边有真狗时木纹阴影被 YOLO 误认 0.39-0.86，模型行为）；③SetUnionControlNetType type 合法值为组合串；④SAM set_image 需 uint8
- 详细验证数据：docs/v16-design.md §4；汇报 docs/reports-20261001.md §4-6

**参考**：SAM2（Meta，视频分割）、CoTracker（Meta，点追踪）、FaceFusion、ProPainter（视频修补）、ControlNet（构图/姿态条件控制）、FLUX.1 Fill/Canny/Depth/Kontext（Black Forest Labs，inpaint/ControlNet/指令编辑）、Wan2.2 VACE（视频编辑一体）、Qwen-Image-Edit（指令编辑）、RVM（视频抠像）。

---

### v17 — 整合已有开源仓库（原 v12）（🎯 待开发）

**目标**：吸收成熟开源项目的工程能力，不重复造轮子；并补上系统一直缺的"会话资产层"——上传素材/中间产物有统一缓冲区管理（生命周期跟会话走），前端支持类 ChatGPT 附件交互，指令用 @引用 替代自然语言指代。

**范围**：

*会话资产层（2026-10-12 新增，M1-M3 优先）*：
- **buffer 会话缓冲区**：`output/buffer/{session_id}/` 管理会话相关资产（用户上传图/视频/音频 + 任务中间产物）——上传即入 buffer、agent 产物可归档进 buffer、会话删除联动删目录、TTL 定期清理兜底
- **前端附件**：类 ChatGPT 交互——拖拽/粘贴/附件按钮上传，消息带附件 chip，发送时 attachments 随命令提交；任务产出的视频/图片卡一键"存入 buffer"复用
- **@ 引用语法**：命令/自然语言中 `@1 @2` 按附件顺序引用（后端发送前替换为 buffer 绝对路径），替代"参考下面第一张图"式指代；LLM 意图层把"用第一张图"规整为 @1（t2c SFT 语料同步采用该格式）

*原有范围*：
- 断点续跑机制：每步输出持久化，中断后可恢复（ViMax checkpoint/resume）
- JSON 容错解析：LLM 输出不稳定时容错（TrailingCommaTolerantParser）
- 结构化视频提示词模板：`[Visual]/[Motion]/[Camera]/[Audio]/[Narrative]` 五维
- RAG 管线：FAISS + BGE Reranker，长文本输入处理（索引源=buffer 内文档资产）
- 结构化剧本拆解：非结构化文本→角色/场景/道具
- 本地语义嵌入 ONNX（all-MiniLM-L6-v2）：资产匹配/场景关联（buffer 资产检索复用）
- 重试标准化：tenacity 统一 API 重试
- 候选整合对象：MoneyPrinterTurbo（架构参考）、ViMax、Toonflow、BigBanana、OpenCut、Open WebUI（会话附件交互）、Dify（message.files 上传协议）、Gradio（临时文件 TTL 清理）

**里程碑**：M1 buffer 目录+上传 API+会话联动删除+TTL 清理 → M2 前端附件（拖拽/粘贴/chip/产物归档）→ M3 @ 引用（后端替换+LLM 意图规整+t2c 语料）→ M4 断点续跑+JSON 容错 → M5 五维提示词模板+RAG → M6 剧本拆解 → M7 嵌入+重试标准化

**参考**：ViMax、Toonflow、BigBanana、MoneyPrinterTurbo（本机 `/mnt/disk_sdb/zxy/MoneyPrinterTurbo/`）；会话资产层专项见 [v17-design.md](./v17-design.md)。

**依赖**：多智能体（v11，原 v13）黑板/chain 是断点续跑的挂载点；会话资产层（M1-M3）是 RAG（M5 文档索引）与 t2c 重训（@ 语料）的前置。

---

### v18 — 长视频质量（原 v14）（🎯 待开发）

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

### v19 — 营销号 Plus：视频链接二创（原 v16）（🎯 待开发，backlog）

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

### v20 — 生成中审核（tensor 导出 + 多模态边生边审）（原 v21，🎯 待开发，2026-09-30 立项）

**目标**：体现**本地部署的优越性**——生成视频时中间有 token/latent 在流动，把中间态**直接导出成可审图像**丢给多模态 LLM 实时审核，**边生成边审**（不等全片渲完再逐帧审），流水线级省时（审片是当前最大耗时瓶颈之一，30-200s/镜）。

**范围**：
- **原理**：Wan T2V/I2V 是 diffusion 迭代去噪——ComfyUI 节点间流动的 latent tensor 可以**中途解码出预览帧**（VAE decode 部分去噪的 latent → 模糊但可判构图/主体的图）。本地部署 = 能拿到中间 tensor；云端 API = 只能等最终结果
- **latent 中途导出**：ComfyUI 自定义节点（`PreviewLatent`/SaveImage 中间态）或 workflow 改造——每 N 步去噪导出一帧预览（步骤数/质量权衡：太多打断 GPU，太少审核滞后）；`utils/latent_probe.py`（workflow JSON 模板 + 中间帧导出）
- **边生边审流水线**：中间帧 → 多模态 LLM（qwen3.8-chat）**与生成并行**审核——构图/主体/角色一致性早判，不合格**提前止损**（terminate 当前 workflow，省下剩余去噪时间）而非渲完再审重做
- **早停重生成**：审核不过 → 提前终止 + 调整 prompt/seed 重生成（相比渲完再审省 50-80% 单镜时间，N 步内发现问题就能止损）
- **渐进式审片**：低步数粗审（快，构图/主体）→ 高步数细审（慢，细节/伪影）分级，最后成片仍走现有逐帧审片（v0 口径）
- **v11 集成**：审核事件进 chain SSE（`event: preview`），前端画布实时显示"生成中预览帧 + 审核意见"——用户可看到 AI 正在边画边自检

**里程碑**：M0 spike（ComfyUI 中间 latent 解码导出验证：改 workflow 8189 实测能否拿到可判图）→ M1 latent_probe 工具化 + 审核接通 → M2 早停止损（不合格提前终止重生成）→ M3 分级粗/细审 + 前端实时预览集成。

**依赖**：Wan/ComfyUI 本地实例（8189）+ 多模态 LLM + v11 chain SSE/前端。

**参考**：ComfyUI PreviewLatent/TAESD（快速 latent 解码小模型）、LCM（低步数快速出图思路）。

---

### v21 — 面向最终用户的交付形态（原 v18，🎯 规划，2026-09-26 立项）

**目标**：从"开发者本地系统"变成"用户可安装可运行的产品"——先探测本机资源，再按资源分发对应部署档，屏蔽底层细节。

**里程碑草案**：
- **M0 资源探测**：`core/doctor.py`（GPU 型号/显存/端口占用/conda 环境/磁盘/外网可达性）→ 输出 profile JSON，`vidance doctor` + `/api/doctor`；首次启动自动跑并推荐档
- **M1 部署分档** ✅（2026-09-26 改五档落地，见 [deploy-tiers.md](./deploy-tiers.md)、deploy/README.md）：五档阶梯 `none`（无 GPU：svg + fast 爬图，LLM/edge-tts 全走远程接口）/ `flux`（+SDXL/FLUX 生图）/ `wan`（+Wan T2V/I2V+RIFE+auto/quick）/ `h3`（+MiniMax-H3 ref2va+custom/h3shot）/ `full`（全量全家桶）——同一份代码 + `VIDANCE_TIER` 环境变量 + `config/tiers/{档}.json` 覆盖（`agents/common/tools/config_loader.py` 深合并，缺省 full 宿主机零变化）；守卫点 `/api/health` 报档 / `/api/tools` 按档过滤 / tool 分发 400 / CLI require() 退出提示换档；Docker：`deploy/Dockerfile`（API 层 ~2GB：ffmpeg+Noto CJK+playwright/Chromium）+ `deploy/Dockerfile.comfyui`（GPU 模板，模型卷挂不进镜像）+ `deploy/docker-compose.yml`（profiles 五档，API 缺省挂 9400，host 网络直连宿主服务）——本机 full 档演示：`VIDANCE_TIER=full VIDANCE_PORT=9401 docker compose -f deploy/docker-compose.yml up -d vidance`
- **M2 一键安装**：`install.sh` 按 M0 探测选档 → 拉镜像/建环境 → start_services 接管 → 冒烟自检（复用 start_services.sh test）
- **M3 面向用户细节**：config 向导（首次填 LLM key/选端口）、失败自诊断提示（端口占用/显存不足/外网不通点名到人）、输出目录与清理策略 UI 化、版本更新通道
- **M4 交付包装**：版本号语义化 + `vidance --version`、CHANGELOG、docs/usage.md 按档重写成用户手册

**依赖**：v13 轻量化（原 v15）是 lite 档地基；v11 多智能体（原 v13）agent API 是网关/机器人接入面。

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
│   ├── vidance.py             # 统一 CLI（auto/custom/quick/concat/fast/hot/ask/compose/svg/make/agent）
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
│   ├── svg_pipeline.py        # v13（原 v15）SVG→mp4（逐帧渲染 + S5 有声流水线，已实现 S1-S5）
│   ├── svg_llm.py             # v13（原 v15）概念→LLM→动效 SVG
│   ├── t2c_server.py          # t2c 自然语言→命令（translate，进程内/可选 HTTP）
│   ├── h3_prompt_video.py     # 整段式 prompt + 参考图 → H3 ref2va 单镜（原生音频直出）
│   ├── oneshot.py             # v18（原 v14）一镜到底（🎯 待实现）
│   ├── notify/                # v14（原 v11）机器人网关（🎯 待实现）
│   ├── luts/  bgm/  workflows/  voices/
├── agents/                    # v11 多智能体（原 v13）：D/G/P/V 物理分层 + 薄包装（docs/v11-design.md）
├── t2c/                       # t2c 模型（mt5-small 微调）+ 推理脚本 + README
├── ui/                        # v7/v8 前端（index.html 自包含，:8894/ui）
├── docs/                      # roadmap + v0-v18 design + usage*.md + instructions/ + v-t2c.md
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
| ViMax / Toonflow / BigBanana | v11 多智能体 / v18 长视频（原 v14）/ v17 开源整合（原 v12）参考 |
| SAM2 / CoTracker / FaceFusion / ProPainter | v16 视频处理编辑（原 v19；分割/追踪/换脸/修补）参考 |
| Marp / Slidev / reveal.js | v15 LLM 生成 PPT（原 v20；Markdown/代码→幻灯片）参考 |
| ComfyUI PreviewLatent / TAESD / LCM | v20 生成中审核（原 v21；latent 中途解码/快速解码）参考 |

---

## 10. 部署记录

各模型部署细节见 `/mnt/disk_sdb/zxy/` 下：
- `MiniMax-H3-部署记录.md`、`Wan2.2-部署记录.md`、`HunyuanVideo-部署记录.md`、`SDXL-部署记录.md`、`FLUX-部署记录.md`
- t2c（mt5-small 微调，自然语言→命令）见 v-t2c.md；模型与推理脚本随项目 `t2c/`
- Hunyuan3Dv2 见 v3-design.md §13

> 模型文件统一存 `/mnt/dataset/zxy/<Model>-ComfyUI/`，通过 `extra_model_paths.yaml` 映射到 ComfyUI。
