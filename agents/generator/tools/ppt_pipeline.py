#!/usr/bin/env python3
"""v15 M1-M4：HTML 幻灯片 deck → mp4 / PDF / PNG（复用 v13 确定性渲染，纯 CPU）

渲染思路（与 v13 svg_pipeline 同构）：
  - 每页 HTML 片段独立渲染：Playwright 确定性逐帧截图（CSS 动画 pause + currentTime）
  - 页内动效：入场 fadeUp + 元素 stagger（CSS animation-delay）逐帧演进
  - 页间转场：ffmpeg xfade 链式拼接（fade/slide/wipe/circleopen，复用 v5 effects）
  - 有声模式（PptLine）：每页 TTS 旁白 → compose() 对齐/字幕/LUT/BGM（复用 v10/v12）
  - PDF/PNG：Playwright page.pdf() / 单帧截图（animate=False 页面）

用法：
  python agents/generator/tools/ppt_pipeline.py --deck deck.html --video -o out.mp4
  python agents/generator/tools/ppt_pipeline.py --deck deck.html --pdf -o deck.pdf
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
import subprocess
import time as _t

from agents.generator.tools.svg_pipeline import (
    _freeze_and_advance, _find_chrome_executable, svg_to_mp4)

PAGE_W, PAGE_H = 1280, 720


def extract_slides(html: str) -> list:
    """deck HTML → 单页 HTML 片段列表（<section class="slide">…</section>）。"""
    m = re.findall(r'<section class="slide[\s\S]*?</section>', html, re.IGNORECASE)
    if not m:
        raise RuntimeError('deck HTML 里没找到 <section class="slide">')
    return m


def slide_html(page: str, theme: dict = None) -> str:
    """单页片段 → 完整可渲染 HTML（page_css 全套设计，:only-of-type 可见）。"""
    from agents.generator.tools.ppt_llm import page_css
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>{page_css(theme)}</style>
</head><body>{page}</body></html>"""


def render_slide_frames(html: str, fps: int, duration: float, settle_ms: int = 250):
    """单页 HTML → 逐帧 yield PNG（确定性时间点，复用 v13 freeze_and_advance）。"""
    from playwright.sync_api import sync_playwright
    exe = _find_chrome_executable()
    with sync_playwright() as p:
        launch_kwargs = {'headless': True}
        if exe:
            launch_kwargs['executable_path'] = exe
        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception:
            if exe:
                browser = p.chromium.launch(headless=True)
            else:
                raise
        page = browser.new_page(viewport={'width': PAGE_W, 'height': PAGE_H},
                                device_scale_factor=1)
        page.set_content(html)
        page.wait_for_timeout(settle_ms)
        total = max(1, int(round(fps * duration)))
        for i in range(total):
            _freeze_and_advance(page, i * 1000.0 / fps)
            yield page.screenshot(type='png')
        browser.close()


def slide_to_mp4(page_html: str, out_path: str, fps: int = 24, duration: float = 3.0,
                 on_frame=None) -> str:
    """单页 → mp4 片段（image2pipe，同 v13 svg_to_mp4）。"""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    tmp = out_path + '.part.mp4'
    cmd = ['ffmpeg', '-y', '-loglevel', 'error',
           '-f', 'image2pipe', '-vcodec', 'png', '-framerate', str(fps), '-i', '-',
           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'medium', '-crf', '18',
           '-r', str(fps), tmp]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = 0
    total = max(1, int(round(fps * duration)))
    try:
        for png in render_slide_frames(page_html, fps, duration):
            try:
                proc.stdin.write(png)
            except (BrokenPipeError, OSError):
                break
            if proc.poll() is not None:
                raise RuntimeError(f'ffmpeg 渲染中途退出 (rc={proc.returncode})')
            n += 1
            if on_frame:
                try:
                    on_frame(n, total)
                except Exception:
                    pass
    finally:
        if proc.stdin:
            proc.stdin.close()
        rc = proc.wait()
    if rc != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
        if os.path.isfile(tmp):
            os.remove(tmp)
        raise RuntimeError(f'ffmpeg 渲染失败 (rc={rc})')
    os.replace(tmp, out_path)
    return out_path


