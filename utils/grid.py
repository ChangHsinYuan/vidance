"""画布网格合成（grid canvas）：多视频拼到 m×n 网格，同时播放、同时停止。

matplotlib subplot 风格：
- ``--grid 2x3`` / ``--rows`` / ``--cols`` 自定义网格；不传则自动方阵（cols=ceil(sqrt(N))）
- 视频按输入顺序**行优先**填格，空格子留底色；视频数超过格子数直接报错
- 每格 contain 缩放不变形（比例不一致时 letterbox 补底色）
- 短视频定格末帧对齐最长路（fill=hold，项目约定 5），或循环填满（fill=loop）
- 输出总时长 = 最长输入；音频 first(第一个有声输入) / mix(混音) / none

实现：单条 ffmpeg 命令 —— color 画布底 + 逐格 scale/pad/fps/tpad + overlay 链 + amix。
"""
import argparse
import math
import os
import shlex
import subprocess
import sys
import time


# ────────────────────────── 探测 ──────────────────────────

def probe_video(path: str) -> dict:
    """ffprobe 探测单个视频：duration/width/height/has_audio。"""
    cmd = ['ffprobe', '-v', 'error', '-print_format', 'json',
           '-show_entries', 'format=duration', '-show_entries',
           'stream=codec_type,width,height', path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'ffprobe 失败 {path}: {r.stderr.strip()[:200]}')
    import json
    data = json.loads(r.stdout or '{}')
    duration = float(data.get('format', {}).get('duration', 0) or 0)
    width = height = None
    has_audio = False
    for st in data.get('streams', []):
        if st.get('codec_type') == 'video' and width is None:
            width, height = int(st.get('width', 0)), int(st.get('height', 0))
        elif st.get('codec_type') == 'audio':
            has_audio = True
    if duration <= 0 or not width or not height:
        raise RuntimeError(f'无法读取视频时长/尺寸: {path}')
    return {'path': path, 'duration': duration, 'width': width,
            'height': height, 'has_audio': has_audio}


# ────────────────────────── 布局计算（纯逻辑，可单测） ──────────────────────────

def auto_grid(n: int) -> tuple:
    """自动方阵推导（matplotlib subplot 习惯）：cols=ceil(sqrt(n))，rows=ceil(n/cols)。"""
    cols = int(math.ceil(math.sqrt(n)))
    rows = int(math.ceil(n / cols)) if cols else 1
    return rows, cols


def parse_grid(spec: str) -> tuple:
    """解析 '2x3' / '2X3' / '2*3' → (rows, cols)。"""
    s = spec.lower().replace('*', 'x')
    parts = s.split('x')
    if len(parts) != 2:
        raise ValueError(f'--grid 形如 MxN，收到: {spec}')
    rows, cols = int(parts[0]), int(parts[1])
    if rows < 1 or cols < 1:
        raise ValueError(f'--grid 行列必须 ≥1: {spec}')
    return rows, cols


class Layout:
    """m×n 网格布局：格尺寸/画布尺寸/每格位置（行优先）。"""

    def __init__(self, rows, cols, cell_w, cell_h, gap, canvas_w, canvas_h):
        self.rows, self.cols = rows, cols
        self.cell_w, self.cell_h = cell_w, cell_h
        self.gap = gap
        self.canvas_w, self.canvas_h = canvas_w, canvas_h

    def position(self, idx: int) -> tuple:
        r, c = divmod(idx, self.cols)
        return (c * (self.cell_w + self.gap), r * (self.cell_h + self.gap))

    def __repr__(self):
        return (f'Layout({self.rows}x{self.cols} cell={self.cell_w}x{self.cell_h} '
                f'canvas={self.canvas_w}x{self.canvas_h} gap={self.gap})')


