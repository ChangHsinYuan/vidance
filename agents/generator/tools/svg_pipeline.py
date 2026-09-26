#!/usr/bin/env python3
"""SVG / HTML 动画 → MP4（无头浏览器逐帧渲染，纯 CPU，v13（原 v15）轻量化）

思路：LLM 产出带 CSS / SMIL 动画的自包含 SVG → 无头浏览器在**确定的时间点**逐帧截图
→ ffmpeg image2pipe 拼帧成 mp4。适合信息图 / 文字动画 / 数据可视化 / 科普短片，秒级出片。

关键点（相较早期 wall-clock 版本）：
  用 Web Animations API + SMIL 把动画**暂停并设到精确时间**再截图，帧率精确、无抖动、
  不受截图耗时影响（wall-clock `wait_for_timeout` 会随机器速度丢帧/重复帧）。

依赖（任一渲染后端）：
  - Playwright：`pip install playwright && playwright install chromium`（推荐，支持 CSS+SMIL）
  - 仅静态帧可用 resvg / cairosvg（无动画）

用法：
  # CLI：从 SVG 文件
  python utils/svg_pipeline.py --svg input/scene.svg -o output/svg_demo/demo.mp4 --duration 3

  # 代码调用
  from utils.svg_pipeline import svg_to_mp4
  svg_to_mp4(svg_code="<svg>...</svg>", out_path="demo.mp4", width=800, height=450,
             fps=24, duration=3.0)
"""

import os as _os
import sys as _sys
_ROOT = _os.path.abspath(__file__)
for _ in range(4):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
import argparse
import os
import shutil
import subprocess
import sys

HTML_TPL = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>html,body{{margin:0;padding:0;background:{bg};overflow:hidden;}}
svg{{display:block;}}</style></head>
<body>{svg}</body></html>"""


def _freeze_and_advance(page, t_ms: float):
    """把页面所有动画暂停并定位到 t_ms（毫秒），保证逐帧确定性。"""
    page.evaluate(
        """(t) => {
            // 1) CSS 动画 / Web Animations API
            if (document.getAnimations) {
                document.getAnimations().forEach(a => {
                    try { a.pause(); a.currentTime = t; } catch (e) {}
                });
            }
            // 2) SVG SMIL 动画
            document.querySelectorAll('svg').forEach(svg => {
                try {
                    svg.pauseAnimations();
                    svg.setCurrentTime(t / 1000.0);
                } catch (e) {}
            });
        }""",
        t_ms,
    )


def _find_chrome_executable():
    """找可用的 Chromium 可执行文件（playwright headless shell 或完整 chrome）。

    返回路径或 None（None 时让 playwright 自行查找）。
    """
    import glob
    cache = os.path.expanduser('~/.cache/ms-playwright')
    patterns = [
        os.path.join(cache, 'chromium_headless_shell-*', 'chrome-headless-shell-linux64', 'chrome-headless-shell'),
        os.path.join(cache, 'chromium-*', 'chrome-linux64', 'chrome'),
        os.path.join(cache, 'chromium-*', 'chrome-linux', 'chrome'),
    ]
    for pat in patterns:
        hits = sorted(glob.glob(pat))
        for h in hits:
            if os.access(h, os.X_OK):
                return h
    return None


def render_frames(svg_code: str, width: int, height: int, fps: int, duration: float,
                  bg: str = '#ffffff', settle_ms: int = 200):
    """生成器：逐帧 yield PNG bytes（确定性时间点截图）。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RuntimeError(
            '未安装 playwright。请先安装渲染后端：\n'
            '  pip install playwright && playwright install chromium\n'
            '（或用 resvg/cairosvg 渲染静态帧）'
        ) from e

    html = HTML_TPL.format(svg=svg_code, bg=bg)
    total_frames = max(1, int(round(fps * duration)))
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
        page = browser.new_page(viewport={'width': width, 'height': height},
                                device_scale_factor=1)
        page.set_content(html)
        page.wait_for_timeout(settle_ms)  # 等字体/资源就绪

        for i in range(total_frames):
            _freeze_and_advance(page, i * 1000.0 / fps)
            yield page.screenshot(type='png')

        browser.close()


