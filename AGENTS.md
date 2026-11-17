# Vidance — AI 有声短片生成

> 本文件供 opencode agent 读取，了解项目约定与命令。

## 项目概述

Vidance 是一个基于 opencode agent 编排的本地视频生成系统。核心流程：中文概念→LLM编剧→Wan T2V生成→双引擎TTS配音→多模态审片→ffmpeg合成→有声短片。

**统一入口**：`python core/vidance.py make`（v12（原 v17）：`--director llm|manual|scout × --generator wan|fast|svg|h3` 排列组合）或直用子命令 `{auto|custom|quick|fast|hot|svg|compose|concat|h3shot}` — auto 模式走 LLM 编剧+Wan/FLUX 生成，custom 模式走参考图+预写脚本+H3 ref2va 生成，quick 模式纯 T2V 无后处理。后处理（RIFE/LUT/BGM/STT）由 `core/postprocess.py` 共享模块提供。

**当前状态：v0-v7 全部实现 + v10 时间线拼接（M1-M8）+ svg 有声流水线（S1-S5）+ t2c 自然语言→命令 + v12 make 统一入口（M1-M2，原 v17）+ v11 多智能体（M0-M4 + v11.1 前端可视化，原 v13，agents/ 目录，docs/design/v11-design.md）+ v15 PPT 流水线（M1-M4，原 v20：ppt_llm plan_deck/模板/svg_chart + ppt_pipeline PptLine 多形态 deck.html/PDF/PNG/mp4 + CLI ppt + generator.ppt agent + /api/tool/ppt）+ v13 blender 3D 简单版（blender_llm plan_scene/模板 title3d+shapes+bars3d + blender_pipeline bpy EEVEE + BlenderLine + CLI blender3d + generator.blender3d agent + /api/tool/blender3d）+ v13 轻量化收口（无模型四线全具备：营销号/SVG/PPT/Blender）+ **v22 宣传海报 ✅（2026-11-17 关版：poster_llm 概念→JSON 规划（zone 五分区白名单+_norm_plan 钳制）+ poster_pipeline FLUX 底板→Grounded-SAM 抠图（亮度键控降级）→PIL 参数化合成（v8 实测参数：色散/辉光/全息渐隐/雨夜/终端卡/QR）→ PosterLine + CLI poster + generator.poster agent + /api/tool/poster 异步 job；tests/test_poster.py 31 项 + GPU E2E 116.7s 出片 qwen 盲检 8/10）** + v16 SAM2 编辑 + 生成式编辑增强 ✅（sam_edit segment/cutout/replace_bg/mosaic/inpaint/visualize/instruct + YOLO 自动 Grounded-SAM/框提示 + video 双向传播追踪 + v16.x M5 FLUX Fill 生成式重绘/M6 Union ControlNet canny 联动/M7 Wan2.1 VACE 参考图生视频/M8 Qwen-Image-Edit 2509 指令式编辑（中文可用）+ CLI edit --engine flux|vace|instruct + post.edit agent + /api/tool/edit|vace + deploy 环境固化三件套；docs/design/v16-design.md）+ **v17 开源整合（原 v12）✅（M1-M7 全绿，2026-10-30 关版：M1-M3 buffer 会话资产层/前端附件/@引用（@N+@文件名 q 搜索+游标 410）/M4 断点续跑 sha256 指纹+JSON 容错/M5 五维模板+RAG/M6 剧本拆解 novel2video（含衣橱系统）/M7 嵌入+重试；对照演示页 docs/v17-benchmark.html；docs/usage/usage-v17.md）** + **v18 长视频质量（原 v14）✅（M1-M4 全绿，2026-10-31 关版，设计稿 docs/design/v18-design.md：M1 一致性资产底座 schema+场景锚+衣橱组装器+过渡选型 / M2 VACE flf2v 首尾帧驱动（M6_FLF=1，镜间边界 MAE clip 级 -87%/part 级 -72.6%）/ M3 一镜到底 utils/oneshot.py + auto --oneshot / M4 world.json+事件线收口；v4/v5 同题对照 + 30s oneshot 验收；docs/usage/usage-v18.md）** + **v19 视频链接二创（原 v16）✅（2026-11-02 关版，设计稿 docs/design/v19-design.md：M1 yt-dlp 合流+STT/多模态并行理解 → source.json / M2 LLM 改写解说词（流式+Levenshtein 防复述断言 <0.55）+重配音 / M3 画面改写 0-5 档 + v10 compose 组装 / M4 rework 子命令四通道（CLI/utils/agent generator.rework/API 异步 job）；utils/rework.py + tests/test_rework.py 15 项；音色黑名单实锤（jieshuo1 句首泄漏）→ 默认 cosy-default；docs/usage/usage-v19.md）** + **v19 烧录字幕消除（2026-11-02/03 补全，复用 v16 ProPainter）✅：rework --remove-sub off/auto/force；定位 = unlimited-ocr 多帧采样 ∪ 白字启发式兜底（⚠ OCR 输出为千分比规范坐标 0-999 须 /1000 映射，误判 1080 空间曾两轮返工；启发式对灰字深底板/夜景高亮失效）；part 级 704p 消除，终验文字行白像素峰 8 段归零；四通道接线 + 测试 23 项**+ **v20 生成中审核（边生边审，原 v21）✅（2026-11-04 关版：comfy_preview PreviewListener/WS latent2rgb 预览帧 + interrupt_if_running 归属校验 + live_audit_patch 实例级补丁（生成代码零改动）+ live_auditor 粗审节流（qwen3.8 review，≤3 次/镜）+ Pipeline wrapper 早停止损换 seed + 开关三通道（config v20_live_audit.enabled 默认 false / CLI --live-audit / API live_audit）+ UI 任务卡实时预览帧+verdict（GET /api/tasks/{id}/preview）；M2 同题对比 ON 仅 +3.7% 时长（粗审藏生成窗口）；M3 全链实跑 auto_20261104_153353（3 镜×3 粗审全 pass，UI 实时卡片验证）；**补验 2026-11-05**：15 次自然粗审全 pass（latent2rgb 看不出语义细节，粗审只挡大崩坏；终审抓到 score 2 实错=一人韩文横幅 vs 五人汉字横幅）；light 审片与下镜并行、fail 不重试（设计取舍，重试仅全量审片路径）；容器镜像须装全依赖（8894/9401 共库抢任务，缺 websockets 曾 shot1 即败）；docs/usage/usage-v20.md）**（v2 长视频 + v2.1 backlog + v3 M0-M7 + v4 M1-M6 + v5 M1-M4 + v6 M1-M4 + v7 前端 M1-M4 + v10 + t2c），**待开发**：无（v14 社交媒体 2026-11-05 由队友仓交付 ✅，不合入本仓；全里程碑收官）。**v21 交付形态 ✅ 关版 2026-11-05（原 v18，1.0.0）**：M0 doctor ✅ `core/doctor.py`+`vidance doctor`+`GET /api/doctor`（tests 13）/ M1 部署分档 ✅（五档 tier + Docker compose）/ M2 一键安装 ✅ `deploy/install.sh` 探测→选档→起容器→冒烟 / M3 面向用户细节 ✅ `vidance init` 向导+`core/diagnose.py` 失败自诊断（hints 附 tasks API+UI 💡）+`core/cleanup.py`（任务目录+保护运行中，旧 clean 漏任务目录已修）+/api/version|settings|clean+⚙ 系统区（tests 24）/ M4 ✅ `--version`+CHANGELOG.md+usage.md 按档用户手册+SKILL demo ×6（templates ×4+healing+showcase，实跑出片 yaml 旁）（2026-09-26 重排 + 2026-09-30 新增 v19-v21 + 2026-10-01 二次重排 + v13/v15 关版、v14 移交队友 + 2026-10-02 v16 M0-M4 + 2026-10-30 v17 关版 + 2026-10-31 v18 关版 + 2026-11-02 v19 关版 + 2026-11-04 v20 关版：括号内为原号）。

**版本路线**：v4 营销号流水线（fast/hot 爬图出片）→ v5 剪辑特效 → v6 prompt 多轮核实（ask + dialog API）→ v7 前端 agent WebUI（:8894/ui）→ **v8 前端增强**（资产库/分镜预览/进度可视化/时间线展示）→ **v9 API 标准化**（多 Vendor 适配/能力发现/用量限流/OpenAPI）→ **v10 拼接与特效**（OpenCut 时间线思路，后端 CLI 可被 LLM 调用）→ **v11 多智能体**（三层 Agent 解耦，原 v13）→ **v12 三排正交**（make 统一入口，原 v17）→ **v13 轻量化 ✅**（无模型四线：营销号/SVG/PPT/Blender 3D；模型加速按需后续，原 v15）→ **v14 接入社交媒体**（发布渠道 + IM 机器人网关，🔗 已移交队友，原 v11）→ **v15 LLM 生成 PPT ✅**（HTML 幻灯片→渲染 mp4/PDF，原 v20）→ **v16 视频处理编辑 ✅**（SAM2 分割/抠图/打码/inpaint/彩色多物体/YOLO 自动 Grounded-SAM/框提示 + 视频双向追踪 + v16.x 生成式编辑：M5 FLUX Fill 重绘/M6 Union ControlNet canny/M7 Wan2.1 VACE 参考图生视频/M8 Qwen-Image-Edit 指令式编辑，原 v19）→ **v17 整合开源仓库 ✅**（buffer 会话资产层/@引用/断点续跑 sha256 指纹/JSON 容错/RAG/五维提示词/剧本拆解 novel2video/嵌入/重试，原 v12，2026-10-30 关版）→ **v18 长视频质量**（关键帧驱动/一镜到底/层级一致性，原 v14）→ **v19 二创**（视频链接二创：改写解说/重配音/LUT/BGM + 烧录字幕消除 + 关键帧模式（静帧去字幕+Ken Burns+RIFE morph）+ 第一人称人称反转，原 v16）→ **v20 生成中审核 ✅**（tensor 边生边审：latent 预览粗审+早停止损，旁挂+开关默认关，原 v21，2026-11-04 关版）→ **v21 交付形态**（部署分档/一键安装，原 v18）。详见 docs/roadmap.md。

