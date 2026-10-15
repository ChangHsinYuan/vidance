# Vidance t2c 架构 — 自然语言对话 → 命令

> 状态：✅ 已接入（2026-09-24）。模型为 mt5-small 微调，位于 `t2c/`。
> 相关：v6 多轮核实（`utils/dialog.py`）、v7 前端（`ui/index.html`）、v10 指令库（`docs/instructions/`）。

## 1. 目标

让用户用**自然语言**（"帮我做个深海探险的视频"）驱动 Vidance，而不用记斜杠命令/参数。
总体逻辑是自建的一个 **agent_loop**，其中：

- **tool** = Vidance 自己的命令（auto/fast/compose/…）
- **text→command 翻译器** = 自训练的 mt5 微调模型（`t2c/model`），非通用 LLM

## 2. 完整链路

```
用户输入（网页输入框）
  │
  ▼
POST /api/chat ── LLM 判断意图
  ├─ 闲聊/无关  → 直接返回 reply，前端显示（不进创作流）
  └─ 创作意图  → 返回 [[VIDEO:<概念>]]（want_video=true）
        │
        ▼
POST /api/dialog/start / reply ── v6 多轮核实
  （6 维：主体/场景/情绪/风格/时长/镜头感，≤3 轮）
        │  全齐 → status = COMPLETE，返回增强 concept
        ▼
POST /api/t2c ── t2c 模型翻译
  输入：详细需求文本（增强 concept）
  输出：`python core/vidance.py auto "城市夜景"`
        │
        ▼
前端展示建议命令 → 用户点 ▶ 执行
        │
        ▼
POST /api/tool/<name> ── 走 v4 队列 / 直接执行
```

前端对应函数（`ui/index.html`）：
- `sendNatural(text)`：先 `/api/chat`，`want_video` 才转 dialog
- `renderDialog(d)`：COMPLETE 后显示「→ 智能翻译成命令」等 chip
- `t2cTranslate()`：调 `/api/t2c`，把 `python core/vidance.py xxx` 显示成 `/xxx`
- `runT2CCmd(slash)`：点执行 → `send()`

## 3. t2c 组件

### 3.1 模型（`t2c/model`）
- 底座：`google/mt5-small` 微调（8 层，d_model=512）
- 参数：约 600MB（safetensors），CPU 可跑，有 GPU 自动用
- 训练机器：另机训练，效果已人工验证（对**已支持的旧命令**翻译通）
- **已知局限**：目前只覆盖训练时的指令分布；"快速营销号"→`quick` 等会偏。计划在**全部指令（含 v10 剪辑）完成后重训**。

### 3.2 推理封装（`utils/t2c_server.py`）
- `translate(text) -> command`：进程内单例加载模型，线程安全（`_lock`）
- 首次调用加载模型（CPU 约 5s），之后毫秒级
- 可独立起 HTTP：`python utils/t2c_server.py --port 9881`
  - `POST /translate {"text": ...}` → `{text, command}`
  - `GET /health`
- 失败返回空串（不抛异常，调用方降级）

### 3.3 API（`core/api_server.py`）
```
POST /api/t2c   {"text": "帮我用auto模式生成一个城市夜景的视频"}
→ {"text": "...", "command": "python core/vidance.py auto \"城市夜景\"", "runnable": true}
```

## 4. 与前缀对话的关系

| 输入形态 | 路径 |
|----------|------|
| `/auto 概念` | 直接 `dispatchSlash` → `/api/tool/auto`（老路，不走 t2c） |
| 自然语言闲聊 | `/api/chat` → 直接回复 |
| 自然语言创作 | `/api/chat` → dialog → **t2c** → 执行 |

t2c 只服务**自然语言创作**这一支，不替代斜杠命令。

## 5. 网页端测试方法

1. 启动服务：`./start_services.sh`（api 8894 必须在线）
2. 浏览器打开 `http://<host>:8894/ui`，**强刷** Ctrl+Shift+R
3. **测闲聊**：输入「你好，你能干嘛」→ 直接得到聊天回复（不进出片流）
4. **测创作 + t2c**：
   - 输入「我想做一个深海探险的视频」
   - 机器人进入 v6 追问（缺维度就问），逐条回答或说「随便」
   - 全齐后出现 **「→ 智能翻译成命令」** 按钮
   - 点击 → 显示建议命令（如 `/auto "..."`）+ **▶ 执行**
   - 点 ▶ 即提交出片
5. **测斜杠**：直接 `/help`、`/help compose`、`/compose <时间线.json>` 等（不走 t2c）

命令行单独测 t2c：
```bash
python utils/t2c_server.py '帮我用auto模式生成一个城市夜景的视频'
# → python core/vidance.py auto "城市夜景"
```

## 6. 后续

- **模型重训**（用户计划）：等 v10+ 全部指令/剪辑指令稳定后，用 `docs/instructions/*.json` 作为数据源，重训覆盖全量命令 + v10 时间线指令的 t2c
- **agent_loop 化**：目前是"对话→翻译→执行"单跳；后续可让翻译结果进入 tool 调用循环（多步任务）

## 7. 文件清单

| 文件 | 作用 |
|------|------|
| `t2c/model/` | mt5-small 微调模型权重 |
| `t2c/t2c.py` | 训练机的独立推理脚本（原样保留） |
| `utils/t2c_server.py` | 项目内推理封装（`translate` + 可选 HTTP） |
| `core/api_server.py` | `POST /api/t2c` 端点 |
| `ui/index.html` | `t2cTranslate` / `runT2CCmd` 前端接入 |
| `docs/instructions/*.json` | 命令库（未来重训数据源） |
