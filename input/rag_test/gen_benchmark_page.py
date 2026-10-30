#!/usr/bin/env python3
"""生成 docs/v17-benchmark.html — v17 与四参考仓库能力对照演示页（自包含，嵌图）。"""
import base64
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def b64(path):
    with open(os.path.join(ROOT, path), 'rb') as f:
        return base64.b64encode(f.read()).decode()


IMG_KF = b64('output/m6/v3/kf_contact.jpg')
IMG_FILM = b64('/tmp/opencode/demo/kongyiji_strip.jpg')
IMG_LIGHT = b64('/tmp/opencode/demo/lighthouse_strip.jpg')
IMG_WARD = b64('/tmp/opencode/demo/wardrobe_small.jpg')

HTML = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>v17 对照演示 — 四参考仓库 vs Vidance 实现</title>
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
  .cols {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .cols > div {{ flex: 1 1 320px; }}
  .note {{ background: #fffbeb; border-left: 4px solid #d69e2e; padding: 8px 12px; font-size: 0.9em; }}
  .stamp {{ color: #718096; font-size: 0.85em; }}
</style>
</head>
<body>
<h1>v17 对照演示 — 四参考仓库 vs Vidance 实测证据</h1>
<p class="stamp">生成于 2026-10-30 · 状态权威：<span class="path">docs/roadmap.md</span> §v17 · 借鉴映射：<span class="path">docs/design/v17-design.md</span> §1</p>

<div class="note"><b>一句话立场</b>：ViMax 证明"断点续跑是刚需"，我们不仅实现了，还在真实中断任务上验证了 45s 续跑出片；
BigBanana 用人工调分镜保长篇一致性，我们用 prompt 工程+人物卡做到了零手工干预的同题全链路。</div>

<h2>一、成片级证据（可直接播放）</h2>
<div class="cols">
<div>
<figure>
<img src="data:image/jpeg;base64,{IMG_FILM}" alt="孔乙己成片抽帧">
<figcaption><b>《孔乙己》36 镜全链路</b> — <span class="path">output/m6/v3/kongyiji_v3.mp4</span>（349.2s，h264 High/yuv420p/aac，ffprobe 实证）。对齐 BigBanana "剧本→资产→关键帧→成片"四阶段；本镜状态区分（#9 早期高大长衫 vs #30 断腿后黑瘦破袄）靠 LLM 中译英+人物卡，非人工调图。</figcaption>
</figure>
</div>
<div>
<figure>
<img src="data:image/jpeg;base64,{IMG_LIGHT}" alt="灯塔成片抽帧">
<figcaption><b>断点续跑实证</b> — <span class="path">output/auto_20261015_200322/final.mp4</span>（10.7s/6镜）。该任务 2026-10-15 中断；2026-10-30 <span class="cmd">--resume</span> 跳过编剧/prompt 优化、6 镜全复用，45s 重拼出片（全新跑约 30min）。</figcaption>
</figure>
</div>
</div>

<h2>二、指纹拦截破坏实验（M4 · ViMax checkpoint 借鉴）</h2>
<table>
<tr><th style="width:24%">实验步骤</th><th>结果</th></tr>
<tr><td>① 给旧任务 checkpoint 回填 6 镜 sha256 指纹（final_video+audio_path 双键）</td>
<td>复用 <span class="path">core/pipeline.py _fingerprint_clip</span>，全部键落盘</td></tr>
<tr><td>② 人为篡改 shot_3.mp4（低码率重编码，文件变但可播，模拟磁盘/人工改动）</td><td>1.1MB → 0.12MB</td></tr>
<tr><td>③ <span class="cmd">auto --resume auto_20261015_200322</span></td>
<td class="ok">日志实证：<span class="path">/tmp/m4_fingerprint_test.log</span> L17-18<br>
「clip shot 3 <b>指纹不符(final_video,audio_path)，将重做</b>」<br>「复用 <b>5</b> 个已完成镜头」→ shot 3 自动走 FLUX+I2V+TTS 重生成，其余 5 镜零 GPU 消耗直接复用</td></tr>
<tr><td>④ 被篡改/被重做的文件均被指纹网捕获，成片仍自动重拼完成</td>
<td class="ok">防御闭环：损坏产物不会混进成片（旧版只查文件存在，会被静默吞下）</td></tr>
<tr><td>⑤ <b>意外收获</b>：实验揪出 resume 重做镜 append 而非替换的真 bug（checkpoint 留含旧 sha 的重复条目）</td>
<td class="ok">已修 <span class="path">core/pipeline.py</span>（重做镜替换同 shot 旧条目）+ 回归用例，修复后 6 镜指纹与磁盘全一致</td></tr>
</table>

<h2>三、能力对照总表</h2>
<table>
<tr><th>参考仓库</th><th>它的招牌能力</th><th>我们的实现</th><th>证据 / 复验命令</th><th>状态</th></tr>
<tr><td rowspan="5"><b>MoneyPrinterTurbo</b><br>40k★<br><span class="stamp">（源码级，8700 行通读）</span></td>
<td>per-task 目录归拢 + 原子写 JSON（fsync+os.replace）</td>
<td>M1 buffer <span class="path">output/buffer/&#123;session&#125;/</span> + M4 <span class="path">checkpoint.json</span> 原子合并写</td>
<td>坏 JSON 半文件容错、合并不覆盖旧键 → <span class="cmd">python tests/test_checkpoint_m4.py</span>（18/18）</td><td class="ok">✅ 实测</td></tr>
<tr><td>上传文件名净化 + 路径围栏（防 ../ 穿越）</td>
<td><span class="path">utils/buffer.py</span> sanitize_name + _resolve_within（越界拒绝）</td>
<td><span class="cmd">python tests/test_buffer.py</span>（26/26）；/api/upload 冒烟</td><td class="ok">✅ 实测</td></tr>
<tr><td>mtime 扫描式 TTL 缓存清理</td><td>buffer TTL 7 天守护线程（每 6h 扫）</td>
<td>单测覆盖 + daemon 挂 <span class="path">core/api_server.py _start_buffer_cleanup_daemon</span></td><td class="ok">✅ 实现（无长周期运行数据）</td></tr>
<tr><td>字幕智能纠正（STT 幻觉/同音字，subtitle.py correct()）</td>
<td><span class="path">utils/subtitle_correct.py</span> Levenshtein 对齐 + 剧本文本替换 + 幻觉丢弃，接入 <span class="path">core/postprocess.py run_stt</span> 三链路</td>
<td><span class="cmd">python tests/test_subtitle_correct.py</span>（20/20）</td><td class="ok">✅ 单测</td></tr>
<tr><td>素材 URL-md5 全局缓存 + 搜索 24h TTL（material.py/material_cache.py）</td>
<td><span class="path">utils/material_cache.py</span> MaterialCache（file:// 下载验证 + TTL）接入 <span class="path">agents/common/tools/asset_crawler.py</span></td>
<td><span class="cmd">python tests/test_material_cache.py</span>（20/20）</td><td class="ok">✅ 单测</td></tr>
<tr><td rowspan="2"><b>Toonflow</b><br>17.4k★<br><span class="stamp">（已克隆，源码级）</span></td>
<td>@ mention 资产引用（MentionAsset 上下文注入）</td>
<td>M3 <span class="cmd">@N</span> 序号引用 → 命令替换 buffer 绝对路径（服务端 refs.json 取值防注入）+ LLM 附件清单注入</td>
<td><span class="cmd">/api/tool/clip <span class="cmd">@1</span></span> 端到端替换实测 + <span class="cmd">/api/assets?q=孔乙己</span> 中文模糊搜索/游标翻页实测；UI chip 交互 <span class="path">:8894/ui</span></td><td class="ok">✅ 实测（@N + @文件名 q 搜索双形态，游标失效 410 Gone）</td></tr>
<tr><td>sha256 revision 乐观并发（409 ESTALE）+ 资产树 API</td>
<td>refs.json revision 校验 + /api/assets 列表 + 删除联动</td>
<td>并发竞态用例 → <span class="cmd">python tests/test_buffer.py</span>；5 项资产 <span class="path">output/buffer/m6_kongyiji_v3/</span></td><td class="ok">✅ 实测</td></tr>
<tr><td rowspan="2"><b>ViMax</b><br>12.6k★<br><span class="stamp">（机制级）</span></td>
<td>渲染 checkpoint：中断后按 task 续跑</td>
<td>M4 <span class="cmd">auto --resume &#123;task_id&#125;</span>：阶段级跳过 + 逐镜复用 + sha256 指纹拦截 + agent_runs 黑板步进记录</td>
<td>本页 §二破坏实验 + 45s 续跑出片；黑板记录 <span class="path">output/tasks.sqlite agent_runs m4:*</span></td><td class="ok">✅ 实测</td></tr>
<tr><td>LLM 多级重试统一封装</td>
<td>M7 <span class="path">utils/retry.py</span> tenacity 三策略（llm 指数退避 / tts 2s×3 / comfy 10s×2；4xx 直抛）</td>
<td><span class="cmd">python tests/test_retry.py</span>（13/13）——重试本身不可视，代码级证明</td><td class="ok">✅ 单测</td></tr>
<tr><td rowspan="3"><b>BigBanana</b><br>2.3k★<br><span class="stamp">（README 机制级）</span></td>
<td>Script-to-Asset-to-Keyframe 四阶段工业流（反抽卡）</td>
<td>M6 拆解 JSON（角色6/场景14/道具8/分镜36）为唯一事实源 → 关键帧 → I2V → 成片</td>
<td><span class="path">output/m6/breakdown_孔乙己.json</span> + 成片见 §一；36 镜全量实测 ~2h GPU</td><td class="ok">✅ 实测</td></tr>
<tr><td>衣橱系统（多套造型同一 Base Look，换衣不换脸）</td>
<td><span class="cmd">optimize_costume_prompts</span>（<span class="path">agents/common/tools/llm.py</span>）：Base Look 锁脸/胡须/体型，N 套服装只变穿着段</td>
<td>孔乙己 3 造型（长衫/破袄/断腿）三 prompt Base Look 前 120 字符全同（程序断言）+ FLUX 出图（<span class="path">output/m6/wardrobe/</span>）→ <span class="cmd">python input/rag_test/m6_wardrobe_test.py --gen</span></td><td class="ok">✅ 实测（见 §四.5）</td></tr>
<tr><td>提示词管理面板（prompt 资产化可复用）</td>
<td>M5 <span class="path">SKILL/templates/</span> 4 模板 × 五维词汇域 + style_pack 锚点覆盖</td>
<td><span class="cmd">auto "概念" --template cinematic</span>；模板落盘即被发现，零代码接入</td><td class="ok">✅ 实测（4 模板 ×5 维加载全通）</td></tr>
</table>

<h2>四、M6 关键帧一致性速查（BigBanana "定妆照"思路）</h2>
<figure>
<img src="data:image/jpeg;base64,{IMG_KF}" alt="36 镜关键帧拼贴">
<figcaption>36 镜 FLUX 关键帧拼贴（<span class="path">output/m6/v3/kf_contact.jpg</span>）——全局 STYLE_EN 统一风格 DNA，同一孔乙己从出场（#9 长衫）到断腿（#30/34 蒲包）状态连续；全部 prompt 可追溯于 <span class="path">prompts.md</span>。</figcaption>
</figure>

<h2>四.5、衣橱系统证据（BigBanana 借鉴 · 换衣不换脸）</h2>
<figure>
<img src="data:image/jpeg;base64,{IMG_WARD}" alt="孔乙己衣橱三造型">
<figcaption>孔乙己三套造型（<span class="path">output/m6/wardrobe/contact.jpg</span>）：出场长衫 chushi / 落魄破袄 luopo / 断腿蒲包 duantui。LLM 生成三 prompt 时 Base Look 特征段（脸型/胡须/长指甲/年龄）逐字复述——三 prompt 前 120 字符程序断言全同；服装段各不相同（filthy tattered long gown / torn short padded jacket, legs crossed / walking on his hands）。复验：<span class="cmd">python input/rag_test/m6_wardrobe_test.py</span>（prompt 级，LLM）或 <span class="cmd">--gen</span>（FLUX 出图）。</figcaption>
</figure>

<h2>五、诚实缺口（未达或仅单测级）</h2>
<table>
<tr><th>项</th><th>现状（2026-10-30 四调收口）</th><th>说明</th></tr>
<tr><td>Toonflow @文件名 模糊搜索</td><td class="ok">✅ 已补齐：search_assets 游标分页 + /api/assets?q=（410 Gone 语义）+ 26/26 单测 + 中文搜索端点实测</td><td>缩略图 chip 留 UI 迭代</td></tr>
<tr><td>MPT 字幕 Levenshtein 纠正</td><td class="ok">✅ 已有（前版页面误列为缺口）：utils/subtitle_correct.py 20/20 + run_stt 接线</td><td>属"已完成未上页"的盘点偏差，非功能缺失</td></tr>
<tr><td>MPT 素材 URL-md5 缓存 + 搜索 24h TTL</td><td class="ok">✅ 已有（同上）：utils/material_cache.py 20/20 + asset_crawler 接线</td><td>同上</td></tr>
<tr><td>BigBanana 衣橱系统</td><td class="ok">✅ 已补齐：optimize_costume_prompts + 孔乙己 3 造型实测（§四.5）</td><td>接入 M6 正式化拆解 schema（角色卡加 costume 列表）待 v18</td></tr>
<tr><td>BigBanana 首尾关键帧插值 / Toonflow 无限画布</td><td class="gap">明确不引入</td><td>关键帧驱动归 v18；画布/MCP 记远期思路</td></tr>
<tr><td>ViMax 上下文压缩</td><td class="gap">未做</td><td>v11 黑板 + 会话记录已够当前规模，量级上来再评估</td></tr>
</table>

<h2>六、测试底座（全部无 pytest 直跑）</h2>
<p><span class="cmd">tests/</span>：buffer <b>26/26</b> · retry <b>13/13</b> · embed_index <b>13/13</b> · checkpoint_m4 <b>18/18</b> · subtitle_correct <b>20/20</b> · material_cache <b>20/20</b> · rag <b>21</b> · rag_novel <b>25</b> · grid <b>36</b> —— 本页所有"实测"结论可由上述命令随时复验。</p>
</body>
</html>
"""

out = os.path.join(ROOT, 'docs', 'v17-benchmark.html')
with open(out, 'w', encoding='utf-8') as f:
    f.write(HTML)
print(f'✓ {out}（{os.path.getsize(out) // 1024}KB，3 图内嵌）')
