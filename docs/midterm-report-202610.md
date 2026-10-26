# Vidance 中期报告（2026-10）

> **一句话**：Vidance 是一个基于本地多模型编排的 AI 短片生成系统——中文一句话创意或一篇小说，经 LLM 编剧、本地视频/图像模型生成、TTS 配音、多模态审片、自动后期，产出有声短片、营销号视频、SVG 动画、PPT、3D 展示等多形态内容。
>
> 本报告覆盖 2026-09-07 立项至 2026-10-16 的全部进展。数据来源：docs/roadmap.md、docs/reports-20261001.md，关键产物路径均经核实存在。

---

## 1. 项目定位与目标

**"agent 当导演"的视频生产系统**，不是单点 API 服务：

| 角色 | 组件 | 职责 |
|------|------|------|
| 制片人 | opencode agent / core 流水线 | 全流程主控，关键决策介入 |
| 编剧/策划 | LLM（deepseek-v4-flash） | 概念→分镜脚本→prompt 优化 |
| 摄影/演员 | 本地生图生视频模型 | FLUX / Wan2.2 / MiniMax-H3 / HunyuanVideo |
| 角色锚 | 3D 重建 + 参考图链路 | TripoSplat(3DGS) / Hunyuan3D(mesh) / FLUX 参考帧，跨镜头不漂移 |
| 配音员 | TTS 双引擎 | edge-tts（在线）+ CosyVoice 2（本地克隆） |
| 审片员 | 多模态 LLM（qwen3.8-chat） | 逐帧读图打分，闭环重做 |
| 剪辑师 | ffmpeg + moviepy + OpenCut 思路 | 拼接/字幕/配乐/调色/转场/特效 |

**核心原则**：应用层不做模型研发——只筛选组合现成开源模型（最多小改动，不调优不训练），把工程精力花在编排、一致性与质量保障上。硬件底座为 4×RTX 4090 工作站，docker 分档部署。

---

## 2. 总体架构（三层）

```
┌──────────────────────────────────────────────────────────┐
│  产品层   有声短片 / 角色一致性 / 长视频 / 营销号 / SVG /      │
│           PPT / Blender 3D / 视频编辑 / 时间线拼接            │
├──────────────────────────────────────────────────────────┤
│  编排层   多入口：CLI / WebUI(:8894/ui) / HTTP API /         │
│           t2c 自然语言翻译 / 多智能体(28 agents) / SKILL 风格  │
│           混合模式：确定性流程硬编码，创意判断交 LLM           │
├──────────────────────────────────────────────────────────┤
│  引擎层   T2I: FLUX   T2V: Wan2.2 / H3 / HunyuanVideo        │
│           3D: TripoSplat / Hunyuan3Dv2                       │
│           音频: CosyVoice 2 + edge-tts + faster-whisper       │
│           后期: ffmpeg + RIFE + LUT + BGM ducking             │
│           LLM: USTC API（编剧 + 多模态审片，不本地部署）        │
└──────────────────────────────────────────────────────────┘
```

核心创新（v1 提出、贯穿全项目）：**角色锚机制**——角色参考图经 3D 重建（3DGS/mesh）或 FLUX 参考帧链路，按镜头角度渲染起始帧喂 I2V，避免跨镜头角色漂移；v3 起扩展到场景锚。

---

## 3. 模型与引擎底座（11+ 本地模型，4×4090 分卡调度）

| 类别 | 模型 | 端口/GPU | 用途 |
|------|------|---------|------|
| T2V/I2V | Wan2.2-TI2V-5B | 8189 / GPU2 | auto 主力 |
| 参考图生视频 | MiniMax-H3 ref2va（原生音频） | 8188 / GPU0 | custom 主力 |
| T2V 备选 | HunyuanVideo 13B | 8190 / GPU3 | 备选 |
| T2I | FLUX.1-dev fp8 | 8192 / GPU3 | 角色/场景图 |
| 3D | TripoSplat（3DGS）/ Hunyuan3Dv2 turbo（mesh） | 8192 / 8193 / GPU1、GPU3 | 角色锚/场景锚 |
| 编辑 | SAM2.1 tiny+small / YOLOv8s / FLUX Fill / Wan2.1 VACE 1.3B / Qwen-Image-Edit 2509 | 8189/8192 共实例 | v16 编辑全家桶 |
| TTS | CosyVoice 2 0.5B（零样本克隆）+ edge-tts | 9880 / GPU2 | 双引擎统一封装 |
| STT | faster-whisper large-v3-turbo | 按需 | 字幕/质检回验 |
| 插帧 | RIFE v4.26 | 随 Wan 实例 | 过渡 + slowmo |
| 嵌入 | bge-small-zh-v1.5（92M，CPU 可跑） | — | RAG |
| 翻译 | mt5-small 微调（t2c） | CPU | 自然语言→命令 |
| 转写 | FunASR paraformer（FunClip） | 按需 | 字级时间戳裁剪 |
| LLM | deepseek-v4-flash + qwen3.8-chat（USTC API） | 远程 | 编剧/审片 |

