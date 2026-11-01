# v18 使用指南 — 长视频质量（一致性底座 / VACE 首尾帧 / 一镜到底 / 世界观）

> v18（原 v14 规划）长视频质量四个里程碑全部完成（2026-10-31 关版）。**不新增模型**：全部为现成基建（FLUX 关键帧 / Wan I2V / Wan2.1 VACE / ffmpeg xfade）的接线与约束。
> 设计文档：[v18-design.md](../design/v18-design.md) · 状态权威：[roadmap.md](../roadmap.md) §v18 · 前置：[usage-v17.md](usage-v17.md)（novel2video 六步流程）

## M1 一致性资产底座（拆解 schema + 场景锚 + 衣橱组装器 + 过渡选型）

### 拆解 schema 升级（m6_breakdown_test.py）

v18 拆解 JSON 新增字段（缺字段降级警告、不阻断，向后兼容 v17 拆解）：

| 字段 | 作用 |
|---|---|
| `world` | `{era, region, style, taboos[]}` 世界观注册表（M4 渲染端注入） |
| `characters[].costumes[]` | 造型列表 `{name, desc, stages:[[起镜,止镜],...]}` 衣橱分区间 |
| `scenes[].anchor_en` | 场景锚英文段（同场景镜头逐字复用，防布景漂移） |
| `storyboard[].costume` | 本镜造型名（区间命中时由 `costume_for` 自动推断） |
| `storyboard[].transition_out` | 片间转场（xfade 16 种白名单，旧值回退 fade） |

旧拆解迁移（防改动断言：原字段值不变，仅允许新增字段；自动 .v17.bak 备份）：

```bash
# dry-run 预览（不写回）
python SKILL/commands/novel2video/m6_upgrade_breakdown.py output/m6/breakdown_孔乙己.json
# --apply 写回
python SKILL/commands/novel2video/m6_upgrade_breakdown.py output/m6/breakdown_孔乙己.json --apply
```

### 渲染端组装器（m6_render_v3.py 自动生效）

关键帧 prompt 三层叠加：**景别 + 场景锚（逐字复用）+ 服装段（stages 区间命中取最窄者）+ LLM 翻译增量**。服装英译缓存在 `output/m6/<out>/kf/costumes_en.json`（键=造型名，重跑零 LLM 调用）。

```bash
# v4 对照渲染（8 关键镜 ~30min；M6_ALL=1 全量 36 镜 ~2h，一律后台化）
M6_OUT=v4 python input/rag_test/m6_render_v3.py
```

验收断言（v18 实测）：14 场景全部镜头锚段逐字注入；镜9=破旧长衫 / 镜30=破夹袄蒲包 / 镜5=None（未出场不注入）。

## M2 VACE flf2v 首尾帧驱动（M6_FLF=1）

```bash
# 首帧=本镜关键帧、尾帧=下镜关键帧（末镜回退自身）；832x480@16fps，组装段 scale+pad 自适配
M6_OUT=v5 M6_FLF=1 python input/rag_test/m6_render_v3.py
```

- 原理：control.mp4 = 首帧定帧 2s → xfade 1.2s → 尾帧定帧（ffmpeg）→ `WanVaceToVideo` 的 `control_video` 序列口，零新模型
- 冒烟：`m6_flf_smoke.py`（首/尾帧 MAE 0.019/0.015，自身首尾差 0.154 = 真运动）
- **同题对照（两级口径）**：镜间边界 MAE（part 尾帧 vs 下镜首帧，160x88 灰度）——clip 级（纯生成产物）**0.198→0.026（-87%，5 对全改善）**；part 级（成片段）**0.199→0.054（-72.6%）**。FLF 模式下组装缓推自动收敛到 1.06（尾帧已对齐下镜，1.14 大幅缩放会破坏对齐）
- 代价：单镜分辨率降档 832x480/81 帧（组装段慢放消化）
- 注意：控制视频须直拷 `/mnt/disk_sdb/zxy/ComfyUI/input/`（LoadVideo 只认 input 目录，脚本已自动处理）

## M3 一镜到底（oneshot）

```bash
# CLI 路由（早退，不走多镜主管线）
python core/vidance.py auto "穿越隧道的光" --oneshot --duration 30
# 直接调用等价；--character 每段重注角色锚
python utils/oneshot.py "穿越隧道的光" --duration 30 --character "金色光流"
```

