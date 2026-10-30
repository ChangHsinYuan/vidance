# v17（原 v12）整合开源仓库 + 会话资产层 — 设计

> 状态：✅ 已关版（2026-10-30，M1-M7 全绿；本文为设计原稿，实现状态以 [roadmap.md](../roadmap.md) §v17 与 [usage-v17.md](../usage/usage-v17.md) 为准）。
> v17 两条主线：①**会话资产层**（buffer + 前端附件 + @ 引用，M1-M3）；②工程能力整合（断点续跑/JSON 容错/RAG/剧本拆解，M4-M7）。
> 参考项目：**MoneyPrinterTurbo、ViMax、Toonflow、BigBanana** 四个同类开源项目——借鉴它们已验证的工程做法，不重复造轮子。

---

## 0. 为什么需要会话资产层（问题陈述）

现状痛点：
- 上传素材没有正式通道：`input/` 靠手动 cp，WebUI 无法拖图；演示时"参考这张图"只能说路径
- 中间产物散落：agent 产物 `output/agent_{ts}/`、编辑 demo `output/edit_demo/`、编辑工作目录 `*_work/`——没有"这次会话用了什么、产了什么"的视图
- 指令指代靠自然语言："参考下面第一张图"→ LLM 路由易错、t2c 小模型更学不会
- 删除无联动：删任务/会话后，中间产物成孤儿

目标形态（对齐 ChatGPT / Toonflow 体验）：
1. 聊天框可拖拽/粘贴/点按钮上传附件 → 存入 buffer
2. 发命令时 `@1 @2` 引用附件，后端自动替换成真实路径
3. 任务产出可"存入 buffer"复用；删除会话时 buffer 资产联动清理
4. 将来 RAG / t2c SFT 都吃这个资产层的红利（文档索引源、@ 语料格式）

---

## 1. 参考项目与借鉴点（四个主力仓库）

### 1.1 MoneyPrinterTurbo（本机 `/mnt/disk_sdb/zxy/MoneyPrinterTurbo/`，可深读源码）

一站式 AI 短视频生成（harry0703，40k+ stars）。**本机已克隆，逐文件研究过，借鉴点最实**：

| 它的做法 | 在哪 | 我们借鉴到 |
|---------|------|-----------|
| **per-task 目录归拢**：`storage/tasks/{task_id}/` 一个目录收全该任务产物（素材/字幕/音频/成片），删任务=删目录 | `app/utils/utils.py::task_dir` | M1 buffer 按 session 归拢的目录范式 + 删除联动语义 |
| **原子写 JSON 清单**：临时文件与目标同目录 + fsync + `os.replace`，进程中断不留半个文件；`patch_script_data` 失败降级不阻断主流程 | `app/services/task_artifacts.py` | M1 buffer 的 `refs.json` 资产清单写入（原子性）；M4 断点续跑的步产物持久化 |
| **可插拔状态后端**：`BaseState` ABC → MemoryState / RedisState 双实现，API 不变 | `app/services/state.py` | M1 会话状态接口设计（先用 SQLite，留后端扩展位） |
| **年龄驱动缓存清理**：扫描缓存目录按 mtime/max_age 出清理候选 + 统计 + 结果对象 | `app/services/cache_manager.py` | M1 buffer TTL 清理器（比定时器式更稳，直接仿写） |
| **上传文件名净化 + 路径围栏**：文件名剥目录只留 basename（防 `../` 穿越）；`resolve_path_within_directory` 强制解析结果在基目录内，越界 403 | `app/controllers/v1/video.py::_sanitize_upload_filename`、`file_security` | M1 `/api/upload` 安全校验（照抄思路，Python 实现同款） |
| **素材目录可配置**：`material_directory = "task"` 时素材存进任务目录 | `config.example.toml` | M1 config `buffer.*` 配置项设计 |

> **2026-10-13 源码级调研收口**：全量通读核心 8700 行后的分档结论（强烈推荐/已有等价物/看情况）落 `docs/research/mpt-research.md`——新增高性价比候选：字幕 Levenshtein 纠正（subtitle.py `correct()`）、preflight 预检（task.py）、素材 URL-md5 全局缓存+下载后验证（material.py `save_video()`）、搜索结果 24h TTL 缓存（material_cache.py）。

### 1.2 ViMax（HKUDS/ViMax，12.6k stars，Agentic 视频生成）

