---
name: novel_to_video
description: "Use when converting a novel/text chapter into a narrated short video. RAG小说→结构化拆解→关键帧→I2V→配音→字幕→成片 全链路流程与踩坑规范。Trigger when user asks to render a video from novel text, chapter breakdown, or 分镜/拆解/成片 in Vidance."
---

# Novel-to-Video Skill — 小说成片全链路（M6 原型定型版）

## 流程总览（六步）

```
小说文本 ─1→ RAG 索引（切章+人物卡）
        ─2→ LLM 结构化拆解（角色/场景/道具/分镜 JSON）
        ─3→ LLM 翻译关键帧英文 prompt → FLUX 出关键帧（每镜一张）
        ─4→ Wan I2V（关键帧做首帧）→ 分镜视频
        ─5→ CosyVoice 配音（旁白/字幕同源）
        ─6→ 慢放对齐 + Ken Burns 尾推 + xfade 拼接 + 烧字幕 + yuv420p 成片
```

参考实现（幂等，可断点续跑）：
- `input/rag_test/m6_breakdown_test.py <章节名>` — 步骤 1-2
- `input/rag_test/m6_render_v3.py` — 步骤 3-6（v3 为定型版；`M6_ALL=1` 渲染全部镜头，默认 8 关键镜）
- `input/rag_test/m6_archive_buffer.py <session_id>` — 步骤 7：产物引用式归档 buffer（幂等）
- `input/rag_test/m6_wardrobe_test.py [--gen]` — 衣橱系统（BigBanana 借鉴）：Base Look 锁脸多套服装，`--gen` FLUX 出图（输出 output/m6/wardrobe/）
- 样片：`output/m6/v3/kongyiji_v3.mp4`（349.2s/36 镜全量，2026-10-30；8 镜子集版已被覆盖）

## 步骤要点

### 1. RAG 索引
- `POST /api/rag/upload` 或 `/rag add <path> --novel`；key=内容 md5
- 人物卡：`idx._load_cards(key)`，**只注入名字出现在本章正文的卡**（全量注入放大输入、拉爆推理时间）
- 已知限制：无独立篇名行的章会并入邻章（《藥》含阿Q正传 36k 字）→ 拆解前检查 `len(ch['text'])`，>8000 字先分段或换短章

### 2. 结构化拆解（LLM）
- schema：characters/scenes/props/storyboard（shot 连续编号，scene 引用场景 id，visual 只写可见画面，narration 白话保留原著语感，duration 数字秒）
- 产出人工检查三处：结尾是否覆盖（最后 1-2 镜应落全文收束句）、道具象征是否准确、各镜人物状态是否随剧情推进
- 总时长建议 3-5 分钟；36 镜/220s 对应 4k 字短篇

### 3. 关键帧（FLUX）
- **必须走 LLM 中译英**：FLUX 对长中文 prompt 理解弱，直接喂中文会风格漂移/内容跑偏（v1 卡通化、v2 内容无关的根因）
- 翻译规则：景别开头（wide establishing/medium/close-up/extreme close-up）；**本镜人物状态优先**（后期"黑瘦/破夹袄"不得套用早期形象）；35-60 词具象名词
- 全局 STYLE 统一追加到每镜（如 `1910s rural Zhejiang, vintage black and white documentary photo, grainy film texture, photorealistic`）——全片风格 DNA 一致的关键
- 产出 `kf_contact.jpg` 拼贴图供人工速查，风格不过关先改 STYLE 再重跑（删 kf/ 即重生）

### 4. 分镜视频（Wan I2V）
- **一律 I2V**（关键帧做首帧），不裸 T2V——T2V 是镜头间风格漂移的源头
- 1280x704 / 24fps / length=97 / steps=20；每镜约 3.5 分钟（单卡）
- prompt=原文 visual + 运镜词（`very subtle slow camera drift, minimal natural human motion`）

### 5. 配音（CosyVoice）
- **音色黑名单机制**：零样本克隆音色的 prompt_text 是幻听源——CosyVoice 把参考文本当上文续写，句首泄漏参考音频内容（`jieshuo1` 50 字参考文本 → 每句开头"街道的街道都在一夜之间"）。新音色先 A/B 单句试听再上片
- `cosy-default`（内置短 prompt）实测零幻听，安全默认
- 杂音护栏（tts.py 首尾检测）只是警告不阻断，幻听要靠选对音色根治

### 6. 拼装成片（ffmpeg）
- 时长对齐：长旁白镜头先**慢放 ≤2x**（纪实感）消化时长差，残余尾段 **Ken Burns 缓推**（zoompan 1.0→1.14），**禁止长时死帧定格**（v1 尾帧冻结 12s 被判"卡顿"的根因）
- 拼接：xfade 0.5s + acrossfade 0.25s + 首尾黑场淡入淡出
- **Windows 兼容铁律**：终拼必须 `-pix_fmt yuv420p -profile:v high -level 4.1`——h264 编码但 4:4:4 采样（yuv444p）Windows 自带播放器放不了（RGB 关键帧经 xfade 链会被带成 4:4:4，每个 ffmpeg 输出环节都要显式 yuv420p）
- 字幕：按各镜实际时长生成 SRT（16 字/行换行），`subtitles` 滤镜烧录，Noto Sans CJK SC Bold 白字黑边 MarginV=26

## 可追溯性

- `prompts.md` 落盘全部 prompt（每镜关键帧 EN/旁白/I2V/时长+全局参数）——用户问"prompt 去哪看"指这个
- 英文翻译原始 JSON：`kf/prompts_en.json`
- 拆解 JSON 是唯一事实源（shot.visual/narration 分列），复跑任何阶段都从它出发

## 耗时预算（单卡 48G）

| 阶段 | 耗时 | 备注 |
|---|---|---|
| 拆解（LLM） | 5-15 min | 必须流式（见下） |
| 关键帧 8 张（FLUX） | ~5 min | 每张 ~35s |
| I2V 8 镜（Wan） | ~30 min | 每镜 ~3.5 min |
| 配音 8 段 | ~2 min | cosy-default |
| 拼装 | ~2 min | 纯 ffmpeg |

## LLM 调用铁律（本项目端点实测）

1. **长任务必须流式**（`chat_stream`）：非流式在长 reasoning 期零字节返回 → read timeout 必死（600s/900s 均超时，流式 1800s 稳过）
2. **chat_json/max_tokens**：推理模型 reasoning 挤占输出额度，默认 4096 会截断 → content None；已改默认 16384
3. 端点延迟波动大（小 prompt 7s，全章拆解曾 15min+），一律后台化（setsid nohup + 轮询日志）
