#!/usr/bin/env python3
"""v15 M1/M3：概念/大纲 → LLM → 多页 HTML 幻灯片（deck）规划 + 模板渲染 + SVG 图表

分工：
  - LLM 只出**结构化 JSON**（版式/标题/要点/图表数据/旁白），不直接产 HTML —— 可控、可容错
  - 版式（title/toc/content/data/end）由 Python 模板渲染，风格统一（主题色/字体全局约束）
  - 图表（bar/line/pie）由 svg_chart() 数据驱动生成矢量 SVG —— LLM 只出数据不出图形

用法：
  python agents/generator/tools/ppt_llm.py "季度总结" --n 5 -o output/ppt/deck.html
"""
import os as _os
import sys as _sys
_ROOT = _os.path.abspath(__file__)
for _ in range(4):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
import argparse
import json
import os
import re

from utils.config_loader import load_config

from agents.generator.tools.svg_llm import _chat_stream

LAYOUTS = ('title', 'toc', 'content', 'data', 'end')

PLAN_SYS = """你是专业的 PPT 策划师。根据主题规划一份 {n} 页的幻灯片大纲（JSON）。
结构要求：第 1 页 title（封面），第 2 页 toc（目录，可省），中间 content/data 穿插，
最后 1 页 end（结尾致谢）。data 页用于数据展示（占比/趋势/对比），一份 PPT 里 1-2 页即可。
每页 notes 是该页的演讲旁白（中文口播稿，30-60 字，递进衔接）。
theme 给全 deck 统一配色（十六进制）：bg 深色底、text 亮字、primary 主色、accent 强调色。
只输出 JSON，不要 markdown 代码块，格式：
{{"title": "deck 总标题",
  "theme": {{"bg": "#0f172a", "text": "#f8fafc", "primary": "#38bdf8", "accent": "#fbbf24"}},
  "slides": [
    {{"layout": "title", "title": "...", "subtitle": "...", "notes": "旁白"}},
    {{"layout": "toc", "title": "目录", "bullets": ["01 ...", "02 ..."], "notes": "旁白"}},
    {{"layout": "content", "title": "...", "bullets": ["要点1", "要点2", "要点3"], "notes": "旁白"}},
    {{"layout": "data", "title": "...", "chart": {{"type": "bar", "data": {{"项A": 30, "项B": 50}}}}, "notes": "旁白"}},
    {{"layout": "end", "title": "谢谢观看", "subtitle": "...", "notes": "旁白"}}
  ]}}"""

DEFAULT_THEME = {'bg': '#0f172a', 'text': '#f8fafc', 'primary': '#38bdf8', 'accent': '#fbbf24'}


def extract_json(text: str) -> dict:
    """从 LLM 回复提取 JSON 对象（容忍 markdown fence / 前后杂字 / 尾逗号）。"""
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        raise RuntimeError('LLM 输出里没找到 JSON 对象')
    raw = m.group(0)
    raw = re.sub(r',\s*([}\]])', r'\1', raw)
    return json.loads(raw)


def _norm_theme(t) -> dict:
    theme = dict(DEFAULT_THEME)
    if isinstance(t, dict):
        for k in theme:
            v = str(t.get(k, '')).strip()
            if re.match(r'^#[0-9a-fA-F]{3,8}$', v):
                theme[k] = v
    return theme


def _norm_chart(c) -> dict | None:
    """图表数据规范化：type 限 bar/line/pie，data 值转 float。坏数据返回 None。"""
    if not isinstance(c, dict):
        return None
    ctype = str(c.get('type', 'bar')).strip().lower()
    if ctype not in ('bar', 'line', 'pie'):
        ctype = 'bar'
    data = c.get('data')
    if not isinstance(data, dict) or not data:
        return None
    clean = {}
    for k, v in list(data.items())[:8]:
        try:
            clean[str(k)[:16]] = float(v)
        except (TypeError, ValueError):
            continue
    if len(clean) < 2:
        return None
    return {'type': ctype, 'data': clean}


