# novel2video — 小说成片技能

小说章节 → 结构化拆解 → 关键帧 → I2V → 配音 → 字幕成片（M6 原型定型版，v17 正式化前手动链路）。

## 文件

| 文件 | 作用 |
|---|---|
| `novel2video.yaml` | 技能参数（doc_key/风格/运镜/默认值） |
| `m6_breakdown_test.py` | 步骤①②：RAG 人物卡注入 → LLM 结构化拆解（角色/场景/道具/分镜 JSON） |
| `m6_render_v3.py` | 步骤③④⑤⑥：英文 prompt 关键帧 → I2V → 配音 → 拼装烧字幕 |
| 流程规范（六步+踩坑）：`.opencode/skills/novel_to_video/SKILL.md` | |

## 用法

```bash
# 前置：服务 UP（./start_services.sh start）+ 小说已索引（/rag add <path> --novel）
PY=/home/zxy/.conda/envs/comfyui/bin/python

# ① 拆解（默认《呐喊》·孔乙己；换书改 yaml doc_key + 传章节名）
$PY SKILL/commands/novel2video/m6_breakdown_test.py 孔乙己

# ②③ 渲染（幂等可续跑；默认 yaml 里 8 关键镜）
$PY SKILL/commands/novel2video/m6_render_v3.py
```

产物（`output/m6/v3/`）：`kongyiji_v3.mp4` 成片（yuv420p/烧字幕，Windows 可放）、
`subs.srt`、`prompts.md`（全部 prompt 清单）、`kf_contact.jpg`（关键帧速查）、
`kf/`（关键帧）、`clips/`（分镜视频+配音）。

## 六步流程

```
小说 ─① RAG 索引（切章+人物卡）
   ─② LLM 拆解（shot.visual/narration 分列 JSON）
   ─③ LLM 中译英 prompt → FLUX 关键帧（全局 STYLE 统一）
   ─④ Wan I2V（关键帧做首帧，禁裸 T2V）
   ─⑤ CosyVoice 配音（旁白=字幕同源）
   ─⑥ 慢放≤2x+Ken Burns 尾推+xfade 拼接+烧字幕+yuv420p
```

## 硬约束（踩坑结晶，违反必翻车）

1. **FLUX 只吃英文**：中文 prompt → 风格漂移/内容跑偏；必须 LLM 中译英（景别开头+本镜人物状态优先）
2. **一律 I2V**：裸 T2V 是镜头间风格漂移源头
3. **音色黑名单**：克隆音色 prompt_text 会被零样本续写（jieshuo1 句首泄漏"街道的街道…"）；新音色先单句 A/B，安全默认 cosy-default
4. **Windows 兼容**：每个 ffmpeg 输出环节显式 `-pix_fmt yuv420p`（RGB 关键帧经 xfade 链变 4:4:4 → Windows 放不了）
5. **禁长死帧**：时长差用慢放 ≤2x 消化，残余用 Ken Burns 缓推（zoompan 1.0→1.14）
6. **LLM 长任务必须流式**：非流式长 reasoning 零字节 → read timeout 必死；chat_json max_tokens 默认已提 16384
7. **超长章先分段**：>8000 字拆解会超时/降质（《藥》=36k 字，含无篇名并入的阿Q正传）
8. **耗时预算**：拆解 5-15min + 关键帧 5min + I2V 3.5min/镜 + 拼装 2min；一律后台化跑
