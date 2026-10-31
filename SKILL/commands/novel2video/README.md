# novel2video — 小说成片技能

小说章节 → 结构化拆解 → 关键帧 → I2V → 配音 → 字幕成片（M6 原型定型版，v17 正式化前手动链路）。

## 文件

| 文件 | 作用 |
|---|---|
| `novel2video.yaml` | 技能参数（doc_key/风格/运镜/默认值） |
| `m6_breakdown_test.py` | 步骤①②：RAG 人物卡注入 → LLM 结构化拆解（角色/场景/道具/分镜 JSON；v18 schema：world/costumes/anchor_en/costume/transition_out） |
| `m6_upgrade_breakdown.py` | v18 迁移：旧拆解 JSON 补齐 v18 字段（dry-run/--apply，防改动断言+.v17.bak 备份） |
| `m6_render_v3.py` | 步骤③④⑤⑥：英文 prompt 关键帧 → I2V → 配音 → 拼装烧字幕（`M6_ALL=1` 全量镜头，默认 8 关键镜；v18：场景锚+衣橱组装器+过渡选型；`M6_FLF=1` VACE 首尾帧驱动 832x480@16fps） |
| `m6_flf_smoke.py` | v18 M2 冒烟：VACE flf2v 单镜（control.mp4 拼接→WanVaceToVideo；首/尾帧 MAE 0.019/0.015） |
| `m6_archive_buffer.py` | 步骤⑦：产物引用式归档 buffer（幂等，按 name+sha 去重） |
| `m6_wardrobe_test.py` | 衣橱系统（BigBanana 借鉴）：Base Look 锁脸多套服装 prompt（`--gen` FLUX 出图+拼贴） |
| `nahan.txt` | 《呐喊》古登堡原文（复现样片用，doc_key=454eb1f2…） |
| 流程规范（六步+踩坑）：`.opencode/skills/novel_to_video/SKILL.md` | |

## 用法

### A. 复现样片（孔乙己，全部素材本目录自带）

```bash
# 前置①：GPU 服务 UP（h3/wan/flux/tts/api）
cd /mnt/disk_sdb/zxy/vidance && ./start_services.sh start && sleep 120

# 前置②：建 RAG 索引（本目录 nahan.txt → doc_key 454eb1f2…）
PY=/home/zxy/.conda/envs/comfyui/bin/python
$PY SKILL/commands/novel2video/m6_breakdown_test.py 孔乙己   # 首次运行自动建索引+拆解

# 渲染（幂等可续跑；M6_ALL=1 渲染拆解里全部镜头）
$PY SKILL/commands/novel2video/m6_render_v3.py
# M6_ALL=1 $PY SKILL/commands/novel2video/m6_render_v3.py   # 全量 36 镜（~2h，后台化跑）
# M6_FLF=1 M6_OUT=v5 $PY SKILL/commands/novel2video/m6_render_v3.py  # v18 M2：VACE 首尾帧驱动（镜间边界 clip 级 -87%/part 级 -72.6%）
# 旧拆解迁移 v18 schema：$PY SKILL/commands/novel2video/m6_upgrade_breakdown.py output/m6/breakdown_孔乙己.json --apply

# 产物归档 buffer（引用式不拷贝，幂等）
$PY SKILL/commands/novel2video/m6_archive_buffer.py m6_kongyiji_v3

# 衣橱（可选）：角色多套造型同 Base Look（换衣不换脸；缺省只出 prompt，--gen 真出图）
$PY SKILL/commands/novel2video/m6_wardrobe_test.py [--gen]
```

产物在 `output/m6/v3/`（同 doc_key 时与历史样片共享缓存，重跑秒过）。

### B. 换一本小说

```bash
# 1. 上传建索引（得到新 doc_key，8 位短前缀即可用）
$PY -c "
import sys; sys.path.insert(0,'.')
from utils.rag import RagIndex
print(RagIndex().add_novel('你的小说.txt')['key'])"
# 或 UI: /rag add /path/to/小说.txt --novel

# 2. 拆解目标章节（章节名要与 /rag status 的章列表一致）
$PY SKILL/commands/novel2video/m6_breakdown_test.py 章节名
#    ⚠ m6_breakdown_test.py 里 KEY/SRC 是《呐喊》硬编码，换书需改文件头两行：
#    KEY='新doc_key'；SRC=你的小说路径

# 3. 渲染：m6_render_v3.py 头部 BD/SHOTS 改成新拆解 JSON 路径和镜头子集
#    STYLE_EN/MOTION_EN 在 yaml（novel2video.yaml）里，换题材同步改写
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
