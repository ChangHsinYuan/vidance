# Changelog

语义化版本（semver）：`主.次.修订`——主版本=能力代际（v 系列里程碑集），次版本=单个 v 里程碑，修订=修复与补全。当前版本见根目录 `VERSION`，运行 `python core/vidance.py --version` 查询。

## Unreleased

开源工程基建（不影响运行时行为）：

- **CI 门禁**：`.github/workflows/ci.yml`——push/PR 在干净环境跑全部 18 套单测（ubuntu + py3.10/py3.12 矩阵，纯 CPU，最小依赖集经干净 venv 验证；模型相关测试走内建跳过守卫）
- **发布通道**：`.github/workflows/release.yml`——push tag（如 `v1.1.0`）自动构建 API 镜像推 GHCR（`ghcr.io/<owner>/vidance-api:{tag,latest}`，GITHUB_TOKEN 免密）+ 创建 GitHub Release（自动生成 notes）
- **云端快速开始**：README 双语新增"云端 API 路线"（docker run 发布镜像，无 GPU 无克隆 5 分钟出片）；compose `vidance`/`tts` 服务支持 `VIDANCE_API_IMAGE` 变量覆盖镜像（缺省行为不变）
- **贡献者设施**：`CONTRIBUTING.md`（双语）+ Bug/功能建议 Issue 表单 + PR 模板
- **文档英文化**：docs/en/ 门面层 11 件全译（README/CHANGELOG/roadmap/AGENTS/usage/deploy/t2c/SKILL/instructions），README 双语切换行；EN 相对链接全部校验可解析
- **CI 首跑修复**：`core/doctor.py` 磁盘检查在 `output/` 缺失时回退最近存在祖先（原 OSError 致 CI 挂）；`test_rework` 测试产物目录自动创建（CI runner 无 /tmp/opencode）；`test_rag_novel` 编码段加本地模型守卫（对齐 test_embed_index 约定，CI 无 bge 目录即跳过）；ci.yml 去掉 torch 安装（守卫后不再需要）、补装 ffmpeg（runner 镜像已移除，rework/skills 的 ffmpeg 链测试需要）并改为失败测试末尾 traceback 以 ::error 注解回传（匿名可读，免登录查日志）

## 1.1.0 (2026-11-17)

v22 宣传海报生成（poster 线）：

- **poster 子命令**：一句概念 → LLM 规划海报 JSON（标题/英文副标/中文标语/底板提示词/生灵分区）→ FLUX 底板（2:3，多 seed 重试）+ 生灵立绘 → Grounded-SAM 抠图（YOLO 框提示，失败自动降级亮度键控）→ PIL 参数化合成 → `output/poster*/poster.jpg`；FLUX 整体缺席时降级紫夜渐变底板继续出片
- **排版体系**（移植自 README 宣传海报 v8 实测参数）：标题色散+辉光、生灵五分区锚点（back-center 全息/mid 渐隐/front 前景）、紫色 wash 防贴纸感、底部渐变蒙版、雨丝、暗角+颗粒；终端卡命令/双 URL/QR 可选
- **四通道**：CLI `poster`（一键 + `--plan` 渲染模式）+ agent `generator.poster` + `POST /api/tool/poster`（异步 job）+ utils 薄壳
- **测试**：tests/test_poster.py 31 项（无 GPU）+ GPU E2E 116.7s 出片盲检 8/10

## 1.0.0 (2026-11-05)

首个语义化版本标签，对应 v21 交付形态关版。**能力代际 v0→v21 全量收录**（括号内为历史编号重排，详见 docs/roadmap.md）：

### 核心生成
- **auto/quick/custom/h3shot**（v0-v3）：中文概念→LLM 编剧→Wan T2V/I2V→双引擎 TTS→审片→ffmpeg 合成；角色锚三路径（3DGS/mesh/flux）+ Hunyuan3Dv2 资产库复用
- **长视频**（v2/v2.1）：RIFE 光流过渡与慢放、并行预取、LUT/BGM/STT 后处理、`--duration` 动态镜头数
- **一镜到底**（v18，原 v14）：链式 I2V 末帧回灌 + LLM 运镜链 + 拼缝 MAE 断言；VACE 首尾帧驱动镜间过渡
- **层级一致性**（v18）：场景锚 + 衣橱系统 + 事件线 world.json

### 轻量无模型线（无 GPU 可跑）
- **fast/hot 营销号**（v4，原 v13）：爬图+校验+Ken Burns+TTS，热点自动选题
- **SVG 动效**（v13）：LLM 生成 SVG→无头浏览器逐帧→mp4
- **PPT**（v15）：deck.html→mp4/PDF/PNG 多形态
- **Blender 3D**（v13）：bpy EEVEE 模板场景→短片

### 编辑与二创
- **SAM2 编辑**（v16，原 v19）：分割/抠图/换底/打码/inpaint/彩色多物体/YOLO 自动/视频双向追踪
- **生成式编辑**（v16.x）：FLUX Fill 重绘、ControlNet canny、VACE 参考图生视频、Qwen-Image-Edit 指令式
- **视频链接二创**（v19，原 v16）：下载→理解→改写解说（防复述断言）→重配音→画面改写；烧录字幕消除（ProPainter）
- **时间线拼接**（v10）：关键帧/掩码/贴纸轨，后端 CLI 剪辑

### 平台与编排
- **多智能体**（v11，原 v13）：D/G/P/V 四层 28 agent + chain 编排 + 黑板台账
- **前端 WebUI**（v7）：:8894/ui 三栏画布、任务卡片、/ 命令补全、⚙ 模型/系统设置
- **API**（v4/v9）：FastAPI :8894 任务队列（SQLite 持久化）、工具分发、OpenAPI
- **t2c 自然语言→命令**：mt5-small 微调翻译层
- **会话资产层**（v17，原 v12）：buffer/@引用/断点续跑 sha256/RAG/五维模板/剧本拆解 novel2video

### 质量与 honesty
- **生成中审核**（v20，原 v21）：WS latent2rgb 预览帧→qwen3.8 粗审→fail 即 interrupt 止损换 seed；UI 实时 verdict 卡片（实测粗审只挡大崩坏，语义细节靠终审——分工边界有实证）
- **审片体系**：5 维全量审片 + light 并行审片 + review_ensemble 多票

### 交付形态（v21）
- **资源探测 doctor**：`vidance doctor` + `/api/doctor`——GPU/端口/conda/磁盘/外网 → 五档推荐（none/flux/wan/h3/full）
- **部署分档**：同一份代码 + `VIDANCE_TIER` + config/tiers 覆盖；Docker 五档 compose profiles
- **一键安装** `deploy/install.sh`：探测→选档→起容器（或 conda setup_env）→冒烟自检
- **面向用户细节**：`vidance init` 配置向导、失败自诊断 hints（端口/显存/外网点名到命令）、输出目录清理（保护运行中任务）、VERSION + `/api/version`

## 0.x（2026-09 前史）

v0 MVP（T2V+TTS+合成）→ v1 角色锚（3DGS）→ 版本重排 v11-v21 立项。原始规划稿：`docs/archive/roadmap_origin.md`。