def _norm_plan(raw: dict, concept: str, n: int) -> dict:
    """LLM 输出规范化：layout 白名单、bullets 限长、chart 规范化、页数对齐。"""
    title = str(raw.get('title', '')).strip() or concept[:24]
    theme = _norm_theme(raw.get('theme'))
    slides = []
    for s in raw.get('slides', []) if isinstance(raw.get('slides'), list) else []:
        if not isinstance(s, dict):
            continue
        layout = str(s.get('layout', 'content')).strip().lower()
        if layout not in LAYOUTS:
            layout = 'content'
        if layout in ('content', 'toc'):
            bullets = [str(b).strip()[:40] for b in (s.get('bullets') or [])
                       if str(b).strip()][:5]
            if not bullets:
                layout = 'title' if not s.get('subtitle') else 'content'
        else:
            bullets = []
        chart = _norm_chart(s.get('chart')) if layout == 'data' else None
        if layout == 'data' and not chart:
            layout = 'content'
            bullets = bullets or [f'{title} · 数据要点待补充']
        t = str(s.get('title', '')).strip()[:30]
        if not t:
            t = title if layout == 'end' else f'{title} · 第{len(slides)+1}页'
        slides.append({'layout': layout, 'title': t,
                       'subtitle': str(s.get('subtitle', '')).strip()[:40],
                       'bullets': bullets, 'chart': chart,
                       'notes': str(s.get('notes', '')).strip()[:120]})
    if not slides:
        slides = [{'layout': 'title', 'title': title, 'subtitle': concept[:40],
                   'bullets': [], 'chart': None, 'notes': concept},
                  {'layout': 'end', 'title': '谢谢观看', 'subtitle': '', 'bullets': [],
                   'chart': None, 'notes': '谢谢观看'}]
    if len(slides) > n:
        slides = slides[:n]
    return {'title': title, 'theme': theme, 'slides': slides}


def plan_deck(concept: str, n: int = 5, model: str = None, on_chunk=None) -> dict:
    """概念 → LLM → deck 规划 JSON（M1 剧本层）。解析失败/页数不足时兜底。"""
    llm = None
    try:
        from utils.llm import LLMClient
        llm = LLMClient(load_config())
    except Exception:
        pass
    sys_p = PLAN_SYS.format(n=n)
    messages = [{'role': 'system', 'content': sys_p},
                {'role': 'user', 'content': f'主题：{concept}'}]
    if llm is not None:
        try:
            text = _chat_stream(llm, messages, model=model, temperature=0.5,
                                read_timeout=20, on_chunk=on_chunk)
            raw = extract_json(text)
            return _norm_plan(raw, concept, n)
        except Exception as e:
            print(f'  ⚠ deck 规划失败（{e}），用概念兜底')
    return _norm_plan({'title': concept[:24], 'theme': DEFAULT_THEME,
                       'slides': [{'layout': 'title', 'title': concept[:24],
                                   'subtitle': '', 'notes': concept}]},
                      concept, n)


# ─────────────────────────── SVG 图表（M3：数据驱动，纯 Python） ───────────────────────────