Director/Screenwriter/Producer/Video Generator 一体化 agent 流水线。借鉴其**会话与断点**（v1.2.0 已验证）：

| 它的做法 | 我们借鉴到 |
|---------|-----------|
| **命名项目 + 会话复用**：`vimax tui resume <session_id>`，agent 会话可挂起、恢复、上下文压缩 | M1 session_id 概念对齐（我们的 session 绑 buffer 目录 + 任务历史）；M4 断点续跑按 session/task 恢复 |
| **渲染 checkpoint**：render status 持久化，Script2Video 中断后从断点续跑（2026-06-28 修复记录） | M4 pipeline 每步产物指纹 + 幂等重入（挂 v11 黑板 agent_runs） |
| **Web UI 三件套**：命名项目管理 / artifact 与 storyboard 预览 / 渲染进度可视 + 文件上传 | M2 前端附件 + 产物卡（我们已有 job 卡轮询，补上传与 artifact 预览入口） |
| **LLM 重试强化**：多级重试统一封装 | M7 tenacity 重试标准化（ViMax 是需求背书，实现用 tenacity） |

### 1.3 Toonflow（HBAI-Ltd/Toonflow-app，17.4k stars，短剧/漫剧工作台）

开源 AI 视频创作平台（无限画布 + Agent + 可视化工作流）。**本机已克隆，源码级借鉴**：

| 它的做法 | 在哪 | 我们借鉴到 |
|---------|------|-----------|
| **工作区资产目录 + 树形 API**：`assets/` 目录独立于代码，list/mkdir/read 三个 route 返回树形结构（相对路径统一 `/`） | `apps/server/src/routes/assets/`、`utils/assets/index.ts` | M1 `/api/assets` 列表接口的返回结构（树形 + 相对路径） |
| **@ mention 资产系统**：`MentionAsset {path,name,type,dataType,preview}` + 游标分页查询（`MentionQuery {query,cursor,limit}`）→ 注入 agent 消息上下文 | `agent/mentionSources.ts`、`agent/mentionFiles.ts`、`agent/runtime/mentions.ts` | **M3 @ 引用的直接原型**——我们的 `@N` 是其简化特例（按附件序号），将来可扩展成 `@文件名` 模糊搜索 + 缩略图 chip（照它的 MentionAsset 形状设计数据结构，留扩展位） |
| **路径围栏 + 乐观并发**：`isWithin/protectWorkspaceRoot` 防穿越；写文件带 sha256 revision，不匹配 409 ESTALE；文件锁 | `utils/workspace/files.ts`、`utils/assets/index.ts::writeAssetFile` | M1 删除/上传的并发安全（revision 校验防"读-改-写"竞态） |
| **资产大小硬限**：单文件 100MB 上限（读/写双查） | `utils/assets/index.ts::maxAssetBytes` | M1 max_file_size 默认值直接取同款（我们 200MB，视频更大） |
| **插件/MCP/node 扩展体系**、无限画布 | `packages/mcp`、`packages/nodes` | 远期（不在 v17 范围，记录思路：agent 工具即 node） |

### 1.4 BigBanana（shuyu-labs/BigBanana-AI-Director，2.3k stars，工业化短剧导演）

"Script-to-Asset-to-Keyframe" 工业化工作流（反抽卡式生成）。借鉴其**资产先行的生产范式**：

| 它的做法 | 我们借鉴到 |
|---------|-----------|
| **四阶段流水线**：叙事规划→一致性资产（角色/场景/道具）→镜头制作（关键帧）→成片交付 | M6 剧本拆解的阶段划分直接对齐（结构化剧本→资产→镜头） |
| **角色一致性三重保障**：①定妆照系统（全片视觉锚点）②衣橱系统（多套造型基于 Base Look，换衣不换脸）③上下文感知生成（镜头自动读取当前场景图+服装+道具参考） | ①我们 v1 角色锚已有雏形；②prompt 级已实现（`optimize_costume_prompts` Base Look 锁脸 + `m6_wardrobe_test.py` 孔乙己 3 造型实测，2026-10-30）；③拆解 schema 正式接入（角色卡 costume 列表→镜头自动注入对应资产）归 v18 |
| **关键帧驱动**：先生成首尾帧（受资产约束）再插值 | 原本 v18 一镜到底/关键帧驱动的主参考（记录，不在 v17 实现） |
| **提示词管理面板**：prompt 资产化、可复用 | M5 五维提示词模板的管理形态参考（模板存成可复用资产而非散在代码） |