def deck_to_mp4(slides: list, out_path: str, fps: int = 24, duration: float = 3.0,
                theme: dict = None, transition: str = 'fade', t_dur: float = 0.5,
                save_pages: bool = True, workdir: str = None,
                stage_cb=None, on_frame=None) -> str:
    """多页 deck → mp4：每页独立渲染 → ffmpeg xfade 链式拼接（M2 页间转场）。

    slides: 单页 HTML 片段列表。transition: fade/slide/wipe/circleopen/crossfade/cut。
    """
    theme = theme or {}
    if workdir is None:
        workdir = out_path.rsplit('/', 1)[0] if '/' in out_path else '.'
    os.makedirs(workdir, exist_ok=True)
    clips = []
    for i, page in enumerate(slides, 1):
        clip = os.path.join(workdir, f'slide_{i}.mp4')
        if save_pages:
            with open(os.path.join(workdir, f'slide_{i}.html'), 'w', encoding='utf-8') as f:
                f.write(slide_html(page, theme))
        if stage_cb:
            try:
                stage_cb(f'[{i}/{len(slides)}] 渲染（{duration:.1f}s）')
            except Exception:
                pass
        print(f'  [{i}/{len(slides)}] 渲染（{duration:.1f}s）…')
        slide_to_mp4(slide_html(page, theme), clip, fps=fps, duration=duration,
                     on_frame=on_frame)
        clips.append(clip)
    if stage_cb:
        try:
            stage_cb(f'拼接（{transition} 转场）')
        except Exception:
            pass
    print(f'  拼接（{transition} 转场）…')
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    if len(clips) == 1:
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', clips[0],
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18',
                        '-r', str(fps), out_path], check=True)
    elif transition == 'cut':
        lst = os.path.join(workdir, 'concat.txt')
        with open(lst, 'w', encoding='utf-8') as f:
            for c in clips:
                f.write(f"file '{os.path.abspath(c)}'\n")
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat',
                        '-safe', '0', '-i', lst, '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', '-crf', '18', out_path], check=True)
    else:
        from utils.effects import concat_with_transitions
        concat_with_transitions(clips, [transition] * (len(clips) - 1), out_path,
                                duration=t_dur)
    return out_path


def deck_to_pdf(slides: list, out_path: str, theme: dict = None, title: str = 'deck') -> str:
    """deck → PDF（Playwright page.pdf，@page 16:9；pdf 模式页面全可见可分页）。

    slides: 单页 HTML 片段列表（<section class="slide">）。
    """
    from agents.generator.tools.ppt_llm import render_deck_html
    from playwright.sync_api import sync_playwright
    theme = theme or {}
    bare = [{'layout': 'content', 'title': '', 'subtitle': '', 'bullets': [],
             'chart': None, 'notes': ''} for _ in slides]
    html = render_deck_html({'title': title, 'theme': theme, 'slides': bare},
                            animate=False, pdf=True)
    # 重建 plan 结构成本高，直接把提取的 section 片段注入 body（CSS 已带分页）
    body = '\n'.join(slides)
    html = re.sub(r'<body>[\s\S]*</body>',
                  f'<body><div class="deck">{body}</div></body>', html, count=1)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    exe = _find_chrome_executable()
    tmp = out_path + '.part.pdf'
    with sync_playwright() as p:
        launch_kwargs = {'headless': True}
        if exe:
            launch_kwargs['executable_path'] = exe
        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception:
            if exe:
                browser = p.chromium.launch(headless=True)
            else:
                raise
        page = browser.new_page(viewport={'width': PAGE_W, 'height': PAGE_H},
                                device_scale_factor=1)
        page.set_content(html)
        page.wait_for_timeout(400)
        page.pdf(path=tmp, width='1280px', height='720px',
                 print_background=True, page_ranges='1-' + str(len(slides)))
        browser.close()
    os.replace(tmp, out_path)
    print(f'✅ PDF {out_path}（{len(slides)} 页）')
    return out_path


