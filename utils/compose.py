"""v10 时间线拼接与特效（OpenCut 思路，后端 CLI 可被 LLM 调用）

时间线 JSON 模型（snake_case，对齐 OpenCut BaseTimelineElement 子集）：
{
  "output": "out.mp4",
  "width": 1280, "height": 704, "fps": 24,
  "main": [ {id,type,source,trim_start,trim_end,start,duration,rate,effects,transition_in,volume} ],
  "overlay": [ {id,type:video|text,source/text,start,duration,pos,scale,opacity,fontsize,fontcolor} ],
  "audio": [ {id,source,start,duration,trim_start,volume,ducking} ]
}

剪辑用 ffmpeg 实现：xfade 链式转场 / overlay 画中画 / drawtext / amix+sidechain ducking / setpts+atempo 变速。
"""
import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 复用 v5 effects（特效 + xfade + ffprobe）
try:
    from utils.effects import (
        apply_effect, transition, concat_with_transitions,
        XFADE_KINDS, _ffprobe_duration, FFMPEG,
    )
except ImportError:
    from effects import (
        apply_effect, transition, concat_with_transitions,
        XFADE_KINDS, _ffprobe_duration, FFMPEG,
    )

FFPROBE = 'ffprobe'
ENC = ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'fast']


def _probe(path: str) -> Dict[str, Any]:
    """探测媒体：{duration,width,height,has_audio}"""
    d = {'duration': 0.0, 'width': 0, 'height': 0, 'has_audio': False}
    try:
        d['duration'] = float(_ffprobe_duration(path))
    except Exception:
        pass
    try:
        r = subprocess.run(
            [FFPROBE, '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height', '-of', 'default=nw=1:nk=1', path],
            capture_output=True, text=True, timeout=20)
        lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
        if len(lines) >= 2:
            d['width'], d['height'] = int(lines[0]), int(lines[1])
    except Exception:
        pass
    try:
        r = subprocess.run(
            [FFPROBE, '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=codec_type', '-of', 'default=nw=1:nk=1', path],
            capture_output=True, text=True, timeout=20)
        d['has_audio'] = 'audio' in r.stdout
    except Exception:
        pass
    return d


def _run(cmd: List[str], timeout: int = 1200) -> None:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        tail = (p.stderr or '')[-1500:]
        raise RuntimeError(f'ffmpeg 失败 rc={p.returncode}\n{tail}\ncmd={" ".join(cmd[:14])}...')


def _scale_rate(rate: float) -> str:
    """atempo 仅支持 [0.5,2.0]，超出用链式。返回 atempo 滤镜串。"""
    if rate == 1.0:
        return ''
    filters = []
    r = rate
    while r > 2.0:
        filters.append('atempo=2.0')
        r /= 2.0
    while r < 0.5:
        filters.append('atempo=0.5')
        r *= 2.0
    filters.append(f'atempo={r:.4f}')
    return ','.join(filters)


