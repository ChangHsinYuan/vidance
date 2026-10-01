# Vidance 使用指南

> 统一入口 `python core/vidance.py <子命令> [参数]`
>
> 分版本文档：[usage-v0.md](./usage-v0.md)（有声短片 MVP/T2V/TTS）· [usage-v1.md](./usage-v1.md)（角色锚/3DGS）· [usage-v2.md](./usage-v2.md)（RIFE/LUT/BGM/ffmpeg/STT）· [usage-v3.md](./usage-v3.md)（mesh/资产库）· [usage-v4.md](./usage-v4.md)（爬虫/队列/声音克隆/fast/hot） · [usage-v6.md](./usage-v6.md)（prompt 多轮核实）· [usage-v7.md](./usage-v7.md)（前端 WebUI）· [usage-v10.md](./usage-v10.md)（时间线拼接与特效）· [usage-v-svg.md](./usage-v-svg.md)（SVG→mp4 流水线）· [usage-v11.md](./usage-v11.md)（多智能体 chain 编排）
>
> 架构：[hierarchy.md](./hierarchy.md)（方法脉络图：视频模型/非视频模型 × 导演方式总览）· [v12-modules.md](./v12-modules.md)（三排正交统一入口）· [v11-design.md](./v11-design.md)（多智能体分层与 Agent 链）· [v-t2c.md](./v-t2c.md)（自然语言→命令翻译层）· [v-svg-pipeline.md](./v-svg-pipeline.md)（SVG 流水线设计）

## 文档地图

| 类别 | 文件 | 内容 |
|------|------|------|
| **入口** | usage.md（本文）· [roadmap.md](./roadmap.md) | 使用总入口 · 总览与版本路线（状态权威来源） |
| **脉络/架构** | hierarchy.md · v12-modules.md · v11-design.md · [deployed-models.md](./deployed-models.md) | 方法脉络图与 v12 流水线 · 三排正交模块契约 · 已部署模型清单 |
| **设计** | v0 · v1 · v2 · [v2.5](./v2.5-design.md) · v3 · v4 · v5 · v6 · v7 · v8 · v9 · v10（各 `-design.md`） | 各版本设计文档（规划版 v8/v9 含被 v16/v14（原 v14/v11）吸收的原始设计） |
| **专项设计** | v-t2c.md · v-svg-pipeline.md | 自然语言→命令 · SVG 流水线 |
| **分版使用** | usage-v0/v1/v2/v3/v4/v6/v7/v10 · usage-v11.md · usage-v-svg.md | 各版本小工具用法速查 |
| **指令库** | [instructions/commands.json](./instructions/commands.json)（22 命令）· [instructions/compose-commands.md](./instructions/compose-commands.md) + .json（43 条剪辑指令） | 前端 `/help` 数据源，t2c 重训数据源 |
| **样例** | [example/](./example/) | 时间线 JSON 示例（compose 演示） |
| **历史** | archive/roadmap_origin.md | 原始规划稿（已归档，仅存参考） |

## 子命令

| 子命令 | 输入 | 引擎 | 角色 | 后处理 | 适用场景 |
|--------|------|------|------|--------|----------|
| `auto` | 一句中文概念 | Wan T2V/I2V + FLUX | 文字描述→FLUX 生图 | 可选 | 快速出片、自动编剧 |
| `custom` | 参考图 + 预写脚本 | H3 ref2va | 三视图直接注入 | 可选 | 精确控制分镜、多角色 |
| `quick` | 一句中文概念 | Wan T2V | 无 | 无 | 最快出片、无角色 |
| `concat` | 多个视频文件 | — | — | — | 拼接已有素材 |
| `fast` (v4) | 一句概念 | 跳过视频模型 | 爬图/FLUX + zoompan 运镜 | 通用后期 | 营销号快速出片，见 usage-v4.md M6 |
| `hot` | 无（爬实时热点） | 同 fast | 爬虫自动选题 | 通用后期 | 一键热点出片，见 usage-v4.md M6 |
| `svg` (v13) | 概念或 SVG 文件 | 无 GPU（纯 CPU） | LLM 生成动效 SVG | TTS/字幕（S5） | 秒级出片，见 usage-v-svg.md |
| `ppt` (v15) | 概念或 deck.html | 无 GPU（纯 CPU） | LLM 规划页面/图表 | TTS 旁白/字幕/LUT/BGM | 幻灯片短片+PDF/PNG 交付 |
| `blender3d` (v13) | 概念或 scene.json | bpy EEVEE（宿主 GPU/容器 CPU） | LLM 规划 3D 场景 | TTS 旁白/字幕 | 3D 质感短片（模板 title3d/shapes/bars3d） |
| `compose` (v10) | 时间线 JSON | — | — | 时间线拼接特效 | 后端 CLI 剪辑，见 usage-v10.md |
| `h3shot` | prompt + 参考图 | H3 ref2va | 整段式单镜 | 原生音频直出 | 整段式单镜（`--ref` 条件注入） |
| `ask` (v6) | 一句概念 | — | LLM 追问核实 | — | 多轮补全增强概念，见 usage-v6.md |
| `make` (v12) | 概念 + 导演/生成器选择 | 任意组合 | 按导演层 | 通用后期 | **统一入口**：--director llm/manual/scout × --generator wan/fast/svg/h3，见 v12-modules.md |
| `agent` (v11) | Agent 名或 chain JSON | 按链步骤 | 三层 Agent 编排 | — | 多智能体 list/run/chain，见 usage-v11.md |