### 1.5 借鉴总原则

- **只抄机制不抄栈**：四个项目分别是 Python-FastAPI / TS-Node 混合栈，我们只取设计（目录范式/接口形状/安全校验/清理策略），全部用现有 Python 栈实现
- **MPT 本机可读**：实现细节随时翻源码；Toonflow 已克隆到 `/tmp/opencode/Toonflow-app`（关键文件提到后建议留档）；ViMax/BigBanana 只取 README 级机制
- **不引入的**：Toonflow 无限画布/MCP/插件体系、BigBanana 关键帧驱动（归 v18）、ViMax 上下文压缩（v11 黑板够用）

---

## 2. 会话资产层设计（M1-M3）

### 2.1 目录结构（M1，范式来自 MPT task_dir + Toonflow workspace）

```
output/
├── buffer/                      # 会话缓冲区根（config 新增 buffer_dir，默认 output/buffer）
│   └── {session_id}/            # 每会话一目录（session_id=uuid4 hex 或前端生成）
│       ├── uploads/             # 用户上传资产（真文件，删除会话时真删）
│       │   └── 20261012_153045_cat.jpg
│       ├── refs.json            # 资产清单：[{id, path, kind, mime, size, sha256, created, refs:[job_id...]}]
│       └── archive/             # 归档产物（引用，不拷贝，见 2.4）
└── （output/ 其余结构不动——成片目录铁律不变）
```

- 遵守项目铁律：一切产出以 config `output_dir` 为唯一根，buffer 是其子目录
- session_id 校验：必须 `[0-9a-f]{8,32}`（uuid 形状，仿 Toonflow workspace protect），防路径穿越；CLI/无会话场景 `session=cli` 兜底目录
- `refs.json` 原子写（仿 MPT `_write_json_atomic`：同目录临时文件 + fsync + os.replace）；写前带 sha256 revision，竞态时 409（仿 Toonflow ESTALE）

### 2.2 API 设计（M1）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/upload` | POST multipart | 上传资产：header/query 带 `session_id`；返回 `{asset_id, path, url(/api/file), name, size, mime, sha256}` |
| `/api/assets` | GET | 列会话资产（uploads+archive 合并树形视图，含引用计数；返回结构仿 Toonflow assets/list：相对路径统一 `/`） |
| `/api/assets/{asset_id}` | DELETE | 删单个资产（被 job 引用时 409 或 `force`） |
| `/api/session/{id}` | DELETE | **删会话=删 buffer/{id}/ 整目录**（联动删除，用户核心诉求）；tasks/dialogs 记录保留（只断链） |

- 上传即注册：图片/视频上传后立刻可作为 `/edit`、`/vace`、`/api/tool/*` 的输入（复用 `/api/file` 预览）
- **安全三件套**（MPT + Toonflow 混合）：①文件名净化只留 basename ②`resolve_path_within_directory` 越界 403 ③单文件 200MB 上限（config `buffer.max_file_size`）
- mime 白名单宽松（img/video/audio/pdf/md/txt）

### 2.3 生命周期（M1，TTL 直接仿 MPT cache_manager）

1. **创建**：首次上传或首次产物归档时懒创建目录
2. **引用**：job 提交时若 args 含 @N / buffer 路径 → refs.json 记 job_id（引用计数）
3. **删除（主动）**：前端删会话 → DELETE /api/session/{id} → uploads 真删 + archive 只删引用记录（output/ 成片不动）+ 关联任务状态标 `session_purged`
4. **删除（兜底 TTL）**：api_server 起守护线程每天扫 buffer/，仿 MPT `clean_video_cache` 按 mtime+max_age 出清理候选（默认 7 天），有活跃 ref 的延后；清理动作返回统计对象便于日志
5. **孤儿回收**：refs.json 与磁盘比对，悬空记录清理

### 2.4 产物归档与"引用而非拷贝"（M1/M2）

- 大文件（视频）不双份：job 完成后产物留在 output/ 原位，buffer/archive 记一条 `kind=reference`（存原路径 + sha256）；小文件（图、mask、SRT）可选真拷贝进 uploads
- 前端视频/图片卡加「存入 buffer」按钮：把该产物注册进当前会话 archive，后续 @ 引用（对齐 ViMax Web UI 的 artifact 预览管理）
- **删除会话时：uploads 真删文件、archive 只删记录**——output/ 成片永远安全

