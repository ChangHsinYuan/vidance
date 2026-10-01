# Vidance Compaction（2026-09-26 晚）

## Session 2026-10-01：v15 PPT 完成（接续记录）

### Done
- **v15 PPT 美化（2026-10-01 晚，用户反馈"太简陋"）**：ppt_llm.py 重写视觉——`page_css()` 单一样式源（deck 放映/视频/PDF/PNG 四形态共用同一套设计，修复单页渲染缺全套 CSS 的根因）+ 深色渐变底+双光斑（body::before/after radial）+ 玻璃卡片要点（渐变底+边框+阴影+渐变序号块）+ 渐变标题（background-clip:text）+ 渐变顶条+品牌页脚（brand 字段）+ svg_chart 升级（渐变柱/面积折线/环形图带中心数值/网格线/uid 防多图渐变 id 撞）；PptLine sections 改用 SLIDE_TPL（顶条/品牌/页码与 deck 模式一致）
- **美化验证**：Vidance 主题 6 页全形态（output/ppt_20261001_173114：final.mp4 77.4s + deck.html + deck.pdf + pngs/，像素 stdev 62 vs 旧版 11-25）；真 LLM CLI 4 页 32.8s（ppt_20261001_181312）；容器 docker cp 同步 + /api/tool/ppt 复测过（ppt_20261001_102118）
- **slide_to_mp4 健壮性修复**：stdin 写入加 BrokenPipeError 捕获 + proc.poll() 存活检查（ffmpeg 中途死→立即报错，不再 stdin 管道无限阻塞——真实 LLM 测试中出现过 2 次渲染挂死，根因是负载 17-20 下 ffmpeg 偶死+管道阻塞）
- **roadmap 两条新增（用户要求）**：v13 轻量化改为"无模型三线=svg+ppt+blender（前两已具备，blender headless 🎯）+ 模型加速路线（量化/蒸馏/小模型/推理优化）"；v16 加 ControlNet 参考条目（inpaint/二改锁定构图姿态，参考列表补 ControlNet）；AGENTS.md 版本路线两处同步
- **残留清理**：4 个超时残留 ppt_ workdir 已删（174205/174622/175237/175552/175844/180340），保留有效产物
- **concat bug 修复**：core/api_server.py 缺 `import subprocess`（容器 /api/tool/concat NameError）→ 已修，用户提交 a6458c6 后 docker build 新镜像 784b2fd41f56 + 容器切换，/concat 复测通过
- **双栈功能测试 7 项全过（产物保留作证据）**：auto/svg/fast/chain/concat×3，详见 output/（auto_20260930_054117、svg_20260930_054545、fast20260930_135454、svg_20260930_140622、t5-t7_concat_*.mp4）
- **roadmap v19-v21 三节新增 + 二次重排（2026-10-01）**：v15 PPT/v16 视频编辑/v17 开源整合/v18 长视频/v19 二创/v20 生成中审核/v21 交付形态；roadmap/AGENTS/deploy-tiers/deploy README 全同步
- **v15 M1**：`agents/generator/tools/ppt_llm.py`（plan_deck LLM→结构化 JSON→_norm_plan + render_deck_html 五版式 title/toc/content/data/end + svg_chart bar/line/pie 数据驱动 SVG + extract_json 尾逗号容错）；离线测试过（PNG×5、mp4 2页+fade、PDF 5 页、图表页像素 stdev 25.9 验证非空白）
- **v15 M3**：svg_chart() 接入 data 版式（LLM 只出数据不出图形）
- **v15 M2**：PptLine 全链实测——LLM 规划 4 页（含 bar 图表页）+ cosy-default TTS 旁白 + 逐页渲染（页时长=max(旁白+0.8, 3s)）+ fade 拼接 → `output/ppt_20261001_122326/final.mp4`（42.9s，总 117.8s，产物齐全 deck.html/subtitle.srt/meta.json/slide_N.{html,mp4,wav}）
- **v15 M4（含 _run_pptjob）**：CLI `ppt` 子命令（core/vidance.py cmd_ppt：一键/渲染双模式、--video/--pdf/--pngs/-n/--transition/--voice/--say/--no-html）+ `generator.ppt` agent（needs_gpu=False）+ config task_prefixes `ppt` + /api/tools ppt spec + tool_dispatch ppt 分发块（_parse_repeated say、ppt_ 时间戳 job_id、复用 h3shot 轮询）+ `_run_pptjob`（仿 _run_svgjob：stage_cb→stage、on_chunk→llm_text、on_frame→frames、PptLine().run、video_url 仅 .mp4）
- **M4 测试 4 连全过**：CLI 一键 --say 2 页 19s（ppt_20261001_123718/final.mp4 6.72s）+ agent run generator.ppt 3 页 8.96s（ppt_20261001_123810）+ API /api/tool/ppt 宿主临时 8999 端口 75s（ppt_20261001_123959）+ 容器 :9401（docker cp 同步 6 文件 + restart）80s（ppt_20261001_044318/final.mp4 6.6s）
- **文档同步**：roadmap.md v15 节 🎯→🔄 M1-M4 已完成 2026-10-01 + 里程碑标 ✅（M4 口径=PDF/PNG 导出+agent 化）；AGENTS.md 当前状态行加 v15 + 目录树加 ppt_llm/ppt_pipeline（agents/generator/tools 与 utils/ 双处）+ 运行命令加 ppt 块 + 修复 520-524 行旧顺序残留（v15 整合开源原 v12 → v15 PPT 原 v20、v16 原 v14 → v18 原 v14）；usage.md 子命令表加 ppt 行