def render_slides_pngs(slides: list, out_dir: str, theme: dict = None, at: float = 1.2) -> str:
    """deck → 每页一张 PNG（单浏览器会话，at 秒时刻截图，预览/IM 卡片用）。"""
    from playwright.sync_api import sync_playwright
    theme = theme or {}
    os.makedirs(out_dir, exist_ok=True)
    exe = _find_chrome_executable()
    with sync_playwright() as p:
        launch_kwargs = {'headless': True}
        if exe:
            launch_kwargs['executable_path'] = exe
        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception:
            if exe:
                browser = p.chromium.launch(headless=True)
            else:
                raise
        page = browser.new_page(viewport={'width': PAGE_W, 'height': PAGE_H},
                                device_scale_factor=1)
        for i, s in enumerate(slides, 1):
            page.set_content(slide_html(s, theme))
            page.wait_for_timeout(150)
            _freeze_and_advance(page, at * 1000.0)
            page.screenshot(type='png', path=os.path.join(out_dir, f'slide_{i}.png'))
        browser.close()
    print(f'✅ PNG {len(slides)} 张 → {out_dir}')
    return out_dir


def load_output_dir() -> str:
    try:
        from utils.config_loader import load_config
        return load_config()['output_dir']
    except Exception:
        return 'output'


def _probe_duration(path: str) -> float:
    from utils.ffmpeg_tools import get_duration
    try:
        return float(get_duration(path))
    except Exception:
        return 0.0