### 2.5 前端附件（M2，交互对齐 ChatGPT，原型=ViMax Web UI + Toonflow mention UI）

- 输入框左侧 📎 按钮 + 整窗拖拽 + Ctrl/V 粘贴图片，三路进同一上传
- 附件 chip 显示在输入框上方（缩略图/文件名+大小，× 可移除；数据形状仿 Toonflow `MentionAsset`：path/name/preview）
- 发送时：带附件的请求 `{args: "...", attachments: [asset_id...]}`；命令文本可写 @1 @2
- job 产物卡（视频/图片）右上「存入 buffer」→ 注册进当前 session
- 会话切换：左栏任务列表旁加会话选择器（前端 localStorage 保存 session_id ↔ 历史映射）
- 零 npm 约束不破：原生 JS 实现

### 2.6 @ 引用语法（M3，原型=Toonflow mentionSources 的简化特例）

**解析优先级**（后端 /api/tool 分发前预处理）：
1. `@N`（N=1..9）→ 第 N 个附件的 buffer 路径；`@N:2` 备选未来扩展（第 N 附件第 2 帧之类，暂不做）
2. 替换后路径强制断言在 buffer/{session_id}/ 内（复用 2.2 的路径围栏，防穿越）；附件数 < N 报错回显
3. 命令语义不变：@1 就是替换成绝对路径字符串，shlex 解析天然兼容
4. **扩展位**：数据结构按 Toonflow `MentionAsset` 形状设计（path/name/preview/dataType），将来可加 `@文件名` 游标分页模糊搜索（`MentionQuery {query,cursor,limit}` 同款），前端 chip 直接升级为搜索建议下拉

**LLM 意图层**（/api/chat）：
- 用户消息带附件时，prompt 注入清单：`[附件1: cat.jpg 800x600 图像] [附件2: demo.mp4 视频 12s]`（仿 Toonflow 把 mention 资产注入 agent 上下文）
- system 规则："命令中引用附件一律用 @序号"（few-shot 2 例）
- 用户说"用第一张图做编辑" → LLM 产出 `/edit @1 cutout -o @archive/xxx.png`，替换后进分发

**t2c SFT 语料**（联动 t2c 计划）：
- 训练对格式：`(含指代的中文, 附件上下文) → (命令含 @1)`——如"参考第一张图把狗换成猫"→ `edit @1 ... --engine vace ...`
- @1/@2 在 mt5 词表中拆成普通 token 即可，无需特殊处理；重训语料收集时把本条规则固化进生成脚本

### 2.7 验收标准

- M1：curl 上传→资产可被 /edit 消费→删会话→目录消失且 output/ 成片健在；TTL 清理器单测（伪造过期 mtime）；并发上传同一 refs.json 无损坏（sha256 revision 冲突 409）
- M2：浏览器拖图→chip 出现→`/edit @1 visualize` 出结果；产物卡存入 buffer 后可 @ 引用
- M3：`/api/chat` 说"用第二张图"产出命令含 @2 并正确替换；t2c 语料生成脚本产出 ≥50 条 @ 样本

---

## 3. 工程能力整合（M4-M7，原 v12 规划，参考项目映射）

### 3.1 M4 断点续跑 + JSON 容错（ViMax checkpoint + MPT 原子清单）

- **ViMax render checkpoint** 证明需求：agent 流水线中断后按 session/task 续跑是刚需。实现：
  - pipeline 每步（编剧/每镜生成/后处理）输出持久化到 `output/{task_id}/steps/{n}.json` + 产物路径（**原子写直接移植 MPT `_write_json_atomic`**）
  - 重启后 `--resume {task_id}`：读 steps/ 找最后完整步（产物指纹校验：文件存在 + sha256 对上），从下一步续跑
  - 挂载点：v11 黑板（agent_runs）天然是步进记录，补"步产物指纹 + 幂等重入"；scheduler 任务加 resume 字段
- **JSON 容错**：llm.py 统一出口加容错解析（尾逗号/单引号/markdown 代码栅栏剥离/截断 JSON 补全），替代各处散落的 try/except json.loads；参考 TrailingCommaTolerantParser 思路