### Key Decisions
- **v15 架构分工**：LLM 只出结构化 JSON（版式/要点/图表数据/旁白），Python 模板渲染 HTML（风格统一可控），图表纯 Python 数据驱动——与 v13 "LLM 产 SVG" 不同的更稳路线
- **渲染复用 v13 确定性逐帧**：_freeze_and_advance 逐页截图 → image2pipe → concat_with_transitions 链式 xfade（签名 (clips, kinds, out_path, duration=0.4)，kinds 长度 N-1）
- **PDF 导出**：render_deck_html(pdf=True) 原生模式，Playwright page.pdf 16:9
- **PptLine 多形态并行**：run(video=/html_out=/pdf=/pngs=) 一次跑多交付形态；API 默认 video=True 当其余形态全关

### Critical Context（更新）
- git HEAD a6458c6（用户已提交 concat 修复）；**v15 全部改动未提交**（ppt_llm/ppt_pipeline/CLI/agent/API/config/文档/薄壳）
- 容器 vidance :9401 已 docker cp 同步 v15+美化 8 文件并重启（health 200，ppt 链路复测通过）；镜像 784b2fd41f56 仍不含 v15（下次 build 才进镜像）
- 宿主 api :8894 仍是旧代码进程；测试时用临时 8999 端口起新代码（已杀）
- Playwright sync 坑：单会话渲染所有页（中途 break 撞 asyncio loop）；render_deck_html theme 空 dict KeyError 'bg' 已修（page_css 内 _norm 兜底）
- **渲染挂死（偶发，环境性）**：系统负载 17-20 时 ffmpeg 偶发中途死→stdin 管道阻塞（已加 proc.poll 检查变报错）；killed 运行会留僵尸 chrome-headless（无害但堆积）；长链测试给足 timeout、失败重跑即可
- PptLine 时长：每页 d_i = max(旁白+0.8, 3.0)；srt 按页累加
- 本机模型（opencode）不支持看图——PNG 视觉验证用像素统计（stdev/角部均值）代替目检

### Next Steps
1. 用户提交 v15 改动（一条 commit）→ docker build 让 v15 进镜像
2. v16 视频处理与编辑（原 v19）：SAM 分割 M1 起步
3. 快赢备选：fast 爬图加搜索缓存（Pexels 网络瓶颈缓解）

## Session 2026-10-01（续）：v13 blender 3D 简单版完成（M0-M3 全部）

### Goal
- v13 blender 线简单版：概念→LLM 规划 3D 场景→bpy EEVEE 渲染→mp4；M0-M2 早已通过，本会话完成 M3（CLI/agent/API/容器）+ 文档同步