---

## auto — 概念自动生成

LLM 自动编剧 → 角色锚生成 → 逐镜生成 → 审片 → 后处理合成。

```bash
# 基本用法（无角色，纯 T2V + 配音 + 后处理）
python core/vidance.py auto "一只猫在月球上跳舞"

# 带角色（默认 auto 模式：先试 3DGS，审查不过降级 flux）
python core/vidance.py auto "深海探险" --character "蓝色水母"

# flux 模式（每镜 FLUX 直接生成角色+场景，质量最稳定）
python core/vidance.py auto "雪山日出" --character "红色小狐狸" --character-mode flux

# 全功能（RIFE 过渡 + LUT 调色 + BGM + STT 字幕）
python core/vidance.py auto "雪山日出：小狐狸的冒险" \
    --character "红色小狐狸" --character-mode flux \
    --lut cool --bgm calm --stt

# 禁用部分后处理
python core/vidance.py auto "概念" --character "角色" --no-rife --no-color --no-bgm

# 长片模式（--duration 60 → 动态 ~15 镜，不传则默认 2-5 镜）
python core/vidance.py auto "深海探险" --character "蓝色水母" --character-mode flux --duration 60

# 全局慢动作（所有镜头 2x 帧倍增慢放）
python core/vidance.py auto "概念" --character "角色" --slowmo 2
```

### auto 参数

| 参数 | 说明 | 默认 |
|------|------|------|
| `concept`（位置参数） | 视频概念（中文） | 必填 |
| `--character` | 角色描述（中文） | 无（纯 T2V） |
| `--character-mode` | `auto`/`3dgs`/`flux` | `auto` |
| `--voice` | TTS 音色（如 `edge-moe`） | config 默认 |
| `--duration` | 目标总时长（秒），动态调整镜头数 | 无（默认 2-5 镜） |
| `--slowmo` | 全局慢动作帧倍率（2=2x 慢放） | 无（用 LLM 标注） |

---

## custom — 参考图 + 脚本生成

用预写分镜脚本 + 角色三视图参考图，通过 H3 ref2va 一步生成带原生音频的视频。

```bash
# 基本用法（双角色故事）
python core/vidance.py custom \
    --ref input/doubao.jpg --ref input/naiwa.jpg \
    --script input/prompt1.txt

# 加后处理
python core/vidance.py custom \
    --ref input/doubao.jpg --ref input/naiwa.jpg \
    --script input/prompt1.txt \
    --lut cinematic --bgm dramatic --stt

# 高保真模式（参考图 2048px，角色身份保真更好，慢 2-3x）
python core/vidance.py custom \
    --ref input/doubao.jpg \
    --script input/prompt1.txt \
    --ref-image-size max

# 指定输出路径
python core/vidance.py custom \
    --ref input/doubao.jpg --ref input/naiwa.jpg \
    --script input/prompt1.txt \
    -o my_video.mp4
```

### custom 参数

| 参数 | 说明 | 默认 |
|------|------|------|
| `--ref`（可重复） | 角色参考图路径 | 必填 |
| `--script` | 分镜脚本文件路径 | 必填 |
| `--ref-image-size` | `match`（快）/ `max`（2048px 高保真） | `match` |

### 分镜脚本格式

```
[全局场景设定行]
[全局角色设定行]
【01A｜标题｜约3秒】
生成提示词：
[镜头描述（可多行）]
【01B｜标题｜约2.5秒】
生成提示词：
[镜头描述]
【剪辑与声音...】（忽略）
```

- `约X秒` 支持小数（如 `约2.5秒`）
- 每镜 H3 最少 5 帧，不足自动对齐到 17k+5 网格
- `<Picture i>` 标签自动引用第 i 张参考图

---

## quick — 纯 T2V

无角色锚、无后处理，最快出片。

```bash
python core/vidance.py quick "一只猫在月球上跳舞"

# 指定音色
python core/vidance.py quick "概念" --voice edge-xiaoxiao
```

---

## concat — 多视频拼接

将多个视频文件拼合为一个，支持三种过渡方式。