v1 角色锚流程：FLUX 生角色图 → TripoSplat 重建 3DGS → 每镜 RenderSplat 按角度渲染参考帧 → Wan I2V 生成。

**t2c 自然语言 → 命令**（2026-09-24 接入，见 docs/design/v-t2c.md）：
自建 agent_loop 的"翻译层"——用户中文口语经 mt5-small 微调模型（`t2c/model`，CPU 可跑）转成 Vidance 命令。链路：`/api/chat`（LLM 判意图，闲聊直接回 / 创作返回 `[[VIDEO:概念]]`）→ v6 dialog 多轮核实 → `POST /api/t2c`（`utils/t2c_server.py` 的 `translate(text)`）→ 得命令 → 前端展示 + ▶ 执行。网页端 `:8894/ui` 直接测；命令行 `python utils/t2c_server.py '帮我auto生成城市夜景'` → `python core/vidance.py auto "城市夜景"`。计划：全部指令（含 v10 剪辑）齐全后重训覆盖全量。



**v2 长视频**（M1-M5 全部完成）：
- **M1 RIFE 光流插帧**：镜头间光流过渡（rife_v4.26，multiplier=8，0.375s@24fps）
- **M2 镜头并行预取**：ThreadPool 并行预取 FLUX 参考帧 + TTS 配音（与 Wan I2V 串行不冲突）
- **M3 ffmpeg 调色**：6 种 3D LUT（cinematic/warm/cool/vintage/vivid/soft），纯 numpy 生成，LLM 自动选风格
- **M4 配乐 ducking**：5 种 BGM（calm/uplifting/mysterious/dramatic/playful），纯 numpy 合成，sidechaincompress ducking
- **M5 faster-whisper STT**：large-v3-turbo 模型，成片音频转写→SRT→重新烧录字幕

**v2.1 backlog**（全部完成）：
- `--duration N` 动态镜头数 + `--slowmo N` 全局慢动作 + per-shot `transition_out` + `concat` 子命令

**v3 2D→3D→新视角**（M0+M1+M2+M3+M4+M5+M6+M7 完成，M8 待开始）：
- **M0 headless 渲染** ✅：trimesh 5.1.0 + pyrender 0.1.45 + EGL 后端，4×4090 headless 渲染 GLB→IMAGE 成功
- **M1 Hunyuan3Dv2 mesh 重建** ✅：DiT turbo（4步,~61s）+ VAE + DINOv2-giant，doubao.jpg→257K verts GLB，pyrender 4 角度预览通过
- **M2 multiview** ✅：3 视角（front/left/back）裁剪自 doubao.jpg 三视图 → 206K verts GLB（~22s warm），aspect 1.69 vs 单图 1.02，主连通分量 63% vs 38%，多视角显著优于单图
- **M3 mesh_render 封装** ✅：`utils/mesh_render.py`（260行），3 层 API + 3-point lighting + depth-based alpha + 背景合成，与 splat_renderer API 对齐，8 项测试全通过（832×480 渲染 0.79s/张）
- **M4 场景锚** ✅：FLUX→Hunyuan3Dv2→mesh_render 全链路验证，2 场景（隔离木屋 238K verts + 雪原环境 411K verts），8 角度渲染一致性确认
- **M5 角色双路径** ✅：`--character-mode mesh` 接入 pipeline，`utils/hunyuan3d.py` 客户端（单图+多视角→GLB），`_build_character_anchor` + `_generate_scene_ref` mesh 分支，doubao.jpg→282K verts GLB 28.8s + 4 角度预览 + 合成参考帧验证通过
- **M6 资产库** ✅：`utils/asset_registry.py`（CRUD+模糊搜索+CLI），pipeline 集成（角色 mesh/3dgs 重建前查库复用 + 重建后自动入库），`--no-asset-reuse` flag，`.opencode/agents/asset.md` subagent，14 项测试全通过
- **M7 端到端联调** ✅：`auto --character-mode mesh` 全链路跑通（FLUX 三视图→Hunyuan3Dv2 multiview→mesh_render→Wan I2V→RIFE slowmo→LUT→BGM→合成），3 镜 12.8s 成片 `output/20260912_183520/final.mp4`。**修复**：RIFE slowmo（4帧→233帧，concat demuxer→image2 demuxer）、LLM 审查模型（claude-haiku-4-5 下架→qwen3.8-chat）、审查超时（60s→180s+retries=2）、multiview mesh（单图 Z=0.009 纸片→三视图 Z=1.56 真实3D）。审查系统生效：角色 score=3、Shot 2 score=3.2/4（retry）、Shot 3 score=6/5/5（retry）

**v4 营销号流水线**（M1-M6 完成；~~批量联调/无人值守~~ 已确认跳过；发布不做，人精选手动上传）：
- **M1 爬虫+选题** ✅：`utils/crawler.py`（B站 API+微博+知乎+百度+RSS+yt-dlp 多源热点抓取）+ `llm.scout_topics()`（热点→概念候选排序）+ `.opencode/agents/scout.md` subagent + `.opencode/skills/topic_scouting/SKILL.md`。端到端验证：45 条热点（B站/微博/知乎各 15）→ 5 个概念候选（9/8/8/7/7 分），概念有画面感且结合热点创意角度
- **M2 异步任务队列** ✅：`core/scheduler.py`（`TaskQueue` SQLite 持久化 + `Scheduler` 线程轮询 + CLI）+ `core/api_server.py`（FastAPI :8894，POST/GET/DELETE /api/tasks + /api/health + /api/scout + /api/dashboard）+ `core/dashboard.py`（自包含 HTML 仪表盘，base64 缩略图，30s auto-refresh）。`pipeline.py` + `vidance.py` 加 `--task-id` 参数。端到端验证：3 任务提交 → 串行执行（max_concurrent=1）→ 3 成片（柴犬 12.7s / 赛博朋克 11.4s / 小厨娘 11.9s），可视化产出 `output/dashboard.html` + `output/m2_results.html`
- **M3 声音克隆生产化** ✅：`utils/voice_clone.py`（B站搜索 API 随机 buvid3 过反爬 → yt-dlp 下载按 bvid 隔离 → faster-whisper VAD 切段（跳过纯 ♪ 器乐、长块取 8s 窗口、均分质量门 -32dB）→ 24kHz mono 16bit ffmpeg 转换 → STT 转写 prompt_text → 入库 voices/{name}/ 自动注册 cosy-{name} → 测试合成存 voice_samples/）。TTS server 加 `POST /voices/reload` 热加载（免重启注册新音色）。API server 加 `POST /api/clone_voice` 异步克隆端点 + `GET /api/voices`。端到端验证：3 音色克隆全通（xinwen1 新闻播音 / jieshuo1 影视解说 / jilupian1 纪录片，单音色 21-30s），STT 转写回验内容一致，注册音色可按名直接调用
- **M4 FunClip 智能裁剪** ✅：`utils/funclip.py`（FunASR `speech_paraformer-large-vad-punc` 转写 + 字级时间戳 + 字级聚合成句 + ffmpeg 时段裁剪拼接 + LLM 语义 keep/drop）。三子命令 CLI（transcribe/clip/smart）。**GPU 修复**：满卡（GPU0 被 H3 占满）连 CUDA context 都建不出来（`cudaMemGetInfo` 直接 OOM），`device='auto'` 逐卡探测跳过建不了 context 的卡并选空闲显存最多的卡。端到端验证：4 句水母剧本拼 12.6s 长音频，指令"只要讲光的句子" → LLM 保留 2 句（含语义含"点亮之光"的一句）drop 2 句 → 输出 3.88s，转写回验内容一致；CLI OOM 修复后 14 字全对
- **M5 素材爬取** ✅：`utils/asset_crawler.py`（必应图片 async 接口搜图下载 + magic bytes 校验 + md5 去重 + LLM concept→关键词 + incompetech BGM 按 feel 搜曲下载 loudnorm→bgm/{mood}.wav）+ 四子命令 CLI（keywords/images/refs/bgm）。**修正**：pieces.json 的时长字段是 `length`（HH:MM:SS 格式）非 duration；filename 自带 `.mp3` 后缀不可重复拼（拼重会 404）；百度图片 acjson 接口需真 cookie 已弃用，必应 `cn.bing.com/images/async` 直连可达。端到端验证：concept"雪山上的日出小狐狸"→LLM 3 关键词→6 张参考图（19-129KB）；`bgm epic --list` 5 首候选（58-62s）→ 爬取 epic.wav（61.4s 10.8MB loudnorm）；pieces.json 固化到 bgm/pieces.json
- **M6 快速营销号链路** ✅：`utils/fastline.py`（`FastLine`）+ `vidance.py fast/hot` 子命令——**跳过视频模型**：LLM 规划 N 段旁白+每段运镜（pan/zoom-in/zoom-out）→ 图片（`--images-source crawl` 必应爬图+**多模态相关性校验**自动删不相关图、不足 FLUX 补足；或 `flux` 逐段文生图；或 `--images` 自供）→ ffmpeg zoompan(Ken Burns) → 逐段 TTS → crossfade 拼接 → LUT/BGM/STT 复用 PostProcessor。**热搜来源**：`--source-topic`+`--trend-date` 写进 meta + 片头顶部 drawtext 角标（独立于字幕，不造成错位）。`--slowmo N` 另出 `final_slow.mp4`（RIFE，视频-only），原片 `final.mp4` 恒保留。**`hot` 子命令**：爬实时热点→LLM scout 自动选题→fast 一步到位。**FLUX 生图质量门**：`optimize_fastline_prompt()` 中文旁白→英文 FLUX prompt（修"塞中文生成无关图"），生成后 `assess_image_relevance` 审核贴合旁白、不过重生成≤2（实测背包青蛙 score=10 / 程序员删89TB 3图 9/7/9）。端到端验证：scout 从 40 条真实热点选"旅行青蛙停运"9 分，crawl 校验滤掉 3 张不相关图（医院/充电器/回收标志均 score=1.0）FLUX 补足；热搜角标+字幕 0s 对齐。**修正**：①`--bgm` choices 加 `epic`；②`_image_to_base64` 支持 RGBA/P/LA/PA 转 RGB（修 `cannot write mode P as JPEG`）；③RIFE slowmo 不带音轨（helper 仅重编码画面）；④**服务缺省兜底（2026-09-15）**：TTS 9880 不可用 → 静音音频兜底 + 打印 `⚠ [TTS 缺省]`（含启动提示）；爬图挂 → 转 FLUX，FLUX 挂 → 纯色渐变占位图（`_gen_placeholder_image`，带概念水印）+ `⚠ [图源/FLUX 缺省]`；plan_narration/select_lut/select_bgm 原有兜底不变——**GPU 服务全关时 fast 任务降级跑完出片不崩**（实测：Pexels 照常 + 静音 + 占位图 → 6.0s completed）

