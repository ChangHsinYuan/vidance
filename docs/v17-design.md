# v17（原 v12）整合开源仓库 + 会话资产层 — 设计

> 状态：🎯 计划稿（2026-10-12，未执行）。roadmap 总览见 `docs/roadmap.md` §v17。
> v17 两条主线：①吸收成熟开源工程能力（断点续跑/JSON 容错/RAG 等，原 v12 规划）；②**会话资产层**（buffer + 前端附件 + @ 引用，2026-10-12 新增，本稿重点）。

---

## 0. 为什么需要会话资产层（问题陈述）

现状痛点：
- 上传素材没有正式通道：`input/` 靠手动 cp，WebUI 无法拖图；演示时"参考这张图"只能说路径
- 中间产物散落：agent 产物 `output/agent_{ts}/`、编辑 demo `output/edit_demo/`、编辑工作目录 `*_work/`——没有"这次会话用了什么、产了什么"的视图
- 指令指代靠自然语言："参考下面第一张图"→ LLM 路由易错、t2c 小模型更学不会
- 删除无联动：删任务/会话后，中间产物成孤儿

目标形态（对齐 ChatGPT 体验）：
1. 聊天框可拖拽/粘贴/点按钮上传附件 → 存入 buffer
2. 发命令时 `@1 @2` 引用附件，后端自动替换成真实路径
3. 任务产出可"存入 buffer"复用；删除会话时 buffer 资产联动清理
4. 将来 RAG / t2c SFT 都吃这个资产层的红利（文档索引源、@ 语料格式）

---

## 1. 开源参考与借鉴点

| 仓库 | 借鉴什么 | 落到哪 |
|------|---------|--------|
| **Open WebUI**（open-webui/open-webui） | chat ↔ file 关联模型（chat.files / file.id）；拖拽+粘贴+点击三种上传交互；删除会话级联删文件；附件 chip + 内联预览 | 前端附件交互（M2）、会话删除联动（M1） |
| **Dify**（langgenius/dify） | message.files 统一协议：文件数组随消息提交（type: image/document/video/audio + transfer_method + id/name/size/mime/url） | `/api/tool`、`/api/chat` 的 attachments 字段形状（M1/M3） |
| **Gradio**（gradio-app/gradio） | 临时文件 cache 目录 + TTL 定时清理线程 + max_file_size 限制 | buffer 清理器（M1）：N 天未活动自动清，防无限膨胀 |
| **MoneyPrinterTurbo**（本机 `/mnt/disk_sdb/zxy/MoneyPrinterTurbo/`） | per-task 资产归拢：`tasks/{task_id}/` 一个目录收全中间产物（素材/字幕/音频/成片），删任务=删目录 | buffer 按 session 归拢的目录范式（M1） |
| **ComfyUI** | input/output/temp 三目录分离 + upload 接口即时注册（我们已有 `upload_image(subfolder=)` 实战） | buffer 上传后立即可被 workflow/agent 引用（M1） |
| **OpenCut**（v10 已参考） | 时间线素材按 asset id 引用复用 | buffer 资产在 compose 时间线 JSON 中按 id/@ 引用（M3 延伸） |
| ViMax | checkpoint/resume 断点续跑 | M4（原规划） |
| tenacity | 标准化 API 重试装饰器 | M7（原规划） |

不引入的部分：Open WebUI 的 RAG 全家桶（向量库/嵌入混合检索）——我们 M5 只取 FAISS+BGE 简版；Dify 的多租户/权限模型——单机单用户不需要。

---

## 2. 会话资产层设计（M1-M3）

### 2.1 目录结构（M1）

```
output/
├── buffer/                      # 会话缓冲区根（config 新增 buffer_dir，默认 output/buffer）
│   └── {session_id}/            # 每会话一目录（session_id=uuid4 hex 或前端生成）
│       ├── uploads/             # 用户上传资产（真文件，删除会话时真删）
│       │   └── 20261012_153045_cat.jpg
│       ├── refs.json            # 资产清单：[{id, path, kind, mime, size, created, refs:[job_id...]}]
│       └── archive/             # 归档产物（引用，不拷贝，见 2.4）
└── （output/ 其余结构不动——成片目录铁律不变）
```

