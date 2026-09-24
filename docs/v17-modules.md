# v17 — 三排正交模块化（导演 × 生成 × 后期 排列组合）

> 2026-09-26。目标：每个环节单一实现，任意组合出一条完整链路。详见 hierachy.md 方法脉络。

## 三层模型

```
概念 + --director + --generator + 后期参数
   │
   ▼ D 导演层 ──产出──> segments[] = [{text 旁白, visual 画面描述, motion?, engine?}]
   │                    （人写 prompt / 手塞 --say 也归一为此格式）
   ▼ G 生成层 ──消费 segments──> clips[] (+audios[] 若模型原生有声如 H3)
   │
   ▼ P 后期层 ──消费 clips(+segments)──> final.mp4 + meta.json
```

统一入口（M2 已实现）：
```bash
python core/vidance.py make 概念 [--director llm|manual|scout] [--generator wan|fast|svg|h3] [后期参数]
# /make 前端同义：api 归一参数后递归分发到 svg/custom/h3shot/fast/auto/quick 现有通道
```
现有子命令（auto/fast/hot/quick/custom/svg/h3shot/compose）全部保留不动。

## D 导演层

| ID | 导演 | 现状 | 归一方式 |
|----|------|------|---------|
| D1 人肉 | 手给整段 prompt/脚本/--say | `h3_prompt_video.py` / `custom_gen.parse_script` | 转成 1~N 条 segment（visual=原文，engine=h3） |
| D2 LLM 自动 | 编剧分镜（6维）/旁白规划 | `pipeline.plan_script`、`fastline.plan_narration`、`svg_llm.plan_narration` **三套 prompt** | 合并 `utils/director.py`：`plan(concept, n, for_generator)` → 同 schema segments |
| D3 热点 | 爬榜→scout 选题→D2 | `crawler+scout_topics`（hot 命令） | 保持，产出 concept 喂 D2 |
| D4 对话 | v6 ask 多轮核实后喂 D2 | `dialog.py` ✅ 已独立 | 保持 |

## G 生成层（并行备选，互不依赖）

| ID | 生成器 | 消费 | 产出 | 代码 |
|----|--------|------|------|------|
| G1 H3 | 参考图+prompt ref2va 原生有声 | D1/D2 segments | clips(+音轨) | `h3_prompt_video.py`/`custom_gen` |
| G2 Wan | auto 管线（含 v1/v3 角色锚 flux/3dgs/mesh 子路线） | D2 | clips | `pipeline.py` |
| G3 爬图/生图 | 必应/Pexels 爬图+校验 / FLUX 补图 + Ken Burns | D2 segments | clips(无声) | `fastline.collect_images`+`_kenburns` |
| G4 SVG | LLM→自包含 SVG→逐帧渲染 | D2(segments) | clips(无声) | `svg_pipeline.SvgLine`（render 部分） |
| G5 二创 | yt-dlp+抽帧重剪（🎯v16） | 链接 | clips | — |

生成器契约：`generate(segments, workdir, opts) -> {clips:[path], audios:[path|None], meta}`；原生有声的（G1）audios 给 None，P 层跳过配音。

## P 后期层（对任何 G 通用，全开关）

| ID | 能力 | 单一实现 | 冗余现状 → 收口 |
|----|------|---------|----------------|
| P0 配音 | 逐段 TTS + 降级链（voice重试→cosy→静音） | **`core/narration.Narrator.say`**（新） | fastline._tts_segment / svg._tts_seg / h3旁路 **各一份 → 删** |
| P1 字幕 | entries→SRT + 烧录 | **`Narrator.srt` / ffmpeg_tools.generate_srt** | 三份 _srt_time → 删 |
| P2 拼接 | cut/crossfade/rife + 音画合 | `ffmpeg_tools.compose` ✅ 已复用 | 保持 |
| P3 调色/配乐 | LUT+BGM ducking | `PostProcessor`（run_all）✅ 已复用 | svg 线绕过 run_all 直连 compose(lut/bgm 参数)，可接受 |
| P4 特效/转场 | 8 特效+30 xfade+LLM选 | `utils/effects.py` ✅ | 保持 |
| P5 时长探测 | ffprobe | `ffmpeg_tools.get_duration` ✅ 已有 | fastline._video_duration / svg._probe_duration 本地版 → 删 |
| P6 时间线 | timeline JSON 精修 | `compose.py run_timeline` ✅ | 保持（P2 的高级形态） |

## 冗余清单（本次修）

1. `svg_pipeline._tts_seg/_silence/_srt_time/_probe_duration` → 改调 `core/narration.Narrator` + `ffmpeg_tools.get_duration`
2. `fastline._tts_segment/_gen_silence/_build_srt/srt_time/_video_duration` → 同上（薄壳转发保兼容）
3. 导演三套 prompt 合并 `utils/director.py`（M3，涉及质量回归，稍后做）

## 里程碑

- **M1 ✅**：`core/narration.py`（Narrator: say/silence/srt）；fastline/svg_pipeline 重复实现改薄壳；SVG S5 回归通过
- **M2 ✅ 2026-09-26**：`vidance.py make` + `/api make`（递归复用现有分发；scout 导演先选题再续；manual 由 --say/--prompt/--script 自动判定）。实测 `make "月夜散步" --generator svg --say ×2` → `output/make_test/m1.mp4` 5.4s 音视双流
- M3：`utils/director.py` 合并编剧/旁白 prompt（schema 统一 + 质量回归对比）
- M4：生成器契约统一后，G5(v16)/G1 多参考图作为新 generator 即插即用

## 组合速查（make 语义）

| 想要 | 组合 |
|------|------|
| 奶蛙徽商 | D1+G1+（原生有声，P 仅 LUT/BGM） |
| 科普快片 | D3→D2+G3+P0-P5（=fast） |
| 数据/概念动画带配音视频 | D2+G4+P0+P1+P2（=svg 有声，S5） |
| 大片全自动 | D2+G2+P0-P5（=auto） |
| 单镜试水 | D2+G2（裸）=P0-P5 全关（=quick） |
| 发布前精修 | 任意成片 + P6 timeline |