- 链式：LLM 运镜脚本（五维 motion 域，段间方向/速度连续）→ FLUX 首帧 → 段 N 末帧 ffmpeg 提取回灌段 N+1 I2V 首帧条件 → concat
- 规格固定 1280x704@24fps、97 帧≈4.04s/段（Wan 上限内）；断点续跑：plan.json/seg_*.mp4/oneshot.mp4 均幂等缓存
- 产物：`output/oneshot/os-*/`（oneshot.mp4 成片 + plan.json 运镜脚本 + prompts.md + report.json 拼缝断言）
- 验收（v18 实测）："穿越隧道的光" 30s 目标 → 28.3s/7 段；拼缝 MAE（成片段 k+1 首帧 vs 回灌条件图）[0.018, 0.016, 0.009, 0.028, 0.015, 0.009] 全部 <0.10

## M4 世界观收口

- **world 注册表**：拆解 `world` 字段 → LLM 英译缓存 `output/m6/world_*.json` → `STYLE_EN` 叠加注入（era/region/色调/质感）；taboos 禁则打印 + 落盘 prompts.md
- **事件线**：`output/m6/events_*.json` 分镜序列 → LLM 按弧线分组摘要卡（每弧 3-6 镜，arc/shots/summary/characters），供长片导航与续写检索（孔乙己 10 弧覆盖 36/36 镜）；prompts.md 尾部追加「世界观」节
- **事件线入 RAG 索引**：渲染时自动 `RagIndex.add_chunks()` 显式分块——**每弧一卡**（首版 `add_document` 会按 ~500 字聚合把 10 弧并成 3 块稀释，已弃用该路径）；key=32b60cbc（10 卡），检索需 `doc_keys=[全 key]` 限定（8 位前缀过滤无效，API 层 `/rag` 有短前缀展开）；程序断言 4 查询命中 3/4（断腿卡 top-2 微差 0.60 vs 0.61，MiniLM 中文细粒度极限）；索引失败仅警告不阻塞渲染
- **正式化**：SKILL/commands/novel2video/（m6_upgrade_breakdown/m6_flf_smoke 归档 + README 流程）、.opencode/skills/novel_to_video/SKILL.md 双位置同步

## 产物速查

| 路径 | 内容 |
|---|---|
| `output/m6/v3/` | v17 证据成片（349.2s/36 镜，勿覆盖） |
| `output/m6/v4/` | v18 M1 对照成片（73.7s/8 镜，场景锚+衣橱+过渡选型） |
| `output/m6/v5/` | v18 M2 FLF 对照成片（74.1s/8 镜，镜间边界 clip 级 -87%/part 级 -72.6%） |
| `output/m6/breakdown_孔乙己.json` | v18 schema 拆解（world/costumes/anchor_en 全量） |
| `output/m6/world_孔乙己.json` | 世界观注册表（style_en 英译缓存） |
| `output/m6/events_孔乙己.json` | 事件线摘要卡（10 弧） |
| `output/m6/events_孔乙己.md` | 事件线可读版（弧线表格，RAG 索引的源格式） |
| `output/oneshot/os-*/` | 一镜到底成片 + 运镜脚本 + 断言报告 |
| `/tmp/opencode/demo/v3_v4_kf_compare.jpg` | v17↔v18 关键帧对照条 |
| `/tmp/opencode/demo/oneshot_contact.jpg` | oneshot 8 帧拼贴（人工查验用） |

## 验证与回归

- 程序断言：场景锚逐字注入 / 衣橱区间命中 / FLF 边界 MAE 两级口径 / oneshot 拼缝 <0.10（各里程碑节内已列）
- 全量回归 7 套件 **116/116**（buffer 26 / checkpoint_m4 18 / retry 13 / embed_index 13 / subtitle_correct 20 / material_cache 20 / preflight 6）
- 对照演示页：[docs/v18-benchmark.html](../v18-benchmark.html)（6 章节/3 图内嵌，含 M2 归因实录）

## 已知边界

- FLUX 无图像条件：场景锚/角色锚全部 prompt 级；图像级合成（背景+角色贴回）依赖 inpaint/Fill 组合，标增强项
- FLF 单镜分辨率 832x480（VACE 模型原生档），高分辨率 FLF 依赖后续模型升级
- 事件线/世界观英译依赖 LLM（缓存幂等；失败回退中文不阻塞渲染）