- 遵守项目铁律：一切产出以 config `output_dir` 为唯一根，buffer 是其子目录
- session_id 校验：必须 `[0-9a-f]{8,32}`（uuid 形状），防路径穿越；CLI/无会话场景 `session=cli` 兜底目录

### 2.2 API 设计（M1）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/upload` | POST multipart | 上传资产：header/query 带 `session_id`；可选 `as=@序号`；返回 `{asset_id, path, url(/api/file), name, size, mime}` |
| `/api/assets` | GET | 列会话资产（uploads+archive 合并视图，含引用计数） |
| `/api/assets/{asset_id}` | DELETE | 删单个资产（被 job 引用时返回 409 或 `force`） |
| `/api/session/{id}` | DELETE | **删会话=删 buffer/{id}/ 整目录**（联动删除，用户核心诉求）；tasks/dialogs 记录保留（只断链） |

- 上传即注册：图片/视频上传后立刻可作为 `/edit`、`/vace`、`/api/tool/*` 的输入（复用 `/api/file` 预览）
- max_file_size 默认 200MB（config `buffer.max_file_size`）；mime 白名单宽松（img/video/audio/pdf/md/txt）

### 2.3 生命周期（M1）

1. **创建**：首次上传或首次产物归档时懒创建目录
2. **引用**：job 提交时若 args 含 @N / buffer 路径 → refs.json 记 job_id（引用计数）
3. **删除（主动）**：前端删会话 → DELETE /api/session/{id} → uploads 真删 + archive 只删引用记录（output/ 成片不动）+ 关联任务状态标 `session_purged`
4. **删除（兜底 TTL）**：api_server 起守护线程，每天扫 buffer/，`mtime + ttl_days(默认 7)` 过期即删整目录（借鉴 Gradio temp 清理）；有活跃 ref 的可延后
5. **孤儿回收**：refs.json 与磁盘比对，悬空记录清理

### 2.4 产物归档与"引用而非拷贝"（M1/M2）

- 大文件（视频）不双份：job 完成后产物留在 output/ 原位，buffer/archive 记一条 `kind=reference`（存原路径）；小文件（图、mask、SRT）可选真拷贝进 uploads
- 前端视频/图片卡加「存入 buffer」按钮：把该产物注册进当前会话 archive，后续 @ 引用
- **删除会话时：uploads 真删文件、archive 只删记录**——output/ 成片永远安全

### 2.5 前端附件（M2）

对齐 ChatGPT：
- 输入框左侧 📎 按钮 + 整窗拖拽 + Ctrl/V 粘贴图片，三路进同一上传
- 附件 chip 显示在输入框上方（缩略图/文件名+大小，× 可移除）
- 发送时：带附件的请求 `{args: "...", attachments: [asset_id...]}`；命令文本可写 @1 @2
- job 产物卡（视频/图片）右上「存入 buffer」→ 注册进当前 session
- 会话切换：左栏任务列表旁加会话选择器（前端 localStorage 保存 session_id ↔ 历史映射）

### 2.6 @ 引用语法（M3）

**解析优先级**（后端 /api/tool 分发前预处理）：
1. `@N`（N=1..9）→ 第 N 个附件的 buffer 路径；`@N:2` 备选未来扩展（第 N 附件第 2 帧之类，暂不做）
2. 替换后路径强制断言在 buffer/{session_id}/ 内（防穿越）；附件数 < N 报错回显
3. 命令语义不变：@1 就是替换成绝对路径字符串，shlex 解析天然兼容

**LLM 意图层**（/api/chat）：
- 用户消息带附件时，prompt 注入清单：`[附件1: cat.jpg 800x600 图像] [附件2: demo.mp4 视频 12s]`
- system 规则："命令中引用附件一律用 @序号"（few-shot 2 例）
- 用户说"用第一张图做编辑" → LLM 产出 `/edit @1 cutout -o @archive/xxx.png`，替换后进分发

