# usage-v-svg — SVG → MP4 流水线（v15 轻量化）

纯 CPU、秒级出片：LLM 产出带 CSS/SMIL 动画的自包含 SVG → 无头浏览器确定性逐帧渲染 → ffmpeg 拼帧成 mp4。
适合信息图 / 文字动画 / 数据可视化 / 科普短片。

## 依赖（已装）
- `playwright`（Python 包）+ Chromium（`~/.cache/ms-playwright/chromium-1243`）
- ffmpeg

## 分步（每步可独立验证）
| 步 | 命令 | 产物 |
|----|------|------|
| S1 | `vidance.py svg --concept "鹈鹕骑自行车"` | SVG + 预览 HTML |
| S2 | `vidance.py svg --svg scene.svg --still --at 1.5` | 单帧 PNG |
| S3 | `vidance.py svg --svg scene.svg --frames` | PNG 序列 |
| S4 | `vidance.py svg --svg scene.svg -o out.mp4` | mp4 |

## 用法

```bash
# 一键：概念 → LLM 生成 SVG → mp4
python core/vidance.py svg --concept "鹈鹕骑自行车" --duration 3 --width 800 --height 450

# 渲染已有 SVG 成 mp4
python core/vidance.py svg --svg output/svg/pelican_bike.svg -o output/svg_demo/out.mp4 --duration 3

# 单帧调试（S2）
python core/vidance.py svg --svg scene.svg --still --at 1.5

# 抽帧（S3）
python core/vidance.py svg --svg scene.svg --frames --frames-dir output/frames

# 直接调模块
python utils/svg_llm.py "鹈鹕骑自行车" -o output/svg/pelican_bike.svg   # S1
python utils/svg_pipeline.py --svg output/svg/pelican_bike.svg -o out.mp4 --duration 3
```

## API / 前端
- `POST /api/tool/svg` — `{"args": "--concept \"鹈鹕骑自行车\""}` 或 `{"args": "--svg path.svg -o out.mp4"}`
- 前端 `:8894/ui` 输入 `/svg --concept "鹈鹕骑自行车"` → 出成片卡片

## 关键设计
- **确定性逐帧**：`document.getAnimations()`（Web Animations）+ SVG SMIL `pauseAnimations/setCurrentTime` 把动画设到精确 t 再截图；不用 wall-clock `wait_for_timeout`（会随机器速度丢帧）。
- **可执行文件探测**：`_find_chrome_executable()` 优先 headless shell，回退完整 chrome；`executable_path` 显式传入，规避 playwright 自动查找（它只认 headless shell）。
- **纯 CPU**，不与 GPU 任务抢资源。

## 输出示例
- `output/svg_demo/pelican_bike.mp4`（72帧@24fps，800×450，3s）
- `output/svg_demo/pelican_bike.svg` / `.preview.html`

## 注意
- SVG 必须**自包含**（无外链图/字体/script），动画用 CSS @keyframes 或 SMIL。
- LLM 生成 SVG 时模型名要用 `deepseek-v4-flash-ascend`（config 已修正，旧的 `-ascend1` 会挂起）。