def svg_chart(chart: dict, width: int = 620, height: int = 400, theme: dict = None,
              uid: str = 'c0') -> str:
    """{type: bar|line|pie, data: {...}} → 矢量 SVG 图表（渐变/网格/环形，无外部依赖）。"""
    theme = theme or DEFAULT_THEME
    data = chart['data']
    ctype = chart['type']
    vals = list(data.values())
    vmax = max(abs(v) for v in vals) or 1.0
    pad, lb_w = 46, 96
    W, H = width, height
    plot_w, plot_h = W - lb_w - pad, H - pad * 2
    tp, ac, bg = theme['primary'], theme['accent'], theme['bg']
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}">',
             f'<defs>'
             f'<linearGradient id="{uid}g" x1="0" y1="0" x2="0" y2="1">'
             f'<stop offset="0" stop-color="{tp}"/><stop offset="1" stop-color="{ac}"/>'
             f'</linearGradient>'
             f'<linearGradient id="{uid}a" x1="0" y1="0" x2="0" y2="1">'
             f'<stop offset="0" stop-color="{tp}" stop-opacity=".32"/>'
             f'<stop offset="1" stop-color="{tp}" stop-opacity="0"/></linearGradient></defs>']
    if ctype == 'bar':
        bw = plot_w / len(data) * 0.58
        gap = plot_w / len(data)
        for g in range(1, 5):
            gy = H - pad - plot_h * g / 4
            parts.append(f'<line x1="{lb_w}" y1="{gy:.1f}" x2="{W-pad/2}" y2="{gy:.1f}" '
                         f'stroke="{theme["text"]}14" stroke-width="1"/>')
        parts.append(f'<line x1="{lb_w}" y1="{H-pad}" x2="{W-pad/2}" y2="{H-pad}" '
                     f'stroke="{theme["text"]}44" stroke-width="2"/>')
        for i, (k, v) in enumerate(data.items()):
            bh = max(6.0, abs(v) / vmax * (plot_h - 10))
            x = lb_w + gap * i + (gap - bw) / 2
            y = H - pad - bh
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                         f'rx="8" fill="url(#{uid}g)" opacity="0.95">'
                         f'<animate attributeName="height" from="0" to="{bh:.1f}" dur="0.7s" '
                         f'fill="freeze"/>'
                         f'<animate attributeName="y" from="{H-pad}" to="{y:.1f}" dur="0.7s" '
                         f'fill="freeze"/></rect>')
            parts.append(f'<text x="{x+bw/2:.1f}" y="{y-10:.1f}" font-size="15" font-weight="700" '
                         f'fill="{theme["text"]}" text-anchor="middle">{v:g}</text>')
            parts.append(f'<text x="{x+bw/2:.1f}" y="{H-pad+22}" font-size="14" '
                         f'fill="{theme["text"]}cc" text-anchor="middle">{k}</text>')
    elif ctype == 'line':
        step = plot_w / max(1, len(data) - 1) if len(data) > 1 else 0
        pts = []
        for i, (k, v) in enumerate(data.items()):
            x = lb_w + step * i
            y = H - pad - abs(v) / vmax * (plot_h - 10)
            pts.append((x, y, k, v))
        poly = ' '.join(f'{x:.1f},{y:.1f}' for x, y, _, _ in pts)
        area = (f'M{lb_w},{H-pad} '
                + ' '.join(f'L{x:.1f},{y:.1f}' for x, y, _, _ in pts)
                + f' L{pts[-1][0]:.1f},{H-pad} Z')
        parts.append(f'<path d="{area}" fill="url(#{uid}a)"/>')
        parts.append(f'<polyline points="{poly}" fill="none" stroke="{tp}" '
                     f'stroke-width="3.5" stroke-linejoin="round" stroke-linecap="round"/>')
        for x, y, k, v in pts:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{ac}" '
                         f'stroke="{bg}" stroke-width="2.5"/>')
            parts.append(f'<text x="{x:.1f}" y="{y-14:.1f}" font-size="14" font-weight="700" '
                         f'fill="{theme["text"]}" text-anchor="middle">{v:g}</text>')
            parts.append(f'<text x="{x:.1f}" y="{H-pad+22}" font-size="13" '
                         f'fill="{theme["text"]}cc" text-anchor="middle">{k}</text>')
    else:  # pie → 环形图
        import math
        cx, cy, r = W * 0.38, H / 2, min(plot_w, plot_h) * 0.42
        total = sum(abs(v) for v in vals) or 1.0
        ang = -math.pi / 2
        for i, (k, v) in enumerate(data.items()):
            frac = abs(v) / total
            a2 = ang + frac * 2 * math.pi
            large = 1 if frac > 0.5 else 0
            x1, y1 = cx + r * math.cos(ang), cy + r * math.sin(ang)
            x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
            color = tp if i % 2 == 0 else ac
            if i % 4 == 3:
                color = theme['text']
            parts.append(f'<path d="M{cx:.1f},{cy:.1f} L{x1:.1f},{y1:.1f} '
                         f'A{r:.1f},{r:.1f} 0 {large} 1 {x2:.1f},{y2:.1f} Z" fill="{color}" '
                         f'opacity="0.92"><animateTransform attributeName="transform" '
                         f'type="rotate" from="-20 {cx:.0f} {cy:.0f}" to="0 {cx:.0f} {cy:.0f}" '
                         f'dur="0.6s" fill="freeze"/></path>')
            lx, ly = cx + r * 1.22 * math.cos((ang + a2) / 2), cy + r * 1.22 * math.sin((ang + a2) / 2)
            parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="14" '
                         f'fill="{theme["text"]}" text-anchor="middle" '
                         f'dominant-baseline="middle">{k} {v:g}</text>')
            ang = a2
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r*0.52:.1f}" fill="{bg}"/>')
        parts.append(f'<text x="{cx:.1f}" y="{cy+7:.1f}" font-size="20" font-weight="800" '
                     f'fill="{theme["text"]}" text-anchor="middle">{total:g}</text>')
    parts.append('</svg>')
    return ''.join(parts)


# ─────────────────────────── HTML 模板渲染（M1/M2：版式系统） ───────────────────────────

SLIDE_TPL = """<section class="slide s-{layout}" id="p{i}">
  <div class="bar"></div>
  {body}
  <div class="brand">{brand}</div>
  <div class="pageno">{i} / {total}</div>
</section>"""


