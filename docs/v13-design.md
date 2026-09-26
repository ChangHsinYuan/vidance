# v13 设计 — 多智能体系统（薄包装版）

> 2026-09-26 定稿并实施（M0-M4 全部完成 + v13.1 前端 /arch 架构图与 chain trace 可视化）。roadmap 见 docs/roadmap.md v13 段。

## 1. 动机与定案

v0-v10/v17 的能力都散在 `utils/` 平铺模块里，由 `core/pipeline.py` 等巨型编排器串死。v13 的目标**不是重写**，而是：

1. **物理分层**——按 D(决策/编剧) / G(生成) / P(后期) / V(审核) + common 五目录归置代码，看清依赖方向（core → agents 层 → common）；
2. **薄包装 Agent**——每个既有能力用 ~10 行包装成统一契约的 Agent，可被链/远程调用，不做自主 LLM 循环（拍板：薄包装，v14+ 再考虑自主性）；
3. **黑板**——所有 Agent 运行记录进 SQLite 一张表，trace 可查；
4. **chain 编排**——声明式 JSON 步骤链，产物经 `${ctx.key}` 传递；
5. **ensemble**——审核层多模型投票基础设施，默认单票（可扩）。

## 2. 目录布局

```
agents/
├── base.py                # TaskResult + @register + REGISTRY + run_agent(计时/兜底/落盘)
├── blackboard.py          # AgentBoard: output/tasks.sqlite 的 agent_runs 表
├── runtime.py             # load_all() + run_chain(steps, ctx) + $() 模板解析
├── director/{__init__.py, agents.py, tools/dialog.py}
├── generator/{__init__.py, agents.py, tools/{comfy_api,rife,mesh_render,hunyuan3d,
│              splat_renderer,vendor,model_router,fastline,svg_llm,svg_pipeline,
│              h3_prompt_video}.py}
├── post/{__init__.py, agents.py, tools/{effects,compose,ffmpeg_tools,music,
│         gen_luts,stt,funclip}.py}
├── audit/{__init__.py, agents.py, tools/}          # V 包装 llm 审片方法，tools 暂空
└── common/{__init__.py, tools/{llm,tts,config_loader,crawler,asset_crawler,
           asset_registry,voice_clone,t2c_server}.py}   # 共享基础设施（无 agents.py）
```

- **迁移机制**：`utils/<x>.py` 原路径保留**薄壳**（`sys.modules[__name__] = importlib.import_module('agents.……')`；`__main__` 时 runpy 转发并补 sys.path）→ 旧 import、旧 CLI、api_server 全部零破坏。
- **不迁移**：`utils/tts_server.py`（start_services 按路径启动）、`utils/{workflows,luts}`、`bgm/` 数据目录——迁移文件内 `__file__` 根路径统一改 4 级 `dirname`：

```python
_ROOT = os.path.abspath(__file__)
for _ in range(4): _ROOT = os.path.dirname(_ROOT)   # agents/X/tools/f.py → 项目根
```

## 3. Agent 契约

```python
from agents.base import TaskResult, register

@register(name='post.fx', layer='post', desc='…', inputs='{video, effect, …}',
          needs_gpu=False)
def fx(params: dict) -> TaskResult: ...
```

- `TaskResult{agent, ok, artifacts:{k:v}, trace:[{step,…}], score|None, error}`
- `run_agent(name, params, board, task_id)`：注册表分发 + 计时 + 异常兜底 + 黑板落盘（黑板失败不影响主流程）。
- 链不回环：重试闭环留在原模块内部（pipeline 审片重试不受影响）。

## 4. 黑板（`agent_runs` 表，复用 tasks.sqlite）

| 列 | 说明 |
|---|---|
| task_id / agent / layer | 归属 |
| ok / score / error | 结果（score 归一 0-1） |
| artifacts_json | 产物（视频路径、脚本 dict、votes…） |
| t_start / t_dur | 时间 |

查询：`GET /api/agents/board`、`GET /api/tasks/{id}/trace`。

## 5. chain 运行器

```json
{"task_id": "demo", "ctx": {},
 "steps": [
   {"agent": "director.scriptwrite", "with": {"concept": "柴犬做早餐", "target_duration": 12}, "as": "sw"},
   {"agent": "director.select_lut",  "with": {"script": "${sw.script}"}},
   {"agent": "post.compose",         "with": {"timeline": "${tl}"}, "optional": true}
 ]}
```

- `"${key}"` 整体引用 → 原物传参（dict/list 保类型）；字符串内嵌 `${key}` → 文本替换。
- 产物以 `as.artifact` 和裸 `artifact` 双键并入 ctx；步骤失败即停（`optional:true` 跳过继续）。
- 入口三件套：`python -m agents.runtime '{…}'`、`vidance.py agent chain steps.json`、`POST /api/agents/chain`；scheduler `mode='chain'` 走队列（进程内执行）。

## 6. 注册 Agent 清单（24）