后期资产均为程序生成或 CC 免版权：6 种 3D LUT（numpy 生成）、6 种 BGM（incompetech CC BY 真实素材 + ducking 混音）。

---

## 4. 已完成工作

### 4.1 时间线（六周）

| 时间 | 里程碑 |
|------|--------|
| 09-07 | **v0 MVP**：概念→Wan T2V→配音→审片→合成，13.3s 成片（3 镜审片 7/7/7） |
| 09-08 | **v1 角色一致性**（含 v1.1：I2V 修复相关性 0.99+、flux/mesh/auto 多模式） |
| 09-10 前后 | **v2 长视频+完整后期**：RIFE 插帧、镜头并行预取、LUT 调色、BGM ducking、STT 字幕 |
| 09-12 | **v3 2D→3D→新视角**（M0-M7）：Hunyuan3Dv2 mesh 重建 + headless EGL 渲染，12.8s 成片 |
| 09-13~15 | **v4 营销号流水线**（M1-M6）：热点爬虫→LLM 选题→异步任务队列→FastAPI(:8894)→声音克隆生产化（B站源自动克隆）→FunClip 语义裁剪→素材爬取→fastline 快速出片线 |
| 09-14 | **v5 剪辑特效**（8 种特效+30 种 xfade+LLM 自动选）、**v6 prompt 多轮核实**（6 维追问状态机） |
| 09-15 | **v7 前端 WebUI**（:8894/ui，零 npm 自包含）+ v8/v9 增强与 API 标准化 |
| 09-24 | **t2c 自然语言→命令**（mt5-small 微调，CPU 可跑） |
| 09-25 | **v10 拼接与特效**（OpenCut 时间线思路，M1-M8：关键帧/掩码/贴纸轨/split） |
| 09-26 | **v11 多智能体**（D/G/P/V 四层 28 agents + 黑板 + 链轨迹 + 前端架构图）、**v12 make 统一入口**（director×generator 排列组合） |
| 10-01 | **v13 轻量化收口**（无 GPU 四线：营销号/SVG/PPT/Blender3D）+ **v15 LLM 生成 PPT**（HTML 幻灯片→mp4/PDF/PNG） |
| 10-02 | **v16 视频编辑**：SAM2 分割/抠图/打码/inpaint、YOLO 自动（Grounded-SAM）、视频双向追踪；**v16.x 生成式编辑**：FLUX Fill 重绘 / Union ControlNet / Wan VACE 参考图生视频 / Qwen-Image-Edit 中文指令编辑 |
| 10-10~11 | docker 部署收口（五档 tier 全线验证）+ VACE 生成式视频 inpaint |
| 10-13 | **工程化四件套**：Buffer 资产层（@引用附件）/ JSON 容错自修 / **断点续跑** / MPT 调研 A 档四项落地（字幕 Levenshtein 纠正、preflight 预检、素材 md5 全局缓存、搜索 TTL 缓存） |
| 10-14 | **SKILL 风格预设系统**（commands/agents 双维度，全模块 --skill 接线）、音色纠错（坏克隆排查）、萌系音色 meng1 本地化、容器重建 |
| 10-15 | **M5 收官**：五维提示词模板 + RAG 参考资料注入（bge+FAISS）；**M6 Toonflow 复现** S1-S6 + R-N/R-API 全落地，两支小说→短剧 E2E 成片 |
| 10-16 | E2E 配音硬伤三轮修复收口（根因到代码级）、/rag 独立命令 + /help 扩容、部署文档补全 |

### 4.2 能力矩阵（版本线 × 状态）