def compute_layout(infos: list, rows: int, cols: int, width: int = 1920,
                   gap: int = 8, cell_ratio: float = None) -> Layout:
    """计算布局。cell_ratio=w/h 手动指定格宽高比；缺省取所有输入宽高比均值。

    Raises ValueError: 视频数超过格子数。
    """
    n = len(infos)
    if n > rows * cols:
        raise ValueError(
            f'{n} 个视频放不进 {rows}x{cols}={rows * cols} 格，'
            f'请扩大网格（如 --grid {auto_grid(n)[0]}x{auto_grid(n)[1]}）')
    cell_w = max(2, (width - gap * (cols - 1)) // cols)
    if cell_ratio is None:
        ratios = [i['width'] / i['height'] for i in infos] or [16 / 9]
        cell_ratio = sum(ratios) / len(ratios)
    cell_h = max(2, round(cell_w / cell_ratio))
    canvas_w = cols * cell_w + gap * (cols - 1)
    canvas_h = rows * cell_h + gap * (rows - 1)
    return Layout(rows, cols, cell_w, cell_h, gap, canvas_w, canvas_h)


# ────────────────────────── ffmpeg 命令构造 ──────────────────────────

def build_filter_complex(infos: list, layout: Layout, max_dur: float,
                         fps: int = 24, bg: str = 'black',
                         audio: str = 'first') -> tuple:
    """返回 (filter_complex 字符串, 选中的音频输入索引列表, 输出侧 -t)。

    每路视频: fps → contain scale → pad 进格子 → setsar →(hold 时 tpad 定格)
    底: color 画布源 → 逐格 overlay（行优先坐标）
    音频: first=第一个有声输入(缺则静音) / mix=全部混音(无声输入补 anullsrc) / none
    """
    pad_extra = 0.5  # 底图比最长视频长一点，防时长取整误差截画面
    parts = []
    for i, info in enumerate(infos):
        chain = (f'[{i}:v]fps={fps},'
                 f"scale=w={layout.cell_w}:h={layout.cell_h}:force_original_aspect_ratio=decrease,"
                 f'pad={layout.cell_w}:{layout.cell_h}:(ow-iw)/2:(oh-ih)/2:color={bg},'
                 f'setsar=1')
        if max_dur > info['duration'] + 0.01:
            chain += f',tpad=stop_mode=clone:stop_duration={max_dur - info["duration"]:.3f}'
        chain += f'[v{i}]'
        parts.append(chain)
    parts.append(f'color=c={bg}:s={layout.canvas_w}x{layout.canvas_h}:'
                 f'd={max_dur + pad_extra:.3f}:r={fps}[base]')
    prev = 'base'
    for i in range(len(infos)):
        x, y = layout.position(i)
        out = f'vout{i}' if i < len(infos) - 1 else 'vout'
        parts.append(f'[{prev}][v{i}]overlay={x}:{y}[{out}]')
        prev = out

    audio_in = []
    if audio == 'none':
        parts.append('[vout]anull[vfin]')
        return ';'.join(parts), audio_in, max_dur

    if audio == 'first':
        src = next((i for i, x in enumerate(infos) if x['has_audio']), None)
        if src is None:
            print('⚠ 无任何输入带音轨 → 静音输出')
            parts.append('[vout]anull[vfin]')
            return ';'.join(parts), audio_in, max_dur
        astreams = [src]
    else:  # mix
        astreams = [i for i, x in enumerate(infos) if x['has_audio']]
        silent = [i for i in range(len(infos)) if not infos[i]['has_audio']]
        audio_in = silent  # 这些输入需额外配 anullsrc
    if not astreams:
        print('⚠ 无任何输入带音轨 → 静音输出')
        parts.append('[vout]anull[vfin]')
        return ';'.join(parts), audio_in, max_dur

    base_silent = len(infos)
    for k, i in enumerate(astreams):
        parts.append(f'[{i}:a]aresample=44100,'
                     'aformat=sample_fmts=fltp:channel_layouts=stereo,'
                     f'apad=whole_dur={max_dur:.3f}[a{k}]')
    for k, _ in enumerate(audio_in):
        parts.append(f'[{base_silent + k}:a]aresample=44100,'
                     'aformat=sample_fmts=fltp:channel_layouts=stereo,'
                     f'apad=whole_dur={max_dur:.3f}[a{len(astreams) + k}]')
    all_a = [f'a{i}' for i in range(len(astreams) + len(audio_in))]
    if len(all_a) == 1:
        parts.append(f'[{all_a[0]}]atrim=0:{max_dur:.3f}[afin]')
    else:
        parts.append(f'{"".join("[" + a + "]" for a in all_a)}'
                     f'amix=inputs={len(all_a)}:duration=longest,'
                     f'atrim=0:{max_dur:.3f}[afin]')
    parts.append('[vout][afin]concat=n=1:v=1:a=1[vfin][afinout]')
    return ';'.join(parts), audio_in, max_dur


def make_grid(video_paths: list, output: str = None, rows: int = None,
              cols: int = None, grid: str = None, width: int = 1920,
              gap: int = 8, bg: str = 'black', audio: str = 'first',
              fps: int = 24, fill: str = 'hold', cell_ratio: float = None,
              crf: int = 20, preset: str = 'veryfast', quiet: bool = False) -> str:
    """m×n 画布合成主入口。返回输出路径。"""
    for vp in video_paths:
        if not os.path.isfile(vp):
            raise FileNotFoundError(f'视频不存在: {vp}')
    n = len(video_paths)

    if grid:
        rows, cols = parse_grid(grid)
    if rows is None and cols is None:
        rows, cols = auto_grid(n)
    elif rows is None:
        rows = max(1, math.ceil(n / cols))
    elif cols is None:
        cols = max(1, math.ceil(n / rows))

    infos = [probe_video(vp) for vp in video_paths]
    layout = compute_layout(infos, rows, cols, width=width, gap=gap,
                            cell_ratio=cell_ratio)
    max_dur = max(i['duration'] for i in infos)

    if not quiet:
        print(f'布局 {layout.rows}x{layout.cols} (cell {layout.cell_w}x{layout.cell_h}, '
              f'画布 {layout.canvas_w}x{layout.canvas_h}, gap={layout.gap}, '
              f'输出 {max_dur:.1f}s, audio={audio}, fill={fill}):')
        for i in range(layout.rows * layout.cols):
            name = (os.path.basename(infos[i]['path'])
                    if i < n else '(空)')
            end = '\n' if (i + 1) % layout.cols == 0 else '  '
            print(f'  [{i}] {name}', end=end)

    fc, extra_silent, _t = build_filter_complex(infos, layout, max_dur,
                                                fps=fps, bg=bg, audio=audio)
    cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error']
    for info in infos:
        if fill == 'loop':
            cmd += ['-stream_loop', '-1']
        cmd += ['-i', info['path']]
    for _ in extra_silent:  # 无声输入补静音源（mix 模式）
        cmd += ['-f', 'lavfi', '-i',
                'anullsrc=channel_layout=stereo:sample_rate=44100']
    cmd += ['-filter_complex', fc,
            '-map', '[vfin]' if '[vfin]' in fc else '[vout]',
            '-t', f'{max_dur:.3f}']
    if audio != 'none' and any(i['has_audio'] for i in infos):
        cmd += ['-map', '[afinout]' if '[afinout]' in fc else '[afin]',
                '-c:a', 'aac', '-b:a', '160k']
    else:
        cmd += ['-an']
    cmd += ['-c:v', 'libx264', '-preset', preset, '-crf', str(crf),
            '-pix_fmt', 'yuv420p', '-r', str(fps)]

    if output is None:
        from core.pipeline import CONFIG_PATH
        with open(CONFIG_PATH) as f:
            import json
            out_dir = json.load(f)['output_dir']
        os.makedirs(out_dir, exist_ok=True)
        output = os.path.join(out_dir, f'grid_{time.strftime("%Y%m%d_%H%M%S")}.mp4')
    if not os.path.isabs(output):
        from core.pipeline import CONFIG_PATH
        with open(CONFIG_PATH) as f:
            import json
            out_dir = json.load(f)['output_dir']
        output = os.path.join(out_dir, output)
    os.makedirs(os.path.dirname(output) or '.', exist_ok=True)
    cmd += [output]

    if not quiet:
        print(f'\n[grid] {shlex.join(cmd)}\n')
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f'ffmpeg 合成失败:\n{r.stderr[-2000:]}')
    if not quiet:
        print(f'Done: {output} ({layout.rows}x{layout.cols} 画布, {max_dur:.1f}s)')
    return output


