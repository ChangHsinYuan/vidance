# Vidance Roadmap — 优化方向规划

> 基于 ViMax、BigBanana AI Director、Toonflow 三个项目的调研，结合 Vidance 现状梳理。
> 标注 `[无GPU]` 的项可在当前工作站（无显卡）上先行开发。

---

## 方向 1：拼接与特效（OpenCut + 自然语言调用特效）

**现状**：已有 RIFE 转场、LUT 调色、BGM 配乐，但特效能力有限，拼接靠 pipeline 硬编码。

### 规划

| 优先级 | 任务 | 来源/参考 | 无GPU |
|--------|------|-----------|-------|
| P0 | 集成 OpenCut（开源剪辑引擎）作为拼接后端，替代当前硬编码拼接 | 方向1 原始需求 | ✅ |
| P0 | 特效模板系统：预定义转场/滤镜/特效 JSON 模板，pipeline 按分镜调用 | Toonflow 的技能系统思路 | ✅ |
| P1 | 自然语言→特效映射：LLM 解析用户描述（如"加一个梦幻模糊转场"）→匹配特效模板 | BigBanana 的 CutOS 粗剪 | ✅ |
| P2 | 时间线编辑器前端：可视化拖拽调整镜头顺序、裁剪、转场 | BigBanana CutOS 风格 | ✅ |
| P2 | 音频对齐：TTS 字幕自动对齐 + BGM 节奏匹配 | 现有 STT 能力扩展 | ✅ |

**关键借鉴**：
- Toonflow 将提示词工程模块化为"技能文件"，特效也可以类似地做成可插拔的模板文件
- BigBanana 的 CutOS 内置粗剪时间线，支持调序/裁剪/滤镜后导出

---

## 方向 2：微信/飞书机器人接口

**现状**：仅有 Web UI 和 REST API，无 IM 集成。

### 规划

| 优先级 | 任务 | 来源/参考 | 无GPU |
|--------|------|-----------|-------|
| P0 | 统一 Bot 网关层：抽象消息收发接口，支持多平台适配 | 架构设计 | ✅ |
| P0 | 飞书机器人接入（飞书开放平台 Bot API，开源 SDK 丰富） | 开源: `lark-oapi` (官方) | ✅ |
| P1 | 微信机器人接入（基于 `wechaty` 或 `itchat` 开源方案） | wechaty / gewechat | ✅ |
| P1 | 消息协议适配：将 Vidance 的对话/任务系统映射为 IM 消息格式 | 现有 dialog 系统 | ✅ |
| P2 | 富媒体卡片消息：在 IM 中展示视频预览卡片、进度条、候选方案选择 | 飞书消息卡片 | ✅ |
| P2 | 审批流：生成完成后推送 IM 消息，用户直接在 IM 中确认/修改/重新生成 | BigBanana 的多候选决策点 | ✅ |

**关键借鉴**：
- BigBanana 在关键节点提供"多候选方案 + 人工选择"模式，IM 机器人天然适合这种交互
- 飞书消息卡片支持按钮/下拉框，可直接做候选方案选择

---

## 方向 3：前端增强（ComfyUI 节点画布 + 时间线编辑）

**现状**：单页聊天 UI，已有模型设置面板，已加 ComfyUI 代理（待部署验证）。

### 规划

| 优先级 | 任务 | 来源/参考 | 无GPU |
|--------|------|-----------|-------|
| P0 | ComfyUI 节点画布集成：`/ui_comfyui` 反向代理，本地启动 ComfyUI 前端连接远程后端 | 已完成代理代码 | ✅ |
| P1 | 资产库面板：角色/场景/道具资产可视化管理，拖拽引用 | BigBanana 的资产系统 | ✅ |
| P1 | 分镜预览面板：九宫格候选视角 + 关键帧编辑 | BigBanana 九宫格分镜 | ✅ |
| P2 | 时间线编辑器（libTV 或自研）：镜头排列、转场、音频轨道 | BigBanana CutOS / libTV | ✅ |
| P2 | 任务进度可视化：pipeline 各步骤实时状态展示（类似 Toonflow 的三层进度） | Toonflow 执行层可视化 | ✅ |