**v5 剪辑特效**（M1-M4 完成，2026-09-14）：
- **M1 特效库** ✅：`utils/effects.py`（8 种镜头内特效：flash/punch_in/glitch/grain_vignette/speed_ramp/freeze_zoom/wipe/zoom，纯 ffmpeg yuv420p）+ 单片段 CLI
- **M2 xfade 转场** ✅：`transition()` 双片段 xfade + `concat_with_transitions()` 单 filter_complex 链式 N 片段拼接（fade/slide/wipe/pixelize/circleopen 等 30+ 种）
- **M3 LLM 自动选** ✅：`llm.select_effects()` 按每镜内容/情绪选特效 + 镜头间转场（`fast/hot --effects auto`，pipeline 内 `apply_effects_to_clips` 施加，失败回退原片）
- **M4 端到端** ✅：`fast "夜色中城市霓虹与火光" --effects auto` 3 镜 → LLM 选 glitch/grain_vignette/freeze_zoom → 9.0s 成片；meta 记录 effects/transitions。xfade 链式拼接 3 clip 5.2s 验证通过
- **修正**：①flash 用 `fade=in` 纯色淡入（修 eq/drawbox 语法错）；②glitch 去 rgbashift（该 ffmpeg 无此滤镜）改 noise+hue 抖动；③wipe/zoom warp 表达式用 `t`/`on` 正确写法

**v6 prompt 多轮核实**（M1-M4 完成，2026-09-14；2026-09-15 修复多轮循环）：
- **M1 完整度评估** ✅：`llm.assess_completeness()` 6 维（主体/场景/情绪/风格/时长/镜头感）+ missing 列表 + 追问建议（异常兜底当 complete）。**口径**：subject/scene/emotion 必填需明确描述（仅名词隐含推测不算）；style/duration/shot 也纳入追问——**全 6 维齐才 COMPLETE**（prompt 靠多轮追问变长变详细）；temperature=0.1
- **M2 对话状态机** ✅：`utils/dialog.py`（DialogManager，OPEN/COLLECTING/COMPLETE/LOCKED，≤3 轮防死循环，SQLite `output/tasks.sqlite` dialogs 表）
- **M3 CLI `ask`** ✅：`vidance.py ask "概念"` 交互多轮追问 → 增强概念（`--out` 存文件）；**每轮把当前问题逐条问完合并成一条 reply**（`；`拼接）→ 一次重评；管道答案实测通过；`dm.locked_concept` 拼接轮次回答（"随便"跳过）
- **M4 API 三端点** ✅：`core/api_server.py` 加 `POST /api/dialog/start`（返回 missing/questions）+ `GET /api/dialog/{dialog_id}` + `POST /api/dialog/{dialog_id}/reply`（每轮返回增强 concept），供 v7 前端调用；start/reply curl 实测通过
- **修复（2026-09-15）**：①cmd_ask idx 跨轮累加导致只问一条就退出 → 重构为每轮批量问完再 reply；②选填维度被当必填判 → missing=[] 卡 COLLECTING → 只以必填维度判 COMPLETE；③评估口径"已隐含算不缺"→"明确描述才算"（temperature 0.3→0.1）；④停止条件过松（必填 3 维齐即 COMPLETE，2 问就停 prompt 长不起来）→ 改为**全 6 维齐才 COMPLETE**，style/duration/shot 也追问，概念经 2-3 轮逐步变长
- 不做自动补全（宁可多问）；≤3 轮 LOCKED 强制放行

**v7 前端 agent WebUI**（M1-M4 代码完成，2026-09-15；浏览器渲染+成片端到端待 GPU 恢复验证）：
- **M1 后端端点** ✅：`core/api_server.py` 加 `GET /api/video/{task_id}`（视频流 FileResponse）+ `GET /api/options`（音色/LUT/BGM/特效/运镜枚举）+ `GET /api/tools`（**15 命令**+参数 schema）+ `POST /api/tool/{name}`（统一分发，shlex 解析 `--key value`/`-n N`/位置参数）+ /ui StaticFiles；`scheduler.py _run_task` 加 **mode 分发**（auto/fast/hot 映射 vidance.py 子命令参数）；TaskSubmit 加 mode/images_source/images_count/effects/top_each/account 字段
- **M2 对话+/命令补全** ✅：`ui/index.html`（自包含 21KB，零 npm）三栏布局（左工具/任务边栏+顶部画布+右下发框）；`/` 弹层（↑↓/Tab/Enter 选择，参数区不弹）；自然语言 → v6 dialog
- **M3 画布** ✅：任务卡片 2s 轮询（进度条+stage+error）+ video 卡片（completed 自动嵌 `<video controls src=/api/video/{id}>`）+ 左栏任务列表（点击回看/轮询）
- **M4 ask+scout 接洽** ✅：/ask → 问题渲染 → 输入续聊（/api/dialog/{id}/reply）→ COMPLETE 后增强概念 chip 一键 `/fast`；scout 候选分数展示；voices/clip(异步轮询)/help 分发
- **验证**：后端 curl 实测（tools **15 命令** 全 dispatch /options/video 流 1.7MB/ask/voices/help/video 分发）；JS node --check 通过；/ui 200（21KB）；GPU 停机期间成片链路未测。新增查询/维护类命令全零 GPU（luts/moods/tasks/status/trends(爬热点不选题)/clean(默认 keep 10)）

**v1.1 改进**：
- **I2V 修复**：`WanImageToVideo` → `Wan22ImageToVideoLatent`（Wan 2.2 原生 48ch latent + noise_mask inpainting），首帧与参考图相关性 0.99+
- **character-mode 开关**：`auto`（默认，3DGS 审查不过自动降级 flux）/ `3dgs` / `mesh`（Hunyuan3Dv2→GLB→mesh_render）/ `flux`（每镜 FLUX 直接生成角色+场景图，不重建 3D）
- **3DGS 位姿修复**：PCA 自动对齐角色主轴到垂直 + 裁剪接地合成（脚踩地不悬浮）
- **3DGS 渲染优化**：飞点过滤 + 超采样渲染 + 大高斯参数，表面更平滑噪声更少
- **角色位姿修复**：FLUX 角色 prompt 强调 "standing upright on the ground"，审查加 pose 维度
- 不传 `--character` 时走 v0 纯 T2V

## 目录结构

