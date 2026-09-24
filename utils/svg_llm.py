#!/usr/bin/env python3
"""S1：概念 → LLM → 带 CSS/SMIL 动画的自包含 SVG

只做一件事：把中文概念（如"鹈鹕骑自行车"）交给 LLM，产出一个**自包含、可动画**的 SVG
文件，供人肉预览确认。生成的 SVG 交给 utils/svg_pipeline.py 渲染成 mp4。

用法：
  python utils/svg_llm.py "鹈鹕骑自行车" \
      --duration 3 --width 800 --height 450 -o output/svg/pelican_bike.svg
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm import LLMClient
from utils.config_loader import load_config


SYSTEM = """You are an expert SVG animator. Given a scene concept, produce ONE self-contained
animated SVG that visually depicts it.

Hard requirements:
- Output ONLY the <svg>...</svg> code. No markdown fences, no explanation, no <html>.
- Root <svg> MUST have xmlns="http://www.w3.org/2000/svg", the exact width/height and
  a viewBox="0 0 W H" matching the requested canvas.
- Fully self-contained: NO external images, NO external fonts, NO <script>. Use only
  built-in SVG shapes (<rect>/<circle>/<ellipse>/<path>/<polygon>/<g>/<text>) and colors.
- Animate with CSS @keyframes inside a <style> block (and/or SMIL <animate>/<animateTransform>).
  The animation MUST loop infinitely and be clearly visible.
- The whole animation cycle should be exactly {duration} seconds.
- Use simple flat colors (hex). Keep it clean, readable, and recognizable.
- Compose the scene with multiple elements (e.g. character + object + background) so it
  reads as the concept, not just one shape.
