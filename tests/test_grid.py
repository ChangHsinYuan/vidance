"""grid 画布网格合成单测：纯逻辑（布局/解析/过滤器）+ ffmpeg 真跑（合成视频自测）。"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.grid import (auto_grid, parse_grid, compute_layout, build_filter_complex,
                        make_grid, probe_video)

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


def _expect_err(name, fn):
    try:
        fn()
        ok(name, False)
    except (ValueError, RuntimeError, FileNotFoundError):
        ok(name, True)


def main():
    # ── 纯逻辑 ──
    ok('auto_grid 方阵 1', auto_grid(1) == (1, 1))
    ok('auto_grid 方阵 4', auto_grid(4) == (2, 2))
    ok('auto_grid 方阵 5→2x3', auto_grid(5) == (2, 3))
    ok('auto_grid 方阵 7→3x3', auto_grid(7) == (3, 3))
    ok('parse_grid 2x3', parse_grid('2x3') == (2, 3))
    ok('parse_grid 2X3', parse_grid('2X3') == (2, 3))
    ok('parse_grid 2*3', parse_grid('2*3') == (2, 3))
    _expect_err('parse_grid 非法', lambda: parse_grid('abc'))
    _expect_err('parse_grid 零格', lambda: parse_grid('0x3'))

    info16 = {'width': 1600, 'height': 900, 'duration': 3.0, 'has_audio': True}
    info91 = {'width': 900, 'height': 1600, 'duration': 2.0, 'has_audio': False}
    lay = compute_layout([info16, info91], 2, 2, width=1000, gap=8)
    ok('cell 宽 = (1000-8)/2', lay.cell_w == 496)
    ok('canvas 尺寸', (lay.canvas_w, lay.canvas_h) == (1000, 2 * lay.cell_h + 8))
    ok('位置行优先 (0,0)/(1,0)', lay.position(0) == (0, 0) and lay.position(1) == (504, 0))
    ok('位置行优先 第二行', lay.position(2) == (0, lay.cell_h + 8))
    _expect_err('视频数超格报错', lambda: compute_layout([info16] * 5, 2, 2))
    _expect_err('布局容 0 视频', lambda: compute_layout([], 0, 2) or _bad())

    lay_r = compute_layout([info16, info91], 1, 2, width=1920, gap=0,
                           cell_ratio=16 / 9)
    ok('cell_ratio 手动 16:9', abs(lay_r.cell_h - round(lay_r.cell_w * 9 / 16)) <= 1)

    # filter_complex 构造
    infos = [dict(info16), dict(info91), dict(info16), dict(info91)]
    lay4 = compute_layout(infos, 2, 2, width=1000, gap=8)
    fc, silent, t = build_filter_complex(infos, lay4, max_dur=3.0, fps=24,
                                         audio='first')
    ok('fc 含 overlay 链', fc.count('overlay=') == 4)
    ok('fc 含 tpad(hold 短视频)', fc.count('tpad') == 2)
    ok('first 取第一个有声', silent == [] and '[0:a]' in fc and '[1:a]' not in fc)
    ok('fc 以 vfin/afinout 收尾', '[vfin][afinout]' in fc)
    fc2, silent2, _ = build_filter_complex(infos, lay4, 3.0, audio='none')
    ok('none 无音频映射', '[a0]' not in fc2)
    fc3, silent3, _ = build_filter_complex(infos, lay4, 3.0, audio='mix')
    ok('mix 无声输入补 anullsrc', silent3 == [1, 3])
    ok('mix amix=4 路', 'amix=inputs=4' in fc3)
    infos_all_mute = [dict(info91), dict(info91)]
    fc4, silent4, _ = build_filter_complex(infos_all_mute, compute_layout(infos_all_mute, 1, 2, 800), 2.0, audio='first')
    ok('全无声 → 静音输出', '[vfin]' in fc4 and '[a0]' not in fc4)

    # ── ffmpeg 真跑（合成测试片） ──
    tmp = tempfile.mkdtemp(prefix='grid_test_')
    ff = shutil_which_ffmpeg()
    if not ff:
        print('⚠ 无 ffmpeg，跳过真跑测试')
    else:
        # 3 个测试片：横屏有声 2s / 竖屏有声 1s / 横屏无声 3s（不同颜色+时间戳）
        specs = [
            ('testsrc2=size=640x360:rate=24:duration=2', True),
            ('color=c=red:size=360x640:rate=24:duration=1', True),
            ('testsrc=size=640x360:rate=24:duration=3', False),
        ]
        vids = []
        for i, (src, with_audio) in enumerate(specs):
            p = os.path.join(tmp, f'v{i}.mp4')
            cmd = ['ffmpeg', '-y', '-loglevel', 'error', '-f', 'lavfi', '-i', src]
            if with_audio:
                cmd += ['-f', 'lavfi', '-i', f'sine=frequency={200 * (i + 1)}:duration=2']
            cmd += ['-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p']
            if with_audio:
                cmd += ['-c:a', 'aac', '-shortest']
            cmd += [p]
            subprocess.run(cmd, check=True, capture_output=True)
            vids.append(p)
        for p in vids:
            info = probe_video(p)
            ok(f'probe {os.path.basename(p)}', info['duration'] > 0.9)

        out = make_grid(vids, output=os.path.join(tmp, 'g22.mp4'),
                        grid='2x2', width=640, gap=4, audio='first', quiet=True)
        info = probe_video(out)
        ok('2x2 输出时长=最长输入(3s)', abs(info['duration'] - 3.0) < 0.25)
        ok('2x2 输出尺寸=640 宽', info['width'] == 640)
        ok('2x2 音轨存在(first)', info['has_audio'])

        out5 = make_grid(vids, output=os.path.join(tmp, 'g32.mp4'),
                         rows=3, cols=2, width=480, gap=2, audio='mix',
                         fill='loop', quiet=True)
        i5 = probe_video(out5)
        ok('3x2 loop 时长=最长输入', abs(i5['duration'] - 3.0) < 0.25)
        ok('3x2 有声(mix 含 anullsrc)', i5['has_audio'])
        ok('3x2 空格子容忍(5 视频进 6 格)', True)

        out1 = make_grid(vids[:1], output=os.path.join(tmp, 'g11.mp4'),
                         grid='1x1', width=320, audio='none', quiet=True)
        i1 = probe_video(out1)
        ok('1x1 单视频 none 静音', not i1['has_audio'] and abs(i1['duration'] - 2.0) < 0.25)

        outt = make_grid(vids, output=os.path.join(tmp, 'g13_trim.mp4'),
                         grid='1x3', width=480, audio='first', trim=1.5, quiet=True)
        it = probe_video(outt)
        ok('trim=1.5 总时长≈1.5s', abs(it['duration'] - 1.5) < 0.25)
        ok('trim 1x3 画布≈480 宽(±6)', abs(it['width'] - 480) <= 6)

    print(f'\n{sum(1 for _, c in PASS if c)}/{len(PASS)} 通过')
    sys.exit(0 if all(c for _, c in PASS) else 1)


def shutil_which_ffmpeg():
    from shutil import which
    return which('ffmpeg')


def _bad():
    raise ValueError('bad')


if __name__ == '__main__':
    main()
