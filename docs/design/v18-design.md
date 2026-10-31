# v18（原 v14）长视频质量 — 设计

> 状态：📝 设计稿（2026-10-30，待用户拍板后开工）。roadmap 总览见 `docs/roadmap.md` §v18。
> 前置：v17 已关版（M1-M7 全绿）。v17 遗留的三个"归 v18"钩子（衣橱 schema 正式化/上下文感知注入/BigBanana 关键帧驱动）是本文主体。
> 原则：**不重复造轮子、不新增模型**——VACE/RIFE/xfade/五维运镜/拆解 JSON 全是现成基建，v18 只做"接线与约束"。

---

## 0. 问题陈述（为什么长片质量上不去）

《孔乙己》36 镜全量实测暴露的三个质量瓶颈：

1. **跨镜一致性靠 prompt 碰运气**：每镜独立 LLM 翻译整句→FLUX 独立 T2I，同一咸亨酒店在 #9 与 #15 长得不一样；孔乙己服装状态切换（长衫→破袄→蒲包）全靠翻译模型自觉。
2. **镜间动作不连贯**：I2V 单首帧驱动，镜尾状态随机漂移，与下镜首帧跳变（现状 xfade 0.4s 只是糊住跳变，不是消除）。
3. **长段连续动作无法表达**：单镜 ≤5s 硬约束下，"孔乙己用手走出酒店"这类连续过程只能拆镜硬切。

## 1. 借鉴映射（站在 v17 调研肩上）

| 参考机制 | 来源 | v18 落法 |
|---|---|---|
| 一致性三重保障（定妆照/衣橱/上下文感知） | BigBanana（v17-design §3.3） | M1：衣橱 prompt 级→schema 正式化 + 场景锚 + 镜头 prompt 组装器 |
| 关键帧驱动（首尾帧先出图再插值） | BigBanana（v17 明确归 v18） | M2：**复用 VACE**（wan_vace.json v16 M7 已接）改 flf2v 双图模式 |
| 一镜到底（末帧回灌+漂移控制） | 原 v8-design 并入 | M3：`utils/oneshot.py` 从零写（末帧提取/I2V/运镜五维全现成） |
| 导演规划五步 | Toonflow | M4：世界观注册表 world.json（轻量 JSON，不做向量库） |
| 模型能力路由矩阵 | BigBanana | **不引入**（只接 1-2 个视频模型，bigbanana-research 已结论） |
| 九宫格 turnaround | BigBanana | **不引入**（依赖 nano-banana 级网格服从度，先单参考图） |

## 2. 设计

### M1 一致性资产底座（三重保障落地，零新模型）

**schema 升级**（`m6_breakdown_test.py` 拆解 prompt + JSON 校验）：
- 角色卡加 `costumes: [{name, desc, stages}]`——stages 为适用镜号区间或事件标签（如 `{"name":"出场长衫","stages":[1,20]}`）
- 场景卡加 `anchor_en`（英文场景定妆描述，LLM 拆解时一并生成）
- 旧拆解 JSON 向后兼容（无 costumes 字段回退现状行为）

**镜头 prompt 组装器** `_build_shot_prompt(shot, characters, scenes)`（渲染脚本内函数）：
- 场景段：`shot.scene_id` → 场景卡 `anchor_en`（同场景所有镜头逐字复述同一段——跨镜场景一致性的最简可靠形态）
- 角色段：镜头涉及角色 → 按 stages 匹配当前 costume → `optimize_costume_prompts` 产物（Base Look 锁脸段 + 服装段）
- 翻译段：LLM 只译"动作/运镜/情绪"增量（不再整句自由发挥）
- FLUX 关键帧 prompt = 场景段+角色段+翻译段+STYLE_EN

**场景定妆图**（视觉校验用）：每场景 1 张 FLUX T2I 存 `scenes/scene_{id}.png`，进拼贴图供人工对照（诚实边界：FLUX 无图像条件能力，场景锚首版是 prompt 级复述+人工校验，图像级合成标增强项）。