| 版本线 | 内容 | 状态 |
|--------|------|------|
| v0 | 有声短片 MVP | ✅ 09-07 |
| v1 | 角色一致性（3DGS/mesh/flux 三模式） | ✅ 09-08 |
| v2 | 长视频 + 完整后期（RIFE/LUT/BGM/STT） | ✅ |
| v3 | 2D→3D→新视角 | ✅ M0-M7 |
| v4 | 营销号流水线（热点→成片） | ✅ M1-M6 |
| v5 / v6 | 剪辑特效 / prompt 多轮核实 | ✅ |
| v7-v9 | 前端 WebUI + 增强 + API 标准化 | ✅ |
| v10 | 时间线拼接与特效（OpenCut 思路） | ✅ M1-M8 |
| t2c | 自然语言→命令翻译层 | ✅ |
| v11 | 多智能体（28 agents + 黑板） | ✅ M0-M4 + v11.1 |
| v12 | make 统一入口（三排正交） | ✅ M1-M2 |
| v13 | 轻量化四线（营销号/SVG/PPT/Blender 3D） | ✅ |
| v15 | LLM 生成 PPT（多形态交付） | ✅ M1-M4 |
| v16 | 视频编辑（SAM2/YOLO/追踪 + 生成式四件套） | ✅ M0-M8 |
| v17 | 整合开源仓库（buffer/@引用/断点续跑/JSON 容错/RAG/五维提示词/Toonflow 复现） | 🟢 主体完成 |
| v14 | 社交媒体接入 | 🔗 移交队友 |
| v18-v21 | 长视频质量 / 视频二创 / 生成中审核 / 交付形态 | 🎯 排期在后（deploy 档位已建） |

---

## 5. 量化成果

| 指标 | 数值 |
|------|------|
| 核心代码规模 | **23,300+ 行** Python（core/ + utils/ + agents/，不含测试） |
| 测试 | **213 项单测全绿**（9 个套件，1,158 行测试代码）+ 十余支端到端全链成片 |
| 版本路线 | 20+ 条线，**15+ 完成**；仅 v14 移交队友，v18-v21 排期在后 |
| 本地模型 | **11+ 个**（视频 3 / 图像 2 / 3D 2 / 编辑 5 / 音频 2 / 嵌入 1），4 GPU 分卡，docker 五档部署 |
| 多智能体 | 28 个注册 agent（导演/生成/后期/审片四层），黑板轨迹可追溯 |
| 开源仓库消化 | **3 个源码级调研**（MoneyPrinterTurbo 8700 行 / BigBanana / Toonflow），A 档条目全部落地 |
| 工程文档 | roadmap（643 行）+ 19 篇设计文档 + 12 篇使用指南 + 3 篇调研 + 部署/命令库 + 全程汇报 |
| 服务面 | CLI 15+ 子命令 / HTTP API 29 工具端点 / WebUI 对话式 / t2c 中文直译 |

---

## 6. 技术亮点

### 6.1 小说→短剧全链路（M6，Toonflow 复现，代表作）

输入一篇 3 章小说，全自动产出多镜头有声短剧。核心是**"把 AI 不一致性钉死"的流程纪律**：

1. **RAG 小说索引**：分章入库 + LLM 抽取人物卡（外貌/服装具体可画）→ 人物卡成为**外貌唯一来源**；
2. **一致性锚点**：风格/色彩/光影/氛围四键全局锚定，各镜 prompt 引用 canonical 描述而非自由发挥；
3. **四视图设定图**：单图四格（特写+正/侧/后）锁定角色形象；
4. **分镜铁律 + 代码兜底**：>20 字拆镜、黄金 6 秒、禁光影词——LLM 不听话时 `_scrub_scene_desc_lighting` 代码层拦截并定向修复（fix-loop 模式）；
5. **风格包确定性覆盖**：anime90s/国风等 SKILL 模板四键直接覆盖 LLM 生成锚点；
6. **音色绑定 + 断点自愈**：speaker→音色映射路由；重启后资产存在即跳过再生。

E2E 验证：6 镜全链（RAG→编剧→锚点→设定图→I2V→审片→配音→后期），人物卡外观逐镜保真，成片 25.9s。

### 6.2 全链质检体系（每个 AI 环节都有质检）