def _trim_media(src: str, out: str, trim_start: float, duration: float, rate: float,
                volume: float, width: int, height: int, is_video: bool) -> None:
    """裁剪 + 变速 + 归一化分辨率/fps/帧率，输出纯净片段（含音轨按 volume）。"""
    vf = [f'scale={width}:{height}:force_original_aspect_ratio=decrease',
          f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2']
    if rate != 1.0:
        vf.append(f'setpts=PTS/{rate:.4f}')
    vf_str = ','.join(vf)
    cmd = [FFMPEG, '-y', '-ss', f'{trim_start:.3f}', '-t', f'{duration:.3f}', '-i', src]
    if is_video:
        cmd += ['-vf', vf_str, '-r', '24']
    else:  # 图片：静态
        cmd += ['-loop', '1', '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2']
    # 音频
    atempo = _scale_rate(rate) if is_video and os.path.splitext(src)[1].lower() in ('.mp4', '.mov', '.webm', '.mkv') else ''
    af = []
    if atempo:
        af.append(atempo)
    if volume != 1.0:
        af.append(f'volume={volume:.3f}')
    if af:
        cmd += ['-af', ','.join(af)]
    else:
        cmd += ['-an']
    cmd += ENC + ['-t', f'{(duration if rate == 1.0 else duration / rate):.3f}' if is_video else f'{duration:.3f}', out]
    # 图片静态时长
    if not is_video:
        # -t 已放在 ENC 后，对静态图也生效
        pass
    _run(cmd)


# 兼容：图片走 loop
def _media_kind(src: str) -> str:
    ext = os.path.splitext(src)[1].lower()
    if ext in ('.mp4', '.mov', '.webm', '.mkv', '.avi'):
        return 'video'
    return 'image'


def normalize_clip(el: Dict[str, Any], work_dir: str) -> str:
    """把一个主轨元素裁剪/变速/特效后输出为独立片段。返回片段路径。"""
    src = el['source']
    cid = el.get('id') or uuid.uuid4().hex[:6]
    kind = el.get('type') or _media_kind(src)
    is_video = kind == 'video'

    probed = _probe(src) if is_video else {'duration': 0}
    ts = float(el.get('trim_start') or 0.0)
    te = el.get('trim_end')
    if te is not None:
        dur_src = float(te) - ts
    else:
        dur_src = (probed['duration'] - ts) if is_video and probed['duration'] > ts else float(el.get('duration') or 3.0)
    rate = float(el.get('rate') or 1.0)
    out_dur = float(el.get('duration') or (dur_src / rate))
    if not is_video:
        # 图片：duration 直接是展示时长
        ts = 0.0
        out_dur = float(el.get('duration') or 3.0)
    volume = float(el.get('volume') if el.get('volume') is not None else 1.0)

    tl = el.get('timeline', {})
    W = int(tl.get('width') or 1280)
    H = int(tl.get('height') or 704)

    tmp = os.path.join(work_dir, f'main_{cid}.mp4')
    _trim_media(src, tmp, ts, out_dur, rate, volume, W, H, is_video)

    # 特效链（复用 v5）
    effects = el.get('effects') or []
    if effects:
        cur = tmp
        for i, eff in enumerate(effects):
            nxt = os.path.join(work_dir, f'main_{cid}_e{i}.mp4')
            name = eff.get('name', 'none')
            params = {k: v for k, v in eff.items() if k != 'name'}
            if name == 'none':
                continue
            try:
                apply_effect(cur, nxt, effect=name, **params)
            except Exception as e:
                print(f'  [compose] 特效 {name} 失败跳过: {e}')
                continue
            cur = nxt
        if cur != tmp:
            shutil.move(cur, tmp)
    return tmp


def build_main_track(main_els: List[Dict[str, Any]], clips: List[str],
                     work_dir: str, out: str) -> str:
    """主轨拼接。若全部无 transition_in 则直接 concat（stream copy 更快），
    否则用 xfade 链式。返回最终主轨视频路径。"""
    n = len(clips)
    if n == 0:
        raise ValueError('主轨为空')
    if n == 1:
        shutil.copy(clips[0], out)
        return out

    # 收集转场类型
    kinds = []
    for el in main_els:
        ti = el.get('transition_in')
        kinds.append(ti.get('kind', 'fade') if ti else None)

    need_xfade = any(k for k in kinds)
    if not need_xfade:
        # 直接 concat（先确认同参数，都是 normalize 过的一致）
        listfile = os.path.join(work_dir, 'concat.txt')
        with open(listfile, 'w') as f:
            for c in clips:
                f.write(f"file '{c}'\n")
        cmd = [FFMPEG, '-y', '-f', 'concat', '-safe', '0', '-i', listfile,
               '-c', 'copy', out]
        _run(cmd, timeout=600)
        return out

    # xfade 链式（两两 transition 合并，避免单次超长 filter）
    dur_default = 0.4
    cur = clips[0]
    for i in range(1, n):
        kind = kinds[i] or 'fade'
        if kind not in XFADE_KINDS:
            kind = 'fade'
        d = float((main_els[i].get('transition_in') or {}).get('duration') or dur_default)
        last = (i == n - 1)
        nxt = out if last else os.path.join(work_dir, f'xf_{i}.mp4')
        ok = transition(cur, clips[i], nxt, kind=kind, duration=d)
        if not ok or not os.path.isfile(nxt) or os.path.getsize(nxt) < 500:
            raise RuntimeError('xfade fail: %s + %s kind=%s' % (clips[i-1], clips[i], kind))
        cur = nxt
    return out


def build_timeline(tl: Dict[str, Any], out: str, tmp_root: Optional[str] = None) -> str:
    """执行时间线 → 成片。返回成片路径。"""
    output = out or tl.get('output')
    if not output:
        raise ValueError('缺少 output')
    work_dir = tmp_root or os.path.join(os.path.dirname(os.path.abspath(output)),
                                        '_compose_tmp_' + uuid.uuid4().hex[:8])
    os.makedirs(work_dir, exist_ok=True)
    tl = dict(tl)
    tl['width'] = tl.get('width') or 1280
    tl['height'] = tl.get('height') or 704

    # 1) 主轨
    main_els = tl.get('main') or []
    clips = [normalize_clip({**el, 'timeline': tl}, work_dir) for el in main_els]
    main_out = os.path.join(work_dir, 'main_joined.mp4')
    build_main_track(main_els, clips, work_dir, main_out)

    # 2) overlay（画中画/文字）
    overlays = tl.get('overlay') or []
    cur = main_out
    if overlays:
        cur = apply_overlays(main_out, overlays, tl, work_dir)

    # 3) 音频混音
    audio_els = tl.get('audio') or []
    final_path = output if os.path.isabs(output) else os.path.abspath(output)
    os.makedirs(os.path.dirname(final_path) or '.', exist_ok=True)
    if audio_els:
        cur = mux_audio(cur, audio_els, tl, work_dir, final_path)
    else:
        cmd = [FFMPEG, '-y', '-i', cur] + ENC + ['-c:a', 'aac', final_path]
        _run(cmd)
    return final_path


def _enable(start: float, dur: float) -> str:
    a = ('%.3f' % start)
    b = ('%.3f' % (start + dur))
    return 'between(t\\,' + a + '\\,' + b + ')'

def apply_overlays(base: str, overlays: List[Dict[str, Any]], tl: Dict[str, Any],
                   work_dir: str) -> str:
    """在主视频上叠加画中画/文字层。用单一 filter_complex 完成。"""
    parts = []
    fc = []
    inputs = ['-i', base]
    prev = '[0:v]'
    idx = 1
    in_idx = 1
    for ov in overlays:
        kind = ov.get('type') or ('text' if ov.get('text') else 'video')
        start = float(ov.get('start') or 0.0)
        dur = float(ov.get('duration') or 3.0)
        if kind in ('video', 'image'):
            src = ov['source']
            inputs += ['-i', src]
            is_video = _media_kind(src) == 'video'
            inlabel = f'[{in_idx}:v]'
            # 缩放 + 透明度 + 时间对齐
            scale = float(ov.get('scale') or 0.35)
            W = tl.get('width') or 1280
            ow = int(W * scale)
            opacity = float(ov.get('opacity') or 1.0)
            fc.append(f'{inlabel}scale={ow}:-1,format=yuva420p'
                      + (f',colorchannelmixer=aa={opacity:.3f}' if opacity < 1.0 else '')
                      + f',setpts=PTS-STARTPTS+{start}/TB[v{in_idx}]')
            posx = ov.get('pos', {}).get('x', 'W-w-40') if isinstance(ov.get('pos'), dict) else 'W-w-40'
            posy = ov.get('pos', {}).get('y', '40') if isinstance(ov.get('pos'), dict) else '40'
            fc.append(f'{prev}[v{in_idx}]overlay=x={posx}:y={posy}:enable={_enable(start,dur)}:eof_action=pass[o{idx}]')
            prev = f'[o{idx}]'
            in_idx += 1
        else:  # text
            text = ov.get('text', '')
            fsize = ov.get('fontsize') or 48
            fcolor = ov.get('fontcolor') or 'white'
            posx = ov.get('pos', {}).get('x', '(W-tw)/2') if isinstance(ov.get('pos'), dict) else '(W-tw)/2'
            posy = ov.get('pos', {}).get('y', '80') if isinstance(ov.get('pos'), dict) else '80'
            esc = str(text).replace(chr(92), chr(92)+chr(92)) \
                .replace(':', chr(92)+':').replace(chr(39), chr(92)+chr(39)) \
                .replace('[', chr(92)+chr(91)).replace(']', chr(92)+chr(93))
            vf = (f"drawtext=text='{esc}':fontsize={fsize}:fontcolor={fcolor}:"
                   f'x={posx}:y={posy}:enable={_enable(start,dur)}')
            fc.append(f'{prev}{vf}[o{idx}]')
            prev = f'[o{idx}]'
        idx += 1
    if not fc:
        return base
    out = os.path.join(work_dir, 'overlaid.mp4')
    cmd = [FFMPEG, '-y'] + inputs + ['-filter_complex', ';'.join(fc), '-map', prev,
                                     '-map', '0:a?',] + ENC + ['-c:a', 'aac', out]
    _run(cmd)
    return out


def mux_audio(video: str, audio_els: List[Dict[str, Any]], tl: Dict[str, Any],
              work_dir: str, final_path: str) -> str:
    """把音频轨混入视频（amix + 可选 sidechain ducking）。"""
    # 视频主轨原声作为 ducking 的 sidechain
    inputs = ['-i', video]
    fc = []
    # 视频原声
    a_labels = []
    has_main_audio = _probe(video)['has_audio']
    if has_main_audio:
        fc.append('[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono[ma]')
        a_labels.append('[ma]')
    idx = 1
    for ael in audio_els:
        src = ael['source']
        start = float(ael.get('start') or 0.0)
        dur = float(ael.get('duration') or 0)
        vol = float(ael.get('volume') or 1.0)
        ts = float(ael.get('trim_start') or 0.0)
        inputs += ['-ss', f'{ts:.3f}', '-t', f'{dur:.3f}' if dur > 0 else '9999', '-i', src]
        fc.append(f'[{idx}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono,'
                  f'volume={vol:.3f},adelay={int(start * 1000)}|{int(start * 1000)}[a{idx}]')
        a_labels.append(f'[a{idx}]')
        idx += 1
    if not a_labels:
        return video
    # ducking：视频原声为被压者，音频轨为 sidechain
    duck = any(ael.get('ducking') for ael in audio_els) and has_main_audio
    if duck:
        side = [l for i, l in enumerate(a_labels) if i > 0]
        fc.append('[ma]asplit[ma_duck][ma_keep]')
        # 用第一个音频轨做侧链
        fc.append(f'[ma_duck]{side[0]}sidechaincompress=threshold=0.02:ratio=8:attack=50:release=300[ducked]')
        mix_labels = ['[ducked]'] + side
    else:
        mix_labels = a_labels
    fc.append(''.join(mix_labels) + f'amix=inputs={len(mix_labels)}:duration=first:dropout_transition=0[mixed]')
    out = final_path if os.path.isabs(final_path) else os.path.abspath(final_path)
    cmd = [FFMPEG, '-y'] + inputs + ['-filter_complex', ';'.join(fc),
                                     '-map', '0:v', '-map', '[mixed]'] +           ['-c:v', 'copy', '-c:a', 'aac', out]
    _run(cmd)
    return out


def run_timeline(tl: Dict[str, Any], out: Optional[str] = None,
                 tmp_root: Optional[str] = None) -> str:
    """对外主入口：dict 或 json 路径 → 成片路径。"""
    if isinstance(tl, str):
        with open(tl) as f:
            tl = json.load(f)
    return build_timeline(tl, out or tl.get('output') or 'compose_out.mp4', tmp_root)


# ── CLI ──
if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='v10 时间线拼接 CLI')
    sub = ap.add_subparsers(dest='cmd')

    p_run = sub.add_parser('run', help='执行时间线 JSON')
    p_run.add_argument('timeline')
    p_run.add_argument('-o', '--output')

    p_probe = sub.add_parser('probe', help='探测媒体')
    p_probe.add_argument('path')

    p_init = sub.add_parser('init', help='生成时间线模板')
    p_init.add_argument('-o', default='timeline.json')

    p_merge = sub.add_parser('merge', help='快捷顺序拼接')
    p_merge.add_argument('clips', nargs='+')
    p_merge.add_argument('--transition', default='fade')
    p_merge.add_argument('--transition-duration', type=float, default=0.4)
    p_merge.add_argument('-o', default='merged.mp4')

    a = ap.parse_args()
    if a.cmd == 'run':
        print(run_timeline(a.timeline, a.output))
    elif a.cmd == 'probe':
        print(json.dumps(_probe(a.path), ensure_ascii=False))
    elif a.cmd == 'init':
        tmpl = {
            'output': 'out.mp4', 'width': 1280, 'height': 704,
            'main': [{'id': 'c1', 'type': 'video', 'source': 'clip1.mp4',
                      'transition_in': {'kind': 'fade', 'duration': 0.4}}],
            'overlay': [{'id': 't1', 'type': 'text', 'text': '标题',
                          'start': 0.5, 'duration': 3, 'fontsize': 48,
                          'fontcolor': 'white'}],
            'audio': [{'id': 'a1', 'source': 'bgm.wav', 'start': 0,
                        'volume': 0.3, 'ducking': True}],
        }
        with open(a.o, 'w') as f:
            json.dump(tmpl, f, ensure_ascii=False, indent=2)
        print(f'template → {a.o}')
    elif a.cmd == 'merge':
        els = [{'id': f'c{i}', 'type': _media_kind(c), 'source': c,
                'transition_in': None if i == 0 else
                {'kind': a.transition, 'duration': a.transition_duration}}
               for i, c in enumerate(a.clips)]
        tl = {'output': a.o, 'main': els}
        print(run_timeline(tl))
    else:
        ap.print_help()