```
vidance/
├── opencode.json              # opencode 配置（agents + permissions）
├── AGENTS.md                  # 本文件
├── config/config.json         # 运行时配置（API key、引擎地址、模型名、音色）
├── core/
│   ├── vidance.py             # 统一 CLI 入口（auto/custom/quick/concat/compose/svg/make）
│   ├── pipeline.py            # auto 模式流水线主控（内部模块）
│   ├── custom_gen.py          # custom 模式 H3 ref2va 生成（内部模块）
│   ├── postprocess.py         # 共享后处理（RIFE/LUT/BGM/STT）
│   ├── narration.py           # v12（原 v17）配音/字幕单一实现（Narrator：TTS 三级降级+静音兜底+SRT）
│   ├── preflight.py           # v17（原 v12）任务预检（硬依赖拦截/可降级警示；5 子命令 --no-preflight；6/6 测试）
│   ├── scheduler.py           # v4 异步任务队列（TaskQueue SQLite + Scheduler 线程轮询）
│   ├── api_server.py          # v4 FastAPI 服务（:8894，任务提交/查询/仪表盘/选题/克隆/裁剪）
│   └── dashboard.py           # v4 HTML 仪表盘生成（队列统计+缩略图+选题批次）
├── utils/
│   ├── comfy_api.py           # ComfyUI HTTP 客户端（T2V/I2V/TripoSplat/FLUX T2I/H3 ref2va）
│   ├── llm.py                 # USTC LLM 客户端（编剧/prompt优化/审片，含图片缩放+重试）
│   ├── tts.py                 # TTS 客户端（双引擎：edge-tts + CosyVoice）
│   ├── tts_server.py          # TTS FastAPI 服务（双引擎，GPU2:9880）
│   ├── splat_renderer.py      # 3DGS PLY 多角度渲染器（render_splat_at_angle + composite_bg）
│   ├── ffmpeg_tools.py        # 抽帧/SRT/合成（含 LUT 调色 + BGM ducking）
│   ├── rife.py                # v2 RIFE 插帧客户端（镜头间过渡 + slowmo）
│   ├── gen_luts.py            # v2 生成 3D LUT .cube 文件（6 种风格）
│   ├── music.py               # v2 生成环境配乐 BGM（5 种风格，numpy 合成）
│   ├── stt.py                 # v2 faster-whisper STT 转写（字幕兜底）
│   ├── mesh_render.py         # v3 headless mesh 渲染器（pyrender+EGL，M3 已封装）
│   ├── hunyuan3d.py           # v3 Hunyuan3Dv2 重建客户端（单图+多视角→GLB，M5 已封装）
│   ├── asset_registry.py      # v3 资产库管理（CRUD+模糊搜索+CLI，M6 已封装）
│   ├── crawler.py             # v4 热点爬虫（B站API+微博+知乎+百度+RSS+yt-dlp，M1 已封装）
│   ├── voice_clone.py         # v4 声音克隆生产化（B站搜索+VAD切段+STT转写+音色注册，M3 已封装）
│   ├── funclip.py             # v4 FunClip 智能裁剪（FunASR字级时间戳+LLM语义keep/drop，M4 已封装）
│   ├── asset_crawler.py       # v4 素材爬取（Pexels 图源首选 + 必应兜底 + LLM关键词 + incompetech BGM，M5 已封装）
│   ├── fastline.py            # v4 M6 快速营销号链路（图片+zoompan 运镜+RIFE，跳过视频模型，M6 已封装）
│   ├── effects.py             # v5 剪辑特效（8 种镜头内特效 + xfade 链式转场，M1-M4 已实现）
│   ├── dialog.py              # v6 prompt 多轮核实状态机（DialogManager，SQLite，M1-M4 已实现）
│   ├── compose.py             # v10 时间线拼接与特效（OpenCut 思路，后端 CLI；M1-M8 已实现：关键帧/掩码/贴纸轨/split）
│   ├── buffer.py              # v17（原 v12）M1 会话缓冲区 BufferManager（sanitize/围栏/搜索游标/TTL 清理；26/26）
│   ├── retry.py               # v17（原 v12）M7 tenacity 重试三策略（llm/tts/comfy；4xx 直抛；13/13）
│   ├── embed_index.py         # v17（原 v12）M7 MiniLM ONNX 本地嵌入 EmbedIndex（暴力余弦+npz 持久化；13/13）
│   ├── subtitle_correct.py    # v17（原 v12）MPT 借鉴字幕 Levenshtein 纠正（幻觉丢弃，接 run_stt；20/20）
│   ├── material_cache.py      # v17（原 v12）MPT 借鉴素材 URL-md5 缓存+搜索 24h TTL（接 asset_crawler；20/20）
│   ├── rag.py                 # v17（原 v12）M5b RAG 索引/检索（文档+小说分章+人物卡；v18 加 add_chunks 显式分块——事件线每弧一卡）
│   ├── t2c_server.py          # t2c 推理封装（translate(text)→command，进程内单例/可选 HTTP）
│   ├── svg_llm.py             # v13（原 v15）概念→LLM→动效 SVG（S1）
│   ├── svg_pipeline.py        # v13（原 v15）SVG→mp4（无头浏览器逐帧渲染，纯 CPU；S2 单帧/S3 抽帧/S4 成片）
│   ├── sam_edit.py            # v16（原 v19）SAM2 编辑：分割/抠图/换底/打码/inpaint/彩色多物体/YOLO 自动/框提示 + 视频双向追踪 + qwen_edit 指令式（GPU 档）
 │   ├── ppt_llm.py             # v15（原 v20）概念→LLM 规划 deck JSON→HTML 幻灯片（模板渲染 + svg_chart bar/line/pie）
 │   ├── ppt_pipeline.py        # v15（原 v20）deck→mp4/PDF/PNG（PptLine 多形态交付，页间 xfade + TTS 旁白，纯 CPU）
 │   ├── blender_llm.py         # v13 blender 简单版：概念→LLM 规划 3D 场景 JSON（模板 title3d/shapes/bars3d + 配色 + 物体/材质/关键帧规范化）
 │   ├── blender_pipeline.py    # v13 blender 简单版：bpy 5.0 进程内建场景→EEVEE 逐帧渲染→ffmpeg 拼帧→TTS→mp4（BlenderLine）
 │   ├── poster_llm.py          # v22 poster 线：概念→LLM 规划海报 JSON（标题/标语/底板提示词/生灵分区，zone 白名单+规范化）
 │   ├── poster_pipeline.py     # v22 poster 线：FLUX 底板→Grounded-SAM 抠图（亮度键控降级）→PIL 参数化合成→jpg（PosterLine）
│   ├── h3_prompt_video.py     # 整段式 prompt + 参考图 → H3 ref2va 单镜（原生音频直出）
│   ├── oneshot.py             # v18（原 v14）一镜到底（✅ 链式 I2V 末帧回灌 + LLM 运镜链 + 拼缝断言；auto --oneshot --duration N）
│   ├── notify/                # v14（原 v11）社交媒体/IM 网关（base/wecom/feishu/dingtalk/factory；🎯 待实现）
│   ├── luts/                  # v2 LUT 文件目录（cinematic/warm/cool/vintage/vivid/soft .cube）
│   └── workflows/
│       ├── wan_t2v.json       # Wan T2V workflow 模板
│       ├── wan_i2v.json       # Wan I2V workflow 模板（12 节点，Wan22ImageToVideoLatent）
│       ├── triposplat.json    # TripoSplat 单图→PLY workflow（13 节点）
│       ├── flux_t2i.json      # FLUX T2I workflow 模板（10 节点）
│       ├── rife_transition.json  # v2 RIFE 插帧 workflow（7 节点）
│       ├── hunyuan3d_single.json  # v3 Hunyuan3Dv2 单图→mesh workflow（M1 验证）
│       └── hunyuan3d_multiview.json  # v3 Hunyuan3Dv2 多视角→mesh workflow（M2 验证）
├── agents/                    # v11 多智能体（原 v13）：D/G/P/V 物理分层 + 薄包装（docs/design/v11-design.md）
│   ├── base.py                # TaskResult + @register 注册表 + run_agent（计时/兜底/落盘）
│   ├── blackboard.py          # agent_runs 黑板（复用 output/tasks.sqlite）
│   ├── runtime.py             # load_all + run_chain（${ctx.key} 引用产物）
│   ├── director/              # D：agents.py(scriptwrite/scout/三选) + tools/dialog.py
│   ├── generator/             # G：agents.py(svg/fast/wan_t2v) + tools/（comfy_api/fastline/svg系/rife/3d系/vendor…）
│   ├── post/                  # P：agents.py(tts/compose/lut/bgm/字幕/stt/fx/transition) + tools/（effects/compose/…）
│   ├── audit/                 # V：agents.py(审片4件+review_ensemble 多票) + tools/
│   └── common/                # 共享：tools/（llm/tts/config_loader/crawler/爬虫系/voice_clone/t2c_server）
│   （utils/ 原 27 模块均留薄壳转发，旧 import/CLI 零破坏；tts_server.py 与数据目录不迁）
├── t2c/                       # t2c 自然语言→命令（mt5-small 微调模型 + 推理脚本 + README）
├── deploy/                    # v21（原 v18）部署档（VIDANCE_TIER=none|flux|wan|h3|full；Dockerfile + Dockerfile.comfyui + docker-compose.yml profiles 五档 + README；API 缺省挂 9400）
├── dist/images/               # 离线交付镜像包（docker save 产物 latest/rag/update.tar.gz，*.tar.gz 已 gitignore；五档共用 latest 一个镜像）
├── ui/                        # v7 前端（index.html 自包含，零 npm，:8894/ui 访问）
├── assets/                    # 项目图片（v0-v9 演进截图）；答辩 PPT + ppt_media/ 提取素材已 gitignore（仅本地暂存，精选后入 docs/）
├── docs/assets/               # README 展示素材（hero.gif + demo 缩略图 + UI 截图）
├── voices/                    # 自定义 CosyVoice 克隆音色素材目录
├── bgm/                       # v2 自定义 BGM 素材目录（放 {mood}.wav 自动使用）
├── .opencode/
│   ├── agents/{director,reviewer,asset,scout}.md
│   └── skills/{scriptwriting,review,topic_scouting,novel_to_video}/SKILL.md
├── SKILL/                     # v17（原 v12）技能资产（双位置之一，命令层）
│   ├── templates/             # M5 五维提示词模板（cinematic/documentary/anime90s/guofeng .yaml，落盘即被发现）
│   └── commands/novel2video/  # M6 小说→成片管线脚本（m6_breakdown_test/m6_render_v3/m6_archive_buffer/m6_wardrobe_test + README）
├── docs/                      # 文档（roadmap + reports；usage/ 使用指南 + design/ 设计文档 + research/ 调研 + instructions/ 命令库与部署 + example/ 示例 + archive/ 历史稿）
│   ├── usage/                 # 使用指南（usage.md 主入口 + usage-v0/v1/v2/v3/v4/v6/v7/v10/v-svg.md 分版本小工具）
│   ├── design/                # 设计文档（v0-v18 design + v12-modules + hierarchy + v-t2c + v-svg-pipeline）
│   ├── research/              # 调研（mpt-research + bigbanana-research）
│   └── instructions/          # 命令库（commands.json + compose 指令库）+ 部署（deploy-tiers/deployed-models）
├── voice_samples/ → /mnt/dataset/...  # 音色试听样本（软链）
└── output/                    # 成片 + 元数据（真实目录，任务=output/{task_id}/，成片 final.mp4）
```

