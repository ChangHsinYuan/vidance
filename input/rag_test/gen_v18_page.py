#!/usr/bin/env python3
"""生成 docs/v18-benchmark.html — v18 长视频质量演示页（自包含，嵌图）。"""
import base64
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def b64(path):
    with open(os.path.join(ROOT, path), 'rb') as f:
        return base64.b64encode(f.read()).decode()


IMG_KF_CMP = b64('/tmp/opencode/demo/v3_v4_kf_compare.jpg')
IMG_FLF = b64('/tmp/opencode/demo/flf_boundary_11_21.jpg')
IMG_ONESHOT = b64('/tmp/opencode/demo/oneshot_contact.jpg')

HTML = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>v18 演示 — 长视频质量（一致性底座 / VACE 首尾帧 / 一镜到底）</title>
<style>
  body {{ font-family: 'Noto Sans CJK SC', 'PingFang SC', 'Microsoft YaHei', sans-serif;
         max-width: 1180px; margin: 24px auto; padding: 0 20px; color: #222; line-height: 1.65; }}
  h1 {{ font-size: 1.5em; border-bottom: 3px solid #2b6cb0; padding-bottom: 8px; }}
  h2 {{ font-size: 1.2em; color: #2b6cb0; margin-top: 2em; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.9em; margin: 12px 0; }}
  th, td {{ border: 1px solid #cbd5e0; padding: 7px 10px; text-align: left; vertical-align: top; }}
  th {{ background: #ebf4ff; white-space: nowrap; }}
  tr:nth-child(even) {{ background: #f7fafc; }}
  .ok {{ color: #276749; font-weight: 600; }}
  .gap {{ color: #9b2c2c; font-weight: 600; }}
  .path {{ font-family: ui-monospace, Consolas, monospace; font-size: 0.86em; background: #edf2f7;
          padding: 1px 5px; border-radius: 3px; word-break: break-all; }}
  .cmd {{ font-family: ui-monospace, Consolas, monospace; font-size: 0.84em; background: #1a202c;
         color: #e2e8f0; padding: 2px 6px; border-radius: 3px; white-space: nowrap; }}
  figure {{ margin: 14px 0; text-align: center; }}
  figure img {{ max-width: 100%; border: 1px solid #cbd5e0; border-radius: 4px; }}
  figcaption {{ font-size: 0.85em; color: #4a5568; margin-top: 5px; }}
  .note {{ background: #fffbeb; border-left: 4px solid #d69e2e; padding: 8px 12px; font-size: 0.9em; }}
  .stamp {{ color: #718096; font-size: 0.85em; }}
</style>
</head>
<body>
<h1>v18 长视频质量 — 同题对照实测证据</h1>
<p class="stamp">生成于 2026-10-31 · 状态权威：<span class="path">docs/roadmap.md</span> §v18 · 设计稿：<span class="path">docs/design/v18-design.md</span> · 用法：<span class="path">docs/usage/usage-v18.md</span></p>

<div class="note"><b>一句话立场</b>：v18 的每一步都"不新增模型"——VACE 首尾帧、xfade 过渡、末帧回灌全是现成基建的接线与约束；
每个结论都有同题对照 + 程序断言 + 可复验命令，含诚实缺口清单（镜 21→24 边界略升、FLUX 无图像条件）。</div>

<h2>一、v17 → v18 关键帧对照（M1 场景锚 + 衣橱组装器）</h2>
<figure>
<img src="data:image/jpeg;base64,{IMG_KF_CMP}" alt="v3 vs v4 关键帧对照">
<figcaption>8 关键镜上下排对照（上= v17 <span class="path">output/m6/v3/</span>，下= v18 <span class="path">output/m6/v4/</span>）。
v18 关键帧 prompt 三层叠加：<b>景别 + 场景锚（同场景逐字复用）+ 服装段（stages 区间命中取最窄）</b>+ LLM 翻译增量。
程序断言：14 场景全部镜头锚段逐字注入；镜9=破旧长衫 / 镜30=破夹袄蒲包 / 镜5=None（未出场不注入）。
全部 prompt 可追溯于 <span class="path">output/m6/v4/prompts.md</span>（含世界观/事件线节）。</figcaption>
</figure>

<h2>二、VACE 首尾帧驱动对照（M2 · M6_FLF=1）</h2>
<figure>
<img src="data:image/jpeg;base64,{IMG_FLF}" alt="FLF 边界对照">
<figcaption>镜11 尾帧 → 镜21 首帧切换（左列 v4 I2V / 右列 v5 FLF）。FLF 模式：首帧=本镜关键帧、尾帧=下镜关键帧
（VACE control_video 序列口，零新模型），下镜开场直接落在"该出现的地方"。</figcaption>
</figure>
<table>
<tr><th>指标（5 对镜间边界，尾帧 vs 下镜首帧，160x88 灰度 MAE）</th><th>v4 I2V</th><th>v5 FLF</th></tr>
<tr><td>clip 级（纯生成产物，生成质量）</td><td>0.198</td><td class="ok"><b>0.026（-87%，5 对全改善）</b></td></tr>
<tr><td>part 级（成片段，含组装配饰）</td><td>0.199</td><td class="ok"><b>0.054（-72.6%）</b></td></tr>
<tr><td>part 级逐对：1→9 / 9→11 / 21→24 / 24→30 / 30→34</td><td>0.247 / 0.197 / 0.163 / 0.196 / 0.189</td>
<td class="ok">0.039 / 0.023 / 0.118 / 0.043 / 0.049</td></tr>
<tr><td>成片规格</td><td colspan="2">两者同为 h264/yuv420p/烧字幕；FLF 单镜 832x480@16fps（VACE 原生档），组装段 scale+pad 自适配、慢放消化</td></tr>
</table>
<p><b>归因与修正实录</b>：首版 part 级仅 -20.6% 且镜 21→24 略升（0.163→0.200）。逐层归因发现 clip 级 FLF 已达 0.026（-87%）、
镜 21→24 生成级 0.037 优于 I2V 的 0.181——"略升"是组装层 Ken Burns 缓推（1.14x）破坏了"尾帧=下镜关键帧"的对齐
（v5#21 part 尾帧 vs clip 尾帧 MAE 0.111 实证）。修正：FLF 模式缓推幅度收敛 1.14→1.06（保"禁长死帧"规则），重拼后 part 级 5 对全改善。</p>

<h2>三、一镜到底（M3 · utils/oneshot.py + auto --oneshot）</h2>
<figure>
<img src="data:image/jpeg;base64,{IMG_ONESHOT}" alt="oneshot 8 帧拼贴">
<figcaption>"穿越隧道的光" 30s 目标 → <span class="path">output/oneshot/os-20261031-010019/oneshot.mp4</span>
（28.3s，7 段 ×4.04s，1280x704@24fps h264+yuv420p）。LLM 运镜链：push-in 0.8→1.5→减速 1.0，pan 0.5°→2.5°，段间连续无跳切；
段 N 末帧 ffmpeg 提取回灌段 N+1 I2V 首帧条件，每段重注角色/风格锚防漂移。</figcaption>
</figure>
<table>
<tr><th>断言（report.json，可复验）</th><th>结果</th></tr>
<tr><td>拼缝 MAE（成片段 k+1 首帧 vs 回灌条件图 kf_k+1，验 I2V 服从度）</td>
<td class="ok">[0.018, 0.016, 0.009, 0.028, 0.015, 0.009] 全部 <0.10（量级=FLF 冒烟 0.015-0.019）</td></tr>
<tr><td>断言口径说明</td><td>首版断言"段 k 末帧 vs 段 k+1 首帧"是循环论证（回灌源本就是同帧提取）；已改为验 I2V 对条件图的真实服从度</td></tr>
</table>

<h2>四、世界观与事件线（M4）</h2>
<table>
<tr><th>产物</th><th>内容</th><th>复验</th></tr>
<tr><td><span class="path">output/m6/world_孔乙己.json</span></td>
<td>拆解 world 字段 → LLM 英译（late Qing dynasty, Jiangnan water town…）→ 叠加进 STYLE_EN；4 条禁则（避免现代服饰/避免血腥奇观/避免偶像剧打光/避免滑稽化迂腐）落盘</td>
<td><span class="cmd">cat output/m6/world_孔乙己.json</span>；prompts.md「世界观」节</td></tr>
<tr><td><span class="path">output/m6/events_孔乙己.json</span></td>
<td>36 镜 → LLM 按弧线分组 10 张摘要卡（酒店格局/温酒伙计/长衫登场/窃书争辩/身世科举/茴字四写/茴香豆/断腿传闻/最后温酒/用手走远），shots 覆盖 36/36 无重叠</td>
<td><span class="cmd">python -c "import json; print(len(json.load(open('output/m6/events_孔乙己.json'))['arcs']))"</span></td></tr>
</table>

<h2>五、诚实缺口</h2>
<table>
<tr><th>项</th><th>现状</th><th>说明</th></tr>
<tr><td>图像级一致性（背景+角色贴回）</td><td class="gap">prompt 级约束</td>
<td>FLUX 无图像条件输入；图像级合成依赖 inpaint/Fill 组合，标增强项（设计稿 §4 风险边界）</td></tr>
<tr><td>FLF 分辨率</td><td class="gap">832x480</td><td>VACE 1.3B 原生档；高分辨率 FLF 依赖模型升级，组装段已自适配不阻塞成片</td></tr>
<tr><td>镜 21→24 边界</td><td class="ok">已归因消除</td><td>生成级 0.037 优于 I2V 0.181；part 级首版略升系 zoompan 装配噪声，缓推收敛 1.06 后 5 对全改善（见 §二归因实录）</td></tr>
<tr><td>事件线检索</td><td class="ok">✅ 已接入 RAG 索引（每弧一块）</td><td><span class="cmd">RagIndex.add_chunks</span> 显式分块（每弧一卡，key=32b60cbc，10 卡）——首版 add_document 聚合到 ~500 字把 10 弧并成 3 块稀释，已改；程序断言 4 查询命中 3/4（断腿卡 top-2 微差 0.60 vs 0.61，MiniLM 中文细粒度极限，诚实记录）；JSON 注册表仍为事实源（不引入向量世界观库）</td></tr>
</table>

<h2>六、复验命令</h2>
<table>
<tr><th>结论</th><th>命令</th></tr>
<tr><td>M1 组装器断言（锚段逐字/服装命中）</td><td><span class="cmd">M6_OUT=v4 python input/rag_test/m6_render_v3.py</span>（全程缓存秒过）+ prompts.md 三层结构目检</td></tr>
<tr><td>M2 边界 MAE 对照</td><td><span class="cmd">M6_OUT=v5 M6_FLF=1 python input/rag_test/m6_render_v3.py</span>；MAE 脚本见 usage-v18.md §M2</td></tr>
<tr><td>M3 oneshot 断言</td><td><span class="cmd">python core/vidance.py auto "穿越隧道的光" --oneshot --duration 30 --no-preflight</span>（产物 report.json）</td></tr>
<tr><td>回归基线（v17）</td><td><span class="cmd">python tests/test_buffer.py</span> 26/26 · checkpoint_m4 18/18 · retry 13/13 · embed_index 13/13 · subtitle_correct 20/20 · material_cache 20/20 · preflight 6/6</td></tr>
</table>
</body>
</html>
"""

out = os.path.join(ROOT, 'docs', 'v18-benchmark.html')
with open(out, 'w', encoding='utf-8') as f:
    f.write(HTML)
print(f'✓ {out}（{os.path.getsize(out) // 1024}KB，3 图内嵌）')
