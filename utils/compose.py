"""v10 时间线拼接与特效（OpenCut 思路，后端 CLI 可被 LLM 调用）

时间线 JSON 模型（snake_case，对齐 OpenCut BaseTimelineElement 子集）：
{
  "output": "out.mp4",
  "width": 1280, "height": 704, "fps": 24,
  "main": [ {id,type,source,trim_start,trim_end,start,duration,rate,effects,transition_in,volume,
             keyframes?,easing?,mask?} ],
  "overlay": [ {id,type:video|image|text,source/text,start,duration,pos,scale,opacity,rotation,
                fontsize,fontcolor,borderw,bordercolor,shadowx,shadowy,shadowcolor,box,boxcolor,
                keyframes?,easing?,mask?} ],
  "sticker": [ 同 overlay image（M7 别名轨） ],
  "audio": [ {id,source,start,duration,trim_start,volume,ducking} ]
}

v10 M5 关键帧：元素 keyframes=[{t,x,y,scale,opacity,rotation}...]（t 为元素本地秒）
  + easing: linear|ease-in-out。x/y→overlay 表达式、rotation→rotate 逐帧、
  scale→scale eval=frame、opacity→灰度掩码源 geq(T)+alphamerge（保原图抠图）。
v10 M6 掩码：mask={kind:circle|rounded|rect|image, radius?, feather?, source?}（白=显示）。
v10 M7 贴纸：静图自动 -loop 1、GIF -ignore_loop 0；drawtext 描边/阴影/底色。
v10 M8 切割：split_media / CLI `split media --at 3 7 [-o prefix] [--precise]`。

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


# ══════════════════════════ v10 M5-M8：关键帧 / 掩码 / 贴纸 ══════════════════════════

def _kf_points(el, prop):
    """元素 keyframes 中某属性的 [(t, val)] 点列（按 t 排序），无则 None。"""
    pts = []
    for k in el.get('keyframes') or []:
        if prop in k and k[prop] is not None:
            pts.append((float(k['t']), k[prop]))
    if not pts:
        return None
    pts.sort(key=lambda p: p[0])
    return [(t, float(v)) for t, v in pts]


def _kf_interp(pts, tvar, easing='linear'):
    """把 [(t,v)...] 编译成逐帧 ffmpeg 表达式。tvar: 时间变量表达式（如 t-1.5）。
    首帧前钳 v0、末帧后钳 vN。easing: linear | ease-in-out。"""
    def seg(t0, v0, t1, v1):
        u = f'(({tvar})-{t0:.4f})/{max(t1 - t0, 1e-6):.4f}'
        if easing == 'ease-in-out':
            e = f'0.5-0.5*cos(PI*clip({u},0,1))'
        else:
            e = f'clip({u},0,1)'
        return f'{v0:.4f}+({v1 - v0:.4f})*({e})'

    expr = f'{pts[-1][1]:.4f}'
    for i in range(len(pts) - 1, 0, -1):
        t0, v0 = pts[i - 1]
        t1, v1 = pts[i]
        expr = f"if(lt({tvar},{t1:.4f}),{seg(t0, v0, t1, v1)},{expr})"
    if pts[0][0] > 0:
        expr = f"if(lt({tvar},{pts[0][0]:.4f}),{pts[0][1]:.4f},{expr})"
    return expr


def _kf_static(el, prop, dflt):
    """无该属性 keyframes 时的静态值（元素顶层字段或默认）。"""
    return float(el.get(prop) if el.get(prop) is not None else dflt)


def _make_mask(spec, w, h, work_dir, base_img=None):
    """按 spec 生成 w×h 灰度掩码 PNG（白=显示）。base_img 给定时与其 alpha 相乘
    （保 PNG 贴纸抠图）。feather>0 高斯模糊边缘。返回路径。"""
    from PIL import Image, ImageDraw, ImageFilter
    import numpy as np
    kind = spec.get('kind', 'circle')
    feather = float(spec.get('feather') or 0)
    m = Image.new('L', (w, h), 0)
    d = ImageDraw.Draw(m)
    if kind == 'image':
        src = spec.get('source')
        mm = Image.open(src).convert('L').resize((w, h)) if src else m
        m = mm
    elif kind == 'rect':
        d.rectangle([0, 0, w - 1, h - 1], fill=255)
    elif kind == 'rounded':
        r = int(spec.get('radius') or min(w, h) * 0.25)
        d.rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    else:  # circle/ellipse
        r = float(spec.get('radius') or 1.0)
        if r >= 1.0:
            d.ellipse([0, 0, w - 1, h - 1], fill=255)
        else:
            rr = int(min(w, h) / 2 * r)
            cx, cy = w // 2, h // 2
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=255)
    if feather > 0:
        m = m.filter(ImageFilter.GaussianBlur(feather))
    if base_img:
        a = np.array(Image.open(base_img).convert('RGBA').resize((w, h)))[:, :, 3]
        m = Image.fromarray((np.array(m, dtype=np.float32) / 255.0 * a.astype(np.float32) / 255.0 * 255).astype('uint8'))
    out = os.path.join(work_dir, f'mask_{uuid.uuid4().hex[:6]}.png')
    m.save(out)
    return out


def _opa_gray_input(spec, dur, fps, easing):
    """动态 opacity 用的白色 gray 源输入参数 + geq 表达式（lum *= opacity 曲线）。
    返回 (ffmpeg_input_args, geq_lum_expr_with_T)。"""
    opa_pts = _kf_points(spec, 'opacity')
    if opa_pts:
        oexpr = _kf_interp(opa_pts, 'T', easing)
    else:
        oexpr = f"{_kf_static(spec, 'opacity', 1.0):.4f}"
    inp = ['-f', 'lavfi', '-framerate', str(fps), '-t', f'{dur + 0.2:.3f}',
           '-i', f'color=white:s=64x64:r={fps}']
    return inp, oexpr


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


def _enforce_duration(src: str, out: str, dur: float, width: int, height: int) -> None:
    """特效后强制归一：精确到 dur 秒（不足克隆末帧，超出截断），保留音轨。"""
    vf = (f"tpad=stop_mode=clone:stop_duration={max(0.0, dur):.3f},"
          f"trim=duration={dur:.3f},setpts=PTS-STARTPTS,"
          f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
    has_a = _probe(src)['has_audio']
    if has_a:
        cmd = [FFMPEG, '-y', '-i', src, '-vf', vf, '-r', '24',
               '-af', f'atrim=duration={dur:.3f},asetpts=PTS-STARTPTS'] + ENC + \
              ['-c:a', 'aac', '-shortest', out]
    else:
        cmd = [FFMPEG, '-y', '-i', src, '-vf', vf, '-r', '24'] + ENC + ['-an', out]
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
            # 特效可能改变时长（speed_ramp/freeze_zoom），强制回到 out_dur 保证时间轴可预测
            fixed = os.path.join(work_dir, f'main_{cid}_fix.mp4')
            _enforce_duration(cur, fixed, out_dur, W, H)
            shutil.move(fixed, tmp)

    # v10 M5/M6：主轨元素也支持关键帧（rotation/scale/opacity）与掩码
    if el.get('mask') or el.get('keyframes'):
        el2 = {'source': tmp, 'start': 0.0, 'duration': out_dur,
               'easing': el.get('easing') or 'linear',
               'rotation': el.get('rotation'),
               'scale': el.get('scale') if el.get('scale') is not None else 1.0,
               'opacity': el.get('opacity'), 'keyframes': el.get('keyframes'),
               'mask': el.get('mask')}
        fc, ins, olabel = [], ['-i', tmp], 'kv'
        try:
            fin, _x, _y, _n = _element_chain(el2, '[0:v]', olabel, tl, work_dir, fc, ins, 0,
                                              zoom_canvas=True)
            kfx = os.path.join(work_dir, f'main_{cid}_kfx.mp4')
            cmd = [FFMPEG, '-y'] + ins + ['-filter_complex', ';'.join(fc),
                                          '-map', fin, '-map', '0:a?'] + ENC + \
                  ['-c:a', 'copy', kfx]
            _run(cmd)
            shutil.move(kfx, tmp)
        except Exception as e:
            print(f'  [compose] 主轨关键帧/掩码失败跳过: {e}')
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
    tl['fps'] = tl.get('fps') or 24

    # 1) 主轨
    main_els = tl.get('main') or []
    clips = [normalize_clip({**el, 'timeline': tl}, work_dir) for el in main_els]
    main_out = os.path.join(work_dir, 'main_joined.mp4')
    build_main_track(main_els, clips, work_dir, main_out)

    # 2) overlay（画中画/文字）+ v10 M7 贴纸轨（=image overlay 别名）
    overlays = list(tl.get('overlay') or [])
    overlays += [{'type': 'image', **e} for e in (tl.get('sticker') or [])]
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
    # 自动清理临时目录（仅当未显式指定 tmp_root）
    if tmp_root is None:
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass
    return final_path


def _enable(start: float, dur: float) -> str:
    a = ('%.3f' % start)
    b = ('%.3f' % (start + dur))
    return 'between(t\\,' + a + '\\,' + b + ')'

def _src_size(src: str, media: str):
    """源素材 (w, h)，探测失败回 None。"""
    try:
        if media == 'image':
            from PIL import Image
            return Image.open(src).size
        p = _probe(src)
        if p['width'] > 0:
            return p['width'], p['height']
    except Exception:
        pass
    return None


def _fq(expr: str) -> str:
    """滤镜选项值含特殊字符时加引号。"""
    return f"'{expr}'" if any(c in expr for c in '(),') else expr


def _element_chain(el, inlabel, outlabel, tl, work_dir, fc, inputs, media_idx,
                   zoom_canvas=False):
    """v10 M5-M8：给 overlay/sticker/主轨元素构建滤镜链：
    format→rotate→(掩码/透明度 alphamerge)→(静态或逐帧 scale)→setpts。
    透明度/掩码在缩放前以源尺寸合并（保抠图且兼容动画缩放）。
    zoom_canvas=True（主轨用）：动画缩放叠到固定 W×H 黑底，保证输出帧尺寸恒定。
    返回 (overlay用标签, x, y, 下一个可用输入索引)。就地追加 fc/inputs。"""
    W = int(tl.get('width') or 1280)
    fps = int(tl.get('fps') or 24)
    start = float(el.get('start') or 0.0)
    dur = float(el.get('duration') or 3.0)
    easing = el.get('easing') or 'linear'
    src = el['source']
    ext = os.path.splitext(src)[1].lower()
    media = _media_kind(src)
    TV = f'(t-{start:.4f})'
    nxt = media_idx + 1

    ch = [inlabel, 'format=rgba']
    rot_pts = _kf_points(el, 'rotation')
    rot0 = _kf_static(el, 'rotation', 0.0)
    if rot_pts:
        ch.append(f",rotate=a='{_kf_interp(rot_pts, TV, easing)}':c=none")
    elif rot0:
        ch.append(f',rotate={rot0:.3f}:c=none')

    ow = int(W * _kf_static(el, 'scale', 0.35)) // 2 * 2
    native = _src_size(src, media) or (ow, max(2, int(ow * _aspect(src, media))))
    oh = max(2, int(ow * native[1] / native[0])) // 2 * 2
    sc_pts = _kf_points(el, 'scale')

    mask_spec = el.get('mask')
    opa_pts = _kf_points(el, 'opacity')
    opa0 = _kf_static(el, 'opacity', 1.0)
    lab = outlabel
    if mask_spec or opa_pts or opa0 < 1.0:
        # 源尺寸的灰度掩码/白场 × opacity 曲线 → alphamerge（在 scale 之前）
        maskfile = None
        mw, mh = native[0] // 2 * 2, native[1] // 2 * 2
        if mask_spec:
            try:
                base_img = src if media == 'image' and ext not in ('.gif',) else None
                maskfile = _make_mask(mask_spec, mw, mh, work_dir, base_img=base_img)
            except Exception as e:
                print(f'  [compose] mask 失败跳过: {e}')
        if maskfile:
            inputs += ['-loop', '1', '-framerate', str(fps), '-t', f'{dur + 0.1:.3f}', '-i', maskfile]
        else:
            inputs += ['-f', 'lavfi', '-t', f'{dur + 0.1:.3f}', '-i', f'color=white:s={mw}x{mh}:r={fps}']
        oexpr = _kf_interp(opa_pts, 'T', easing) if opa_pts else f'{opa0:.4f}'
        mlab = f'[m{nxt}]'
        fc.append(f'[{nxt}:v]format=gray,setsar=1,'
                  f"geq=lum='lum(X,Y)*({oexpr})',"
                  f'setpts=PTS-STARTPTS+{start:.4f}/TB{mlab}')
        lab = f'{outlabel}m'
        fc.append(''.join(ch) + f'[cel{nxt}];[cel{nxt}]{mlab}alphamerge[{lab}]')
        nxt += 1
    else:
        fc.append(''.join(ch) + f'[{lab}]')

    # scale 在 alphamerge 之后（动画 scale 用 eval=frame 逐帧重算，不影响掩码尺寸）
    sc_end = f'{outlabel}s'
    if sc_pts:
        wex = f"{ow}*({_kf_interp(sc_pts, TV, easing)})"
        fc.append(f"[{lab}]scale=w='{wex}':h='trunc(({wex})*in_h/in_w/2)*2':eval=frame[{sc_end}]")
    else:
        fc.append(f'[{lab}]scale={ow}:{oh}[{sc_end}]')

    if sc_pts and zoom_canvas:
        # 逐帧变尺寸喂编码器会导致 x264 stride 崩溃：叠到固定 W×H 黑底居中
        H = int(tl.get('height') or 704)
        base = f'{outlabel}b'
        fc.append(f'color=black:s={W}x{H}:r={fps}:d={dur + 0.15:.3f},format=rgba[{base}];'
                  f'[{base}][{sc_end}]overlay=(W-w)/2:(H-h)/2:eof_action=pass[{outlabel}]')
        sc_end = outlabel

    fin = f'[fin{nxt}]'
    fc.append(f'[{sc_end}]setpts=PTS-STARTPTS+{start:.4f}/TB{fin}')
    x_pts = _kf_points(el, 'x')
    y_pts = _kf_points(el, 'y')
    posx = (_kf_interp(x_pts, TV, easing) if x_pts
            else (el.get('pos', {}) or {}).get('x', 'W-w-40'))
    posy = (_kf_interp(y_pts, TV, easing) if y_pts
            else (el.get('pos', {}) or {}).get('y', '40'))
    return fin, str(posx), str(posy), nxt


def apply_overlays(base: str, overlays: List[Dict[str, Any]], tl: Dict[str, Any],
                   work_dir: str) -> str:
    """在主视频上叠加画中画/文字/贴纸层。单一 filter_complex。
    支持 M5 关键帧(keyframes/easing)、M6 掩码(mask)、M7 贴纸轨（静图 loop/GIF 循环）。"""
    parts = []
    fc = []
    inputs = ['-i', base]
    prev = '[0:v]'
    idx = 1
    in_idx = 1
    for ov in overlays:
        kind = ov.get('type') or ('text' if ov.get('text') else 'image' if ov.get('source') else 'video')
        if kind == 'sticker':
            kind = 'image'
        start = float(ov.get('start') or 0.0)
        dur = float(ov.get('duration') or 3.0)
        if kind in ('video', 'image'):
            src = ov['source']
            ext = os.path.splitext(src)[1].lower()
            if ext == '.gif':
                inputs += ['-ignore_loop', '0', '-i', src]
            elif kind == 'image':
                inputs += ['-loop', '1', '-framerate', str(int(tl.get('fps') or 24)),
                           '-t', f'{dur + 0.05:.3f}', '-i', src]
            else:
                inputs += ['-i', src]
            inlabel = f'[{in_idx}:v]'
            olabel = f'v{in_idx}'
            ovlab, ox, oy, in_idx = _element_chain(ov, inlabel, olabel, tl, work_dir,
                                                   fc, inputs, in_idx)
            fc.append(f'{prev}{ovlab}overlay=x={_fq(ox)}:y={_fq(oy)}:enable={_enable(start,dur)}:eof_action=pass[o{idx}]')
            prev = f'[o{idx}]'
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
            for k in ('borderw', 'bordercolor', 'shadowx', 'shadowy', 'shadowcolor'):
                if ov.get(k) is not None:
                    vf += f':{k}={ov[k]}'
            if ov.get('box'):
                vf += (':box=1:boxcolor=' + str(ov.get('boxcolor') or 'black@0.5')
                       + ':boxborderw=' + str(ov.get('boxborderw') or 8))
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


def split_media(src: str, times: List[float], out_prefix: str, precise: bool = False) -> List[str]:
    """v10 M8：按时间点切割。times=[3, 7.5] → prefix_01/02/03。
    默认 stream copy（快，切点吸附关键帧）；precise 重编码帧级精确。"""
    dur = _probe(src)['duration']
    if dur <= 0:
        raise ValueError(f'无法探测时长: {src}')
    bounds = sorted(set([0.0] + [float(t) for t in times] + [dur]))
    bounds = [b for b in bounds if 0.0 <= b <= dur]
    ext = os.path.splitext(src)[1] or '.mp4'
    outs = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if b - a < 0.04:
            continue
        o = f'{out_prefix}_{i + 1:02d}{ext}'
        cmd = [FFMPEG, '-y', '-ss', f'{a:.3f}', '-t', f'{b - a:.3f}', '-i', src]
        cmd += (ENC + ['-c:a', 'aac']) if precise else ['-c', 'copy']
        cmd += [o]
        _run(cmd, timeout=600)
        outs.append(o)
    return outs


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

    p_split = sub.add_parser('split', help='v10 M8 按时间点切割（--precise 帧级）')
    p_split.add_argument('media')
    p_split.add_argument('--at', type=float, nargs='+', required=True, help='切点秒数，可多个')
    p_split.add_argument('-o', '--prefix', default=None, help='输出前缀（默认 媒体名_split）')
    p_split.add_argument('--precise', action='store_true', help='重编码帧级精确')

    a = ap.parse_args()
    if a.cmd == 'run':
        print(run_timeline(a.timeline, a.output))
    elif a.cmd == 'probe':
        print(json.dumps(_probe(a.path), ensure_ascii=False))
    elif a.cmd == 'init':
        tmpl = {
            'output': 'out.mp4', 'width': 1280, 'height': 704, 'fps': 24,
            'main': [{'id': 'c1', 'type': 'video', 'source': 'clip1.mp4',
                      'transition_in': {'kind': 'fade', 'duration': 0.4},
                      'keyframes': [{'t': 0, 'scale': 1.0, 'opacity': 0.0},
                                     {'t': 0.8, 'scale': 1.0, 'opacity': 1.0}],
                      'easing': 'ease-in-out'}],
            'overlay': [{'id': 't1', 'type': 'text', 'text': '标题',
                          'start': 0.5, 'duration': 3, 'fontsize': 48,
                          'fontcolor': 'white', 'borderw': 2, 'bordercolor': 'black',
                          'box': True, 'boxcolor': 'black@0.5'}],
            'sticker': [{'id': 's1', 'source': 'sticker.png', 'start': 1, 'duration': 4,
                         'scale': 0.25, 'mask': {'kind': 'circle', 'feather': 6},
                         'keyframes': [{'t': 0, 'x': 1280, 'y': 60, 'opacity': 0.0, 'rotation': -12},
                                        {'t': 0.6, 'x': 980, 'y': 60, 'opacity': 1.0, 'rotation': 0}],
                         'easing': 'ease-in-out'}],
            'audio': [{'id': 'a1', 'source': 'bgm.wav', 'start': 0,
                        'volume': 0.3, 'ducking': True}],
        }
        with open(a.o, 'w') as f:
            json.dump(tmpl, f, ensure_ascii=False, indent=2)
        print(f'template → {a.o}')
    elif a.cmd == 'split':
        for o in split_media(a.media, a.at, a.prefix or (a.media.rsplit('.', 1)[0] + '_split'),
                             precise=a.precise):
            print(o)
    elif a.cmd == 'merge':
        els = [{'id': f'c{i}', 'type': _media_kind(c), 'source': c,
                'transition_in': None if i == 0 else
                {'kind': a.transition, 'duration': a.transition_duration}}
               for i, c in enumerate(a.clips)]
        tl = {'output': a.o, 'main': els}
        print(run_timeline(tl))
    else:
        ap.print_help()