```bash
# 硬切拼接（ffmpeg stream copy，最快）
python core/vidance.py concat clip1.mp4 clip2.mp4 clip3.mp4 -o merged.mp4 --transition cut

# RIFE 光流过渡（需 GPU2 ComfyUI 8189 在线）
python core/vidance.py concat clip1.mp4 clip2.mp4 clip3.mp4 -o merged.mp4 --transition rife

# 交叉淡化
python core/vidance.py concat clip1.mp4 clip2.mp4 -o merged.mp4 --transition crossfade --crossfade-duration 0.5
```

### concat 参数

| 参数 | 说明 | 默认 |
|------|------|------|
| `videos`（位置参数） | 待拼接视频文件列表 | 必填 |
| `--transition` | `cut`/`rife`/`crossfade` | `cut` |
| `--crossfade-duration` | 交叉淡化时长（秒） | `0.5` |
| `-o/--output` | 输出路径 | `merged.mp4` |

---

## 共享后处理参数（auto + custom）

| 参数 | 说明 |
|------|------|
| `--lut <style>` | 指定 LUT 风格：`cinematic`/`warm`/`cool`/`vintage`/`vivid`/`soft` |
| `--no-color` | 禁用 LUT 调色 |
| `--bgm <mood>` | 指定 BGM mood：`calm`/`uplifting`/`mysterious`/`dramatic`/`playful` |
| `--no-bgm` | 禁用背景音乐 |
| `--no-rife` | 禁用 RIFE 镜头间过渡 |
| `--stt` | 使用 faster-whisper STT 字幕对齐 |
| `-o/--output` | 输出路径（相对路径自动 resolve 到 output_dir） |

不传 `--lut`/`--bgm` 时，由 LLM 根据概念自动选择风格。`--no-rife`/`--no-color`/`--no-bgm` 覆盖 config 中的 `enabled: true`。

---

## 输出

- 不传 `-o`：自动输出到 `{output_dir}/{custom_}TIMESTAMP/final.mp4`
- 传 `-o` 相对路径：自动 resolve 到 `{output_dir}/` 下
- 传 `-o` 绝对路径：按指定路径输出
- 每次任务生成 `meta.json`（脚本/prompt/seed/时间戳等完整元数据）

---

## TTS 音色

| 前缀 | 引擎 | 示例 |
|------|------|------|
| `edge-*` | edge-tts（微软在线） | `edge-moe` 萌系高音 / `edge-xiaoxiao` 晓晓 / `edge-yunjian` 云健 |
| `cosy-*` | CosyVoice（本地 GPU） | `cosy-default` / `cosy-cross` |
| `cosy-<自定义>` | CosyVoice 克隆 | 在 `voices/<名>/prompt.wav` 放素材自动注册 |

> custom 模式用 H3 原生音频，不使用 TTS。`--voice` 仅对 auto/quick 有效。

---

## 服务依赖

运行前需确认对应 ComfyUI 实例已启动：

| 子命令 | 需要的服务 | 端口 |
|--------|-----------|------|
| auto | Wan (T2V/I2V) + FLUX/TripoSplat | 8189 + 8192 |
| auto（3dgs/auto 模式） | 额外需要 TripoSplat | 8192 |
| custom | H3 ref2va | 8188 |
| quick | Wan T2V | 8189 |
| fast/hot | TTS 9880（FLUX 8192 可选补图；爬图/占位图有缺省兜底） | 9880 |
| svg | 无（纯 CPU，TTS 可选） | — |
| agent/make | 按链步骤依赖（`GET /api/agents` 看 GPU 标注） | — |
| 所有（带 `--voice`） | TTS 服务 | 9880 |
| 所有（带 `--stt`） | faster-whisper（GPU） | 内嵌 |

---

## 向后兼容

旧入口仍可用，但不推荐：

```bash
python core/pipeline.py ...      # 等同 auto
python core/custom_gen.py ...    # 等同 custom（不含后处理参数）
```

---

## 完整示例

### 示例 1：auto 全自动带角色

```bash
python core/vidance.py auto "雪原上的红斗篷少年" \
    --character "穿红色斗篷的短发少年" \
    --character-mode flux \
    --voice edge-moe \
    --lut cool --bgm calm \
    --stt
```

流程：LLM 编剧 → FLUX 生角色图 → 逐镜 FLUX 场景图 + Wan I2V + TTS → 审片 → RIFE 过渡 → LUT 调色 → BGM ducking → STT 字幕

### 示例 2：custom 双角色故事

```bash
python core/vidance.py custom \
    --ref input/doubao.jpg --ref input/naiwa.jpg \
    --script input/prompt1.txt \
    --ref-image-size match \
    --lut cinematic --bgm dramatic
```

流程：解析脚本 → LLM 看参考图描述角色 → H3 ref2va 逐镜生成（带原生音频）→ RIFE 过渡 → LUT 调色 → BGM ducking

### 示例 3：quick 极速出片

```bash
python core/vidance.py quick "一只猫在月球上跳舞"
```

流程：LLM 编剧 → Wan T2V → TTS 配音 → ffmpeg 合成（无调色无 BGM 无过渡）