class PptLine:
    """v15：概念 → deck 规划 → [TTS 旁白] → 逐页渲染 → 拼接/导出（对标 SvgLine）。

    交付形态：
      - run(video=True)  → mp4（有声：notes 旁白 TTS + 字幕；无声：固定时长）
      - run(html=True)   → deck.html（浏览器放映）
      - run(pdf=True)    → deck.pdf
      - run(pngs=True)   → 每页 PNG
    降级链同 SvgLine：voice → cosy-default → 静音兜底（出片不崩）。
    """

    def __init__(self, config=None):
        from utils.config_loader import load_config
        from core.narration import Narrator
        self.config = config or load_config()
        self.output_dir = self.config.get('output_dir', 'output')
        self.narr = Narrator(self.config)
        self._plan = None
        self._render = None

    def _lazy(self):
        if self._plan is None:
            from agents.generator.tools.ppt_llm import plan_deck, render_deck_html
            self._plan = plan_deck
            self._render = render_deck_html

    def run(self, concept, n=5, say=None, voice=None, out_path=None,
            fps=24, duration=3.0, transition='fade', t_dur=0.5, theme=None,
            model=None, lut=None, bgm=None,
            video=True, html_out=True, pdf=False, pngs=False,
            stage_cb=None, on_chunk=None, on_frame=None) -> dict:
        """一键出 PPT（多形态并行）。say 给定时用手动大纲（每元素一页标题），否则 LLM 规划。"""
        import json as _json
        from datetime import datetime
        from utils.ffmpeg_tools import compose
        self._lazy()
        start = _t.time()

        from agents.common.tools.config_loader import task_id_for
        ts = task_id_for('ppt')
        workdir = os.path.join(self.output_dir, ts)
        os.makedirs(workdir, exist_ok=True)

        # 1) deck 规划（M1）
        if stage_cb:
            try:
                stage_cb(f'M1 deck 规划（{n} 页）')
            except Exception:
                pass
        if say:
            plan = {'title': concept[:24], 'theme': theme or dict(self._theme_hint()),
                    'slides': []}
            for j, s in enumerate(say):
                plan['slides'].append(
                    {'layout': 'title' if j == 0 else ('end' if j == len(say) - 1 and len(say) > 2 else 'content'),
                     'title': s[:30], 'subtitle': '', 'bullets': [], 'chart': None,
                     'notes': s})
        else:
            print(f'[M1] deck 规划（{n} 页）…')
            plan = self._plan(concept, n, model=model, on_chunk=on_chunk)
            if theme:
                plan['theme'].update(theme)
        slides_plan = plan['slides']
        total = len(slides_plan)
        print(f'  {total} 页: ' + ' | '.join(s['title'] for s in slides_plan))

        # 2) 渲染 HTML 片段（M1 模板，SLIDE_TPL 带顶条/品牌/页码——与 deck 模式同一套）
        from agents.generator.tools.ppt_llm import render_slide_body, render_deck_html, SLIDE_TPL
        brand = str(plan.get('brand', 'Vidance'))[:32]
        # render_slide_body 返回 body 内层；包成 section（逐页渲染/导出用）
        sections = [SLIDE_TPL.format(layout=s['layout'], i=i, total=total, brand=brand,
                                     body=render_slide_body(s, i, plan['theme']))
                    for i, s in enumerate(slides_plan, 1)]

        artifacts = {'task_id': ts, 'concept': concept, 'mode': 'ppt',
                     'pages': total, 'theme': plan['theme'], 'slides': slides_plan}

        # 3) deck.html（浏览器放映形态）
        html_path = None
        if html_out:
            html_path = os.path.join(workdir, 'deck.html')
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(render_deck_html(plan))
            artifacts['html'] = html_path
            print(f'  ✅ deck.html（浏览器放映）')

        # 4) PDF / PNG（M4 交付形态）
        if pdf:
            if stage_cb:
                try:
                    stage_cb('M4 导出 PDF')
                except Exception:
                    pass
            artifacts['pdf'] = deck_to_pdf(sections, os.path.join(workdir, 'deck.pdf'),
                                           theme=plan['theme'])
        if pngs:
            if stage_cb:
                try:
                    stage_cb('M4 导出 PNG')
                except Exception:
                    pass
            artifacts['pngs'] = render_slides_pngs(sections, os.path.join(workdir, 'pngs'),
                                             theme=plan['theme'])

        # 5) mp4（video=False 时跳过，纯 HTML/PDF 交付）
        if not video:
            artifacts['duration'] = 0.0
            artifacts['elapsed_s'] = round(_t.time() - start, 1)
            with open(os.path.join(workdir, 'meta.json'), 'w', encoding='utf-8') as f:
                _json.dump(artifacts, f, ensure_ascii=False, indent=2)
            print(f'✅ {artifacts["elapsed_s"]}s（HTML/PDF 交付，未出片）')
            return artifacts

        # 6) TTS 旁白 + 有声 mp4（M2）
        voice = voice or self.config.get('tts', {}).get('default_voice', 'cosy-default')
        audios, srt_ts, t0 = [], [], 0.0
        durs = []
        for i, s in enumerate(slides_plan, 1):
            note = s.get('notes', '')
            if note:
                wav = os.path.join(workdir, f'slide_{i}.wav')
                if stage_cb:
                    try:
                        stage_cb(f'[{i}/{total}] TTS 旁白')
                    except Exception:
                        pass
                print(f'  [{i}/{total}] TTS "{note[:18]}…"')
                self.narr.say(note, wav, voice=voice)
                adur = _probe_duration(wav)
                d_i = max(adur + 0.8, duration)
            else:
                wav = None
                adur = 0.0
                d_i = duration
            audios.append(wav)
            durs.append(d_i)
            srt_ts.append({'start': t0, 'end': t0 + adur + 0.3, 'text': note or s['title']})
            t0 += d_i

        # 逐页渲染（页时长按旁白对齐）
        rendered = []
        for i, (s, d_i) in enumerate(zip(slides_plan, durs), 1):
            clip = os.path.join(workdir, f'slide_{i}.mp4')
            if stage_cb:
                try:
                    stage_cb(f'[{i}/{total}] 渲染（{d_i:.1f}s）')
                except Exception:
                    pass
            print(f'  [{i}/{total}] 渲染（{d_i:.1f}s）…')
            page_html = slide_html(sections[i - 1], plan['theme'])
            with open(os.path.join(workdir, f'slide_{i}.html'), 'w', encoding='utf-8') as f:
                f.write(page_html)
            slide_to_mp4(page_html, clip, fps=fps, duration=d_i, on_frame=on_frame)
            rendered.append(clip)

        srt_path = self.narr.srt(srt_ts, os.path.join(workdir, 'subtitle.srt'))

        if out_path is None:
            out_path = os.path.join(workdir, 'final.mp4')
        elif not os.path.isabs(out_path):
            out_path = os.path.join(self.output_dir, out_path)

        # 7) 拼接（页间转场 + 字幕 + LUT/BGM，复用 v10 compose）
        lut_path = None
        if lut and lut != 'none':
            cand = os.path.join(_ROOT, 'utils', 'luts', f'{lut}.cube')
            lut_path = cand if os.path.isfile(cand) else None
        bgm_path = None
        if bgm and bgm != 'none':
            for d in (os.path.join(_ROOT, 'bgm'), 'bgm'):
                cand = os.path.join(d, f'{bgm}.wav')
                if os.path.isfile(cand):
                    bgm_path = cand
                    break
        extra = (' + LUT ' + str(lut) if lut_path else '') + \
                (' + BGM ' + str(bgm) if bgm_path else '')
        if stage_cb:
            try:
                stage_cb(f'拼接（{transition}{extra}）')
            except Exception:
                pass
        print(f'[M2] 拼接（{transition}{extra}）…')
        audios_use = audios if any(audios) else None
        compose(rendered, audios_use if audios_use else [None] * len(rendered),
                srt_path=srt_path, output_path=out_path,
                transition_types=[transition] * max(0, total - 1),
                transition_duration=t_dur, lut_path=lut_path, bgm_path=bgm_path)

        artifacts.update({'voice': voice, 'clips': rendered, 'output': out_path,
                          'transition': transition,
                          'duration': _probe_duration(out_path),
                          'elapsed_s': round(_t.time() - start, 1)})
        with open(os.path.join(workdir, 'meta.json'), 'w', encoding='utf-8') as f:
            _json.dump(artifacts, f, ensure_ascii=False, indent=2)
        print(f'✅ {out_path}（{artifacts["duration"]:.1f}s，{artifacts["elapsed_s"]}s）')
        return artifacts

    def _theme_hint(self) -> dict:
        from agents.generator.tools.ppt_llm import DEFAULT_THEME
        return dict(DEFAULT_THEME)


