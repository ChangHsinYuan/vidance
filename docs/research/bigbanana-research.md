# BigBanana 源码级调研（2026-10-15）

> 对象：`/mnt/disk_sdb/zxy/BigBanana/`（本机克隆）。注意：**工作区已无源码**（仅剩 README/docs/docker-compose），全部结论来自 git 历史最后一个全量提交 `fdaaa8f`（只读提取到 /tmp/opencode/bb-src/）。
> 定位：Script→Assets→Director→Edit 四阶段工作台，纯前端直连各家 LLM/图像/视频 API（无业务后端，数据全存 IndexedDB），面向"剧本化多镜头短剧"生产。
> 分档：**A 强烈推荐（M6 落地）/ B 已有等价物 / C 过重不搬**。

## A. 强烈推荐（M6 剧本拆解+一致性资产 候选）

| # | 机制 | BigBanana 实现（fdaaa8f 源码位置） | Vidance 落地建议 |
|---|------|-----------------------------------|------------------|
| 1 | **全局美术指导文档（consistencyAnchors）** | `services/ai/visualService.ts generateArtDirection`：结构化剧本后先产出一份 ArtDirection（colorPalette/characterDesignRules/lightingStyle/textureStyle/moodKeywords + `consistencyAnchors` 风格锚点文本），之后**每次**资产/镜头提示词生成强制注入 | M6 第一步：一次 LLM 调用产 style_anchor，剧本拆解与每镜 T2V prompt 均携带——风格漂移从逐镜博弈变单点约束，成本极低 |
| 2 | **分档一致性提示词** | `services/promptTemplateService.ts:310`：有参考图→"面部/发型/服装/体型逐项严格遵循参考图（最高优先级）"；无参考图→文字描述约束档；道具同分两档 | 纯提示词工程直接移植：v3 asset_registry 有定妆图的角色走硬约束档，没有的走描述档 |
| 3 | **镜头级资产引用 + 参考图上限** | `components/StageDirector/utils.ts:171 getRefImagesForShot`：Shot 携带 characters[]/props[] 引用集合，生成关键帧时组装参考图，**上限 5 张**，超出丢弃并计数（droppedTurnaroundCount） | M6 镜头→资产绑定套用：引用集合 + 注入上限 + 丢弃告警，防止参考图超限静默劣化 |
| 4 | **PromptVersion 版本历史** | `services/promptVersionService.ts`（69 行）：`{prompt, createdAt, source: ai-generated\|manual-edit\|rollback, note}` 环形上限 30 条 + 去重 + 首次编辑 backfill 基线 | 用户必然会手改 AI 资产提示词；asset_registry 每字段加 versions 数组即可，小成本高价值 |
| 5 | **生成状态机 + 指纹防重** | 资产/关键帧全带 `status: pending\|generating\|completed\|failed` 持久化 + `generationMeta` 三指纹（structureKey/visualsKey/shotsKey）检测"剧本/风格变了要重生成"+ 卡 generating 恢复 | M4 checkpoint 已覆盖断点续跑；补资产级 status 字段与"拆解输入变了→资产失效"指纹即可 |

**剧本拆解 JSON schema（可直接参考）**：`promptTemplateService.ts storyboard.shotGeneration` 要求 LLM 输出
`{"shots":[{id, sceneId, actionSummary, dialogue, cameraMovement, shotSize, characters, props, keyframes}]}`，
模板内嵌 33 条运镜参考表（Dolly Shot (推镜头) / POV Shot (主观视角)…），并配 shotRepair 修复提示词（要求恰好 N 镜）。
剧本结构化（`scriptService.ts`）：原文→`ScriptData{title, genre, logline, characters, scenes, props, storyParagraphs}`。

## B. 已有等价物（无需借鉴）

| BigBanana 机制 | 实现 | Vidance 对应 |
|----------------|------|--------------|
| JSON 容错解析 | `apiCore.ts parseJsonWithRecovery + cleanJsonString` | M4a 修复层 + 带报错回喂自修 2 次 |
| LLM 重试退避 | `apiCore.ts retryOperation`（3 次，仅 429/504/timeout/network） | M7 计划 tenacity 同款策略 |
| 断点续跑 | `ScriptGenerationCheckpoint`（structure→visuals→shots 三步） | M4 checkpoint.json 全阶段覆盖，不逊色 |
| 首尾帧连贯性约束 | 结束帧必须与起始帧同身份/服装/场景锚点/光照 | H3 首尾帧链路已有；提示词约束可并入 M6 模板 |

## C. 过重/不适用（明确不搬）

| # | 机制 | 评估 |
|---|------|------|
| 6 | **九宫格定妆照 turnaround**（9 视角面板替代多图参考） | 思路好但依赖图像模型对复杂网格布局的服从度，BigBanana 为此写了大量 guardrail（布局硬约束/panel 校验/禁文字规则）。vidance 图像模型非 nano-banana 级，先做**单参考图 + 变体图**，宫格列后续增强 |
| 7 | **模型能力路由**（sora/veo/doubao 三族 × 中英 × 网格/首尾帧模板矩阵） | 支撑 10+ 视频模型的通用层；vidance 只接 1-2 个视频模型，写死一套"首帧驱动+尾帧可选"模板，模型 >3 个再抽象 |
| 8 | **纯前端直连 + IndexedDB** | 密钥暴露 + 存储膨胀；vidance 有后端，只借鉴其数据结构与提示词组织 |
| 9 | 网格分镜驱动视频（九宫格整图作视频参考 + guardrail 强制单画面全屏） | 依赖同 #6，缓 |

## 调研方法备注

- 工作区无源码：`git log` 定位 `fdaaa8f`（2026-03-08 最后全量提交）→ `git archive` 只读提取到 /tmp/opencode/bb-src/，未改仓库任何内容
- 仓库体积 59M（.git 为主），README 宣称的完整管线在历史提交中
