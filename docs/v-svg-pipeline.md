# SVG 生成 → MP4 流水线设计（v15 轻量化）

> 目标：**纯 CPU、秒级出片**，适合信息图 / 文字动画 / 数据可视化 / 科普短片。
> 理念：LLM 产出带 CSS/SMIL 动画的**自包含 SVG** → 无头浏览器**确定性逐帧**渲染 → ffmpeg 拼帧成 mp4。

## 分步路线（每步都可独立验证，逐步放行）

| 步骤 | 做什么 | 产物 | 验证方式 | 脚本 |
|------|--------|------|----------|------|
| **S1** | 调用 LLM 生成 SVG（如"鹈鹕骑自行车"） | `output/svg/<name>.svg` | **人肉看一眼**（浏览器/预览图） | `utils/svg_llm.py` |
| **S2** | 单帧渲染（无头浏览器截一张 PNG） | `<name>.png` | 看 PNG 是否与 SVG 一致 | `utils/svg_pipeline.py --still` |
| **S3** | 多帧确定性抽帧（把动画按 fps 定位到各时间点截 PNG 序列） | `frames/0001.png…` | 抽查几帧 + 帧数 = fps×时长 | `utils/svg_pipeline.py --frames` |
| **S4** | ffmpeg 拼帧成 mp4 | `<name>.mp4` | 播放检查流畅度/音画（无音） | `utils/svg_pipeline.py` |
| **S5** |（可选）加 TTS 旁白 / BGM / 字幕 | 成片 | 复用 v2 后处理 | 待定 |

> 原则：**S1 产物先给人确认**，OK 再进 S2；每步命令独立、可回退。

## 关键设计

- **确定性逐帧**：用 Web Animations API（`document.getAnimations()`）+ SVG SMIL（`pauseAnimations/setCurrentTime`）把动画**暂停并设到精确 t** 再截图 —— 不用 wall-clock `wait_for_timeout`（否则随机器速度丢帧/重复帧）。
- **渲染后端**：Playwright + Chromium（支持 CSS 动画 + SMIL）。仅静态帧时可用 `cairosvg` 兜底。
- **纯 CPU**：不占 GPU，可与 GPU 任务并行。
- **SVG 约束给 LLM**：自包含（无外链资源/字体）、固定 viewBox、动画时长明确、颜色用 hex。

## 依赖

- `pip install playwright && playwright install chromium`（下载 ~150MB）
- ffmpeg（已有）

## 文件

- `utils/svg_llm.py`：S1，概念 → LLM → SVG 文件（+ 可选预览 HTML）
- `utils/svg_pipeline.py`：S2-S4，SVG → 帧 → mp4（`--still` / `--frames` / 默认出 mp4）