## 运行命令

### 统一入口 `core/vidance.py`（推荐）

四个子命令：`auto`（LLM 编剧+生成+后处理）、`custom`（参考图+脚本→H3→后处理）、`quick`（纯 T2V）、`concat`（多视频拼接）。

```bash
# ── auto：概念 → LLM 编剧 → Wan/FLUX 生成 → 后处理 ──
# v2 全功能：RIFE 过渡 + 并行预取 + LUT 调色 + BGM ducking + STT 字幕
python core/vidance.py auto "雪山日出：小狐狸的冒险" --character "红色小狐狸" --character-mode flux --stt

# auto 模式（默认 3DGS→flux 降级）
python core/vidance.py auto "一只猫在月球上跳舞" --character "穿宇航服的白猫"

# 指定调色风格和配乐 mood
python core/vidance.py auto "深海探险" --character "蓝色水母" --character-mode flux --lut cool --bgm mysterious

# 长片模式（动态镜头数，目标 60s → ~15 镜）
python core/vidance.py auto "深海探险" --character "蓝色水母" --character-mode flux --duration 60

# 全局慢动作（所有镜头 2x 慢放）
python core/vidance.py auto "概念" --character "角色" --slowmo 2

# 禁用部分功能
python core/vidance.py auto "概念" --character "角色" --no-rife --no-color --no-bgm

# ── custom：参考图 + 预写脚本 → H3 ref2va → 后处理 ──
python core/vidance.py custom --ref input/doubao.jpg --ref input/naiwa.jpg --script input/prompt1.txt

# custom + 后处理
python core/vidance.py custom --ref input/doubao.jpg --ref input/naiwa.jpg --script input/prompt1.txt --lut cinematic --bgm dramatic --stt

# custom 高保真模式（2048px 参考图，慢 2-3x）
python core/vidance.py custom --ref input/doubao.jpg --script input/prompt1.txt --ref-image-size max

# ── quick：纯 T2V，无角色无后处理 ──
python core/vidance.py quick "一只猫在月球上跳舞"

# ── concat：多视频拼接 ──
# 硬切拼接（ffmpeg stream copy，最快）
python core/vidance.py concat clip1.mp4 clip2.mp4 clip3.mp4 -o merged.mp4 --transition cut
# RIFE 光流过渡（需 GPU2 ComfyUI 8189 在线）
python core/vidance.py concat clip1.mp4 clip2.mp4 clip3.mp4 -o merged.mp4 --transition rife
# 交叉淡化
python core/vidance.py concat clip1.mp4 clip2.mp4 -o merged.mp4 --transition crossfade --crossfade-duration 0.5
```

**参数速查**：

| 参数 | auto | custom | quick | concat | 说明 |
|------|:----:|:------:|:-----:|:------:|------|
| `concept` (位置参数) | ✓ | — | ✓ | — | 视频概念（中文） |
| `videos` (位置参数) | — | — | — | ✓ | 待拼接视频文件列表 |
| `-o/--output` | ✓ | ✓ | ✓ | ✓ | 输出路径（相对→output_dir） |
| `--character` | ✓ | — | — | — | 角色描述（中文） |
| `--character-mode` | ✓ | — | — | — | auto/3dgs/mesh/flux |
| `--no-asset-reuse` | ✓ | — | — | — | 禁用资产库复用 |
| `--voice` | ✓ | — | ✓ | — | TTS 音色 |
| `--duration` | ✓ | — | — | — | 目标总时长（秒），动态镜头数 |
| `--slowmo` | ✓ | — | — | — | 全局慢动作倍率 |
| `--ref` | — | ✓ (可重复) | — | — | 角色参考图 |
| `--script` | — | ✓ | — | — | 分镜脚本路径 |
| `--ref-image-size` | — | ✓ | — | — | match/max |
| `--transition` | — | — | — | ✓ | cut/rife/crossfade |
| `--crossfade-duration` | — | — | — | ✓ | 交叉淡化时长 |
| `--lut` | ✓ | ✓ | — | — | LUT 风格 |
| `--no-color` | ✓ | ✓ | — | — | 禁用调色 |
| `--bgm` | ✓ | ✓ | — | — | BGM mood |
| `--no-bgm` | ✓ | ✓ | — | — | 禁用 BGM |
| `--no-rife` | ✓ | ✓ | — | — | 禁用 RIFE 过渡 |
| `--stt` | ✓ | ✓ | — | — | STT 字幕对齐 |

# ── svg：v13（原 v15）SVG 流水线（概念→LLM 生成 SVG→逐帧渲染→mp4，纯 CPU）──
python core/vidance.py svg --concept "鹈鹕骑自行车"                    # 一键
python core/vidance.py svg --svg output/svg/pelican_bike.svg -o output/svg_demo/out.mp4 --duration 3
python core/vidance.py svg --svg scene.svg --still --at 1.5           # 单帧调试
python core/vidance.py svg --svg scene.svg --frames                    # 抽帧成 PNG 序列

# ── ppt：v15（原 v20）PPT 流水线（概念→LLM 规划→HTML 幻灯片→渲染 mp4/PDF/PNG，纯 CPU）──
python core/vidance.py ppt "Vidance 项目介绍" --video                  # 一键：deck.html + final.mp4（TTS 旁白）
python core/vidance.py ppt "季度总结" --say "第一页旁白" --say "第二页旁白" --video -n 2  # 手动大纲逐页旁白
python core/vidance.py ppt --deck output/ppt_xxx/deck.html --video --pdf --pngs       # 渲染模式：多形态交付
python core/vidance.py ppt "主题" --pdf -n 5 --transition wipe --voice cosy-default    # PDF 5 页 + 指定转场/音色
python core/vidance.py blender3d "Vidance 3D 展示" --duration 6 --voice cosy-default   # 一键：LLM 规划 3D 场景 + bpy EEVEE 渲染 + TTS → final.mp4
python core/vidance.py blender3d --scene output/blender3d_xxx/scene.json              # 渲染模式：按 scene.json 重建渲染

# ── poster：v22 宣传海报（概念→LLM 规划→FLUX 底板+SAM 抠图→PIL 合成→jpg）──
python core/vidance.py poster "紫色雨夜霓虹月亮下的红蓝猫" --title VIDANCE --tagline "从一句话，到一整部片"   # 一键：output/poster*/poster.jpg
python core/vidance.py poster "主题" --url github.com/x/vidance --qr-url https://github.com/x/vidance       # 页脚双 URL + 右下角 QR
python core/vidance.py poster --plan output/poster_xxx/plan.json --bg bg.png --creatures c1.png,c2.png      # 渲染模式：现成底板/生灵迭代重排
python agents/generator/tools/poster_llm.py "主题" -o /tmp/plan.json                                       # 单步：只出 JSON 规划

# ── edit：v16（原 v19）SAM2 编辑（图七模式 / 视频双向追踪；GPU 档）──
python core/vidance.py edit cutout 图.jpg --point 311,175 -o out.png                  # 抠主体 → 透明 PNG（省略 --point = 自动主体）
python core/vidance.py edit inpaint 图.jpg --point x,y -o out.png                     # 去水印/局部替换（cv2 TELEA）
python core/vidance.py edit mosaic 图.jpg --point x,y --mode pixel                    # 区域打码（pixel/blur）
python core/vidance.py edit replace_bg 图.jpg --point x,y --bg blur                   # 换背景（纯色 hex 或 blur）
python core/vidance.py edit visualize 图.jpg                                          # 彩色多物体可视化（SAM demo 风格，省略 --point 自动）
python core/vidance.py edit visualize 图.jpg --yolo --classes "cat,dog"               # YOLO 自动检测→SAM 框提示（Grounded-SAM，标签绘制）
python core/vidance.py edit visualize 图.jpg --box "x1,y1,x2,y2;x1,y1,x2,y2"          # 框提示多物体（大物体比点准，盆栽 17.5%→46%）
python core/vidance.py edit video in.mp4 --point x,y --op mosaic -o out.mp4           # 视频传播：首帧点提示逐帧打码/换底
python core/vidance.py edit video in.mp4 --point "x1,y1;x2,y2" --op color             # 视频彩色多物体（每点独立追踪一色）
python core/vidance.py edit video in.mp4 --point "x1,y1;x2,y2" --op color --frame 30  # 提示帧 30 起双向传播（两动物同框帧更准）
python core/vidance.py edit video in.mp4 --yolo --frame 30 --op color                 # YOLO 检测帧→框提示→双向追踪
# ── edit 生成式增强（v16.x M5-M8；需 flux 8192 / wan 8189 在线）──
python core/vidance.py edit inpaint 图.jpg --box "x1,y1,x2,y2" --engine flux --prompt "a wooden table" -o out.png   # M5 Fill mask 内重绘（--point/--box/--yolo 均可）
python core/vidance.py edit replace_bg 图.jpg --box "x1,y1,x2,y2" --engine flux --prompt "a sunny beach" -o out.png # M5 生成式换底（mask 反转）
python core/vidance.py edit inpaint 图.jpg --box "x1,y1,x2,y2" --engine flux --prompt "a golden retriever puppy" --controlnet canny --controlnet-strength 0.55 -o out.png  # M6 结构保持改物种
python core/vidance.py vace ref.png "a dog running on grass" --length 81 -o out.mp4   # M7 VACE 参考图生视频（480x832@16fps）
python core/vidance.py edit instruct 图.jpg --prompt "把猫换成狗" -o out.png           # M8 指令式编辑（Qwen-Image-Edit，中文指令，无需 mask）