**镜间过渡升级**（顺手，全现成）：`shot.transition_out` 字段（v2.1 已有）+ v5 `select_effects` 思路 → LLM 按镜尾/镜首情绪与节奏从 xfade 30+ 种里选 kind（替代现状全局 fade）。

**验收**：重跑孔乙己 8 关键镜，拼贴图对照——同场景镜头场景描述逐字一致（程序断言）、孔乙己服装按 stages 正确切换。

### M2 首尾帧驱动（VACE flf2v）

**第一步冒烟**：验证 wan_vace.json 能否吃双图条件（ComfyUI VACE 原生支持 first-last-frame，预期只改 workflow JSON 的 image 引用为两图）。失败则整条 M2 降级不做（M1 收益仍在），如实记录。

**接入 `m6_render` FLF 模式**（环境变量 `M6_FLF=1`，与 M6_ALL 并列）：
- 首帧 = 本镜 FLUX 关键帧（M1 组装器产物）
- 尾帧 = 下镜关键帧（镜间连贯）或本镜 LLM 描述末状态单独生成的末帧图（镜内动作）
- VACE flf2v 出片替代现状单图 I2V；时长/分辨率/编码约束不变（yuv420p 铁律）

**验收**：同题 8 镜对照——FLF 模式 vs 现状 I2V，"镜尾→下镜首帧"画面差值（感知哈希）+ 人工拼贴，给出量化对比数据。

### M3 一镜到底（oneshot.py）

- 链式循环：段 N 末帧提取（ffmpeg，现成）→ 段 N+1 I2V 首帧条件 + **角色锚重注入**（每段 prompt 重新拼 Base Look+场景段，防漂移累积）+ 段长 ≤5s（现有硬约束）
- 运镜脚本：LLM 生成连续运镜链（五维 motion 域，段间方向/速度连续）
- CLI：`python core/vidance.py auto "概念" --oneshot --duration 30`
- **验收**：30s 连续运镜片（如"穿越隧道的光"），人工查验段间拼缝

### M4 长文本管线 + 世界观收口

- 世界观注册表 `world.json`：时代/地域/风格/全局禁则（拆解时 LLM 一并产出），渲染 STYLE_EN 与编剧 system 双端注入
- 事件线接入：拆解 JSON 事件序列 → 长片分段摘要卡（RAG 人物卡已有的路子延伸）
- 正式化收尾：M1 组装器/场景锚/衣橱进 `SKILL/commands/novel2video/` README 流程（v17 双位置同步惯例）；roadmap/演示页/usage 同步更新

## 3. 里程碑总表

| # | 交付 | 依赖 | 新模型 | 风险 |
|---|---|---|---|---|
| M1 | schema 升级+场景锚+组装器+过渡升级 | v17 拆解/衣橱/v5 转场 | 无 | 低（纯接线） |
| M2 | VACE flf2v + m6_render FLF 模式 + 同题对照 | M1 关键帧 | 无（VACE 已接） | **中**（双图 workflow 未验证，先冒烟） |
| M3 | oneshot.py + `--oneshot` CLI | M2 末帧思想 | 无 | 中（漂移控制靠每段重注锚） |
| M4 | world.json + 事件线 + 正式化收口 | M1-M3 | 无 | 低 |

建议顺序 M1→M2→M3→M4；M2 冒烟失败不影响 M1/M3 交付。

## 4. 风险与边界

1. **VACE flf2v 未验证**是最大不确定项——M2 第一步即单镜冒烟，失败降级路径明确（维持 M1 prompt 级约束）。
2. **FLUX 无图像条件**：场景锚/角色锚首版全部 prompt 级；图像级合成（背景+角色贴回）依赖 inpaint/Fill 组合，标增强项不承诺。
3. **不引入清单**：模型能力路由矩阵、九宫格 turnaround、向量世界观库（JSON 注册表够当前量级）。
4. **算力不变**：FLF/链式单镜时长与现状 I2V 同量级（~2.3min/镜），36 镜全量仍 ~2h。
5. **Windows 铁律延续**：所有新 ffmpeg 环节显式 h264+yuv420p；成片必须烧字幕。