### Done
- **M3 API 完成**：_run_blenderjob（core/api_server.py，仿 _run_pptjob：stage/llm_text/frames 写 job 字段 + BlenderLine 调用，video_url 仅 .mp4）+ /api/tool/blender3d 分发块（b3d_* job 复用 h3shot 轮询）+ /api/tools blender3d spec（GPU 加速标注，4-20s 时长提示）
- **utils 薄壳**：utils/blender_llm.py + blender_pipeline.py 门面（转发 agents/generator/tools/，旧 import 兼容）
- **M3 测试 4 连全过**：①CLI 一键"深海探索主题三维动画" 6s 58.3s（blender3d_20261001_192947）②agent run generator.blender3d "雪山日出三维场景" 5s（blender3d_20261001_193101）③宿主临时 8999 端口 /api/tool/blender3d（b3d_20261001_193212，100s 内 completed）④容器 :9401（b3d_20261001_114559，120/120 帧，6.0s final.mp4 + scene.json/scene.mp4/narration.wav/subtitle.srt/meta.json 齐全）
- **容器 bpy 安装**：容器内 pip install bpy（5.0.1，numpy 1.26.4 随装）+ apt libsm6/libxext6/libxrender1/libx11-6/libxi6/libxxf86vm1/libxfixes3/libxkbcommon0/libgl1/libegl1（缺 libSM.so.6 报错后补）；bpy 5.0.1 容器内 import 通过；容器已重启
- **容器渲染性能**：容器无 GPU 直通 → CPU EEVEE 约 2.5s/帧（120 帧 5s 片段约 6.5 分钟）；宿主 GPU CUDA ~156ms/帧
- **文档同步**：roadmap.md v13 blender 条目 🎯→🔄（简单版已实现，含实测数据/依赖说明）；AGENTS.md 状态行 + 目录树双处（agents/generator/tools/ + utils/ 薄壳）+ blender3d 命令块双处（ppt 块后）

### Key Decisions
- API 用 b3d_ 前缀区分 ppt_ 的 job_id；时长默认 8s（4-20 钳制）
- 容器 bpy 走容器内 pip（非宿主拷贝 site-packages，CP 版本一致 3.11 但稳妥）
- bpy 在容器装包顺带 numpy 1.26.4（与宿主 bpy 安装同样降级，无害）

### Critical Context
- 容器镜像 784b2fd41f56 仍不含 bpy/v15/blender（本次容器内 pip+apt 是运行时安装，**容器重建后丢失**，需下次 build 时写进 Dockerfile 或 build 时 pip install bpy + apt libsm6 等）
- 宿主 bpy 5.0.1 在 /home/zxy/.conda/envs/comfyui；numpy 降级 2.4.4→1.26.4（fast/svg 等链路 import 待最终验证——本会话 CLI/api 跑通即已侧面验证）
- 测试产物保留：output/blender3d_20261001_{192947,193101,193212,114559}/
- 临时 8999 端口 api 已杀

### Next Steps
1. 用户提交（v15+美化+blender+文档一条 commit）
2. 可选：下次 docker build 时 Dockerfile 加 `pip install bpy` + `apt-get install libsm6 libxext6 libxrender1 libgl1 libegl1`（否则容器重建后 blender3d 不可用）
3. v16 视频处理与编辑（原 v19）：SAM 分割 M1 起步

## Session 2026-10-01（续 2）：v13 轻量化收口 ✅ + roadmap 重排 + v14 移交队友

### Done
- **v13 收口 ✅**（用户拍板"标 ✅ 完成"）：无模型四线（营销号/SVG/PPT/Blender 3D）全部完成；模型加速路线标"按需后续，不阻塞 v13 关版"；纯 API 云端模式标"后续项"
- **roadmap 重排**：v15 PPT 条目从待开发区块移入已实现区（v13 后），待开发条目（v16-v21）位置前移，**编号不变**；v14 标 `🔗 移交队友，暂不在本仓排期` + 移交说明块（utils/notify/ 骨架已预留，队友按原里程碑推进）
- **顶部总览**：已实现加 v13 轻量化无模型四线 + v15 PPT；待开发去掉 v15、v14 标队友；三调注释
- **AGENTS.md 同步**：状态行（v13 收口 + v14 队友）+ 版本路线（v13 ✅/v15 ✅/v14 🔗 队友）
- **usage.md**：子命令表加 blender3d 行
- compaction.md + docs/reports-20261001.md 记录

### Next Steps
1. v16 视频处理与编辑（原 v19）规划（SAM 分割起步）→ 用户拍板里程碑后开工 M0 spike
2. 用户提交改动（v15+美化+blender+文档+收口一条 commit）

---