def _main():
    ap = argparse.ArgumentParser(description='HTML deck → mp4/PDF/PNG（v15 渲染管线）')
    ap.add_argument('--deck', required=True, help='deck.html 路径')
    ap.add_argument('-o', '--output', default=None, help='输出路径（mp4/pdf）')
    ap.add_argument('--video', action='store_true', help='渲染成 mp4')
    ap.add_argument('--pdf', action='store_true', help='导出 PDF')
    ap.add_argument('--pngs', action='store_true', help='导出每页 PNG')
    ap.add_argument('--fps', type=int, default=24)
    ap.add_argument('--duration', type=float, default=3.0, help='无声模式每页时长（秒）')
    ap.add_argument('--transition', default='fade',
                    help='页间转场 fade/slide/wipe/circleopen/crossfade/cut')
    args = ap.parse_args()

    with open(args.deck, 'r', encoding='utf-8') as f:
        slides = extract_slides(f.read())
    out = args.output or args.deck.rsplit('.', 1)[0]
    if args.video:
        deck_to_mp4(slides, out if out.endswith('.mp4') else out + '.mp4',
                    fps=args.fps, duration=args.duration, transition=args.transition)
    if args.pdf:
        deck_to_pdf(slides, out if out.endswith('.pdf') else out + '.pdf')
    if args.pngs:
        render_slides_pngs(slides, out + '_pngs' if not out.endswith('_pngs') else out)
    if not (args.video or args.pdf or args.pngs):
        ap.error('需要 --video / --pdf / --pngs 之一')


if __name__ == '__main__':
    _main()