def page_css(theme: dict) -> str:
    """单一样式源：deck 放映 / 单页渲染（视频/PDF/PNG）共用同一套设计。

    深色渐变底 + 双光斑 + 玻璃卡片 + 渐变标题 + 渐变顶条/品牌页脚。
    不含 .fx 动画规则（入场动效只在 deck html 加，单页渲染需元素立即可见）。
    """
    t = dict(DEFAULT_THEME)
    if isinstance(theme, dict):
        for k in t:
            v = str(theme.get(k, '')).strip()
            if re.match(r'^#[0-9a-fA-F]{3,8}$', v):
                t[k] = v
    bg, tx, tp, ac = t['bg'], t['text'], t['primary'], t['accent']
    return f"""*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:1280px;height:720px;overflow:hidden;color:{tx};
  font-family:'PingFang SC','Microsoft YaHei','Noto Sans CJK SC',sans-serif;
  background:linear-gradient(135deg,{bg} 0%,{tp}14 48%,{bg} 100%)}}
body::before{{content:'';position:absolute;width:640px;height:640px;top:-230px;right:-170px;
  background:radial-gradient(circle,{tp}2e,transparent 70%)}}
body::after{{content:'';position:absolute;width:540px;height:540px;bottom:-210px;left:-150px;
  background:radial-gradient(circle,{ac}22,transparent 70%)}}
.deck{{width:1280px;height:720px;position:relative}}
.slide{{width:1280px;height:720px;padding:60px 84px 58px;position:absolute;inset:0;
  display:none;flex-direction:column}}
.slide.active,.slide:only-of-type{{display:flex}}
.s-title,.s-end{{justify-content:center;align-items:center;text-align:center}}
.vcenter{{display:flex;flex-direction:column;align-items:center;gap:28px;max-width:1060px}}
h1{{font-size:76px;font-weight:800;letter-spacing:.03em;line-height:1.18;
  background:linear-gradient(100deg,{tx} 25%,{tp} 62%,{ac});-webkit-background-clip:text;
  background-clip:text;color:transparent}}
h2{{font-size:44px;font-weight:700;letter-spacing:.02em}}
.subtitle{{font-size:25px;opacity:.78;letter-spacing:.04em}}
.rule{{width:132px;height:6px;border-radius:3px;background:linear-gradient(90deg,{tp},{ac});
  box-shadow:0 0 18px {tp}66}}
.kicker{{font-size:15px;letter-spacing:.42em;color:{ac};font-weight:700}}
.head{{margin-bottom:38px;display:flex;flex-direction:column;gap:13px}}
.head::after{{content:'';width:78px;height:5px;border-radius:3px;
  background:linear-gradient(90deg,{tp},{ac})}}
.bullets{{list-style:none;display:flex;flex-direction:column;gap:18px;font-size:26px;
  font-weight:500}}
.bullets li{{display:flex;align-items:center;gap:18px;padding:17px 26px;border-radius:16px;
  background:linear-gradient(90deg,{tx}12,{tx}05);border:1px solid {tx}1c;
  box-shadow:0 8px 26px rgba(0,0,0,.22)}}
.idx{{min-width:44px;height:44px;display:flex;align-items:center;justify-content:center;
  border-radius:12px;font-weight:800;font-size:19px;color:{bg};
  background:linear-gradient(135deg,{tp},{ac})}}
.chartwrap{{flex:1;display:flex;align-items:center;justify-content:center;padding:16px 20px;
  background:linear-gradient(135deg,{tx}0a,{tx}04);border:1px solid {tx}16;border-radius:20px;
  box-shadow:0 12px 34px rgba(0,0,0,.26)}}
.bar{{position:absolute;top:0;left:0;height:6px;width:100%;
  background:linear-gradient(90deg,{tp},{ac} 55%,{tp}00)}}
.brand{{position:absolute;bottom:26px;left:44px;font-size:14px;letter-spacing:.14em;
  color:{tx}59;font-weight:600}}
.pageno{{position:absolute;bottom:26px;right:44px;font-size:15px;color:{tx}59;
  font-variant-numeric:tabular-nums}}"""

BODY_TPL = {
    'title': """<div class="vcenter">
    <h1 class="fx">{title}</h1>
    {subtitle}<div class="rule fx"></div></div>""",
    'end': """<div class="vcenter">
    <h1 class="fx">{title}</h1>
    {subtitle}<div class="rule fx"></div></div>""",
    'toc': """<div class="head fx"><span class="kicker">CONTENTS</span><h2>{title}</h2></div>
    <ul class="bullets">{bullets}</ul>""",
    'content': """<div class="head fx"><span class="kicker">0{i}</span><h2>{title}</h2></div>
    <ul class="bullets">{bullets}</ul>""",
    'data': """<div class="head fx"><span class="kicker">DATA</span><h2>{title}</h2></div>
    <div class="chartwrap">{chart}</div>""",
}

