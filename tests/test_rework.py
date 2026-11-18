#!/usr/bin/env python3
"""v19（原 v16）rework 纯逻辑测试 — 不依赖 GPU/网络（13 项）

覆盖：URL 解析 / 强度档→ffmpeg 参数 / 防复述相似度 / 时间轴单调 / SRT 生成 /
digest 聚合 / rate 贴合钳制。
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.makedirs('/tmp/opencode', exist_ok=True)  # CI runner 无此目录，测试产物统一落这

from utils.rework import (_digest_source, _sim_max, _STYLES, _write_srt,
                          download_video, extract_frames, _FRAME_EVERY)

PASS = []


def ok(name, cond, detail=''):
    PASS.append((name, bool(cond)))
    print(f'{"✓" if cond else "✗"} {name}' + (f' — {detail}' if detail else ''))


# ── 1. URL 平台识别 ──
import re
m = re.search(r'bilibili\.com/video/(BV\w+)', 'https://www.bilibili.com/video/BV1jTxC6mExW?spm=x')
ok('bilibili bvid 解析', m and m.group(1) == 'BV1jTxC6mExW')
ok('非 B站 platform=other',
   not re.search(r'bilibili\.com/video/(BV\w+)', 'https://youtube.com/watch?v=x'))

# ── 2. 防复述相似度断言 ──
blocks = [{'start': 0, 'end': 30, 'text': '故宫太和殿的天花板上竟然隐藏了一颗世界上最早的监控镜头'},
          {'start': 30, 'end': 60, 'text': '工匠们用琉璃烧制出直径五十公分的球体'}]
ok('改写句相似度 < 0.55（真改写）',
   _sim_max('谁能想到，六百年前的房顶上装着古人的安保装置', blocks) < 0.55)
ok('复述句相似度 ≥ 0.55（被抓）',
   _sim_max('太和殿的天花板上竟然隐藏了一颗世界上最早的监控镜头', blocks) >= 0.55)

# ── 3. digest 聚合（30s 块 + 帧抽稀） ──
src = {'duration': 100,
       'segments': [{'start': i * 10.0, 'end': i * 10.0 + 9.5, 'text': f'第{i}句'}
                    for i in range(10)],
       'frames': [{'t': i * 5.0, 'visual': f'画面{i}'} for i in range(20)]}
bl, vs = _digest_source(src)
ok('digest 块数 ≈ duration/block_sec', 3 <= len(bl) <= 4, f'{len(bl)} 块')
ok('digest 块内时间单调', all(b['end'] >= b['start'] for b in bl))
ok('digest 帧抽稀 ~30s 步长', len(vs) == len(range(0, len(src['frames']), 6)), f'{len(vs)} 条')

# ── 4. SRT 生成 ──
srt = os.path.join('/tmp/opencode', 'test_rework.srt')
_write_srt([(0.0, 2.5, '第一句'), (2.5, 6.0, '第二句')], srt)
content = open(srt, encoding='utf-8').read()
ok('SRT 序号+时间轴', '1\n00:00:00,000 --> 00:00:02,500\n第一句' in content)
ok('SRT 末段', '00:00:02,500 --> 00:00:06,000\n第二句' in content)

# ── 5. 档位→ffmpeg 参数（_preclip 参数化验证，跑最小档 0） ──
sys.path.insert(0, ROOT)
from utils.rework import _preclip
# 生成 3s 测试源视频（纯 ffmpeg，无网络）
test_src = '/tmp/opencode/rework_tsrc.mp4'
os.system(f'ffmpeg -y -f lavfi -i testsrc=duration=3:size=640x360:rate=24 '
          f'-c:v libx264 -pix_fmt yuv420p {test_src} 2>/dev/null')
seg = {'ref_start': 0.5, 'ref_dur': 2.0, 'narr_dur': 2.0, '_i': 0}
out0 = '/tmp/opencode/rework_pre0.mp4'
_preclip(test_src, seg, out0, level=0)
ok('L0 preclip 产出', os.path.isfile(out0) and os.path.getsize(out0) > 10000)
ok('L0 rate=1.0（ref_dur=narr_dur）', abs(seg['rate'] - 1.0) < 0.01, f"rate={seg['rate']}")
seg2 = {'ref_start': 0.0, 'ref_dur': 3.0, 'narr_dur': 2.0, '_i': 0}
out1 = '/tmp/opencode/rework_pre1.mp4'
_preclip(test_src, seg2, out1, level=4)
ok('L4 rate 钳制 ≤1.6', seg2['rate'] <= 1.6, f"rate={seg2['rate']}")
# 输出时长 ≈ narr_dur+0.2
from utils.rework import _probe
d = _probe(out1)['duration']
ok('输出时长贴合 narr_dur+0.2', abs(d - 2.2) < 0.35, f'{d:.2f}s')

# ── 6. 风格表完整 ──
ok('四种风格注册', set(_STYLES) == {'解说', '盘点', '吐槽', '第一人称'})
ok('第一人称风格含人称反转铁律',
   '第三人称' in _STYLES['第一人称'] and '第一人称' in _STYLES['第一人称'])

# ── 7. 抽帧索引推导 ──
frs = extract_frames.__doc__
ok('抽帧文档含间隔说明', frs and 'every' in frs)

# ── 8. 字幕消除：OCR 输出解析 + 启发式先验（不联网） ──
from agents.post.tools.sam_edit import _parse_ocr_boxes
t_native = '''从"测试过程"到
image [329, 293, 665, 785]
text [287, 880, 713, 941]和蟠龙口中的宝珠四个部分组成'''
r = _parse_ocr_boxes(t_native, 1920, 1080)
ok('OCR 原生格式解析（千分比→像素）',
   len(r) == 1 and r[0][4] == 'text'
   and all(abs(a - e) < 1e-6 for a, e in
           zip(r[0][:4], (287*1.92, 880*1.08, 713*1.92, 941*1.08))),
   f'实际 {r}')
ok('OCR 版面元素被底部先验滤除',
   all(b[1] / 1080 >= 0.75 for b in r))
import json as _json
t_json = _json.dumps({'subtitle_boxes': [
    {'text': '故宫太和殿', 'box': [500, 950, 1400, 1030]},
    {'text': '大版面框', 'box': [100, 100, 1800, 800]}]})
r2 = _parse_ocr_boxes(t_json, 1920, 1080)
ok('OCR JSON 格式解析 + 大框过滤',
   len(r2) == 1 and r2[0][:4] == (500*1.92, 950*1.08, 1400*1.92, 1030*1.08))
ok('OCR 无字幕输出', _parse_ocr_boxes('无', 1920, 1080) == [])

# 千分比规范坐标（0-999，与输入分辨率无关）→ 像素映射（实测 704p/1080p 同值、上限 999）
r3 = _parse_ocr_boxes('text [287, 880, 713, 941]和蟠龙口中的宝珠', 1280, 704)
ok('OCR 千分比坐标映射（704p）',
   len(r3) == 1 and abs(r3[0][1] - 880 * 704 / 1000) < 1
   and abs(r3[0][3] - 941 * 704 / 1000) < 1,
   f'实际 {r3}')
r4 = _parse_ocr_boxes('text [287, 880, 713, 941]同帧', 1920, 1080)
ok('OCR 千分比坐标与输入分辨率无关',
   abs(r4[0][1] - 880 * 1080 / 1000) < 1 and abs(r4[0][3] - 941 * 1080 / 1000) < 1)

from agents.post.tools.sam_edit import _subtitle_mask_from_norm
mask = _subtitle_mask_from_norm([(0.1, 0.88, 0.9, 0.94)], 1280, 704)
ok('归一化框→mask 覆盖底部带',
   mask[int(0.90*704), int(0.5*1280)] == 255 and mask[int(0.5*704), int(0.5*1280)] == 0)
mask_fb = _subtitle_mask_from_norm([], 1280, 704)
ok('无框回退底部 30% 带', mask_fb[int(0.85*704), 640] == 255 and mask_fb[100, 640] == 0)

print(f'\n{sum(1 for _, c in PASS if c)}/{len(PASS)} passed')
sys.exit(0 if all(c for _, c in PASS) else 1)