# （以下为 2026-09-26 晚原记录）

## Goal
- 本轮完成：全库版本号重排（已完成块前移 v11/v12/v13）+ usage/design 系文档审计补缺（6 处修复 + 新建 usage-v11.md）
- 当前状态：**只收尾不开工**——4 个文档改动待提交（一条 commit），之后今天到此为止
- 下次开工已定路线：打磨快赢 → v15 开源整合 → v16 长视频；v14 社交媒体已交队友并行

## Constraints & Preferences
- 代码在 /mnt/disk_sdb/zxy/vidance；重启 api / 长耗时 GPU 测试用户自己跑；README.md 禁 AI 改
- /tmp/opencode 为唯一预授权外部目录；output 相对/绝对路径一律尊重不改写，仅 /tmp 越界改写；**厌恶软链**（final 并入链目录用真文件复制）
- 跑链期间禁止重启 api（daemon 随进程死）；不用 wan 测 agent（用 svg/fast/artist 快链）；命令里别带 out_path
- 一命令=一会话内积累（不另开新会话）、会话/记录命名=概念前 10 字、顶栏不加新按钮
- 不自动发布：成片人工精挑细选手动上传（发布模块已删）
- 前端零 npm 自包含 HTML+vanilla JS
- 验证要老实、不空转、不编造；误删用户文件是大忌（16:27 事故已道歉，流程已改）

## 编号映射表（全库同步唯一依据）
| 原号 | 新号 | 内容 |
|------|------|------|
| v13 | **v11** | 多智能体（M0-M4 完成 + v11.1/v11.2 前端闭环） |
| v17 | **v12** | 三排正交（make 统一入口，M1-M2 完成） |
| v15 | **v13** | 轻量化/SVG 流水线（S1-S5 已实现） |
| v11 | **v14** | 接入社交媒体（notify/，🎯 队友并行中） |
| v12 | **v15** | 整合开源仓库（断点续跑/RAG，🎯 待开发） |
| v14 | **v16** | 长视频质量/一镜到底（🎯 待开发，用户拍板放后面——较难） |
| v16 | **v17** | 视频链接二创（🎯 backlog） |
| v0-v10/v2.5/t2c/v18 | 不变 | 已完成块 + 交付形态 |

## Progress

### Done（本轮）
- **UI 转圈圈/日志/流式三问题修复（v18 后追修，未提交）**：
  1. `/svg` 无声模式同步阻塞 → 黑屏无反馈（回归根因）：api_server /svg 全部 job 化（无声 concept_to_mp4 / 有声 narrate_to_mp4 同走 _run_svgjob 异步线程），stage/llm_text/frames 写 _h3_jobs + 阶段/完成写 output/{job}/agent.log（日志面板有料）
  2. LLM 流式打印：svg_llm._chat_stream 加 on_chunk 逐 delta 回调 → generate_svg/plan_narration → svg_pipeline concept_to_mp4/narrate_to_mp4 透传（stage_cb/on_chunk/on_frame）→ job llm_text 字段（尾 600 字）→ 前端 .llmt 流式预览
  3. 前端 pollH3 重写：svg_/h3_ 前缀分流（svg 3s/h3 5s 轮询）、spin 转圈圈 + stage + 耗时 + 帧进度 + llm_text 打字预览（**details/summary 折叠式**，保留用户开合状态）、完成回填 ✓ + 成片卡片 + setLogTask 跟踪
  4. /api/logs/tail 加 VIDANCE_LOG_PREFIX（前缀路径谁存在读谁）：容器读宿主 /tmp 服务日志；compose 挂 /tmp:/hostlogs/tmp:ro + env VIDANCE_LOG_PREFIX=/hostlogs
  5. 验证（容器 full :9401 实跑）：无声 /svg job S1→S4→完成（llm_text 流式、72/72 帧、out.mp4 落宿主）、有声 --say job TTS→SVG→合成（80/80、final.mp4 落宿主）、两 job agent.log 经 /api/tasks/{id}/log 可读、/api/logs/tail 读宿主 wan 日志 OK；宿主 :8894 不受影响；py_compile + node --check 过