def svg_to_mp4(svg_code: str = None, svg_path: str = None, out_path: str = 'output.mp4',
               width: int = 800, height: int = 450, fps: int = 24, duration: float = 3.0,
               bg: str = '#ffffff') -> str:
    """把 SVG 动画渲染成 mp4（纯 CPU）。返回输出路径。"""
    if svg_code is None:
        if not svg_path:
            raise ValueError('需要 svg_code 或 svg_path 之一')
        with open(svg_path, 'r', encoding='utf-8') as f:
            svg_code = f.read()

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    tmp_path = out_path + '.part.mp4'

    ffmpeg_cmd = [
        'ffmpeg', '-y', '-loglevel', 'error',
        '-f', 'image2pipe', '-vcodec', 'png', '-framerate', str(fps),
        '-i', '-',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'medium', '-crf', '18',
        '-r', str(fps),
        tmp_path,
    ]
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE)

    n = 0
    try:
        for png_bytes in render_frames(svg_code, width, height, fps, duration, bg=bg):
            proc.stdin.write(png_bytes)
            n += 1
    finally:
        if proc.stdin:
            proc.stdin.close()
        rc = proc.wait()

    if rc != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
        raise RuntimeError(f'ffmpeg 渲染失败 (rc={rc})')

    os.replace(tmp_path, out_path)
    print(f'✅ 生成完成 {out_path}（{n} 帧 @ {fps}fps, {width}x{height}, {duration:.1f}s）')
    return out_path


def render_still(svg_code: str = None, svg_path: str = None, out_path: str = 'still.png',
                 width: int = 800, height: int = 450, at: float = 0.0,
                 bg: str = '#ffffff') -> str:
    """S2：把 SVG 在某一时刻渲染成单张 PNG（调试用）。返回路径。"""
    if svg_code is None:
        with open(svg_path, 'r', encoding='utf-8') as f:
            svg_code = f.read()
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
    for png in render_frames(svg_code, width, height, 1, max(at, 0.001), bg=bg):
        with open(out_path, 'wb') as f:
            f.write(png)
        break
    print(f'✅ 单帧 {out_path}（t={at}s）')
    return out_path


def dump_frames(svg_code: str = None, svg_path: str = None, out_dir: str = 'frames',
                width: int = 800, height: int = 450, fps: int = 24, duration: float = 3.0,
                bg: str = '#ffffff') -> str:
    """S3：把 SVG 按 fps 确定性抽帧成 PNG 序列到 out_dir。返回目录。"""
    if svg_code is None:
        with open(svg_path, 'r', encoding='utf-8') as f:
            svg_code = f.read()
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for png in render_frames(svg_code, width, height, fps, duration, bg=bg):
        with open(os.path.join(out_dir, f'{n:04d}.png'), 'wb') as f:
            f.write(png)
        n += 1
    print(f'✅ 抽帧 {n} 张 → {out_dir}')
    return out_dir


def concept_to_mp4(concept: str, out_path: str = None, duration: float = 3.0,
                   width: int = 800, height: int = 450, fps: int = 24,
                   model: str = None, bg: str = '#ffffff', save_svg: bool = True) -> dict:
    """S1+S4 一键：概念 → LLM 生成 SVG → 渲染 mp4。返回 {svg, svg_path, mp4}。"""
    from utils.svg_llm import generate_svg

    if out_path is None:
        out_path = os.path.join(load_output_dir(), 'svg_pipeline', 'out.mp4')
    base = os.path.splitext(out_path)[0]
    svg_path = base + '.svg'

    print(f'[S1] LLM 生成 SVG：{concept}')
    svg = generate_svg(concept, duration=duration, width=width, height=height, model=model)
    if save_svg:
        os.makedirs(os.path.dirname(os.path.abspath(svg_path)) or '.', exist_ok=True)
        with open(svg_path, 'w', encoding='utf-8') as f:
            f.write(svg + '\n')
        # 预览 HTML
        html_path = base + '.preview.html'
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(f'<!DOCTYPE html><html><body style="margin:0;background:#fff">'
                    f'{svg}</body></html>')

    print(f'[S4] 渲染 mp4 …')
    svg_to_mp4(svg_code=svg, out_path=out_path, width=width, height=height,
               fps=fps, duration=duration, bg=bg)
    return {'svg': svg, 'svg_path': svg_path if save_svg else None, 'mp4': out_path}