LI_TPL = '<li class="fx" style="animation-delay:{d:.2f}s"><span class="idx">{idx}</span>{text}</li>'


def render_slide_body(s: dict, i: int, theme: dict) -> str:
    """单页 body HTML（按版式）。图表页 chart → svg_chart 数据驱动。"""
    if s['layout'] == 'data' and s.get('chart'):
        chart = svg_chart(s['chart'], theme=theme, uid=f'c{i}')
    else:
        chart = ''
    bullets = ''.join(
        LI_TPL.format(d=0.35 + j * 0.18, idx=f'{j+1:02d}', text=b)
        for j, b in enumerate(s.get('bullets', [])))
    sub = f'<p class="subtitle fx" style="animation-delay:.3s">{s["subtitle"]}</p>' \
        if s.get('subtitle') else ''
    return BODY_TPL[s['layout']].format(
        title=s['title'], subtitle=sub, bullets=bullets, chart=chart, i=i)


def render_deck_html(plan: dict, animate: bool = True, pdf: bool = False) -> str:
    """deck 规划 → 自包含 HTML（16:9，渐变主题+玻璃卡片，入场动效，浏览器可放映）。

    animate=False 时去 CSS 动画（元素直接可见不依赖动画帧）。
    pdf=True 时所有页 position:relative + display:flex + page-break（分页打印），
    并去掉翻页 <script>。
    """
    theme = _norm_theme(plan.get('theme'))
    total = len(plan['slides'])
    brand = str(plan.get('brand', 'Vidance'))[:32]
    sections = []
    for i, s in enumerate(plan['slides'], 1):
        sections.append(SLIDE_TPL.format(
            layout=s['layout'], i=i, total=total, brand=brand,
            body=render_slide_body(s, i, theme)))
    css = page_css(theme)
    script = ''
    if pdf:
        css += (".slide{position:relative;inset:auto;width:1280px;height:720px;"
                "padding:60px 84px 58px;display:flex;flex-direction:column;"
                "page-break-after:always}")
    else:
        css += ".slide{position:absolute;inset:0;display:none;flex-direction:column}"
        if animate:
            css += """
.fx{opacity:0;animation:fadeUp .7s ease forwards}
@keyframes fadeUp{from{opacity:0;transform:translateY(26px)}to{opacity:1;transform:none}}
.slide.active .fx{animation-play-state:running}"""
        script = """
<script>
var slides=document.querySelectorAll('.slide'),cur=0;
function show(n){slides[cur].classList.remove('active');cur=(n+slides.length)%slides.length;
  slides[cur].classList.add('active');}
document.addEventListener('keydown',function(e){
  if(e.key==='ArrowRight'||e.key===' ')show(cur+1);
  if(e.key==='ArrowLeft')show(cur-1);});
document.addEventListener('click',function(){show(cur+1)});
slides[0].classList.add('active');
</script>"""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{plan['title']}</title>
<style>{css}</style></head>
<body><div class="deck">
{''.join(sections)}
</div>
{script}</body></html>"""


def main():
    ap = argparse.ArgumentParser(description='概念/大纲 → LLM → HTML 幻灯片（v15）')
    ap.add_argument('concept', help='主题/大纲（中文）')
    ap.add_argument('-o', '--output', default=None, help='HTML 输出路径')
    ap.add_argument('--n', type=int, default=5, help='页数')
    ap.add_argument('--model', default=None, help='LLM 模型')
    ap.add_argument('--no-anim', action='store_true', help='去入场动效（PDF 用）')
    args = ap.parse_args()

    out = args.output or os.path.join(load_config()['output_dir'], 'ppt', 'deck.html')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    print(f'[ppt] LLM 规划 deck：{args.concept}（{args.n} 页）')
    plan = plan_deck(args.concept, n=args.n, model=args.model)
    html = render_deck_html(plan, animate=not args.no_anim)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'✅ {out}（{len(plan["slides"])} 页，主题 {plan["theme"]["bg"]}）')
    for i, s in enumerate(plan['slides'], 1):
        print(f'   p{i} [{s["layout"]}] {s["title"]}' +
              (f' · chart={s["chart"]["type"]}' if s.get('chart') else ''))


if __name__ == '__main__':
    main()