> 旧入口 `python core/pipeline.py ...` 和 `python core/custom_gen.py ...` 仍可用（向后兼容），但推荐使用 `vidance.py`。

### 启动模型服务（推荐：一键脚本）

```bash
cd /mnt/disk_sdb/zxy/vidance && ./start_services.sh          # 启动默认集（h3/wan/flux/tts/api）
./start_services.sh start h3d        # 额外启动 Hunyuan3Dv2（v3 mesh 用）
./start_services.sh stop             # 停止全部
./start_services.sh restart          # 重启
./start_services.sh status           # 端口/进程/显存
./start_services.sh test             # 逐服务连通 + LLM + TTS 合成自检
./start_services.sh logs tts         # 跟踪日志
```
> 脚本头部有完整注释（服务↔端口↔GPU 对应、ComfyUI 禁 `--cuda-device`、edge-tts 外网问题等）。
> 端口：h3 8188(GPU0) / wan 8189(GPU2) / flux 8192(GPU3) / hunyuan 8190(GPU3，与 flux 互斥) / h3d 8193(GPU1) / tts 9880(GPU2) / api 8894(CPU)。
> 模型按需加载，ComfyUI 启动只占几百 M；TTS 启动即加载 CosyVoice（约 28s）。

### 启动 TTS 服务（手动，脚本等价）
```bash
conda activate cosyvoice
CUDA_VISIBLE_DEVICES=2 TTS_FP16=1 python utils/tts_server.py &
```

### 单条测试命令（验证服务是否正常）
```bash
# ComfyUI 实例（返回 200/JSON 即可达）
curl -s -o /dev/null -w "8189 wan: %{http_code}\n" http://127.0.0.1:8189/
curl -s -o /dev/null -w "8192 flux: %{http_code}\n" http://127.0.0.1:8192/
curl -s -o /dev/null -w "8188 h3: %{http_code}\n" http://127.0.0.1:8188/

# TTS 健康 + 合成（返回 {"audio":"<base64 wav>"} 即成功）
curl -s http://127.0.0.1:9880/health
curl -s -X POST http://127.0.0.1:9880/tts -H 'Content-Type: application/json' \
  -d '{"text":"测试一下声音是否正常","voice":"cosy-default"}' | head -c 120
# edge-* 需外网；连不上（Connection timeout to speech.platform.bing.com）就改用 cosy-* 本地音色

# Vidance API + UI
curl -s http://127.0.0.1:8894/api/health
curl -s -o /dev/null -w "ui: %{http_code}\n" http://127.0.0.1:8894/ui

# 端到端快速出片（本地音色，绕开 edge 外网问题；-n ≤5；全服务在线才出真声真图）
python core/vidance.py fast "深夜灯塔的故事" -n 2 --voice cosy-jieshuo1
```

### 单步操作
```bash
# 编剧
python utils/llm.py --concept "概念"

# T2V 生成
python utils/comfy_api.py "english prompt" -o output/clips/shot_1.mp4

# TTS 配音（列出所有音色）
python utils/tts.py --list-voices

# TTS 配音（指定音色，edge-* 或 cosy-*）
python utils/tts.py "中文旁白" -v edge-moe -o output/clips/shot_1.wav

# 抽帧
python utils/ffmpeg_tools.py frames output/clips/shot_1.mp4 -n 4

# v4 热点爬虫
python utils/crawler.py --top 20
python utils/crawler.py --source bilibili --top 10
python utils/crawler.py --top 20 -o output/hot_topics.json

# v4 Scout 选题
python -c "
from utils.crawler import Crawler
from utils.llm import LLMClient
topics = Crawler().fetch_hot_topics(top_per_source=20)
candidates = LLMClient().scout_topics(topics, account_type='影视解说', n_candidates=5)
for c in candidates:
    print(f'[{c[\"predicted_score\"]}] {c[\"concept\"]}')
"

# v4 异步任务队列
# 启动 API server（含调度器，max_concurrent=1）
python core/api_server.py --port 8894

# 提交任务（CLI）
python core/scheduler.py submit "一只猫在月球上跳舞" --character "穿宇航服的白猫" --character-mode flux
# 提交任务（API）
curl -X POST http://127.0.0.1:8894/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"concept":"深海探险","character":"蓝色水母","character_mode":"flux"}'

# 查看队列
python core/scheduler.py list
curl http://127.0.0.1:8894/api/tasks | python -m json.tool

# 查看任务状态
python core/scheduler.py status <task_id>
curl http://127.0.0.1:8894/api/tasks/<task_id>

# 生成仪表盘
python core/scheduler.py dashboard -o output/dashboard.html
# 或访问 http://127.0.0.1:8894/api/dashboard

# v4 声音克隆生产化
# 搜索人声源（B站）
python utils/voice_clone.py search --keyword 新闻播报 --top 10
# 完整克隆流水线（搜索→下载→VAD切段→转写→注册→测试合成）
python utils/voice_clone.py clone --keyword 新闻播报 --name xinwen1 --desc "新闻播音-男声"
# 测试已注册音色（样本存 voice_samples/）
python utils/voice_clone.py test --name xinwen1
# 列出已注册音色
python utils/voice_clone.py list
# 热加载新音色（免重启 TTS server）
curl -X POST http://127.0.0.1:9880/voices/reload
# API 异步克隆（提交后轮询 /api/clone_voice/{job_id}）
curl -X POST http://127.0.0.1:8894/api/clone_voice \
  -H 'Content-Type: application/json' \
  -d '{"keyword":"纪录片解说","name":"jilupian1","desc":"纪录片-男声"}'
```

## TTS 音色规范

音色按前缀路由引擎（服务在 9880）：

| 前缀 | 引擎 | 示例 |
|------|------|------|
| `edge-*` | edge-tts（微软在线，自然） | `edge-xiaoxiao` 晓晓 / `edge-moe` 萌系高音 / `edge-family` 家人们风 |
| `cosy-*` | CosyVoice（本地 GPU，可克隆） | `cosy-default` / `cosy-cross` |
| `cosy-<自定义>` | CosyVoice 自定义克隆 | `voices/<名>/prompt.wav` + `meta.json`（prompt_text/desc）自动注册，或 `utils/voice_clone.py clone` 全自动爬取克隆；新增后 `POST /voices/reload` 热加载 |

试听样本：`vidance/voice_samples/`（17 个 wav）。默认音色 `edge-moe`（config.json，萌系高音-哈基米风）。

## 服务端口

| 服务 | 端口 | GPU | 环境 |
|------|------|-----|------|
| MiniMax-H3 ref2va (ComfyUI) | 8188 | GPU0 | comfyui |
| Hunyuan3Dv2 turbo (ComfyUI) | 8193 | GPU1 | comfyui |
| Wan T2V/I2V + RIFE (ComfyUI) | 8189 | GPU2 | comfyui |
| HunyuanVideo (ComfyUI) | 8190 | GPU3 | comfyui |
| FLUX + TripoSplat (ComfyUI) | 8192 | — | comfyui |
| SDXL (ComfyUI) | 8191 | — | comfyui |
| TTS 双引擎 (edge-tts + CosyVoice) | 9880 | GPU2 | cosyvoice |
| Vidance API (任务队列 + 仪表盘 + v6/v7) | 8894 | — | comfyui |
| Vidance WebUI (v7 前端) | 8894/ui | — | comfyui（浏览器访问） |

> H3 (8188) 独占 GPU0，用于 custom 模式参考图条件视频生成。模型按需加载，首次 workflow 触发后占 ~46G。
> Hunyuan3Dv2 (8193) 独占 GPU1，v3 3D 重建引擎。
> Wan+RIFE (8189) 独占 GPU2，auto/quick 模式视频生成。
> HunyuanVideo (8190) 独占 GPU3，T2V 备选。
> FLUX(8192)/SDXL(8191) **已停**，需要时重启（FLUX 需找空卡或与 H3 互斥）。
> ⚠️ ComfyUI 启动**不能加 `--cuda-device`**，否则会覆盖 `CUDA_VISIBLE_DEVICES` 环境变量（main.py:87 逻辑）。正确做法：`CUDA_VISIBLE_DEVICES=N python main.py --listen 127.0.0.1 --port XXXX`。

## 关键约定

0. **统一产出目录**：一切成片/音频/GLB 等产物落 `output/{时间戳…}/`（任务=`output/{task_id}/`，Agent 缺省=`output/agent_{ts}_{agent名}/`，svg=`output/svg{ts}/`；config `output_dir` 为唯一根）。`/tmp` 只放临时中间文件。Agent 缺省路径由 `agents/base.py::default_out()` 统一实现