**关键借鉴**：
- BigBanana 的网格化导演工作台：全景管理所有镜头，逐镜头查看上下文
- Toonflow 的分镜表（storyboard table）：结构化的镜头列表视图

---

## 方向 4：API 接口（模型接入/切换/生图/生视频）

**现状**：已完成动态模型提供商系统（添加/删除/切换），已测试 SiliconFlow API。

### 规划

| 优先级 | 任务 | 来源/参考 | 无GPU |
|--------|------|-----------|-------|
| P0 | SiliconFlow 正式接入：添加为提供商，配置 Kolors(T2I) + Wan2.2(I2V/T2V) | 已测试通过 | ✅ |
| P0 | API 端点标准化：对外暴露 RESTful API，支持第三方调用 Vidance 能力 | Toonflow vendor 适配层 | ✅ |
| P1 | 生图/生视频独立切换：前端分别选择 T2I 模型和 I2V/T2V 模型 | 现有 model_router 扩展 | ✅ |
| P1 | 多 Vendor 适配层：统一接口协议（text/image/video/tts），新增提供商只需写适配器 | Toonflow `data/vendor/` | ✅ |
| P2 | 模型能力自动发现：查询 `/v1/models` 后自动标注哪些模型支持 t2i/i2v/t2v | 已有 discover 基础 | ✅ |
| P2 | 用量统计与限流：记录各 API 调用次数/花费，设置并发上限 | ViMax Semaphore 控制 | ✅ |

**关键借鉴**：
- Toonflow 的 vendor 适配层：每个供应商统一暴露 text/image/video/tts 四类接口
- ViMax 的 `tools/protocols.py`：Protocol 抽象，切换后端只改配置
- ViMax 的 Semaphore 并发控制：对不同 API 设置合理并发上限避免限流

---

## 方向 5：开源整合与功能优化

**现状**：核心 pipeline 自研，ComfyUI 作为本地后端。

### 规划

| 优先级 | 任务 | 来源/参考 | 无GPU |
|--------|------|-----------|-------|
| P0 | 整合 ViMax 的断点续跑机制：每步输出持久化，中断后可从断点恢复 | ViMax checkpoint/resume | ✅ |
| P0 | 整合 ViMax 的 JSON 容错解析：LLM 输出不稳定时的容错处理 | ViMax TrailingCommaTolerantParser | ✅ |
| P1 | 整合 Toonflow 的结构化视频提示词模板：[Visual]/[Motion]/[Camera]/[Audio]/[Narrative] 五维 | Toonflow 视频提示词 | ✅ |
| P1 | 整合 ViMax 的 RAG 管线：FAISS + BGE Reranker，用于长文本输入处理 | ViMax Novel2Movie | ✅ |
| P1 | 整合 BigBanana 的结构化剧本拆解：从非结构化文本自动提取角色/场景/道具 | BigBanana Phase 01 | ✅ |
| P2 | 整合本地语义嵌入模型（all-MiniLM-L6-v2 ONNX）：用于资产匹配/场景关联 | Toonflow 本地嵌入 | ✅ |
| P2 | 重试机制标准化：tenacity 库统一处理 API 调用重试 | ViMax tenacity | ✅ |

---

## 方向 6：多智能体系统

**现状**：单 pipeline 串行执行，无独立 Agent 角色分工。

### 规划