- **多模态审片**：5 维打分（一致性/质量/运动/伪影/角色），综合分 ≥7 过审，失败重试 ≤2 取最高分兜底；
- **S4 scrub**：分镜表违例（光影词/超长句）检测→LLM 定向修复→仍违例不采纳；
- **TTS 护栏**：合成后 whisper 反转写 + 拼音音节校验，对不上自动重试、按词界裁剪，**绝不落盘幻觉音频**；时长合理性校验拦截废音频；
- **字幕纠正**：STT 只贡献时间轴，文本以剧本原文为准，Levenshtein 相似度对齐修错字、丢幻觉段、单长段按剧本句占比展开；
- **preflight 预检**：硬依赖挂拒绝启动、软依赖挂警告降级（vidance 哲学与 MPT 全拦的差异点）。

### 6.3 工程化韧性

- **断点续跑**：`--resume TASK_ID` 原子 checkpoint（编剧/prompt/角色/逐镜四阶段），损坏镜头自动重做、健康镜头复用；
- **全局缓存**：素材 URL-md5 命名跨任务秒回 + 下载完整性验证 + 搜索结果 24h TTL（实测第二次 0.0s vs 首次 10.4s）；
- **可靠写盘**：tempfile+fsync+os.replace 原子写贯穿 checkpoint/缓存/RAG 索引；
- **降级哲学**：GPU 服务全挂时 fast 线仍降级出片不崩（静音兜底/占位图/引擎降级链）；
- **部署**：docker 五档 tier（none→full）按显存档位组合服务，一键 start_services 脚本。

### 6.4 多形态输出 + 多入口

- 五条产出线共享同一编排底座：**视频**（auto/custom/quick）、**营销号**（fast/hot：热点爬取→爬图→Ken Burns→配音）、**SVG 动画**、**PPT**（deck.html→mp4/PDF/PNG）、**Blender 3D**；
- 四种入口殊途同归：CLI / WebUI 对话（:8894/ui）/ HTTP API（29 工具）/ 中文自然语言（t2c + LLM 意图层）；
- 28 个 agent 按物理分层（Director/Generator/Post/Audit），chain 链式编排 + ${ctx} 产物引用 + 运行轨迹可视化。

---

## 7. 典型问题与解决案例（体现排障深度）

### 案例一：E2E 配音硬伤——五轮迭代追到根因
- **现象**：成片 3 个镜头音频 0.6s 废片 + 句首尾杂音（幽灵音节）；
- **根因 1**：CosyVoice fp16 在 3 路并行预取时采样数值崩坏（服务端日志实锤 `probability tensor contains inf/nan`），服务返回 200 但音频废片，客户端无校验直接落盘；
- **根因 2**：零样本克隆的 prompt 文本被 LLM 当上文续写——prompt 过长或语义引导性强时，正文句首尾被接上 prompt 相关音节（用户点破"杂音只在 prompt 里"是关键线索）；
- **修复**（全在客户端，服务端保持官方原样）：全局串行锁 + 时长校验重试 + STT 反转写音节护栏 + 词界精裁 + 定版"话题中性短句"克隆样本（A/B 三候选实测选出）；
- **沉淀**：克隆样本选段规则进 meta.json，护栏使所有克隆音色长期受益。

### 案例二：25 秒字幕塌缩成一句
- **根因链**：whisper 在长旁白+BGM 下把 12 小句并成 1 个 25s 长段 → 纠正层"对不齐以剧本兜底"把首句套上整段时间轴 → 其余 11 句被当"漏识别"跳过；
- **修复**：加预步骤——STT 字数 ≥ 剧本 60% 时按剧本句字符占比把长段时间轴展开成句级伪字幕；真漏识别维持"宁缺勿错"；
- **复盘**：引擎都没坏，是"长文艺文案+calm BGM+克隆音色"新组合暴露三个老毛病，全部收口并回归 108 测试。

### 案例三：角色链断裂的暴露与自愈
- 首支小说 E2E 走了纯 T2V（人物卡没进角色锚）→ 修 schema 恒含 character 字段；LLM 回坏 JSON 直接 KeyError → 结构校验 + 报错回喂 LLM 自修 + pipeline 守卫；shot3 首审 5 分缺角色 → 重试 8 分过——**审片闭环在生产环境真实生效**。

---

## 8. 与开题计划的对照与偏差说明