**t2c SFT 语料**（联动 t2c 计划）：
- 训练对格式：`(含指代的中文, 附件上下文) → (命令含 @1)`——如"参考第一张图把狗换成猫"→ `edit @1 ... --engine vace ...`
- @1/@2 在 mt5 词表中拆成普通 token 即可，无需特殊处理；重训语料收集时把本条规则固化进生成脚本

### 2.7 验收标准

- M1：curl 上传→资产可被 /edit 消费→删会话→目录消失且 output/ 成片健在；TTL 清理器单测（伪造过期 mtime）
- M2：浏览器拖图→chip 出现→`/edit @1 visualize` 出结果；产物卡存入 buffer 后可 @ 引用
- M3：`/api/chat` 说"用第二张图"产出命令含 @2 并正确替换；t2c 语料生成脚本产出 ≥50 条 @ 样本

---

## 3. 原有工程整合（M4-M7，原 v12 规划细化）

### 3.1 M4 断点续跑 + JSON 容错
- **借鉴 ViMax**：pipeline 每步（编剧/每镜生成/后处理）输出持久化到任务目录（output/{task_id}/steps/{n}.json + 产物），重启后 `--resume {task_id}` 从最后完整步续跑
- 挂载点：v11 黑板（agent_runs）天然是步进记录，缺的是"步产物指纹 + 幂等重入"；scheduler 任务加 resume 字段
- **JSON 容错**：llm.py 统一出口加容错解析（尾逗号/单引号/markdown 代码栅栏剥离/截断 JSON 补全），替代各处散落的 try/except json.loads；参考 TrailingCommaTolerantParser 思路

### 3.2 M5 五维提示词模板 + RAG
- 模板：`[Visual]主体场景风格 / [Motion]动作节奏 / [Camera]运镜 / [Audio]旁白配乐 / [Narrative]叙事目的`——llm.scriptwrite 输出强制五维字段，T2V prompt 组装时拼全
- RAG：上传文档（buffer uploads 的 pdf/md/txt）→ 切分 → FAISS 索引（bge-small-zh）→ 编剧时可引用长文本素材；BGE Reranker 视效果再加

### 3.3 M6 结构化剧本拆解
- 非结构化文本（小说/新闻）→ LLM 拆 角色(外观/服装锚)/场景(时间/地点)/道具/事件线 → 喂 auto 流水线 character/scene 参数；输出 schema 复用 v3 资产库（asset_registry）便于角色复用

### 3.4 M7 嵌入 + 重试标准化
- all-MiniLM-L6-v2 ONNX（CPU 可跑）：buffer 资产语义检索（"那张雪山的图"→ 按嵌入找）、镜头间场景关联
- tenacity 统一重试：llm/tts/comfy 三客户端的重试逻辑收敛为装饰器（现各写各的）

---

## 4. 里程碑总表

| 里程碑 | 内容 | 依赖 |
|--------|------|------|
| M1 | buffer 目录+上传 API+会话联动删除+TTL 清理 | 无（纯 api_server + 文件系统） |
| M2 | 前端附件（拖拽/粘贴/chip/产物存入） | M1 |
| M3 | @ 引用（后端替换+LLM 意图规整+t2c 语料格式） | M1（前端 chip 可后置） |
| M4 | 断点续跑 + JSON 容错 | v11 黑板 |
| M5 | 五维提示词 + RAG（索引源=buffer 文档） | M1 |
| M6 | 剧本结构化拆解 | M4/M5 |
| M7 | 嵌入检索 + tenacity 重试标准化 | M1 |

建议执行顺序：M1→M2→M3（资产层先立，用户体验见效快）→ M4 → M5 → M6/M7。

## 5. 风险与边界

- **路径安全**：@ 替换/session_id/asset_id 全部白名单校验，杜绝 `..` 穿越；删除操作限定 buffer/ 内
- **output/ 铁律**：buffer 只增 uploads 子目录与引用记录，不改成片目录结构
- **磁盘膨胀**：TTL + max_file_size + archive 引用不拷贝，三重防膨胀
- **与 /api/file 的关系**：buffer 文件预览复用现有 /api/file?path=（已支持任意 output/ 下路径）
- **前端零 npm 约束**：附件 chip/拖拽均原生 JS 实现（index.html 自包含惯例不破）