# ────────────────────────── CLI ──────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(
        description='画布网格合成：多视频 m×n 拼贴同放（matplotlib subplot 风格）')
    ap.add_argument('videos', nargs='+', help='待拼贴视频（按行优先填格）')
    ap.add_argument('-o', '--output', default=None,
                    help='输出路径（缺省 output/grid_<时间戳>.mp4）')
    ap.add_argument('--grid', default=None, help='网格 MxN（如 2x3）')
    ap.add_argument('--rows', type=int, default=None, help='行数（与 --cols 二选一）')
    ap.add_argument('--cols', type=int, default=None, help='列数')
    ap.add_argument('--width', type=int, default=1920, help='画布总宽（默认 1920）')
    ap.add_argument('--gap', type=int, default=8, help='格间距像素（默认 8）')
    ap.add_argument('--bg', default='black', help='底色（ffmpeg color，如 0x202020）')
    ap.add_argument('--audio', default='first', choices=['first', 'mix', 'none'],
                    help='音频: first=第一个有声输入 / mix=混音 / none')
    ap.add_argument('--fps', type=int, default=24)
    ap.add_argument('--fill', default='hold', choices=['hold', 'loop'],
                    help='短视频填格方式: hold=定格末帧 / loop=循环')
    ap.add_argument('--cell-ratio', type=float, default=None,
                    help='格宽高比 w/h（缺省取输入均值）')
    args = ap.parse_args(argv)
    make_grid(args.videos, output=args.output, rows=args.rows, cols=args.cols,
              grid=args.grid, width=args.width, gap=args.gap, bg=args.bg,
              audio=args.audio, fps=args.fps, fill=args.fill,
              cell_ratio=args.cell_ratio)


if __name__ == '__main__':
    main()
