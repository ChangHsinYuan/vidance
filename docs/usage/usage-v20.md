# v20 生成中审核（边生边审）使用指南

> 2026-11-04 实现。开关式旁挂模块：**关 = 原路径一字节不变；开 = 生成调用外套边审 wrapper**。

## 是什么

Wan T2V/I2V 是 diffusion 迭代去噪。本地 ComfyUI 以 `--preview-method latent2rgb` 启动后，采样中的 latent 会经 WS 实时推出模糊预览帧。v20 把这些中间帧丢给多模态 LLM（qwen3.8-chat）**与生成并行粗审**——构图/主体/崩坏早判，判死立即 `POST /interrupt` 止损换 seed 重生成，不再"渲完再审重来"（单镜最坏省 60%+ 生成时间，M0 实测）。

- **粗审**（新）：latent 预览帧，判"值不值得继续生成"，模糊不扣分
- **终审**（原 light/full 不变）：成片关键帧，判细节/伪影——两级正交

## 开关三通道

| 通道 | 用法 | 默认 |
|---|---|---|
| config | `config.json → v20_live_audit.enabled: true`（另有 max_reviews/min_step/timeout） | `false` |
| CLI | `python core/vidance.py auto "概念" --live-audit` | 关 |
| API | `POST /api/tasks {"mode":"auto","live_audit":true,...}` 或 `/api/tool/auto "概念" --live-audit` | 关 |

CLI 开关优先于 config；任务卡 meta 的每镜 `live_audit` 字段记录 reviews/fails/interrupted/逐次 history。

## 前端（:8894/ui）

`--live-audit` 任务运行中，任务卡片下方实时显示**当前粗审预览帧 + verdict + score + 理由**（6s 轮询 `/api/tasks/{id}/preview`）——AI 边画边自检可视化。数据源是 pipeline 落盘的 `output/{task_id}/v20_preview_{shot}.png` + `v20_preview.json`。

## 配置项（config.json `v20_live_audit`）

```json
"v20_live_audit": {
  "enabled": false,     // 总开关
  "max_reviews": 3,     // 每镜最多几次粗审 API（审核比生成慢，必须节流）
  "min_step": 4,        // 步数 <4 不审（早期全白帧无结构，跳过省 API）
  "timeout": 60         // 粗审单次超时；异常一律放行不阻塞生成
}
```

## 模块

| 文件 | 职责 |
|---|---|
| `agents/generator/tools/comfy_preview.py` | `PreviewListener`（WS 收预览帧/进度）+ `interrupt_if_running`（查 /queue 校验归属再 interrupt，防误杀同实例 RIFE）+ `live_audit_patch`（实例级补丁上下文，generate_i2v/t2v 内部调用零改动） |
| `agents/audit/tools/live_auditor.py` | `LiveAuditor`（节流 + 帧结构判定 + 粗审 prompt + 异常放行）、`load_cfg` |
| `core/pipeline.py` | `_process_shot` 生成调用外套 wrapper；EarlyStop → continue 换 seed 重生成；meta 记 live_audit |

## 实测（M0-M2，2026-11-04）

- **M0 spike**：8 张预览帧 WS 推流；step 8/20 interrupt 立即生效（queue 清空，省时 ~60%）；qwen3.8 读 step-8 预览帧："雪地场景，动物"——粗审够用
- **M1 联调**：真实 8189 + 真实 qwen3.8，2 次粗审正常；踩坑：粗审默认走了 `models['script']`（deepseek 无多模态，400）→ 显式用 `models['review']`
- **M2 对比**（同题 3 镜 quick 式，红狐狸）：OFF 895.8s vs ON 929.2s（**+3.7%**，9 次粗审全部藏在生成窗口内）；终审分 7/7/9 vs 7/9/9；meta 每镜 live_audit 落库 ✓
- 早期止损（fail→interrupt→重生成）路径：spike 实测 interrupt + 单测覆盖判定/重生成接线；自然触发 fail 的全链样本未遇（狐狸题全 pass）

## 已知限制

1. 8189 需 `--preview-method latent2rgb`（start_services.sh wan 已加；别的实例没加）
2. `/interrupt` 是实例级——`interrupt_if_running` 先查 `/queue` 校验 prompt_id 归属，但理论上仍有竞态窗口（极小）
3. 粗审 prompt 口径偏宽（模糊不扣分）——挡的是"跑偏/崩坏"，不是画质问题（那是终审的活）
4. latent2rgb 预览色彩有偏（线性插值近似解码），只可用于构图/主体判断