def load_output_dir() -> str:
    try:
        from utils.config_loader import load_config
        return load_config()['output_dir']
    except Exception:
        return 'output'


def _probe_duration(path: str) -> float:
    """P5：时长探测（统一走 ffmpeg_tools.get_duration）。"""
    from utils.ffmpeg_tools import get_duration
    try:
        return float(get_duration(path))
    except Exception:
        return 0.0


class SvgLine:
    """S5：概念 → 分段旁白 → 逐段 TTS → 逐段 SVG 渲染 → crossfade 拼接 + 字幕 + 可选 LUT/BGM。

    与 fastline 同构（图换成 SVG 动画）。配音/字幕复用 core.narration.Narrator（v12（原 v17）单一实现），
    降级链：voice → cosy-default → 静音兜底（出片不崩）。
    """

    def __init__(self, config=None):
        from utils.config_loader import load_config
        from utils.svg_llm import plan_narration, generate_svg
        from core.narration import Narrator
        self.config = config or load_config()
        self.output_dir = self.config.get('output_dir', 'output')
        self.narr = Narrator(self.config)
        self._plan = plan_narration
        self._gen_svg = generate_svg

    def run(self, concept, n=3, say=None, voice=None, out_path=None,
            width=800, height=450, fps=24, bg='#ffffff', model=None,
            lut=None, bgm=None, keep_workdir=False) -> dict:
        """一键出有声 SVG 短片。say 给定时用手动旁白（每元素一段），否则 LLM 规划 n 段。"""
        import json as _json
        from datetime import datetime
        from utils.ffmpeg_tools import compose
        import time as _t
        start = _t.time()

        if say:
            segments = [{'text': t, 'scene': t} for t in say]
        else:
            print(f'[S5] 旁白规划（{n} 段）…')
            segments = self._plan(concept, n, model=model)
        n = len(segments)
        print(f'  {n} 段: ' + ' | '.join(s['text'] for s in segments))

        ts = datetime.now().strftime('svg%Y%m%d_%H%M%S')
        workdir = os.path.join(self.output_dir, ts)
        os.makedirs(workdir, exist_ok=True)
        voice = voice or self.config.get('tts', {}).get('default_voice', 'cosy-default')

        clips, audios, srt_ts, t = [], [], [], 0.0
        for i, seg in enumerate(segments, 1):
            wav = os.path.join(workdir, f'seg_{i}.wav')
            print(f'  [{i}/{n}] TTS "{seg["text"]}"')
            self.narr.say(seg['text'], wav, voice=voice)
            adur = _probe_duration(wav)
            d_i = max(adur + 0.6, 2.5)
            print(f'  [{i}/{n}] SVG+渲染（{d_i:.1f}s）…')
            svg = self._gen_svg(f"{concept}——{seg['scene']}", duration=d_i,
                                width=width, height=height, model=model)
            svg_path = os.path.join(workdir, f'seg_{i}.svg')
            with open(svg_path, 'w', encoding='utf-8') as f:
                f.write(svg + '\n')
            clip = os.path.join(workdir, f'seg_{i}.mp4')
            svg_to_mp4(svg_code=svg, out_path=clip, width=width, height=height,
                       fps=fps, duration=d_i, bg=bg)
            clips.append(clip)
            audios.append(wav)
            srt_ts.append({'start': t, 'end': t + adur + 0.3, 'text': seg['text']})
            t += d_i

        from core.narration import Narrator
        srt_path = Narrator.srt(srt_ts, os.path.join(workdir, 'subtitle.srt'))

        if out_path is None:
            out_path = os.path.join(workdir, 'final.mp4')
        elif not os.path.isabs(out_path):
            out_path = os.path.join(self.output_dir, out_path)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)

        lut_path = None
        if lut and lut != 'none':
            cand = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'utils', 'luts', f'{lut}.cube')
            lut_path = cand if os.path.isfile(cand) else None
        bgm_path = None
        if bgm and bgm != 'none':
            for d in (os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'bgm'),
                      'bgm'):
                cand = os.path.join(d, f'{bgm}.wav')
                if os.path.isfile(cand):
                    bgm_path = cand
                    break

        extra = (' + LUT ' + str(lut) if lut_path else '') + \
                (' + BGM ' + str(bgm) if bgm_path else '')
        print(f'[S5] 合成（crossfade + 字幕{extra}）…')
        compose(clips, audios, srt_path=srt_path, output_path=out_path,
                transition_types=['crossfade'] * max(0, n - 1),
                lut_path=lut_path, bgm_path=bgm_path)

        meta = {'task_id': ts, 'concept': concept, 'mode': 'svg',
                'segments': segments, 'voice': voice, 'clips': clips,
                'lut': lut, 'bgm': bgm, 'output': out_path,
                'duration': _probe_duration(out_path),
                'elapsed_s': round(_t.time() - start, 1)}
        with open(os.path.join(workdir, 'meta.json'), 'w', encoding='utf-8') as f:
            _json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f'✅ {out_path}（{meta["duration"]:.1f}s，{meta["elapsed_s"]}s）')
        return meta