- **按计划**：版本路线 v0-v17 主干全部按序推进，核心创新（角色锚、审片闭环、多智能体编排）均落地；
- **既定约束而非偏差**：应用层不研发/不调优模型，全部采用现成开源模型组合（开题即明确的边界）；
- **偏差与调整**：
  - v14 社交媒体接入移交队友（人力分工）；
  - 3DGS 角色锚效果受限（特写/侧面走样），实践中形成 "auto 审查不过自动降级 flux" 的工程结论——多路径冗余比单点死磕更有效；
  - 部分版本线状态标注在 roadmap 中滞后于实际进展（以本报告功能描述为准）；
  - 后期（10-13 起）重心从"功能扩张"转向"质量与工程化"（质检体系/断点续跑/缓存），是为长视频质量（v18）打地基的主动调整。

---

## 9. 下一步计划（答辩后）

| 优先级 | 事项 | 说明 |
|--------|------|------|
| 短期 | 收尾 v17 | jieshuo1 音色 prompt 重选（同法）、meta.character_mode 回填小瑕疵、容器镜像重建带入 M6 全部改动 |
| 短期 | **画布多视频同放**（新需求，已评估） | 多路视频拼合同一画布、同步播放/停止——两条实现路线：①ffmpeg xstack 网格合成（离线出片，同步天然成立，半天~1 天，可作 v10 拼接线延伸）；②WebUI 前端多 `<video>` 同步控制器（主时钟对齐+漂移校正，1~2 天）。建议先做① |
| 中期 | **v18 长视频质量** | 关键帧驱动/一镜到底/层级一致性——质检与断点地基已备 |
| 中期 | **v19 视频链接二创** | 爬虫/FunClip/编辑全家桶均已就位 |
| 远期 | v20 生成中审核 / v21 交付形态 / t2c 语料重训 | — |

---

## 附录 A：演示产物索引（均已核实存在）

| Demo | 路径 | 时长 | 说明 |
|------|------|------|------|
| 小说→短剧（定版） | `output/auto_20261015_211033/final.mp4` | 25.9s | 3 章小说→6 镜全链，代表作 |
| 小说→短剧（首支） | `output/auto_20261015_200322/final.mp4` | 10.7s | 同概念对照 |
| 叙事风格快线 | `output/fast20261014_172551/final.mp4` | 26.3s | SKILL narrative + RIFE + 电影 LUT |
| 营销号快线 | `output/fast20261014_110602/final.mp4` | 6.8s | SKILL marketing：钩子文案+硬切+加速 |
| 长片叙事快线 | `output/fast20261014_112331/final.mp4` | 51.0s | 6 段文艺长句+全后期 |
| agent 配方出片 | `output/fast20261014_204913/final.mp4` | 10.8s | SKILL artist 职业配方 |
| SAM2 编辑 | `output/edit_demo/`（9 件） | — | 分割/抠图/打码/换底 |
| VACE 参考图生视频 | `output/vace14b_rabbit_f0.mp4` | 5.1s | 生成式编辑 |
| ProPainter 视频去物 | `output/pelican_propainter.mp4` | 3.0s | 生成式视频 inpaint |
| SVG 动画 | `output/svg_*/`（5 批） | — | 鹈鹕骑车等 |
| PPT 多形态 | `output/ppt_*/`（8 批） | — | deck.html/mp4/PDF |
| Blender 3D | `output/blender3d_*/`（8 批） | — | bpy EEVEE 渲染 |
| 猫狗打斗 | `output/tb_work_dog/` | — | H3 参考图生成+SAM2 逐帧追踪 |

## 附录 B：单测套件（213 项 = 9 套件）

skills 74 / subtitle_correct 20 / material_cache 20 / buffer 19 / preflight 6 / rag 21 / m6_anchors 20 / rag_novel 15 / m6_s5s6 18

## 附录 C：文档索引

- 总览：`docs/roadmap.md`；全程汇报：`docs/reports-20261001.md`
- 设计：`docs/design/`（19 篇，v0-v18 + v12-modules + v-t2c + v-svg-pipeline + hierarchy）
- 调研：`docs/research/`（mpt-research / bigbanana-research / toonflow-research）
- 使用：`docs/usage/`（12 篇）；部署与命令库：`docs/instructions/`（deployed-models / deploy-tiers / commands.json）