1. **随机 seed**：每次 T2V/I2V 生成必须用随机 seed（ComfyUI 缓存命中问题）
2. **每镜 ≤5s**：Wan 单次上限 121 帧≈5s@24fps
3. **旁白字数**：duration × 4 字（中文约 4 字/秒）
4. **审片阈值**：综合分 ≥7 通过，最多重试 2 次，取最高分兜底
5. **时长对齐**：成片按配音时长为准，画面不足定格末帧
6. **元数据完整**：每次任务记录 meta.json（脚本/prompt/seed/审片/时间戳）
7. **角色锚流程**（v1.1 + v3）：`--character` 传入角色描述 → FLUX 生角色参考图 → 按 `--character-mode` 分流：
   - `flux`：每镜 FLUX 直接生成角色+场景完整图 → Wan I2V（不重建 3D，质量最稳定）
   - `3dgs`：FLUX 图 → TripoSplat→3DGS → 每镜 RenderSplat 按角度渲染 → composite bg → Wan I2V（所有镜头强制 3DGS）
   - `mesh`（v3）：FLUX 图 → Hunyuan3Dv2→GLB → 每镜 mesh_render 按角度渲染 → composite bg → Wan I2V（几何更准，可导出）
   - `auto`（默认）：先走 3DGS 流程 + review_character 审查，不过则自动降级 flux
   - **资产复用**（v3 M6）：mesh/3dgs 模式重建前先查资产库（相似度≥0.6 + score≥7），命中则跳过重建直接渲染预览；重建后 review≥7 自动入库。`--no-asset-reuse` 可禁用
8. **审片 5 维**（v1）：consistency/quality/motion/artifact/character_consistency，与角色参考图对比
9. **审片图片缩放**：上传前 resize 到 512px + JPEG 85%（减少 payload，加快 API 响应）
10. **审片超时处理**：180s timeout + 2 retries，失败则 safe fallback auto-pass（不阻塞流水线）
11. **RIFE 过渡**（v2）：镜头间提取首尾帧 → RIFE 光流插帧（multiplier=8）→ 0.375s 过渡片段，config `rife.enabled`
12. **镜头并行预取**（v2）：ThreadPool 并行预取 FLUX 参考帧 + TTS 配音，与 Wan I2V 串行不冲突
13. **LUT 调色**（v2）：6 种 3D LUT 程序生成（`gen_luts.py`），LLM 自动选风格，ffmpeg `lut3d` 滤镜，config `color.enabled`——**2026-11-04 起默认关**（用户偏好：预览帧与成片观感一致，成片保持原始生成色；需要时显式 `--lut warm|cool|...` 仍生效）
14. **BGM ducking**（v2）：5 种 BGM 程序合成（`music.py`），ffmpeg `sidechaincompress` 配音时自动降 BGM，config `bgm.enabled`
15. **STT 字幕兜底**（v2）：faster-whisper large-v3-turbo 转写成片音频→SRT→重新烧录，`--stt` 开关，默认关闭（TTS 时间戳通常够用）
16. **git 归用户**（2026-10-15 用户拍板）：未经用户明说，agent 不得执行任何 git 写操作（commit/mv/checkout/push 等）；提交时机与内容由用户决定

## Python 环境

- **主环境 (comfyui)**：`/home/zxy/.conda/envs/comfyui/bin/python`（torch 2.13+cu130）
  - 用于：pipeline、comfy_api、llm、ffmpeg_tools、moviepy、rife、stt、music、gen_luts、**mesh_render（v3: trimesh+pyrender+EGL）**
- **TTS 环境 (cosyvoice)**：`/home/zxy/.conda/envs/cosyvoice/bin/python`（torch 2.3.1+cu121）
  - 用于：tts_server（CosyVoice 推理）
- **STT 模型**：`/mnt/dataset/zxy/hf_cache/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/`（int8_float16 GPU，HF_HOME 指向 hf_cache）
- **v3 headless 渲染依赖**（comfyui 环境）：trimesh 5.1.0 + pyrender 0.1.45 + PyOpenGL 3.1.0，EGL 后端（`PYOPENGL_PLATFORM=egl`）

## LLM 模型

| 模型 | 用途 |
|------|------|
| deepseek-v4-flash | 编剧、prompt 优化、LUT 风格选择、BGM mood 选择 |
| qwen3.8-chat | 多模态审片（主力，~30-120s/镜，支持视觉） |
| deepseek-v4-flash | 编剧、prompt 优化、LUT/BGM 选择（纯文本，不支持视觉） |

## 已知限制（v2 + v3）

1. **3DGS 角色重建质量仍是瓶颈**（character_consistency 2-4/10）：
   - TripoSplat 262K 高斯渲染稀疏，像素覆盖 31-35%（v1.1 位姿修复后提升，原 13-26%）
   - 3DGS 颜色偏暗（mean 0.51 vs FLUX 原图 0.94），宇航服细节丢失
   - **v1.1 位姿修复**：`load_ply` PCA 自动对齐角色主轴到垂直（替代手动 Y/Z 交换），`composite_bg` 裁剪角色 bbox → 缩放 55% 画面高 → 接地放置 88% 位置（脚踩地不悬浮）
   - **v1.1 I2V 修复**：Wan22ImageToVideoLatent（48ch + noise_mask），首帧与参考图相关性 0.99+
   - **v1.1 缓解**：`flux` 模式跳过 3D 重建；`auto` 模式 3DGS 审查不过自动降级 flux
   - **v1.1 渲染优化**：`_filter_floaters` 过滤孤立高斯（距离>99th pct + opacity<0.03），渲染参数 min_px 3→5、gain 2→3、supersample=2（2x 渲染→LANCZOS 缩放），LLM 确认"噪声显著减少，表面更平滑"
   - **剩余问题**：3DGS 镜头类型受限（只能全身远景/中景，无法特写），部分角度重建质量不均
   - **后续**：v2 探索多图 3D 重建 / 参考图 ControlNet / IP-Adapter 角色锁定 / 表面平滑
2. **flux 模式角色一致性依赖 FLUX prompt**：侧面/背面镜头（yaw≠0）FLUX 生成角色可能走样，无 3D 约束
3. **多模态审片 API 延迟波动大**（12s-200s+）：
   - USTC qwen3.8-chat 多模态调用延迟 30-120s/镜，已加 180s timeout + 2 retries + safe fallback
   - 多数审片实际 auto-pass（超时降级），仅前 2 次成功返回详细反馈
4. **review_character 超时**：4 张 512×512 预览图 + 1 ref，payload 较大，通常超时 auto-pass
 5. **BGM 已修复为真实素材**（2026-09-13 修复）：原 numpy 程序合成（music.py）有两个问题——①归一化 bug `wave/max(1,np.max(...))*0.8` 用 `max(1,...)` 钳制分母导致峰值锁死 -18dB；②calm/mysterious/dramatic 设计成超低频 drone（55-82Hz），人耳+普通喇叭听不见（放大音量也无济于事）。**修复**：①`music.py` 归一化改为 `wave/(np.max(np.abs(wave))+1e-9)*0.8`；②从 incompetech.com（Kevin MacLeod，CC BY 免版权，直连可达）下 5 首真实纯音乐经 loudnorm 归一到 I≈-20 LUFS 存 `bgm/{calm,uplifting,mysterious,dramatic,playful}.wav`，`select_bgm` 自动优先使用 custom_dir（无需改代码）。注意 `bgm/` 是真实长曲（59-261s），compose 会按视频时长截断；如需换曲直接替换 `bgm/{mood}.wav`（响度建议 I≈-20 LUFS）
6. **LUT 为程序生成**（v2）：numpy 生成 6 种风格 3D LUT，效果不如专业 LUT 包，留 `color.lut_dir` 自定义路径
7. **STT 默认关闭**（v2）：TTS 时间戳通常够用，`--stt` 仅在需要重新对齐时开启（额外 GPU 显存+耗时）
8. **视频编码统一 yuv420p**（v2 修复）：LUT 调色 + STT 烧录的 ffmpeg 命令均加 `-pix_fmt yuv420p`，确保所有播放器兼容（之前 lut3d 滤镜导致输出 yuv444p，部分播放器无法播放）
9. **~~长片未验证~~ → 已实现**（v2.1）：`--duration N` CLI 动态调整 LLM 编剧镜头数（`target_duration/4` 镜），解锁长片能力
10. **~~单镜慢动作未接入~~ → 已实现**（v2.1）：`--slowmo N` 全局慢动作 + LLM 自动标注 `shot.slowmo`，pipeline 调用 `RIFEClient.slowmo()` 帧倍增
11. **~~per-shot 过渡类型未实现~~ → 已实现**（v2.1）：LLM 标注 `shot.transition_out: "rife"|"crossfade"|"cut"`，pipeline 按类型分流过渡，compose 支持混合过渡
12. **后期审片 4 维**（v2.1 跳过）：API 不稳定，投入产出比低，保留逐镜审片
13. **music subagent 简化**（v2 偏差）：设计 §8.2 定义独立 music subagent，实际简化为 pipeline 内联 LLM 调用（`llm.select_bgm_mood()`），功能等价
14. **~~无 `--duration` CLI~~ → 已实现**（v2.1）：`--duration` 已加入 auto 子命令
15. **concat 子命令**（v2.1 新增）：`vidance.py concat` 支持多视频拼接（cut/rife/crossfade），可复用于已有素材合并
16. **v3 M1 mesh 为 non-watertight**（v3）：Hunyuan3Dv2 turbo 输出 mesh 为 non-watertight（VoxelToMesh surface net 特性），不影响渲染但影响后续物理仿真/布尔运算。M2 多视角重建改善：主连通分量 38%→63%，bbox 比例更自然（aspect 1.02→1.69）
17. **v3 pyrender 材质处理**（v3，✅ M3 已处理）：GLB 的 PBR 材质在 pyrender 可能部分丢失，M3 封装时已加 3-point lighting（key+fill+ambient）和 `gray_fallback` 选项（覆盖为灰色材质用于预览审查）
18. **~~v3 Hunyuan3Dv2 与 Wan 共实例~~ → 已分离**（v3）：Hunyuan3Dv2 已独立到 GPU1:8193，不再与 Wan 共用 8189，3D 重建与视频生成可并行