| 层 | Agent | 包装对象 |
|---|---|---|
| D | director.scriptwrite | llm.script_write |
| D | director.scout | crawler.fetch_hot_topics + llm.scout_topics |
| D | director.select_lut / select_bgm / select_effects | llm 三选 |
| D | **director.brain**（智囊） | llm.chat / chat_json（model 可换任意 LLM） |
| G | generator.svg / fast / wan_t2v | SvgLine.run / FastLine.run / Pipeline(quick 语义) |
| G | **generator.artist**（美术师） | comfy flux/sdxl t2i + AssetCrawler 爬图互备 |
| P | post.tts / compose / lut / bgm / subtitle_burn / stt / fx / transition | Narrator / run_timeline / PostProcessor / effects / stt |
| P | **post.voice**（配音师） | TTSClient 多引擎（edge/cosy/克隆）+ 音色降级链 |
| V | audit.review_shot / review_character / relevance / describe_character / **review_ensemble** | llm 审片系 / 多票投票 |

## 7. API

- `GET /api/agents` — 注册表
- `POST /api/agents/{name}/run` `{params, task_id}` — 单跑
- `POST /api/agents/chain` `{steps, ctx, task_id}` — 链
- `GET /api/agents/board?task_id&limit`、`GET /api/tasks/{id}/trace`
- `POST /api/tasks` `{mode:'chain', chain:[…], ctx:{…}, concept:'标签'}` — 排队链任务

## 8. 验证记录（2026-09-26）

- 27 模块旧/新别名同一性；core 7 模块 import；壳 CLI（compose/llm/stt）；端到端 `split --precise`
- 三步 LLM 链 61s 全通：编剧(柴犬的太空早餐) → LUT(cinematic) → 审片(score 2/10，正确识别静态图)
- scheduler chain 任务：queued→completed，output 回写，scheduler.log 含 chain result JSON，`agent_runs` 落盘

## 9. v13.1 前端可视化 + 角色包装（2026-09-26）

- **`/arch`**：`tool_dispatch('arch')` 返回分层骨架（core/D/G/P/V/common，每层含运行时注册 Agent + 实现模块清单），`ui/index.html renderArch()` 渲染彩色分层卡片（core 紫/D 橙/G 蓝/P 绿/V 红/common 灰，⚡=需 GPU）；数据实时取自注册表。
- **chain trace**：任务卡检测 `options.mode==='chain'` → 卡片内 trace 子区，轮询时 `GET /api/tasks/{id}/trace` 渲染步骤时间线（`#步骤 层`徽章 + ✓/✗ + 评分 + 错误 + 耗时）；`/agent run|chain` 结果同用 `traceRows()` 渲染，产物含 video 自动内嵌播放。
- `/agent` 命令：`list` 注册表 / `run <name> --with '<json>'` / `chain --steps '<json>'`（CLI/API/UI 三端同源）；`--with/--steps` **贪婪捕获**到行尾（UI 里 JSON 不带引号、含空格也不会被 shlex 切碎）。
- **角色包装 Agent（21→24）**：`generator.artist` 美术师（`engine: flux|sdxl|crawl` 生图/爬图拿原材料，爬落兜 FLUX）；`post.voice` 配音师（多引擎+音色降级链 edge/cosy/克隆）；`director.brain` 智囊（`{prompt, model?, json?}` 任意 LLM 一问一答）。
- **修复**：①`${ctx.key}` 与 `${key}` 双语法（runtime `_lookup`）；②P/G/D 层 `load_config` 误从 compose 导入（M0 迁移遗留，`_post()` 连带修复，post.lut 回归通过）；③`post.lut` 接受 `style` 别名；④`/arch` inputs 字符串渲染崩溃。
- 快速用法：UI 直敲 `/agent chain --steps {"steps":[{"agent":"post.lut","as":"c","with":{"video":"/in.mp4","lut":"warm","out_path":"/tmp/l.mp4"}},{"agent":"post.fx","with":{"video":"${c.video}","effect":"zoom","out_path":"/tmp/f.mp4"}}]}`；排队异步 `POST /api/tasks {"mode":"chain","chain":[…],"ctx":{}}`。

## 10. v13.2 闭环与 GPU 注册（2026-09-26）

- **pipeline 审片接 ensemble**：`_safe_review_shot` 按 config `review.ensemble.{enabled, models}` 走 `audit.review_ensemble`（`run_agent` 落台账，task=pipeline），返回映射回 pipeline 口径（score×10、全票 pass、feedback 拼接）；全票失败/异常**自动回退单票**不崩。默认关。实测双票 (7✓,5✗)→score 6.0 pass=False。
- **Agent 注册（24→28）**：`generator.h3shot`（prompt+refs→H3 有声单镜）、`generator.splat`（单图→3DGS PLY，实测 17.8MB）、`post.pip`（画中画 overlay，svg→glitch→pip 三连实测出片）、`generator.mesh`（图→GLB，Hunyuan3D 离线时干净报错）。
- **根治**：`run_agent` 未注册名自举 `load_all()`（此前 host 不调 load_all 会得到 unknown agent）。

## 11. Backlog

/ui 链视图（DAG 图）；h3shot 实卡长测；v11 网关复用 agent API；chain 并联/断点。