"""

USER = """Scene concept: {concept}
Canvas: {width}x{height} (viewBox 0 0 {width} {height}), animation cycle {duration}s.
Draw and animate it as a single self-contained SVG. Output SVG only."""


def extract_svg(text: str) -> str:
    """从 LLM 回复里提取 <svg>...</svg>（容忍 markdown 代码块/前后杂字）。"""
    m = re.search(r'<svg[\s\S]*?</svg>', text, re.IGNORECASE)
    if not m:
        raise RuntimeError('LLM 输出里没找到 <svg>…</svg>')
    svg = m.group(0)
    if 'xmlns=' not in svg.split('>', 1)[0]:
        svg = svg.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return svg


def _chat_stream(llm, messages: list, model: str = None, temperature: float = 0.4,
                 max_tokens: int = 8192, read_timeout: int = 30,
                 total_timeout: int = 300) -> str:
    """流式调用 LLM（SSE），边收边累加 —— 避免长输出的单次读超时。

    用 urllib 直接读 `stream: true` 的 SSE 响应；每次 socket 读超时设小（read_timeout），
    但只要还有数据就继续，总时长由 total_timeout 兜底。
    """
    import json as _json
    import urllib.request as _rq
    import time as _t

    model = model or llm.models['script']
    payload = {'model': model, 'messages': messages, 'temperature': temperature,
               'max_tokens': max_tokens, 'stream': True}
    data = _json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = _rq.Request(f'{llm.base_url}/chat/completions', data=data,
                      headers={'Content-Type': 'application/json',
                               'Authorization': f'Bearer {llm.api_key}'})
    parts = []
    t0 = _t.time()
    with _rq.urlopen(req, timeout=read_timeout) as resp:
        for raw in resp:
            if _t.time() - t0 > total_timeout:
                break
            line = raw.decode('utf-8', 'ignore').strip()
            if not line or not line.startswith('data:'):
                continue
            chunk = line[5:].strip()
            if chunk == '[DONE]':
                break
            try:
                obj = _json.loads(chunk)
                delta = obj['choices'][0].get('delta', {}).get('content')
                if delta:
                    parts.append(delta)
            except Exception:
                continue
    return ''.join(parts)


def generate_svg(concept: str, duration: float = 3.0, width: int = 800, height: int = 450,
                 model: str = None, temperature: float = 0.4, stream: bool = True) -> str:
    llm = LLMClient(load_config())
    sys_p = SYSTEM.format(duration=duration)
    user_p = USER.format(concept=concept, width=width, height=height, duration=duration)
    messages = [{'role': 'system', 'content': sys_p},
                {'role': 'user', 'content': user_p}]
    if stream:
        text = _chat_stream(llm, messages, model=model, temperature=temperature)
    else:
        text = llm.chat(messages, model=model, temperature=temperature,
                        max_tokens=8192, timeout=300, retries=2)
    return extract_svg(text)


NARR_SYS = """你是科普/营销短视频的旁白撰稿人。根据主题写 {n} 段递进式中文旁白，
每段 15-35 字（朗读约 3-7 秒），口语化、有信息量、段间衔接自然。
同时为每段给一个适合 SVG 矢量动画表现的**画面描述**（具体图形元素+颜色+动作，扁平风格，不要真人实拍感）。
只输出 JSON 数组，不要其他文字，格式：
[{{"text": "旁白文本", "scene": "画面视觉描述"}}]"""


def plan_narration(concept: str, n: int = 3, model: str = None) -> list:
    """概念 → LLM → n 段旁白 [{text, scene}]（S5 配音模式的剧本层）。

    解析失败/数量不足时兜底：截断 JSON 或按段复制概念。
    """
    llm = LLMClient(load_config())
    sys_p = NARR_SYS.format(n=n)
    messages = [{'role': 'system', 'content': sys_p},
                {'role': 'user', 'content': f'主题：{concept}'}]
    import json as _json
    try:
        text = _chat_stream(llm, messages, model=model, temperature=0.6, read_timeout=20)
        m = re.search(r'\[[\s\S]*\]', text)
        segs = _json.loads(m.group(0)) if m else []
        segs = [{'text': str(s.get('text', '')).strip(),
                 'scene': str(s.get('scene', '')).strip() or str(s.get('text', concept))}
                for s in segs if isinstance(s, dict) and s.get('text')]
    except Exception as e:
        print(f'  ⚠ 旁白规划失败（{e}），用概念兜底')
        segs = []
    if not segs:
        segs = [{'text': concept, 'scene': concept} for _ in range(n)]
    return segs[:n] if len(segs) >= n else segs


def main():
    ap = argparse.ArgumentParser(description='概念 → LLM → 动效 SVG（S1）')
    ap.add_argument('concept', help='场景概念（中文），如"鹈鹕骑自行车"')
    ap.add_argument('-o', '--output', default=None, help='SVG 输出路径')
    ap.add_argument('--duration', type=float, default=3.0, help='动画周期（秒）')
    ap.add_argument('--width', type=int, default=800)
    ap.add_argument('--height', type=int, default=450)
    ap.add_argument('--model', default=None, help='LLM 模型（缺省用 config 的 script 模型）')
    ap.add_argument('--no-stream', action='store_true', help='禁用流式，用一次性请求')
    args = ap.parse_args()

    out = args.output
    if not out:
        slug = re.sub(r'[^0-9a-zA-Z]+', '_', args.concept).strip('_') or 'svg'
        out = os.path.join(load_config()['output_dir'], 'svg', f'{slug}.svg')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    print(f'[S1] LLM 生成 SVG：{args.concept}  ({args.width}x{args.height}, {args.duration}s)')
    svg = generate_svg(args.concept, duration=args.duration, width=args.width,
                       height=args.height, model=args.model)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(svg + '\n')

    # 同时写一个预览 HTML，方便浏览器直接打开看动画
    html_path = out.rsplit('.', 1)[0] + '.preview.html'
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(f'<!DOCTYPE html><html><body style="margin:0;background:#fff">'
                f'{svg}</body></html>')

    print(f'✅ SVG: {out}  ({len(svg)} 字符)')
    print(f'👁  预览 HTML: {html_path}（浏览器打开看动画）')
    print(f'   确认 OK 后再进 S2：python utils/svg_pipeline.py --svg {out} --frames')


if __name__ == '__main__':
    main()
