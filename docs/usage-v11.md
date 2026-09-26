# usage-v11 — 多智能体系统（原 v13）

> 三层 Agent 物理分层（D 导演 / G 生成 / P 后期 / V 审片）+ 薄包装 + chain 编排。设计见 [v11-design.md](./v11-design.md)。

## CLI

```bash
# 列出全部 Agent（28 个，按层排序，GPU 依赖标注 [GPU]）
python core/vidance.py agent list

# 单跑一个 Agent（--with 传 JSON 参数；缺省产物写 output/agent_{ts}_{名}/）
python core/vidance.py agent run post.fx --with '{"video":"a.mp4","effect":"zoom"}'
python core/vidance.py agent run director.brain --with '{"prompt":"帮我规划一个 3 镜脚本"}'

# 跑一条链（参数为 JSON 字符串或 JSON 文件路径；失败退出码 1）
python core/vidance.py agent chain '{"steps":[{"agent":"director.brain","with":{"prompt":"..."},"as":"brain"}]}'
python core/vidance.py agent chain chain.json --task-id mytask
```

## API（:8894）

| 端点 | 说明 |
|------|------|
| `GET /api/agents` | 注册表（28 Agent + 参数 schema） |
| `POST /api/agents/{name}/run` | 单跑 `{params, task_id}` |
| `POST /api/agents/chain` | 同步跑链 `{steps, ctx, task_id}` |
| `POST /api/tasks` | 排队链任务 `{"mode":"chain","chain":[{"agent":"post.lut","with":{...}}],"ctx":{},"concept":"标签"}` |
| `GET /api/tasks/{id}/trace` | 链执行轨迹（黑板 agent_runs） |
| `GET /api/agents/board?task_id&limit` | 黑板记录查询 |

## chain 步骤语法

```json
{"agent": "post.lut", "with": {"video": "${fast.artifact}", "lut": "cool"}, "as": "lut", "optional": false}
```

- `agent`：注册名（`python core/vidance.py agent list` 查看）
- `with`：参数对象；`${ctx.key}` 引初始上下文，`${步骤as.artifact}` 引上一步产物
- `as`：产物别名（供后续步骤 `${as.artifact}` 引用）
- `optional`：`true` 时该步失败不中断整链

## 代表性 Agent

| 层 | Agent | 说明 |
|----|-------|------|
| D | `director.brain` | 智囊：llm.chat/chat_json，流式逐 delta 回答 |
| D | `director.scriptwrite` / `scout` | 编剧 / 爬热点选题 |
| G | `generator.svg` / `fast` / `wan_t2v` | SVG 流水线 / 营销号快速链 / T2V |
| G | `generator.artist` | 美术师：FLUX 生图 + 爬图互备 |
| P | `post.tts` / `compose` / `lut` / `bgm` / `stt` / `fx` / `transition` | 配音/拼接/调色/配乐/字幕/特效/转场 |
| V | `audit.review_shot` / `review_ensemble` | 逐镜审片 / 多票投票 |

> 实际清单以 `python core/vidance.py agent list` 为准。

## WebUI（:8894/ui）

- `/arch` — 分层架构图，跑链时按链路实时点亮节点
- `/agent list|run|chain` — Agent 交互面板
- chain 任务卡片内嵌 trace 时间线（每步耗时/产物可展开）
- 📋 日志面板 — tab 切换 台账/wan/flux/tts/api/h3，2s 轮询自动滚动
- 流式：chain 执行经 SSE 推事件（步骤开始/完成 + brain 回答逐 delta 打字）

## 注意

- light/none 档位强制 `max_retries=0`（避免审片重试卡 30 分钟）
- 跑链期间不要重启 api（daemon 随进程死）；并行审片用 `_review_pool` 与下一镜生成重叠
- 产物统一落 `output/{task_id}/`，黑板落 `output/tasks.sqlite` agent_runs 表