### 3.2 M5 五维提示词模板 + RAG（模板管理参考 BigBanana 提示词面板）

- 模板：`[Visual]主体场景风格 / [Motion]动作节奏 / [Camera]运镜 / [Audio]旁白配乐 / [Narrative]叙事目的`——llm.scriptwrite 输出强制五维字段，T2V prompt 组装时拼全
- 模板资产化（BigBanana 思路）：常用模板存 buffer/资产库可复用，不散在代码里
- RAG：上传文档（buffer uploads 的 pdf/md/txt）→ 切分 → FAISS 索引（bge-small-zh）→ 编剧时可引用长文本素材；BGE Reranker 视效果再加

### 3.3 M6 剧本结构化拆解 + 一致性资产（BigBanana 四阶段 + 三重保障）

- 非结构化文本（小说/新闻）→ LLM 拆 **四阶段对齐的结构**：角色(定妆照描述/衣橱)/场景(时间/地点)/道具/事件线 → 喂 auto 流水线
- **一致性三重保障的落地**（BigBanana 核心）：
  - 定妆照 = 我们 v1 角色锚（已有，复用）
  - 衣橱 = 角色多套造型基于同一 Base Look 生成（prompt 级已实现：`agents/common/tools/llm.py optimize_costume_prompts` + `input/rag_test/m6_wardrobe_test.py`；拆解 schema 正式接入归 v18）
  - 上下文感知生成 = 每镜生成时自动注入当前场景图+角色服装+道具参考（联动 v3 资产库 asset_registry，M6 实现）
- 输出 schema 复用 asset_registry 便于角色/场景跨集复用

### 3.4 M7 嵌入 + 重试标准化

- all-MiniLM-L6-v2 ONNX（CPU 可跑）：buffer 资产语义检索（"那张雪山的图"→ 按嵌入找）、镜头间场景关联
- tenacity 统一重试：llm/tts/comfy 三客户端的重试逻辑收敛为装饰器（ViMax 多级重试是同款需求背书）

---

## 4. 里程碑总表

| 里程碑 | 内容 | 主参考 | 依赖 |
|--------|------|--------|------|
| M1 ✅ | buffer 目录+上传 API+会话联动删除+TTL 清理 | MPT（task_dir/原子写/TTL/安全）+ Toonflow（围栏/revision） | 无 |
| M2 ✅ | 前端附件（拖拽/粘贴/chip/产物存入） | ViMax Web UI + Toonflow MentionAsset 形状 | M1 |
| M3 ✅ | @ 引用（后端替换+LLM 意图规整+t2c 语料格式） | Toonflow mentionSources（简化特例） | M1 |
| M4 ✅ | 断点续跑 + JSON 容错 | ViMax checkpoint + MPT 原子清单 | v11 黑板 |
| M5 ✅ | 五维提示词 + RAG（索引源=buffer 文档） | BigBanana 提示词面板 | M1 |
| M6 ✅ | 剧本结构化拆解 + 一致性资产（定妆照/衣橱/上下文注入） | BigBanana 四阶段+三重保障 | M4/M5 + v3 资产库 |
| M7 ✅ | 嵌入检索 + tenacity 重试标准化 | ViMax 重试强化 | M1 |

建议执行顺序：M1→M2→M3（资产层先立，用户体验见效快）→ M4 → M5 → M6/M7。

## 5. 风险与边界

- **路径安全**：@ 替换/session_id/asset_id 全部白名单校验 + MPT 式 basename 净化 + 越界 403，杜绝 `..` 穿越；删除操作限定 buffer/ 内
- **output/ 铁律**：buffer 只增 uploads 子目录与引用记录，不改成片目录结构
- **磁盘膨胀**：TTL（仿 MPT cache_manager）+ max_file_size + archive 引用不拷贝，三重防膨胀
- **并发**：refs.json 原子写 + sha256 revision 乐观锁（Toonflow ESTALE 同款），防多 job 同时归档竞态
- **与 /api/file 的关系**：buffer 文件预览复用现有 /api/file?path=（已支持任意 output/ 下路径）
- **前端零 npm 约束**：附件 chip/拖拽均原生 JS 实现（index.html 自包含惯例不破）
- **参考仓库时效**：ViMax/BigBanana 仅 README 级研究（本机未克隆）；如实现中发现机制拿不准，优先回 MPT/Toonflow 源码找同款实现