| 优先级 | 任务 | 来源/参考 | 无GPU |
|--------|------|-----------|-------|
| P0 | Agent 角色定义与分工架构设计 | 三个项目共同方向 | ✅ |
| P0 | **编剧 Agent**：故事生成 / 剧本拆解 / 分镜规划（LLM API） | ViMax Screenwriter + Toonflow 决策层 | ✅ |
| P0 | **审核 Agent**：多模态 LLM 审核生成结果（画面质量/一致性/内容安全） | 方向6 原始需求 | ✅ |
| P1 | **美术 Agent**：角色定妆照 / 场景概念图 / 道具设计（生图模型） | BigBanana 资产系统 + Toonflow L0-L6 | 需GPU/API |
| P1 | **演员 Agent**：关键帧生成 + 视频生成（生视频模型） | ViMax StoryboardArtist | 需GPU/API |
| P1 | **剪辑 Agent**：自动拼接 + 转场 + 节奏控制（OpenCut） | 方向1 + 方向6 | ✅ |
| P1 | **配音配乐 Agent**：TTS + BGM 选择 + 音效 | 现有 CosyVoice 扩展 | ✅ |
| P2 | 三层架构落地：决策层（编排）→ 执行层（生成）→ 监督层（审核） | Toonflow 三层 Agent | ✅ |
| P2 | Agent 间通信协议 + 状态管理 | ViMax agent_runtime | ✅ |

**关键借鉴**：

**ViMax 的 14 Agent 分工**：
- Screenwriter（编剧）、StoryboardArtist（分镜师）、CharacterExtractor（角色提取）、SceneExtractor（场景提取）、BestImageSelector（最佳画面选择）等
- 每个 Agent 单一职责，通过 pipeline 编排

**Toonflow 的三层解耦**：
- 决策层：不执行，只派发 → 对应 Vidance 的 scheduler 升级
- 执行层：实际调用 API 生成 → 对应 Vidance 的各工具 Agent
- 监督层：只提问题，不修改 → 对应 Vidance 的审核 Agent

**BigBanana 的资产驱动**：
- "先建资产再生成"比"每次从 prompt 生成"更可控
- 角色定妆照 → 衣橱系统 → 上下文感知生成

---

## 方向 7：长视频质量

**现状**：短视频（几十秒）生成为主，无长视频处理能力。

### 规划

| 优先级 | 任务 | 来源/参考 | 无GPU |
|--------|------|-----------|-------|
| P0 | 关键帧驱动生成：先生成首帧/尾帧，再插值生成中间视频 | BigBanana + ViMax StoryboardArtist | 需GPU/API |
| P0 | 分镜间一致性：上下文感知注入（当前场景/角色/服装参考） | BigBanana 三重保障 + Toonflow 上下文注入 | ✅ |
| P1 | 一镜到底控制：单镜头内的 prompt 时序分段描述 | ViMax [Motion] 时间轴分段 | ✅ |
| P1 | clip 间过渡管理：镜头间的情绪/色调/节奏连贯性 | Toonflow 导演规划（情绪分析+过渡设计） | ✅ |
| P1 | 层级角色一致性：Scene 级 → Event 级 → 全局角色注册表 | ViMax 三级角色管理 | ✅ |
| P2 | 长文本处理管线：小说压缩 → 事件提取 → RAG 检索 → 场景分解 | ViMax Novel2Movie 7 步管线 | ✅ |
| P2 | 世界观持久化：地图/区域/风格等全局上下文持续注入 | BigBanana 世界观构建 | ✅ |
| P2 | 衍生资产系统：自动识别角色变身/场景时间变体，生成衍生资产 | Toonflow derive_assets | 需GPU/API |

**关键借鉴**：
- ViMax 的 Novel2Movie 管线是目前开源界最完整的长视频处理方案
- BigBanana 的关键帧驱动 + 首尾帧插值，比纯 T2V 可控得多
- Toonflow 的导演规划五步流程：读取剧本→拆分场次→统计台词→分析情绪→设计过渡

---

## 方向 8：轻量化（无 GPU 优先）

**现状**：依赖本地 ComfyUI + GPU，无 GPU 时功能受限。

### 规划