- **全 pipeline 流式交互（第二轮追修，未提交）**：
  1. **/quick 修复**：scheduler 对所有模式追加 --task-id 但 vidance.py quick 子命令没这参数 → argparse exit 2（用户实测"quick 不太行"根因）；p_quick 加 --task-id + cmd_quick 透传 pipeline.run(task_id=)
  2. **llm.py 全局 live 流式**：set_live(cb) 全局开关 + _LIVE_CB；chat() 有 CB 时自动走 chat_stream(on_chunk=_LIVE_CB)（chat_json/script_write/optimize_*/assess_*/review_* 全部生效，因底层都走 chat）；chat_stream 回退改 _chat_plain（原调 self.chat 会无限递归，已拆出）；vidance.py main() 设 set_live(print) → CLI 全 pipeline（auto/quick/fast/hot/custom/agent）LLM 打字机输出
  3. **scheduler 日志 watcher**：_run_task subprocess.run → Popen + _watch_progress 线程（2s tail scheduler.log 解析 === [1] 编剧 === / ▸ / ▶ / [S1] 标记 → queue.update_task(stage=)，仅 status=running 时回写防竞态）；TimeoutExpired 补 proc.kill()
  4. **前端任务卡片**：meta 行加耗时（Date.now()-started_at）
  5. **验证（容器 full :9401 实跑）**：/quick 端到端 ~20 min 全链——阶段实时推送 [1]编剧→[2]prompt 优化→[4] shot 1-4 生成→[5]合成→completed（任务卡片轮询可见）、LLM 流式 JSON 全文进 scheduler.log（日志面板可读）、审片 score 8/9 落 log、final.mp4 4.8MB 落宿主盘；CLI smoke：agent run scriptwrite 流式输出确认（带 [Δ] 前缀调试验证）；py_compile + node --check 过
- **roadmap 重排全部收尾**：git mv v13-design→v11-design、v17-modules→v12-modules（留史）；§4 节序重排+17 处（原 vN）标注；头部摘要/v18 依赖/部署分档/仓库表同步；§5-§10 整块重复两份 → 删重复（671→549 行）；§8 目录树旧号改新号+补 agents/ 行+v0-v18
- **代码注释版本号全同步**：core×4 + agents×3 + tools 层 + utils 24 个门面薄壳 docstring，全库 py_compile 通过，零逻辑改动
- **grep 复验零残留**：docs/ AGENTS.md commands.json 旧号链接全清（v13-design/v17-modules 引用归零）
- **usage/design 系文档审计补缺（6 处）**：
  1. roadmap §5-§10 重复块删除（结构性 bug）
  2. **新建 docs/usage-v11.md**（多智能体此前无 usage 文档）：CLI agent list/run/chain、7 API 端点、chain 步骤语法 ${ctx.key}、代表 Agent 表、WebUI /arch/流式、注意事项
  3. usage.md「四种子命令」5 行 → 「子命令」12 行总览（补 fast/hot/svg/compose/h3shot/ask/agent）
  4. roadmap §8 目录树旧号+缺 agents/ 目录 → 全部修正
  5. roadmap §4 v8/v9/v10/v11/v13 五节补 `**详细设计**：[...]` 链接
  6. v11-design.md §6「注册 Agent 清单（24）」→ 28（实际 post 10/G 7/D 6/V 5）
- **无缺口确认**：usage-v4 已含 M6 fast/hot；usage-v0/v1/v2/v3/v6/v7/v10/v-svg 健在；v5 无 usage 属历史刻意省略；v8/v9 design 存在（规划版，已被吸收，有标注）

### Done（本轮之前，摘要）
- multiagent v11（原 v13）全闭环：28 Agent/chain/SSE/`${ctx}` 引用/并行轻度审片/明细日志/内嵌预览/三源历史
- LLM 真流式全链：chat_stream（SSE 逐 delta）→ brain on_chunk → run_agent inspect 分发 → run_chain chunk 事件 → 前端流式打字
- UI：📋 日志面板 7 tab（/api/logs/tail）、pipe-bar 置顶条、streamAgent 重写（概念前 10 字命名）、live 转圈圈
- records 扫描重写：三类目录 + meta.json/agent.log 双源 + `'■' in last` 判定 + 第三根 /mnt/dataset 树
- _vault_final 链目录归并（output 内但不在 {tid} → 复制 final.ext 进链目录，真文件非软链）
- fast out_path 别名 bug 修复；output 架构还原（软链拆净）；fast 链端到端验证 194.9s ok

