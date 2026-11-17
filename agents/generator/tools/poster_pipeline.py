#!/usr/bin/env python3
"""v22 M2/M3（poster 线）：海报 JSON → FLUX 底板 → SAM 抠图 → PIL 合成排版 → jpg

管线（照抄 v13 blender / v15 ppt 的 Line 架构；效果函数移植自宣传海报 v8 实测参数）：
  - generate_plates()   FLUX 文生图（底板 2:3 + 生灵立绘纯黑底）
  - cutout_creatures()  Grounded-SAM（YOLO 框提示）抠图；失败时亮度键控兜底
  - compose_poster()    数据驱动合成：标题色散+辉光 / 生灵分区贴图 / 终端卡片 / QR / 雨丝 / 暗角颗粒
  - PosterLine          一键：LLM 规划 → 底板 → 抠图 → 合成 → output/poster*/poster.jpg

分区（相对画布）：back-center 后景全息 / mid-* 中景渐隐 / front-* 前景最大
降级：FLUX 不可用 → 渐变底板+无生灵（meta degraded=true）；SAM 不可用 → 亮度键控抠图

用法：
  python agents/generator/tools/poster_pipeline.py "紫色雨夜霓虹月亮下的红蓝猫" -o /tmp/poster.jpg
  python agents/generator/tools/poster_pipeline.py --plan plan.json --bg bg.png --creatures c1.png,c2.png
"""
import os as _os
import sys as _sys
_ROOT = _os.path.abspath(__file__)
for _ in range(4):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
import argparse
import json as _json
import random
import time as _t

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from agents.generator.tools.poster_llm import _norm_plan, plan_poster

# ── 字体（DejaVu 拉丁 + Noto CJK 黑体；混排见 _font_for） ──
_FONTS = {
    'bold': ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'],
    'mono': ['/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'],
    'cjk': ['/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc',
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
            '/usr/share/fonts/noto-cjk/NotoSansCJK-Black.ttc'],
}
_DEFAULT_FONT = ImageFont.load_default()


def _font(kind, size, index=0):
    for p in _FONTS[kind]:
        try:
            return ImageFont.truetype(p, size, index=index)
        except Exception:
            continue
    return _DEFAULT_FONT


def font_cjk(size):
    """Noto CJK ttc 常见 index 探测（Black 通常在 2）。"""
    for idx in (2, 0, 1, 3, 4):
        f = _font('cjk', size, index=idx)
        if f is not _DEFAULT_FONT:
            return f
    return _font('bold', size)


def _font_for(seg, latin, cjk):
    """终端卡混排：含 CJK（ord>0x2E7F）用中文字体，否则等宽拉丁（防豆腐块）。"""
    return cjk if any(ord(ch) > 0x2E7F for ch in seg) else latin


# ── 效果函数（v8 实测参数） ──

def refine_alpha(im, lo=35, hi=120):
    """亮度键控精修：杀 mask 内残留暗底像素（发光生灵在纯黑底上抠得干净）。"""
    arr = np.asarray(im).astype(np.float32)
    luma = arr[:, :, :3].max(axis=2)
    t = np.clip((luma - lo) / max(hi - lo, 1), 0, 1)
    arr[:, :, 3] = arr[:, :, 3] * t
    a = Image.fromarray(arr.astype(np.uint8))
    return a.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(1.2))


def ghost_fade(im, frac=0.30):
    """全息渐隐：底部 alpha 衰减（中景/后景生灵防贴纸感）。"""
    arr = np.asarray(im).astype(np.float32)
    h = arr.shape[0]
    n = max(int(h * frac), 1)
    ramp = np.linspace(1.0, 0.10, n)[:, None]
    arr[h - n:, :, 3] *= ramp
    return Image.fromarray(arr.astype(np.uint8))


def glow_layer(img, radius, color):
    a = img.split()[3].filter(ImageFilter.GaussianBlur(radius))
    g = Image.new('RGBA', img.size, tuple(color) + (0,))
    g.putalpha(a)
    return g