| 优先级 | 任务 | 来源/参考 | 无GPU |
|--------|------|-----------|-------|
| P0 | **纯 API 模式**：所有生成任务可切换为云端 API（SiliconFlow 等），完全不依赖本地 GPU | 已完成模型提供商系统 | ✅ |
| P0 | Pipeline 轻量化：去除 GPU 依赖的预处理/后处理步骤，或替换为 CPU 版本 | 架构优化 | ✅ |
| P1 | 模型层面轻量化：用小模型做预览/草稿，大模型做最终渲染 | 方向8 原始需求 | ✅ |
| P1 | 按需加载：pipeline 各步骤按需初始化，不预加载所有模型 | 架构优化 | ✅ |
| P2 | Docker 轻量化部署：分离 CPU 服务（API/前端/调度）和 GPU 服务（生成） | BigBanana Docker Compose | ✅ |
| P2 | 本地 ONNX 小模型：语义嵌入/分类等用 ONNX 替代大模型调用 | Toonflow all-MiniLM-L6-v2 | ✅ |

---

## 实施节奏建议

### Phase 1（1-2 周）— 基础设施，全部无 GPU

- [x] 动态模型提供商系统（已完成）
- [x] SiliconFlow API 测试（已完成）
- [ ] SiliconFlow 正式接入（T2I: Kolors, I2V/T2V: Wan2.2）
- [ ] 多 Vendor 适配层（统一 text/image/video/tts 接口协议）
- [ ] 断点续跑机制（每步输出持久化）
- [ ] JSON 容错解析（LLM 输出容错）

### Phase 2（2-3 周）— 多智能体骨架，全部无 GPU

- [ ] Agent 角色定义（编剧/美术/演员/剪辑/配音/审核）
- [ ] 编剧 Agent：结构化剧本拆解 + 分镜规划
- [ ] 审核 Agent：多模态 LLM 审核
- [ ] 结构化视频提示词模板（五维：Visual/Motion/Camera/Audio/Narrative）
- [ ] 飞书机器人接入

### Phase 3（3-4 周）— 资产系统 + 前端增强

- [ ] 资产库系统（角色/场景/道具管理）
- [ ] 关键帧驱动生成（首帧/尾帧 + 插值）
- [ ] 分镜预览面板（九宫格候选 + 关键帧编辑）
- [ ] ComfyUI 节点画布集成验证（部署到服务器）
- [ ] 时间线编辑器原型

### Phase 4（持续迭代）— 长视频 + 深度优化

- [ ] 长文本处理管线（RAG + 小说压缩 + 事件提取）
- [ ] 层级角色一致性（Scene → Event → Global）
- [ ] 自然语言→特效映射
- [ ] 微信机器人接入
- [ ] 世界观持久化 + 衍生资产系统

---

## 三个项目核心启发总结

| 维度 | ViMax | BigBanana | Toonflow |
|------|-------|-----------|----------|
| **最大亮点** | 14 Agent 分工 + Novel2Movie 长视频管线 | 资产驱动 + 关键帧控制 + CutOS 粗剪 | 三层 Agent 解耦 + 技能系统 + 多 Vendor 适配 |
| **架构** | Pipeline + Agent Runtime | 前端 + 4 微服务 Docker | 三层 Agent + 模块化技能 |
| **角色一致性** | 三级层级管理（Scene/Event/Novel） | 三重保障（定妆照/衣橱/上下文注入） | L0-L6 分层叠加 + 四视图设定图 |
| **提示词工程** | Pydantic 结构化输出 + 容错解析 | 版本管理 + 跨阶段排查 | 技能文件（风格×类型×技法三维正交） |
| **视频控制** | 分镜分解（首帧/尾帧/运动） | 关键帧驱动 + 首尾帧插值 | 结构化五维提示词模板 |
| **长文本** | RAG + 小说压缩 + 事件提取 | 多集拆解 + 世界观构建 | 骨架生成 + 改编策略 |
| **工程化** | 断点续跑 + Semaphore 并发 + tenacity 重试 | IndexedDB 本地存储 + Docker 部署 | 本地 ONNX 嵌入 + 可编程 Vendor 适配 |
