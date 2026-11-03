# v19 使用指南 — 视频链接二创（营销号 Plus）

> v19（原 v16 规划）视频链接二创（2026-11-02 关版）。**不新增模型**：yt-dlp（v4 voice_clone）/ faster-whisper STT（v2 M5）/ qwen3.8 多模态（v0 审片）/ deepseek 编剧 / CosyVoice / v10 compose / v5 特效 / v2 LUT+RIFE——全部现成基建接线。
> 设计文档：[v19-design.md](../design/v19-design.md) · 状态权威：[roadmap.md](../roadmap.md) §v19

## 一条命令

```bash
python core/vidance.py rework "https://www.bilibili.com/video/BVxxxx" \
    --style 解说 --duration 60 --visual-rewrite 2 \
    --lut cinematic --bgm dramatic
```

- `--style`：解说（钩子+时间线+点评）/ 盘点（分点罗列）/ 吐槽（玩梗但事实准确）
- `--duration`：目标成片秒数（默认 60，4 字/秒约束 LLM 字数）
- `--visual-rewrite 0-5`（组合式，档 N 含全部 <N）：
  - 0 原样引用 · 1 +变速（0.75-1.6x 贴合旁白）· 2 +LUT 调色 · 3 +镜像/裁剪构图 · 4 +光流插帧（minterpolate，加速>1.25x 时平滑）· 5 +v5 特效（punch_in/zoom/grain_vignette 轮换）
- `--voice`：默认 `cosy-default`（**安全默认**；`cosy-jieshuo1` 在音色黑名单——句首泄漏"街道…"幻听，实锤见 output/rework/rw-smoke1 日志）
- `--lut`：cinematic/warm/cool/vintage/vivid/soft · `--bgm`：calm/uplifting/mysterious/dramatic/playful/epic（终拼 sidechaincompress ducking）
- `--remove-sub`（复用 v16 ProPainter，**消除原片烧录字幕**）：
  - `off`（默认）不动原片字幕 · `auto` = 检出才消 · `force` = 无框也按底部带强制消
  - 定位：`unlimited-ocr`（USTC 端点，多帧采样）**∪ 像素启发式兜底**（白字行聚堆 ≥2 帧确认）——OCR 端点排队波动大（实测 7s~7min+ 首字节），启发式保证检测永不卡死
  - **⚠ 坐标空间（两次返工换来的铁律）**：unlimited-ocr 输出为**千分比规范坐标（0-999，与输入分辨率无关）**，须按 x*w/1000、y*h/1000 映射；曾误判为"高 1080 像素空间"，704p 帧归一化错 1.53 倍，mask 盖到字幕上方渐变条、字幕原样保留（视觉验收两轮被骗：白像素/MAE 口径均被"消的是渐变条"假象污染，最终以**文字行白像素峰结构消失**（raw 峰 313→part 0）+ 裁剪放大 OCR 读不出原字幕为准）
  - **⚠ 启发式局限**：只对"白字亮场"有效；灰字+深色底板字幕（本源片）或夜景高亮场景（汉白玉）会漏检/误检——OCR 是主定位，启发式仅兜底。检测结果落 `subtitle.json`，各 part 复用零重复 OCR
  - 消除：part 粒度（preclip 后 1280x704，ProPainter fp16 ~20G 显存；1080p 全片直接跑会 OOM，须 resize_ratio 0.67）→ RAFT 双向光流补全非生成式，无字幕区域回填原画面无损
  - 终验（rw-api1）：8 段文字行白像素峰 7 段归零、1 段剩平滑场景重建（边缘密度 0.000/OCR 无文字）

## 流水线（四级幂等缓存）

```
链接 ─M1→ 下载(yt-dlp 合流) + STT(faster-whisper) ∥ 抽帧(5s/帧,512px)+多模态批量理解(8帧/批)
     → source.json（转写段+帧视觉描述）
     ─M2→ LLM 改写解说词（流式 JSON + Levenshtein 防复述断言 <0.55，超阈回喂重写）
         + 时间轴映射（每段 ref_start/ref_dur 引用原片画面区间）
         + 逐段 TTS（串行+杂音护栏）→ script.json + subs.srt（同源）
     ─M3→ 逐段画面改写（强度档 ffmpeg）→ v10 compose 时间线（xfade+旁白轨）
         → 终拼（BGM ducking + LUT + 烧字幕 + h264/yuv420p）
     ─M4→ meta.json（来源 URL 必录）→ 人工审核出口（不做自动发布）
```

产物 `output/rework/rw-*/`：`final.mp4` + `source.json`（原片理解）+ `script.json`（二创脚本+相似度）+ `subs.srt` + `prompts 留痕`（meta.json）+ `parts/`（改写后各段）。

## 三通道

| 通道 | 用法 |
|---|---|
| CLI | `python core/vidance.py rework <链接> [参数]` |
| utils | `python utils/rework.py rework <链接> --out output/rework/rw-x`（M1 单步：`... source <链接>`） |
| agent/API | `generator.rework` agent（32 号注册表）· `POST /api/tool/rework`（异步 job，`/api/h3shot/{job_id}` 轮询，stage 回传） |

## 程序断言（tests/test_rework.py，15 项纯逻辑）

URL 平台解析 / 防复述相似度双向断言（真改写 <0.55、复述句被抓）/ digest 聚合块数与时间单调 / SRT 时间轴 / L0-L4 preclip 产物与 rate 钳制（≤1.6）/ 输出时长贴合 narr_dur / 风格表。

## 验收实录（2026-11-02，B站真实链接）

- 原片：《故宫太和殿天花板藏百年监控探头》533s → `output/rework/rw-smoke1/`（CLI）+ `rw-api1/`（API 目录）
- M1：203 段转写/1743 字 + 107 帧视觉理解 107/107 非空（140.9s）
- M2：8 段解说词，相似度 max=0.195（真改写），81.06s
- M3/M4：final.mp4 h264/yuv420p/1280x704/24fps + 字幕烧录（base vs final 字幕带 MAE 27.6 程序断言）+ LUT 生效（主体 MAE 19.2）；rw-smoke1 82.0s / rw-api1 64.3s（贴合各自 narr_total，xfade 重叠扣减属预期）
- API 通道：job 生命周期 running→completed 验证（stage 回传：下载+理解 → LLM 改写解说词 → TTS 配音 → 画面改写+组装，agent.log 留痕；缓存命中时跳级播报）

## 已知边界

- **M1 只承诺 B站**（yt-dlp 已验证可达）；YouTube/抖音需外网或 cookie，best-effort 报错点名
- 嘈杂 BGM 视频转写质量下降 → 低置信时段靠帧视觉描述兜底
- 多模态理解失败 safe fallback（visual 置空不阻塞，纯 STT 也能出片）
- **发布前请人工审核**（meta 录来源 URL；不做自动发布/账号矩阵）
- 长视频（>10min）M1 转写+理解耗时线性增长（533s 原片 M1≈2.5min）
