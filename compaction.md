# Vidance Compaction（2026-09-26 晚）

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
- **提交未提交改动**：v18 部署三件套 + UI 追修五轮（转圈圈/日志/流式/quick/截断/pipe-bar 彩色方块/命名统一/svg 落盘）+ 打磨快赢三项 + gitignore 清理
  - 建议消息：`feat:v18 部署分档 + 全pipeline流式/彩色pipe-bar/输出命名统一/svg截断+落盘修复 + fast爬图并行/日志轮转/llm健康灯`
- **Dockerfile.update 临时薄镜像**：playwright CDN 修复未验证（npmmirror build 超时）；CDN 恢复后重 build 主 Dockerfile，成功后可删 Dockerfile.update

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
1. **提交全部未提交改动**（见 In Progress；commit 前先 git status/diff 复核）
2. CDN 恢复后重 build 主 Dockerfile（trixie 包名已修 + 清华 apt 源 + npmmirror playwright），成功后删 Dockerfile.update
3. 下次开工选项（快赢三项已完成）：
   - **v15 开源整合**：M1 断点续跑（挂 v11 黑板）+ JSON 容错 → M2 五维提示词+RAG（2-3 天）
   - **v16 长视频**：M0 spike 末帧回灌验证（Wan I2V 连续 3-5 段抽末帧回灌，实测漂移 SSIM）→ M2 oneshot.py + `--oneshot --duration N` → M1 关键帧/M3 层级一致性/M4 长文本
   - v14 队友做完后 review 接入

## Critical Context
- git HEAD：`56c8b92 docs:roadmap:change version orders`（重排主体已提交）；**大量代码追修未提交**（v18 部署+五轮 UI/管线追修+快赢三项+Dockerfile 修复）
- Docker：vidance 容器现跑 **full 档 :9401**（host 网络）+ 镜像 e306d8d82502（薄镜像：老镜像+最新代码，含全部追修+快赢三项）+ 挂载 ../ui:/app/ui:ro + /tmp:/hostlogs/tmp:ro + VIDANCE_LOG_PREFIX=/hostlogs
- 主 Dockerfile（deploy/Dockerfile）已修 trixie 包名 t64 + 清华 apt 源 + npmmirror playwright，但整 build 未走通（playwright CDN/npmmirror 均超时）；CDN 恢复后重 build
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