- **SVG 截断修复 + pipe-bar 彩色方块 + 输出命名统一（第四轮，未提交）**：
  1. **SVG "LLM 输出里没找到 svg" 修复**：实测 LLM 输出被 max_tokens 截断（有 `<svg` 无 `</svg>`，约 50% 概率，LEN 2-7K）→ extract_svg 补 `</svg>` 兜底（Chromium 自动闭合）+ generate_svg 自动重试一次（重试时强调"只输出 SVG、元素精简 60 行内"）；容器复测同款场景成功
  2. **pipe-bar 升级（用户拍板样式）**：每步一个彩色方块（按 layer 配色：D 浅红/G 浅橙/P 浅蓝/V 浅绿/C 浅粉，d0-d4 CSS 类）+ 未完成时当前步边缘虚线转圈圈（.pnode.run::before border-dashed 旋转）+ 完成高亮（ok 类绿光/fail 红光）；去掉旧 pspin 圆圈改 ::before
  3. **输出命名统一（用户要求）**：config.json 加 task_prefixes（auto/quick/fast/hot/custom/make/chain→agent）+ config_loader.task_id_for(mode, task_id=None) 统一生成 `{prefix}_{YYYYmmdd_HHMMSS}`；接入：scheduler.submit（缺省改 mode 前缀）、pipeline.run（auto）、custom_gen.run_custom（custom）、svg_pipeline concept_to_mp4/SvgLine/_main（svg，修 svg_pipeline/out.mp4 覆盖问题）、fastline（f→fast 前缀）；make 的 _resolve_out 已有 make_{tag}；agent/records 扫描目录名无关安全
  4. **chain "TypeError failed to fetch" 结论**：非代码 bug——SSE 流 curl 实测正常（task/start/step/chunk/done 全事件）；用户点 chain 时容器恰在重建/重启（本轮反复 build 期间），或浏览器连接被断。容器稳定后不会再出现
  5. 验证：/svg 无声容器实跑（S1→S4、72/72 帧、新命名 svg_20260929_093034.mp4、agent.log 可读）、/quick 提交即 quick_ 前缀+阶段推送（[1] 编剧，验证后取消）、task_id_for 单测 7 例、extract_svg 兜底单测、py_compile+node --check 过；测试产物已清（仅剩用户 svg_20260929_072112/093034 跑 + assets）
  6. compose 已加 `../ui:/app/ui:ro`（改前端零重建）；本轮后端改动已重建进镜像 df3a6de53ba1
- **svg 落盘修复（第五轮，用户报"svg 视频不在对应目录下面而是同级"）**：concept_to_mp4 缺省 out_path 上一轮改命名时只给文件名没放进任务目录 → mp4/svg/preview 散落 output/ 同级、任务目录空。修复：缺省路径改 `output/{svg_ts}/final.mp4`（svg/svg/preview 同目录，与有声路径 final.mp4 口径一致）。验证：单测（mock LLM/渲染，三文件全进 svg_ 目录）+ 容器端到端两连跑（svg_20260929_110601、130723，72/72 帧、agent.log/final.mp4/final.svg/final.preview.html 全在目录内、同级无散落）；旧散落文件已归位（093034 宿主移/100333 容器移）
- **打磨快赢三项（第五轮，未提交，全部进镜像）**：
  1. **fast 爬图提速**：下载/审核两阶段并行（ThreadPool max_workers=3，按关键词序回填保序"图-段对应"）+ 每词 top=2 候选（多一份备选）+ 审核失败用同词备选补位（零额外搜索）+ FLUX 兜底提前、原概念重爬降为最后手段（串行无审核）。实测瓶颈：Pexels API 单次搜索 50-65s（网络）> 下载 79s > assess 4s/张 > extract 2s。单测：15s→5.5s 保序、备选补位保序、全失败 FLUX 兜底三场景 PASS；容器实跑 284s（3 词 Pexels 搜索 ~55s×3 串行为主，并行省下审核/下载时间）
  2. **api 日志轮转**：api_server __main__ 加 copytruncate 线程（/tmp/api_{port}.log >10MB → 拷 .1 + truncate 0，O_APPEND fd 下安全，300s 检查一次）+ start_services.sh bg_run 加 append 模式（api 用，配合轮转）；单测 O_APPEND truncate 后写入回到开头 PASS
  3. **llm 健康灯**：/api/health 加 llm 字段（/models 探活 2s 超时、30s 缓存、不阻塞）+ api_server 补 urllib import + UI topbar llm-dot 红绿点（init 30s 轮询 pollLlmHealth，绿=ok+latency、红=不可达、灰=旧版 API）；容器验证 {'ok': True, 'latency_ms': 143}