# v4 FunClip 智能裁剪（长素材语义裁剪，device='auto' 自动选卡）
# 转写显示字级时间戳
python utils/funclip.py transcribe output/clips/narration.wav
# LLM 语义裁剪（一句话描述保留什么）
python utils/funclip.py smart long.wav -i "只要讲龙的部分，去掉口误" -o dragon.wav
# API 异步裁剪（提交后轮询 /api/clip/{job_id}）
curl -X POST http://127.0.0.1:8894/api/clip \
  -H 'Content-Type: application/json' \
  -d '{"input":"/path/long.wav","instructions":"只要讲龙的部分","output":"dragon.wav"}'

# v4 M5 素材爬取（参考图 + BGM）
# LLM concept → 图片搜索关键词
python utils/asset_crawler.py keywords "雪山上的日出小狐狸"
# concept → 关键词 → 图片下载（一条龙）
python utils/asset_crawler.py refs "雪山上的日出小狐狸" -o output/ref/ --top 2
# BGM：列候选 / 下载（→ bgm/{mood}.wav，--bgm epic 直接生效）
python utils/asset_crawler.py bgm epic --list
python utils/asset_crawler.py bgm epic

# v4 M6 快速营销号链路（图片+zoompan+RIFE，跳过视频模型）
# 概念 → LLM 旁白 → 出图 → KenBurns 伪动态 → TTS → crossfade → LUT/BGM/STT
python core/vidance.py fast "雪山日出小狐狸" -n 5                        # 自动爬图+校验+自动 BGM/LUT
python core/vidance.py fast "概念" --images-source flux -n 5              # FLUX 逐段文生图
python core/vidance.py fast "概念" --bgm epic --lut warm --stt --slowmo 2 # 指定 BGM/LUT + STT + RIFE 慢放
python core/vidance.py fast "概念" --source-topic "热搜标题" --trend-date 2026-09-14  # 热搜角标+meta

# ✅ 固定流程（一步到位）：爬实时热点 → LLM scout 选题 → 出片
python core/vidance.py hot -n 5 --top-each 10 --account "影视解说"

# v5 剪辑特效（--effects auto 由 LLM 逐段选特效）
python core/vidance.py fast "概念" --images dir/ --effects auto       # LLM 选 glitch/颗粒/定格等
python utils/effects.py apply in.mp4 --effect punch_in -o out.mp4     # 单片段特效
python utils/effects.py transition a.mp4 b.mp4 --kind slide -o out.mp4 # xfade 双段拼接

# v11 多智能体（原 v13；薄包装 Agent + chain + 黑板）
python core/vidance.py agent list                                          # 28 个 Agent
python core/vidance.py agent run post.fx --with '{"video":"a.mp4","effect":"zoom"}'
curl http://127.0.0.1:8894/api/agents                                       # 注册表
curl http://127.0.0.1:8894/api/tasks/{id}/trace                             # 链轨迹（agent_runs）
# 排队链任务：POST /api/tasks {"mode":"chain","chain":[{"agent":"post.lut","with":{...}}],"ctx":{},"concept":"标签"}
# chain 步骤支持 ${ctx.key}/$ {as.artifact} 引用上一步产物；POST /api/agents/chain 同步跑
# v11.1 前端：/ui 里 /arch 画分层架构图（运行时点亮），/agent list|run|chain，chain 任务卡片内嵌 trace 时间线

# v6 prompt 多轮核实（信息不全时追问，增强后概念可喂 auto/fast）
python core/vidance.py ask "深海探险"                 # 交互多轮追问（≤3 轮），--out 存增强概念
python core/vidance.py ask "深海探险" --out input/concept.txt
# dialog API（v7 前端用）
curl -X POST http://127.0.0.1:8894/api/dialog/start -H 'Content-Type: application/json' -d '{"concept":"深夜灯塔"}'
curl -X POST http://127.0.0.1:8894/api/dialog/dlg_xxx/reply -H 'Content-Type: application/json' -d '{"text":"暴风雨夜，灯塔守护人独自值班"}'

# v7 前端 agent WebUI（浏览器访问 http://127.0.0.1:8894/ui）
# 左栏工具/任务边栏 + 顶部画布 + 右下发框；/ 弹命令补全
# /fast 概念 -n 3 --effects auto   → 提交任务 → 画布轮询 → 成片 video 卡片
# /hot /auto /ask /clip /scout /voices /video {id} /help 同理
# 后端对应：
curl http://127.0.0.1:8894/api/tools                     # 15 命令 + 参数 schema
curl http://127.0.0.1:8894/api/options                   # 音色/LUT/BGM/特效枚举
curl -X POST http://127.0.0.1:8894/api/tool/fast -H 'Content-Type: application/json' -d '{"args":"概念 -n 3 --effects auto"}'
curl http://127.0.0.1:8894/api/video/{task_id} -o final.mp4   # 成片视频流

# ── v17 开源整合（原 v12，✅ 2026-10-30 关版）——完整命令见 docs/usage/usage-v17.md ──
# buffer：POST /api/upload?session_id=s 上传 / GET /api/assets?session_id=s&q=关键词（@文件名搜索，游标翻页失效 410）
#         POST /api/assets/archive 归档 / DELETE /api/session/{s} 整会话删除
# 断点续跑：python core/vidance.py auto --resume {task_id}（阶段跳过+逐镜复用+sha256 指纹拦截篡改产物）
# 五维模板：python core/vidance.py auto "概念" --template cinematic|documentary|anime90s|guofeng
# RAG：python core/vidance.py rag add 文档.md --novel / rag search "问题" / rag ask "问题"
# novel2video：SKILL/commands/novel2video/{m6_breakdown_test,m6_render_v3,m6_archive_buffer,m6_wardrobe_test}.py
# 衣橱：python input/rag_test/m6_wardrobe_test.py [--gen]（Base Look 锁脸多套服装 prompt+FLUX 出图）
# 测试：python tests/test_{buffer,checkpoint_m4,retry,embed_index,subtitle_correct,material_cache,preflight}.py

# ── v18 长视频质量（原 v14，✅ 2026-10-31 关版）——完整实录见 docs/usage/usage-v18.md ──
# 旧拆解迁移 v18 schema（dry-run 预览 / --apply 写回+.v17.bak 备份）
python SKILL/commands/novel2video/m6_upgrade_breakdown.py output/m6/breakdown_孔乙己.json --apply
# M6 渲染（v18：场景锚+衣橱组装器+xfade 过渡选型；M6_ALL=1 全量 ~2h 一律后台化）
M6_OUT=v4 python input/rag_test/m6_render_v3.py
# M6_FLF=1：VACE 首尾帧驱动（首帧=本镜关键帧、尾帧=下镜关键帧，832x480@16fps；镜间边界 clip 级 -87%/part 级 -72.6%）
M6_OUT=v5 M6_FLF=1 python input/rag_test/m6_render_v3.py
# 一镜到底（LLM 运镜链 + 末帧回灌链式 I2V + 每段锚重注入；拼缝 MAE 断言 <0.10）
python core/vidance.py auto "穿越隧道的光" --oneshot --duration 30
python utils/oneshot.py "穿越隧道的光" --duration 30 --character "金色光流"   # 直接调用等价

# ── v19 视频链接二创（原 v16，✅ 2026-11-02 关版）——完整实录见 docs/usage/usage-v19.md ──
# 一条命令：链接 → 下载+理解 → LLM 改写解说（防复述断言）→ 重配音 → 画面改写 → 成片
python core/vidance.py rework "https://www.bilibili.com/video/BVxxxx" --style 解说 --duration 60 --visual-rewrite 2 --lut cinematic --bgm dramatic
python utils/rework.py source "链接" --out output/rework/rw-x   # M1 单步（source.json）
# agent/API：generator.rework agent；POST /api/tool/rework（异步 job，/api/h3shot/{job_id} 轮询）
# ⚠ 默认音色 cosy-safe（cosy-default）；发布前人工审核（meta 录来源 URL）

# ── v20 生成中审核（边生边审，原 v21，✅ 2026-11-04 关版）——完整实录见 docs/usage/usage-v20.md ──
# 开 = 生成中 WS latent2rgb 预览帧丢 qwen3.8 粗审，判死即 interrupt 止损换 seed；关 = 原路径不变
python core/vidance.py auto "红狐狸雪原捕猎" --live-audit
# config 常开：config.json → v20_live_audit.enabled: true；API：POST /api/tasks {live_audit:true} / /api/tool/auto "概念" --live-audit
# 前端 :8894/ui 任务卡实时显示预览帧+verdict（GET /api/tasks/{id}/preview）

# ── 已规划（🎯 待实现，见 docs/roadmap.md §4）──
# v14 接入社交媒体（原 v11）
# v21 交付形态（原 v18）
# v10 拼接命令示例（规划）：
# python core/vidance.py compose timeline.json -o final.mp4