def narrate_to_mp4(concept=None, n=3, say=None, **kwargs) -> dict:
    """S5 便捷函数。"""
    sl = SvgLine()
    if not concept and say:
        concept = say[0][:24]
    return sl.run(concept, n=n, say=say, **kwargs)


def _main():
    ap = argparse.ArgumentParser(description='SVG → MP4 流水线（无头浏览器逐帧渲染，纯 CPU）')
    ap.add_argument('--svg', help='SVG 文件路径（渲染模式）')
    ap.add_argument('--concept', help='概念（一键模式：LLM 生成 SVG → mp4）')
    ap.add_argument('-o', '--output', default=None, help='输出路径（mp4；缺省 output/svg_pipeline/）')
    ap.add_argument('--width', type=int, default=800)
    ap.add_argument('--height', type=int, default=450)
    ap.add_argument('--fps', type=int, default=24)
    ap.add_argument('--duration', type=float, default=3.0)
    ap.add_argument('--bg', default='#ffffff')
    ap.add_argument('--model', default=None, help='LLM 模型（一键模式）')
    ap.add_argument('--still', action='store_true', help='S2：只渲染单帧 PNG')
    ap.add_argument('--at', type=float, default=0.0, help='--still 的时刻（秒）')
    ap.add_argument('--frames', action='store_true', help='S3：抽帧成 PNG 序列')
    ap.add_argument('--frames-dir', default=None, help='抽帧输出目录')
    ap.add_argument('--voice', default=None, help='S5：配音音色（给定即进入有声旁白模式）')
    ap.add_argument('--say', action='append', default=None, help='S5：手动旁白段（可重复）')
    ap.add_argument('-n', type=int, default=3, help='S5：LLM 规划旁白段数')
    ap.add_argument('--lut', default=None, help='S5：调色风格（LUT 名）')
    ap.add_argument('--bgm', default=None, help='S5：BGM mood')
    args = ap.parse_args()

    out = args.output
    if out is None:
        d = os.path.join(load_output_dir(), 'svg_pipeline')
        out = os.path.join(d, 'out.mp4')

    if args.voice or args.say:
        narrate_to_mp4(concept=args.concept, n=args.n, say=args.say, out_path=out,
                       width=args.width, height=args.height, fps=args.fps,
                       model=args.model, bg=args.bg, lut=args.lut, bgm=args.bgm)
    elif args.concept:
        concept_to_mp4(args.concept, out_path=out, duration=args.duration,
                       width=args.width, height=args.height, fps=args.fps,
                       model=args.model, bg=args.bg)
    elif args.svg:
        if args.still:
            render_still(svg_path=args.svg, out_path=os.path.splitext(out)[0] + '.png',
                         width=args.width, height=args.height, at=args.at, bg=args.bg)
        elif args.frames:
            dump_frames(svg_path=args.svg, out_dir=args.frames_dir or os.path.splitext(out)[0] + '_frames',
                        width=args.width, height=args.height, fps=args.fps,
                        duration=args.duration, bg=args.bg)
        else:
            svg_to_mp4(svg_path=args.svg, out_path=out, width=args.width,
                       height=args.height, fps=args.fps, duration=args.duration, bg=args.bg)
    else:
        ap.error('需要 --svg 或 --concept 之一')


if __name__ == '__main__':
    _main()