def draw_spaced(layer, xy, text, font, fill, spacing=14, anchor_center_x=None):
    d = ImageDraw.Draw(layer)
    widths = [d.textlength(c, font=font) for c in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x = (anchor_center_x - total / 2) if anchor_center_x is not None else xy[0]
    for c, w in zip(text, widths):
        d.text((x, xy[1]), c, font=font, fill=fill)
        x += w + spacing
    return total


def _hex_rgb(s):
    s = str(s).strip().lstrip('#')
    try:
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (0, 229, 255)


# ── 生灵分区（相对画布 W/H，v8 版式） ──
# x: 锚点比例（left=左缘 / right=右缘 / center=居中）；y/h: 顶部与高度比例
ZONE_LAYOUT = {
    'back-center': {'x': 0.50, 'y': 0.433, 'h': 0.19, 'anchor': 'center',
                    'ghost': 0.0, 'before_title': True},
    'mid-left':    {'x': 0.05, 'y': 0.472, 'h': 0.167, 'anchor': 'left',
                    'ghost': 0.30, 'before_title': False},
    'mid-right':   {'x': 0.95, 'y': 0.472, 'h': 0.167, 'anchor': 'right',
                    'ghost': 0.30, 'before_title': False},
    'front-left':  {'x': 0.05, 'y': 0.622, 'h': 0.30, 'anchor': 'left',
                    'ghost': 0.0, 'before_title': False},
    'front-right': {'x': 0.95, 'y': 0.622, 'h': 0.30, 'anchor': 'right',
                    'ghost': 0.0, 'before_title': False},
}
ZONE_ORDER = ('back-center', 'mid-left', 'mid-right', 'front-left', 'front-right')
DEFAULT_GLOW = ((0, 229, 255), (255, 0, 200))


def paste_glowed(base, img, x, y, h, glow_colors=DEFAULT_GLOW, gr=24):
    """生灵贴图：refine_alpha → 紫色 wash（防贴纸感）→ 双色辉光 → 落位。"""
    w = int(img.width * h / img.height)
    im = refine_alpha(img).resize((w, h), Image.LANCZOS)
    a = im.split()[3]
    tint = Image.new('RGBA', im.size, (120, 80, 210, 0))
    tint.putalpha(a.point(lambda v: int(v * 0.14)))
    im.alpha_composite(tint)
    for gc in list(glow_colors)[:2]:
        g = glow_layer(im, gr, gc)
        g.putalpha(g.split()[3].point(lambda v: int(v * 0.55)))
        base.alpha_composite(g, (x - gr, y - gr))
    base.alpha_composite(im, (x, y))
    return w


def compose_poster(bg_img, creatures, plan, canvas=(1200, 1800), command=None,
                   urls=(), qr_url=None, rain=True, seed=42):
    """底板 + 生灵 + 排版 → 合成海报（RGB）。creatures: [{img, zone, height, glow?}]。

    所有排版常量按画布比例缩放（v8 = 1200×1800 基准）。
    """
    W, H = int(canvas[0]), int(canvas[1])
    sx, sy = W / 1200.0, H / 1800.0
    random.seed(seed)
    np.random.seed(seed)

    bg = bg_img.convert('RGB').resize((W, H), Image.LANCZOS)
    canvas_im = bg.convert('RGBA')

    # ── 后景生灵（title 之下，全息小尺寸） ──
    for c in creatures:
        L = ZONE_LAYOUT.get(c.get('zone'), {})
        if not L.get('before_title'):
            continue
        base_h = L['h'] * (float(c.get('height') or L['h']) / L['h'])
        ch = int(base_h * H)
        cw = int(c['img'].width * ch / c['img'].height)
        paste_glowed(canvas_im, c['img'], W // 2 - cw // 2, int(L['y'] * H), ch,
                     glow_colors=c.get('glow') or ((255, 0, 200),), gr=int(26 * sx))

    # ── 标题（色散 + 大辉光，-2.5° 旋转；超宽自动缩字号） ──
    title_txt = plan.get('title') or 'VIDANCE'
    tsize = int(185 * sx)
    probe = ImageDraw.Draw(Image.new('RGBA', (10, 10)))
    while tsize > 40:
        tf = _font('bold', tsize)
        widths = [probe.textlength(ch_, font=tf) for ch_ in title_txt]
        total = sum(widths) + int(26 * sx) * (len(title_txt) - 1)
        if total <= 0.86 * W:
            break
        tsize = int(tsize * 0.92)
    tf = _font('bold', tsize)
    title = Image.new('RGBA', (int(W * 1.3), int(tsize * 3)), (0, 0, 0, 0))
    draw_spaced(title, (0, int(tsize * 0.48)), title_txt, tf, (255, 255, 255, 255),
                spacing=int(26 * sx), anchor_center_x=title.width // 2)
    title = title.rotate(-2.5, expand=True, resample=Image.BICUBIC)
    tw, _th = title.size
    tx, ty = W // 2 - tw // 2, int(0.311 * H)
    off = int(5 * sx)
    ca_m = Image.new('RGBA', title.size, (0, 0, 0, 0))
    ca_m.paste((255, 0, 190, 160), mask=title.split()[3])
    ca_c = Image.new('RGBA', title.size, (0, 0, 0, 0))
    ca_c.paste((0, 220, 255, 160), mask=title.split()[3])
    canvas_im.alpha_composite(glow_layer(ca_m, int(10 * sx), (255, 0, 190)),
                              (tx - off, ty + int(2 * sy)))
    canvas_im.alpha_composite(glow_layer(ca_c, int(10 * sx), (0, 220, 255)),
                              (tx + off, ty - int(2 * sy)))
    canvas_im.alpha_composite(glow_layer(title, int(24 * sx), (90, 60, 255)), (tx, ty))
    canvas_im.alpha_composite(ca_m, (tx - off, ty + int(2 * sy)))
    canvas_im.alpha_composite(ca_c, (tx + off, ty - int(2 * sy)))
    canvas_im.alpha_composite(title, (tx, ty))

    # ── 副标题 ──
    sub_txt = (plan.get('subtitle') or '').strip()
    if sub_txt:
        sub = Image.new('RGBA', (W, int(120 * sy)), (0, 0, 0, 0))
        draw_spaced(sub, (0, int(30 * sy)), sub_txt.upper(), _font('bold', int(34 * sx)),
                    (190, 245, 255, 235), spacing=int(10 * sx), anchor_center_x=W // 2)
        canvas_im.alpha_composite(glow_layer(sub, int(8 * sx), (0, 200, 255)), (0, 0))
        canvas_im.alpha_composite(sub, (0, 0))

    # ── 中景/前景生灵（title 之上，按分区顺序） ──
    fronts = [c for c in creatures
              if not ZONE_LAYOUT.get(c.get('zone'), {}).get('before_title')]
    for c in sorted(fronts, key=lambda c: ZONE_ORDER.index(c.get('zone', 'front-right'))):
        L = ZONE_LAYOUT[c['zone']]
        base_h = L['h'] * (float(c.get('height') or L['h']) / L['h'])
        ch = int(base_h * H)
        im = ghost_fade(c['img']) if L['ghost'] else c['img']
        cw = int(im.width * ch / im.height)
        if L['anchor'] == 'right':
            x = int(L['x'] * W) - cw
        elif L['anchor'] == 'center':
            x = W // 2 - cw // 2
        else:
            x = int(L['x'] * W)
        paste_glowed(canvas_im, im, x, int(L['y'] * H), ch,
                     glow_colors=c.get('glow') or DEFAULT_GLOW, gr=int(20 * sx))

    # ── 中文标语（紫色辉光） ──
    tag_txt = (plan.get('tagline') or '').strip()
    if tag_txt:
        tag = Image.new('RGBA', (W, int(160 * sy)), (0, 0, 0, 0))
        gf = font_cjk(int(66 * sx))
        d = ImageDraw.Draw(tag)
        d.text(((W - d.textlength(tag_txt, font=gf)) / 2, int(20 * sy)), tag_txt,
               font=gf, fill=(255, 255, 255, 250))
        canvas_im.alpha_composite(glow_layer(tag, int(14 * sx), (140, 80, 255)), (0, 0))
        canvas_im.alpha_composite(tag, (0, int(0.722 * H)))

    # ── 底部可读性渐变 ──
    scrim_h = int(0.267 * H)
    scrim = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    for i in range(scrim_h):
        a = int(205 * (i / scrim_h) ** 1.5)
        sd.line((0, H - scrim_h + i, W, H - scrim_h + i), fill=(4, 6, 18, a))
    canvas_im.alpha_composite(scrim)

    # ── 终端卡片（真实命令；混排字体防 CJK 豆腐块） ──
    if command:
        mf = _font('mono', int(24 * sx))
        cf = font_cjk(int(24 * sx))
        seg_w = sum(probe.textlength(seg, font=_font_for(seg, mf, cf)) for seg in command)
        cw = max(int(seg_w) + int(64 * sx), int(160 * sx))
        ch = int(92 * sy)
        cx = (W - cw) // 2
        card = Image.new('RGBA', (W, ch), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cy_c = 0
        cd.rounded_rectangle((cx, cy_c, cx + cw, cy_c + ch), radius=int(16 * sx),
                             fill=(8, 10, 26, 200), outline=(0, 229, 255, 160),
                             width=max(2, int(2 * sx)))
        x, y = cx + int(32 * sx), cy_c + int(30 * sy)
        for seg in command:
            f = _font_for(seg, mf, cf)
            cd.text((x, y), seg, font=f, fill=(180, 255, 220, 255))
            x += probe.textlength(seg, font=f)
        cd.rectangle((x + int(8 * sx), y + int(2 * sy), x + int(13 * sx),
                      y + int(26 * sy)), fill=(0, 255, 170, 255))
        cy0 = int(0.829 * H)
        canvas_im.alpha_composite(glow_layer(card, int(10 * sx), (0, 180, 255)), (0, cy0))
        canvas_im.alpha_composite(card, (0, cy0))

    # ── 页脚 URL + 柔影 + QR ──
    urls = [u for u in (urls or ()) if u]
    if urls:
        uf = _font('bold', int(24 * sx))
        ax = (W - int(150 * sx)) // 2
        fy = int(0.90 * H)
        shadow = Image.new('RGBA', (W, int(110 * sy)), (0, 0, 0, 0))
        for i, u in enumerate(urls[:2]):
            draw_spaced(shadow, (0, int(8 * sy) + i * int(50 * sy)), u.upper(), uf,
                        (0, 0, 0, 140), spacing=int(3 * sx), anchor_center_x=ax)
        canvas_im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(2.5)), (0, fy))
        url_l = Image.new('RGBA', (W, int(110 * sy)), (0, 0, 0, 0))
        for i, u in enumerate(urls[:2]):
            draw_spaced(url_l, (0, int(8 * sy) + i * int(50 * sy)), u.upper(), uf,
                        (255, 255, 255, 225) if i == 0 else (210, 230, 255, 190),
                        spacing=int(3 * sx), anchor_center_x=ax)
        canvas_im.alpha_composite(url_l, (0, fy))
    if qr_url:
        try:
            import qrcode
            q = qrcode.QRCode(border=1, box_size=4)
            q.add_data(qr_url)
            q.make()
            qi = q.make_image(fill_color='white', back_color=(10, 12, 26)).convert('RGBA')
            qi = qi.resize((int(120 * sx), int(120 * sx)), Image.NEAREST)
            canvas_im.alpha_composite(qi, (W - int(160 * sx), int(0.883 * H)))
        except Exception as e:
            print(f'  ⚠ QR 跳过（{e}）')

    # ── 雨丝 ──
    if rain:
        rain = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        rd = ImageDraw.Draw(rain)
        n = max(60, int(140 * (W * H) / (1200 * 1800)))
        for _ in range(n):
            x, y = random.randint(0, W), random.randint(0, H)
            ln = random.randint(int(18 * sy), int(42 * sy))
            dx = int(ln * 0.22)
            a = random.randint(24, 70)
            rd.line((x, y, x - dx, y + ln), fill=(200, 220, 255, a), width=1)
        canvas_im.alpha_composite(rain.filter(ImageFilter.GaussianBlur(0.6)))

    # ── 暗角 + 颗粒 + 对比/饱和 ──
    yy, xx = np.mgrid[0:H, 0:W]
    cx0, cy0 = W / 2, H * 0.45
    dist = np.sqrt(((xx - cx0) / (W * 0.72)) ** 2 + ((yy - cy0) / (H * 0.72)) ** 2)
    vig = np.clip(1.12 - 0.42 * np.clip(dist - 0.45, 0, None) ** 1.6, 0.55, 1.12)
    arr = np.asarray(canvas_im.convert('RGB')).astype(np.float32)
    arr *= vig[:, :, None]
    arr += np.random.normal(0, 4.5, arr.shape)
    out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    out = ImageEnhance.Contrast(out).enhance(1.05)
    return ImageEnhance.Color(out).enhance(1.12)


def gradient_bg(w, h):
    """FLUX 降级底板：紫夜渐变 + 月晕（纯 numpy，无 GPU 依赖）。"""
    top, mid, bot = (16, 8, 38), (58, 26, 110), (10, 6, 24)
    yy, xx = np.mgrid[0:h, 0:w]
    t = yy / max(h - 1, 1)
    arr = np.zeros((h, w, 3), np.float32)
    for i in range(3):
        arr[:, :, i] = top[i] * (1 - t) ** 2 + mid[i] * 2 * t * (1 - t) + bot[i] * t ** 2
    cy, cx = int(h * 0.28), int(w * 0.5)
    d2 = ((xx - cx) / (w * 0.16)) ** 2 + ((yy - cy) / (h * 0.10)) ** 2
    halo = np.clip(1 - d2, 0, 1) ** 2
    for i, c in enumerate((220, 205, 255)):
        arr[:, :, i] += halo * c * 0.55
    arr += np.random.normal(0, 3.0, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ── M2/M3：底板生成 + 抠图 ──

def generate_plates(plan, workdir, bg_seeds=None, creature_seeds=None,
                    width=1024, height=1536, client=None):
    """FLUX 生成底板与生灵立绘。返回 (bg_path|None, {name: path}, notes[])。

    底板多 seed 重试；生灵单 seed 失败即跳过（不阻塞海报）。FLUX 整体不可用 → (None, {}, notes)。
    """
    notes = []
    bg_seeds = list(bg_seeds or [101, 202, 303])
    creature_seeds = list(creature_seeds or [11, 33, 55])
    plates_dir = _os.path.join(workdir, 'plates')
    _os.makedirs(plates_dir, exist_ok=True)
    cli = client
    if cli is None:
        try:
            from agents.generator.tools.comfy_api import ComfyClient
            cli = ComfyClient(instance='flux')
        except Exception as e:
            notes.append(f'FLUX 客户端不可用：{e}')
            return None, {}, notes
    bg_path = None
    for seed in bg_seeds:
        out = _os.path.join(plates_dir, f'bg_{seed}.png')
        if _os.path.exists(out):
            bg_path = out
            break
        try:
            print(f'  [flux] bg seed={seed} {width}x{height} …')
            cli.generate_flux_t2i(plan['bg_prompt'], seed=seed, width=width,
                                  height=height, steps=20, guidance=3.5,
                                  output_path=out)
            bg_path = out
            break
        except Exception as e:
            notes.append(f'bg seed={seed} 失败：{e}')
    creatures = {}
    for i, c in enumerate(plan.get('creatures', [])):
        seed = creature_seeds[i % len(creature_seeds)] + i
        name = c.get('name') or f'creature{i}'
        out = _os.path.join(plates_dir, f'{name}_{seed}.png')
        try:
            print(f'  [flux] {name} seed={seed} …')
            cli.generate_flux_t2i(c['prompt'], seed=seed, width=1024, height=1024,
                                  steps=20, guidance=3.5, output_path=out)
            creatures[name] = out
        except Exception as e:
            notes.append(f"生灵 {name} 生成失败：{e}")
    return bg_path, creatures, notes


_YOLO_CLASSES = ('cat', 'dog', 'bird', 'horse', 'sheep', 'cow', 'bear',
                 'elephant', 'zebra', 'giraffe', 'person')


def _guess_yolo_class(name):
    n = str(name).lower()
    for c in _YOLO_CLASSES:
        if c in n:
            return c
    return None


def cutout_creatures(creature_plates, workdir, classes=None):
    """Grounded-SAM（YOLO 框提示）逐只抠图 → RGBA。失败单只降级亮度键控。

    返回 ({name: RGBA Image}, {name: 'sam'|'luma'}, notes[])。
    """
    notes = []
    out, how = {}, {}
    from PIL import Image as _Image
    se = None
    try:
        from agents.post.tools import sam_edit as se
    except Exception as e:
        notes.append(f'SAM2 不可用：{e}')
    for name, path in creature_plates.items():
        png = _os.path.join(workdir, 'cutouts', f'{name}.png')
        _os.makedirs(_os.path.dirname(png), exist_ok=True)
        done = False
        if se is not None:
            try:
                import numpy as _np
                img = _np.array(_Image.open(path).convert('RGB'))
                cls = (classes or {}).get(name) or _guess_yolo_class(name)
                dets = se.detect_objects(img, classes=[cls] if cls else None, conf=0.25)
                if dets:
                    box = max(dets, key=lambda d: (d[2][2] - d[2][0]) * (d[2][3] - d[2][1]))[2]
                    masks, scores, _ = se.segment_from_boxes(img, [box])
                    if masks:
                        se.cutout(img, masks[0], png)
                        out[name] = _Image.open(png).convert('RGBA')
                        how[name] = 'sam'
                        done = True
                if not done:
                    notes.append(f'{name} YOLO/SAM 未检出 → 亮度键控兜底'
                                 + (f'（类别 {cls}）' if cls else ''))
            except Exception as e:
                notes.append(f'{name} SAM 抠图失败（降级亮度键控）：{e}')
        if not done:
            im = _Image.open(path).convert('RGBA')
            out[name] = refine_alpha(im, lo=20, hi=95)
            how[name] = 'luma'
    return out, how, notes


# ── M4：一键管线（对标 BlenderLine/PptLine） ──

class PosterLine:
    """概念 → LLM 海报规划 → FLUX 底板 → SAM 抠图 → 合成排版 → poster.jpg。"""

    def __init__(self, config=None):
        from utils.config_loader import load_config
        self.config = config or load_config()
        self.output_dir = self.config.get('output_dir', 'output')

    def run(self, concept, title=None, tagline=None, plan_path=None, out_path=None,
            width=1024, height=1536, seeds=None, creature_seeds=None, model=None,
            style_hint=None, command=None, no_terminal=False, urls=None,
            qr_url=None, rain=True, creature_classes=None, stage_cb=None,
            on_chunk=None) -> dict:
        import datetime
        from agents.common.tools.config_loader import task_id_for
        start = _t.time()
        ts = task_id_for('poster')
        workdir = _os.path.join(self.output_dir, ts)
        _os.makedirs(workdir, exist_ok=True)
        plan = {}

        def _scb(s):
            if stage_cb:
                try:
                    stage_cb(s)
                except Exception:
                    pass
            print(f'[{s}]')

        # 1) 规划（LLM / plan.json 渲染模式）
        _scb('M1 海报规划')
        if plan_path:
            with open(plan_path, 'r', encoding='utf-8') as f:
                plan = _norm_plan(_json.load(f), concept or '')
        else:
            plan = plan_poster(concept, model=model, on_chunk=on_chunk,
                               style_hint=style_hint)
        if title:
            plan['title'] = str(title)[:12]
        if tagline:
            plan['tagline'] = str(tagline)[:14]
        with open(_os.path.join(workdir, 'plan.json'), 'w', encoding='utf-8') as f:
            _json.dump(plan, f, ensure_ascii=False, indent=2)
        print(f'  {plan["title"]} · {len(plan["creatures"])} 生灵 · {plan["tagline"]}')

        # 2) FLUX 底板
        _scb('M2 FLUX 底板生成')
        bg_path, creature_plates, notes = generate_plates(
            plan, workdir, bg_seeds=seeds, creature_seeds=creature_seeds,
            width=width, height=height)
        degraded = bg_path is None
        if degraded:
            notes.append('FLUX 不可用 → 渐变底板降级')
            bg_img = gradient_bg(width, height)
        else:
            bg_img = Image.open(bg_path)

        # 3) SAM 抠图
        _scb('M3 SAM 抠图')
        creature_imgs, how, cut_notes = cutout_creatures(
            creature_plates, workdir, classes=creature_classes)
        notes.extend(cut_notes)
        creatures = []
        for c in plan.get('creatures', []):
            name = c.get('name') or f'creature{c.get("zone", "")}'
            if name in creature_imgs:
                creatures.append({'img': creature_imgs[name],
                                  'zone': c.get('zone', 'front-right'),
                                  'height': c.get('height'),
                                  'glow': [_hex_rgb(g) for g in (c.get('glow') or [])]})
        print(f'  抠图 {len(creatures)}/{len(creature_plates)}'
              + (' · '.join(f'{k}={v}' for k, v in how.items()) if how else ''))

        # 4) 合成排版
        _scb('M4 合成排版')
        scale = 1200.0 / width
        canvas = (1200, int(height * scale))
        cmd = None if no_terminal else (command or
                                        f'python core/vidance.py auto "{concept[:18]}"')
        poster = compose_poster(bg_img, creatures, plan, canvas=canvas,
                                command=cmd, urls=urls, qr_url=qr_url, rain=rain)
        out = out_path or _os.path.join(workdir, 'poster.jpg')
        _os.makedirs(_os.path.dirname(_os.path.abspath(out)), exist_ok=True)
        poster.save(out, quality=90)

        meta = {'task_id': ts, 'concept': concept, 'mode': 'poster',
                'plan': plan, 'output': out, 'size': list(poster.size),
                'degraded': degraded, 'creature_mode': how,
                'plates': {'bg': bg_path, 'creatures': creature_plates},
                'notes': notes, 'elapsed_s': round(_t.time() - start, 1),
                'created_at': datetime.datetime.now().isoformat()}
        with open(_os.path.join(workdir, 'meta.json'), 'w', encoding='utf-8') as f:
            _json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f'✅ {out}（{poster.width}×{poster.height}'
              f'{" · 降级" if degraded else ""} · {meta["elapsed_s"]}s）')
        return meta


def main():
    ap = argparse.ArgumentParser(description='概念 → 海报 jpg（v22 poster 线）')
    ap.add_argument('concept', nargs='?', default=None, help='主题（一键模式）')
    ap.add_argument('--plan', default=None, help='plan.json 路径（渲染模式）')
    ap.add_argument('--bg', default=None, help='现成底板（跳过 FLUX）')
    ap.add_argument('--creatures', default=None, help='现成生灵图（逗号分隔，跳过 FLUX）')
    ap.add_argument('--title', default=None, help='覆盖主标题（≤12 字符）')
    ap.add_argument('--tagline', default=None, help='覆盖中文标语（≤14 字）')
    ap.add_argument('-o', '--output', default=None, help='jpg 输出路径')
    ap.add_argument('--width', type=int, default=1024, help='底板宽（2:3）')
    ap.add_argument('--height', type=int, default=1536, help='底板高')
    ap.add_argument('--seeds', type=int, nargs='*', default=None, help='底板 seed 序列')
    ap.add_argument('--command', default=None, help='终端卡命令文本（缺省 auto 示例）')
    ap.add_argument('--url', action='append', default=None, help='页脚 URL（可重复 2 个）')
    ap.add_argument('--qr-url', default=None, help='右下角 QR 链接')
    ap.add_argument('--no-terminal', action='store_true', help='不画终端卡片')
    ap.add_argument('--no-rain', action='store_true', help='不画雨丝')
    ap.add_argument('--model', default=None, help='LLM 模型')
    args = ap.parse_args()

    line = PosterLine()
    concept = args.concept or ''
    if args.plan:
        with open(args.plan, 'r', encoding='utf-8') as f:
            plan = _norm_plan(_json.load(f), concept)
        # 渲染模式：--bg/--creatures 给了就跳过 FLUX；否则按 plan 生成
        workdir = 'output/poster_render'
        if args.bg:
            bg_img = Image.open(args.bg)
            plates = {}
            if args.creatures:
                for i, p in enumerate(args.creatures.split(',')):
                    plates[f'c{i}'] = p
            notes = []
        else:
            bg_path, plates, notes = generate_plates(plan, workdir,
                                                     bg_seeds=args.seeds,
                                                     width=args.width,
                                                     height=args.height)
            bg_img = Image.open(bg_path) if bg_path else gradient_bg(args.width, args.height)
        imgs, how, cn = cutout_creatures(plates, workdir)
        creatures = []
        for i, c in enumerate(plan.get('creatures', [])):
            key = c.get('name') or f'creature{i}'
            if key in imgs:
                creatures.append({'img': imgs[key], 'zone': c.get('zone', 'front-right'),
                                  'height': c.get('height'),
                                  'glow': [_hex_rgb(g) for g in (c.get('glow') or [])]})
            elif f'c{i}' in imgs:
                creatures.append({'img': imgs[f'c{i}'], 'zone': c.get('zone', 'front-right'),
                                  'height': c.get('height'),
                                  'glow': [_hex_rgb(g) for g in (c.get('glow') or [])]})
        scale = 1200.0 / args.width
        canvas = (1200, int(args.height * scale))
        cmd = None if args.no_terminal else (
            args.command or f'python core/vidance.py auto "{(concept or plan["tagline"])[:18]}"')
        poster = compose_poster(bg_img, creatures, plan, canvas=canvas, command=cmd,
                                urls=args.url or (), qr_url=args.qr_url,
                                rain=not args.no_rain)
        out = args.output or 'output/poster_render/poster.jpg'
        _os.makedirs(_os.path.dirname(_os.path.abspath(out)), exist_ok=True)
        poster.save(out, quality=90)
        print(f'✅ {out}（{poster.width}×{poster.height}）')
        return
    if not concept:
        ap.error('需要 concept 或 --plan')
    line.run(concept, title=args.title, tagline=args.tagline, out_path=args.output,
             width=args.width, height=args.height, seeds=args.seeds, model=args.model,
             command=args.command, no_terminal=args.no_terminal, urls=args.url,
             qr_url=args.qr_url, rain=not args.no_rain)


if __name__ == '__main__':
    main()