- **Dockerfile 三连修（第五轮）**：基础镜像 python:3.11-slim 已升 Debian 13 (trixie) → ①apt 包名 5 个改 t64（libasound2t64/libatk1.0-0t64/libatk-bridge2.0-0t64/libatspi2.0-0t64/libcups2t64，逐一 apt-cache 验证）；②deb.debian.org 直连不稳 → sed 换清华镜像（debian.sources 优先/sources.list 兜底）；③playwright CDN（cdn.playwright.dev+storage.googleapis.com）双超时 → PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright（build 仍超时未验证）；**当前方案：deploy/Dockerfile.update 薄镜像**（FROM vidance-api:latest 只叠代码，秒级 build 零网络下载）→ 已 build e306d8d82502 并重启容器验证全通

### In Progress
- (none)

### Blocked
- (none)

## Key Decisions
- 编号映射表（见上）为全库唯一依据；重排必须带（原 vN）括号标注——方便对照旧 commit 回退（用户拍板）
- v14 社交媒体**孤立性强 → 交队友并行做**（这几天应该会做好）
- v16 长视频**较难 → 放后面**；顺序定为：打磨快赢 → v15 → v16
- 今天只收尾不开工（用户拍板）
- 一命令=一会话 + 概念前 10 字命名；records 三类目录全扫 + final 真文件并入链目录
- light/none 强制 max_retries=0（30 分钟灾难根因）

## Next Steps
1. 可选小优化：fast 爬图加搜索缓存（关键词→结果落盘，重复概念秒出）——Pexels 网络瓶颈的缓解项
2. 下次开工选项（快赢三项已完成）：
   - **v15 开源整合**：M1 断点续跑（挂 v11 黑板）+ JSON 容错 → M2 五维提示词+RAG（2-3 天）
   - **v16 长视频**：M0 spike 末帧回灌验证（Wan I2V 连续 3-5 段抽末帧回灌，实测漂移 SSIM）→ M2 oneshot.py + `--oneshot --duration N` → M1 关键帧/M3 层级一致性/M4 长文本
   - v14 队友做完后 review 接入

## Critical Context
- git HEAD：`56c8b92 docs:roadmap:change version orders`（重排主体已提交）；**大量代码追修未提交**（v18 部署+五轮 UI/管线追修+快赢三项+Dockerfile 修复）
- Docker：vidance 容器现跑 **full 档 :9401**（host 网络）+ **正式构建镜像 d217e29b19a2（vidance-api:latest）**（npmmirror playwright 源 build 成功，含全部追修+快赢三项）+ 挂载 ../ui:/app/ui:ro + /tmp:/hostlogs/tmp:ro + VIDANCE_LOG_PREFIX=/hostlogs
- 主 Dockerfile（deploy/Dockerfile）已修 trixie 包名 t64 + 清华 apt 源 + npmmirror playwright，**已 build 成功**（之前超时是下载慢被 15min timeout 杀，后台跑即成）；cdn.playwright.dev 不可达（000），npmmirror 200 可达；Dockerfile.update 临时薄镜像已无用可删
- **用户已提交全部改动**（e999d64 docker_deploy_try 覆盖 fastline/svg/健康灯/轮转/Dockerfile/config；54bbbe1/575531e/527d8e7/42ce625 前置），工作区干净
- fastline v2 备选补位容器实测：词 1 两张全废 → 从词 2 备选补位（零重爬、保序）✓；总耗时 276s = Pexels 网络瓶颈（单搜索 50-65s，并发带宽挤占等效串行，外部因素代码已到极限；如需再快可加搜索缓存）
- output/ 现状：assets、quick_20260929_101107（用户真实任务）、svg_20260929_093034/100333/130723（用户+验证，已归位进目录）、tasks.sqlite
- 服务状态：h3(8188)/wan(8189)/flux(8192)/tts(9880)/api 宿主 :8894(旧代码) UP；hunyuan(8190)+h3d(8193) DOWN
- 容器 api :9401 = 最新代码；宿主 api :8894 = 旧代码（start_services 启的，重启才会换）
- fastline 爬图瓶颈（实测）：Pexels API 单次搜索 50-65s（网络慢，无法再省）> 下载 79s > assess 4s/张 > extract 2s；已并行化（省审核+下载串行时间），3 词 Pexels 搜索仍串行约 165s 是下限
- agent.log 行格式 `[HH:MM:SS] ▶/⏳/✓/■`；status 判定必须 `'■' in last` 非 startswith
- agent 总数 28（post 10/generator 7/director 6/audit 5）
- whisper 模型路径需带 snapshots/ 子目录；TestClient/stream 超时会杀 daemon 线程（长链验证给足 timeout 或查盘）
- fastline 图源：Pexels 首选（中文 keyword 必须 LLM 英译），必应兜底；FLUX 仅补足+兜底
- Pexels key 在 config.json pexels.api_key；USTC LLM 双模型：deepseek-v4-flash（编剧/纯文本）、qwen3.8-chat（多模态审片）
- 主 Python：/home/zxy/.conda/envs/comfyui/bin/python；TTS 环境 cosyvoice；4× RTX 4090
- GPU 分配：h3 8188(GPU0)/h3d 8193(GPU1)/wan 8189(GPU2)/hunyuan 8190(GPU3)/flux 8192(GPU3 与 hunyuan 互斥)/tts 9880(GPU2)/api 8894(CPU)
- 测试产物即测即删（用户要求）；误删用户文件是大忌

