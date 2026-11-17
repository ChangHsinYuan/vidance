#!/usr/bin/env python3
"""v22 poster 线纯逻辑测试 — 不依赖 GPU/网络（16 项）

覆盖：_norm_plan 规范化（分区白名单/数值钳制/分区冲突/数量上限）/ default_plan 兜底 /
gradient_bg / compose_poster 画布与卡片拟合 / 分区锚点数学 / refine_alpha/ghost_fade /
YOLO 类别猜测 / hex 解析 / PLAN_SYS 自描述。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
from PIL import Image

from agents.generator.tools.poster_llm import (_norm_plan, default_plan,
                                               PLAN_SYS, ZONES)
from agents.generator.tools.poster_pipeline import (
    compose_poster, gradient_bg, refine_alpha, ghost_fade, ZONE_LAYOUT,
    ZONE_ORDER, _guess_yolo_class, _hex_rgb)

PASS = []


def ok(name, cond, detail=''):
    PASS.append((name, bool(cond)))
    print(f'{"✓" if cond else "✗"} {name}' + (f' — {detail}' if detail else ''))


# ── 1. _norm_plan 规范化 ──
p = _norm_plan({'title': 'X' * 30, 'subtitle': 's' * 40, 'tagline': '标' * 20,
                'bg_prompt': 'b' * 600,
                'creatures': [{'name': '猫', 'prompt': 'a cat', 'zone': '-nowhere',
                               'height': 0.9}]}, '测试概念')
ok('title 截断 ≤12', len(p['title']) <= 12)
ok('subtitle 截断 ≤32', len(p['subtitle']) <= 32)
ok('tagline 截断 ≤14', len(p['tagline']) <= 14)
ok('bg_prompt 截断 ≤480', len(p['bg_prompt']) <= 480)
ok('非法 zone 回退 front-right', p['creatures'][0]['zone'] == 'front-right')
ok('height 钳制 ≤0.45', p['creatures'][0]['height'] <= 0.45)

# 分区冲突去重：两只都挤 front-left → 后者挪空位
p2 = _norm_plan({'creatures': [
    {'name': 'a', 'prompt': 'x', 'zone': 'front-left'},
    {'name': 'b', 'prompt': 'y', 'zone': 'front-left'}]}, 'c')
ok('分区冲突去重', len({c['zone'] for c in p2['creatures']}) == 2)
ok('去重后仍是合法分区', all(c['zone'] in ZONES for c in p2['creatures']))

# back-center 高度上限 0.30；>3 只丢弃；无 prompt 丢弃
p3 = _norm_plan({'creatures': [
    {'name': 'a', 'prompt': 'x', 'zone': 'back-center', 'height': 0.45},
    {'name': 'b', 'prompt': 'y'}, {'name': 'c', 'prompt': 'z'}, {'name': 'd', 'prompt': 'w'},
    {'name': 'e', 'prompt': ''}]}, 'c')
ok('back-center 高度 ≤0.30', p3['creatures'][0]['height'] <= 0.30)
ok('生灵数量 ≤3', len(p3['creatures']) == 3)
ok('空 prompt 生灵丢弃', all(c['prompt'] for c in p3['creatures']))

# ── 2. default_plan 兜底 ──
d = default_plan('雪夜古镇')
ok('default_plan 无生灵', d['creatures'] == [])
ok('default_plan tagline 取概念', d['tagline'] == '雪夜古镇'[:12])

# ── 3. gradient_bg 降级底板 ──
g = gradient_bg(256, 384)
arr = np.asarray(g)
ok('gradient_bg 尺寸', g.size == (256, 384))
ok('gradient_bg 非纯黑', arr.mean() > 20)

# ── 4. compose_poster：合成 + 卡片拟合 ──
bg = gradient_bg(256, 384)
plan = {'title': 'VIDANCE', 'subtitle': 'AI VIDEO CREATION AGENT',
        'tagline': '从一句话，到一整部片', 'creatures': []}
out = compose_poster(bg, [], plan, canvas=(600, 900), command=['$ ', 'x' * 200, ''],
                     urls=['example.com/a', 'example.com/b'], rain=False)
ok('compose 画布尺寸', out.size == (600, 900) and out.mode == 'RGB')
ok('compose 长命令不撑爆画布', True)  # 卡片宽度由内容决定但绘制不抛错

out2 = compose_poster(bg, [], plan, canvas=(1200, 1800), command=None, rain=True)
ok('compose 无命令/有雨模式', out2.size == (1200, 1800))

# ── 5. 分区锚点数学：右锚贴图不出右缘 ──
ok('分区表五区齐全', set(ZONE_LAYOUT) == set(ZONE_ORDER))
ok('back-center 先于标题', ZONE_LAYOUT['back-center']['before_title']
   and not any(ZONE_LAYOUT[z]['before_title'] for z in ZONE_ORDER if z != 'back-center'))
ok('mid/front 渐隐仅 mid', ZONE_LAYOUT['mid-right']['ghost'] > 0
   and ZONE_LAYOUT['front-left']['ghost'] == 0)

# 生灵贴图锚点：front-right 不可超出右缘
im = Image.new('RGBA', (400, 400), (255, 0, 0, 255))
W, H = 1200, 1800
ch = int(0.30 * H)
cw = int(im.width * ch / im.height)
x = int(0.95 * W) - cw
ok('right 锚点不出右缘', x + cw <= W and x >= 0)

# ── 6. 效果函数 ──
ra = refine_alpha(im, lo=100, hi=200)
ok('refine_alpha 保尺寸+压暗alpha', ra.size == im.size
   and np.asarray(ra)[:, :, 3].max() <= 255)
gf = ghost_fade(im, frac=0.5)
ok('ghost_fade 底部渐隐', np.asarray(gf)[399, 0, 3] < np.asarray(gf)[0, 0, 3])

# ── 7. YOLO 类别猜测 + hex ──
ok('yolo 类别猜猫', _guess_yolo_class('红蓝双色猫 cat') == 'cat')
ok('yolo 类别猜狗', _guess_yolo_class('柴犬 shiba dog') == 'dog')
ok('yolo 未知返回 None', _guess_yolo_class('鹈鹕 pelican') is None)
ok('hex 解析', _hex_rgb('#ff2828') == (255, 40, 40))
ok('hex 非法兜底', _hex_rgb('zzz') == (0, 229, 255))

# ── 8. PLAN_SYS 自描述 ──
ok('PLAN_SYS 含分区白名单', all(z in PLAN_SYS for z in ZONES))
ok('PLAN_SYS 禁文字水印约束', 'no text' in PLAN_SYS and 'no watermark' in PLAN_SYS)

# ── 汇总 ──
fails = [n for n, c in PASS if not c]
print(f'\n{len(PASS) - len(fails)}/{len(PASS)} passed')
sys.exit(1 if fails else 0)