## Relevant Files
- `/mnt/disk_sdb/zxy/vidance/docs/roadmap.md` — §4 新节序+（原 vN）标注+5 处设计链接+§8 目录树+去重后 549 行（**待提交**）
- `/mnt/disk_sdb/zxy/vidance/docs/usage.md` — 子命令 12 行总览+文档地图+服务依赖补全（**待提交**）
- `/mnt/disk_sdb/zxy/vidance/docs/v11-design.md` — §6 Agent 数 24→28（**待提交**）
- `/mnt/disk_sdb/zxy/vidance/docs/usage-v11.md` — **新建**（多智能体 usage）（**待提交**）
- `/mnt/disk_sdb/zxy/vidance/docs/v12-modules.md`（原 v17-modules，git mv）/`docs/v11-design.md`（原 v13-design）
- `/mnt/disk_sdb/zxy/vidance/AGENTS.md` — 状态/路线/目录/命令注释全按新号（已随 56c8b92 提交）
- `/mnt/disk_sdb/zxy/vidance/core/api_server.py` — agent_records/_vault_final/api/logs/tail/agent_stream/llm 健康灯/copytruncate（**未提交**）
- `/mnt/disk_sdb/zxy/vidance/agents/generator/tools/fastline.py` — 并行爬图+top=2 备选+FLUX 兜底提前（**未提交**）
- `/mnt/disk_sdb/zxy/vidance/agents/generator/tools/svg_pipeline.py` — svg 落盘进任务目录（**未提交**）
- `/mnt/disk_sdb/zxy/vidance/agents/{base,runtime,blackboard}.py` + `core/{vidance,scheduler,narration}.py` — 注释已同步（已提交）
- `/mnt/disk_sdb/zxy/vidance/utils/*.py` — 24 个门面薄壳 docstring 已同步（已提交）
- `/mnt/disk_sdb/zxy/vidance/ui/index.html` — streamAgent/pipe-bar 彩色方块/日志 tab/llm-dot 健康灯/conceptOf（**未提交**）
- `/mnt/disk_sdb/zxy/vidance/deploy/Dockerfile` — trixie t64 包名+清华 apt 源+npmmirror playwright（**未提交**）
- `/mnt/disk_sdb/zxy/vidance/deploy/Dockerfile.update` — 临时薄镜像（CDN 恢复后可删）
- `/mnt/disk_sdb/zxy/vidance/start_services.sh` — bg_run append 模式（**未提交**）
- `/mnt/disk_sdb/zxy/vidance/docs/instructions/commands.json` — v12-modules 链接已同步（已提交）
- `/mnt/disk_sdb/zxy/vidance/config/config.json` — task_prefixes（**未提交**）
- `/mnt/disk_sdb/zxy/vidance/agents/common/tools/config_loader.py` — task_id_for() helper（**未提交**）
