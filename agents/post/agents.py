"""P 层 Agent（薄包装）：配音、拼接、调色、BGM、字幕、特效、STT。"""
import os
import sys
import shutil
import subprocess

_ROOT = os.path.abspath(__file__)
for _ in range(3):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agents.base import TaskResult, default_out, register


def _post():
    from core.postprocess import PostProcessor
    from agents.common.tools.llm import LLMClient
    from agents.common.tools.config_loader import load_config
    return PostProcessor(load_config(), llm=LLMClient())


@register(name='post.tts', layer='post', desc='文本 → 配音 wav（Narrator 降级链）',
          inputs='{text, out_path?, voice?, speed?}')
def tts(p):
    from core.narration import Narrator
    narr = Narrator()
    out = p.get('out_path') or default_out('post.tts', 'voice', 'wav')
    ok = narr.say(p['text'], out, voice=p.get('voice'), speed=p.get('speed', 1.0))
    return TaskResult(ok=bool(ok) and os.path.isfile(out),
                      artifacts={'audio': out})


@register(name='post.compose', layer='post', desc='时间线 JSON → 成片（v10 compose 引擎）',
          inputs='{timeline(dict|json路径), out_path?}')
def compose(p):
    import json
    from agents.post.tools.compose import run_timeline
    tl = p['timeline']
    if isinstance(tl, str):
        tl = json.load(open(tl, encoding='utf-8'))
    out = run_timeline(tl, out=p.get('out_path'))
    return TaskResult(ok=os.path.isfile(out), artifacts={'video': out})


@register(name='post.lut', layer='post', desc='视频套用 LUT 风格',
          inputs='{video, lut(cinematic|warm|cool|vintage|vivid|soft), out_path?}')
def lut(p):
    from agents.post.tools.gen_luts import generate_cube
    style = p.get('lut') or p.get('style')
    out = p.get('out_path') or p['video']
    if out != p['video']:
        shutil.copy(p['video'], out)
    lut_dir = os.path.join(_ROOT, 'utils', 'luts')
    os.makedirs(lut_dir, exist_ok=True)
    lut_path = os.path.join(lut_dir, '%s.cube' % style)
    if not os.path.isfile(lut_path):
        generate_cube(style, 33, lut_path)
    ok = _post().apply_lut(out, lut_path)
    return TaskResult(ok=bool(ok), artifacts={'video': out})


@register(name='post.bgm', layer='post', desc='为视频加 BGM（mood 合成或指定文件）',
          inputs='{video, mood?|bgm_path?, out_path?}')
def bgm(p):
    from agents.post.tools.music import generate_bgm
    from agents.post.tools.ffmpeg_tools import get_duration
    video = p['video']
    out = p.get('out_path') or video
    if out != video:
        shutil.copy(video, out)
    path = p.get('bgm_path')
    if not path:
        path = os.path.splitext(out)[0] + '_bgm.wav'
        generate_bgm(p.get('mood', 'calm'), get_duration(out), path)
    ok = _post().add_bgm(out, path)
    return TaskResult(ok=bool(ok), artifacts={'video': out, 'bgm': path})


@register(name='post.subtitle_burn', layer='post', desc='烧录 SRT 字幕',
          inputs='{video, srt_path, out_path?}')
def subtitle_burn(p):
    video, srt = p['video'], p['srt_path']
    out = p.get('out_path') or video
    if out != video:
        shutil.copy(video, out)
    ok = _post().burn_subtitles(out, srt)
    return TaskResult(ok=bool(ok), artifacts={'video': out})


@register(name='post.stt', layer='post', desc='视频/音频 → Whisper 字幕 SRT',
          inputs='{video, srt_path?, language?}')
def stt(p):
    from agents.post.tools.stt import transcribe_to_srt
    src = p['video']
    srt = p.get('srt_path') or os.path.splitext(src)[0] + '.srt'
    got = transcribe_to_srt(src, srt, language=p.get('language', 'zh'))
    return TaskResult(ok=bool(got), artifacts={'srt': srt})


@register(name='post.fx', layer='post', desc='单镜 ffmpeg 特效（flash/glitch/zoom…）',
          inputs='{video, effect, out_path?, **kw}')
def fx(p):
    from agents.post.tools.effects import apply_effect
    src = p['video']
    out = p.get('out_path') or (os.path.splitext(src)[0] + '_fx.mp4')
    kw = {k: v for k, v in p.items() if k not in ('video', 'effect', 'out_path')}
    ok = apply_effect(src, out, effect=p['effect'], **kw)
    return TaskResult(ok=bool(ok), artifacts={'video': out})


@register(name='post.transition', layer='post', desc='两镜 xfade 转场拼接',
          inputs='{clip_a, clip_b, kind?, duration?, out_path?}')
def transition(p):
    from agents.post.tools.effects import transition as tfade
    out = p.get('out_path') or default_out('post.transition', 'merged')
    ok = tfade(p['clip_a'], p['clip_b'], out, kind=p.get('kind', 'fade'),
               duration=p.get('duration', 0.4))
    return TaskResult(ok=bool(ok), artifacts={'video': out})


@register(name='post.voice', layer='post',
          desc='配音师：多引擎配音（edge-*/cosy-*/克隆音色，失败自动降级）',
          inputs='{text, out_path?, voice?, speed?, prompt_wav?, prompt_text?}')
def voice(p):
    from agents.common.tools.tts import TTSClient
    from agents.common.tools.config_loader import load_config
    cfg = load_config()
    client = TTSClient(cfg)
    out = p.get('out_path') or default_out('post.voice', 'voice', 'wav')
    wanted = p.get('voice') or client.default_voice
    chain = [wanted]
    for fb in (cfg.get('tts', {}).get('fallback_voice'), 'cosy-default', 'edge-xiaoxiao'):
        if fb and fb not in chain:
            chain.append(fb)
    last_err = ''
    for v in chain:
        try:
            r = client.synthesize(p['text'], out, voice=v,
                                  speed=p.get('speed', 1.0),
                                  prompt_wav=p.get('prompt_wav'),
                                  prompt_text=p.get('prompt_text'))
            if r and os.path.isfile(out):
                score = None
                return TaskResult(ok=True, artifacts={'audio': out, 'voice': v})
            last_err = 'synthesize 无产物'
        except Exception as e:
            last_err = str(e)[:200]
    return TaskResult(ok=False, error='配音全部降级失败: %s' % last_err)


@register(name='post.pip', layer='post',
          desc='画中画：第二段视频等比缩小叠到主画面角上（可定时窗）',
          inputs='{video, overlay, out_path?, position?=br|bl|tr|tl|c, scale?=0.35, t0?, dur?}')
def pip(p):
    from agents.post.tools.effects import pip as _pip
    out = p.get('out_path') or (os.path.splitext(p['video'])[0] + '_pip.mp4')
    ok = _pip(p['video'], p['overlay'], out,
              position=p.get('position', 'br'), scale=float(p.get('scale', 0.35)),
              t0=float(p.get('t0', 0)), dur=p.get('dur'))
    return TaskResult(ok=bool(ok), artifacts={'video': out},
                      error='' if ok else 'pip 输出失败')


@register(name='post.edit', layer='post',
          desc='SAM2 编辑：分割/抠图/换底/打码/inpaint/彩色多物体（图）或视频传播（video）；YOLO 自动（yolo/classes）+ 框提示（box）+ 提示帧（frame）+ FLUX Fill 生成式重绘（engine=flux + prompt，v16.x M5）',
          inputs='{image|video, out_path?, point?="x,y x,y", box?="x1,y1,x2,y2", yolo?, classes?="cat,dog", conf?, frame?, op=segment|cutout|replace_bg|mosaic|inpaint|visualize|video, vop=mosaic|blur_bg|cutout|color, bg?, mode?, strength?, size?, engine?=cv|flux, prompt?, steps?, guidance?, controlnet?=canny, controlnet_strength?}')
def edit(p):
    from agents.post.tools import sam_edit as se
    import numpy as np
    from PIL import Image

    if p.get('video'):
        pts = se.parse_points(p.get('point') or '')
        boxes = se.parse_boxes(p.get('box') or '')
        if p.get('yolo'):
            import cv2
            probe = cv2.VideoCapture(p['video'])
            fr_idx = max(0, int(p.get('frame') or 0))
            probe.set(cv2.CAP_PROP_POS_FRAMES, fr_idx)
            ok, fr = probe.read()
            if not ok:
                return TaskResult(ok=False, error='提示帧读取失败（frame 超出视频帧数？）')
            dets = se.detect_objects(fr[:, :, ::-1],
                                     classes=[c for c in (p.get('classes') or '').split(',') if c] or None,
                                     conf=float(p.get('conf') or 0.25))
            boxes = [d[2] for d in dets]
            if not boxes:
                return TaskResult(ok=False, error='YOLO 未检出目标（调低 conf 或换 frame）')
        if not pts and not boxes:
            return TaskResult(ok=False, error='video 模式需要 point="x,y" / box="x1,y1,x2,y2" / yolo=true')
        out = p.get('out_path') or (os.path.splitext(p['video'])[0] + '_edit.mp4')
        if p.get('vop') == 'color':
            r = se.video_color(p['video'], out, pts, size=p.get('size', 'small'),
                               device=p.get('device', ''),
                               prompt_frame=int(p.get('frame') or 0),
                               boxes=boxes or None)
            return TaskResult(ok=True, artifacts={'video': r['output'],
                                                  'frames': r['frames'],
                                                  'objects': r['objects'], 'op': 'color'})
        r = se.video_edit(p['video'], out, pts, op=p.get('vop', 'mosaic'),
                          size=p.get('size', 'small'), device=p.get('device', ''),
                          mode=p.get('mode', 'pixel'), strength=int(p.get('strength', 16)),
                          prompt_frame=int(p.get('frame') or 0),
                          boxes=boxes or None)
        return TaskResult(ok=True, artifacts={'video': r['output'],
                                              'frames': r['frames'], 'op': r['op']})
    if not p.get('image'):
        return TaskResult(ok=False, error='需要 image（图路径）或 video（视频路径）')
    # M8 指令式编辑：整图自然语言修改，无需 SAM mask（Qwen-Image-Edit）
    if p.get('op') == 'instruct':
        if not p.get('prompt'):
            return TaskResult(ok=False, error='instruct 需要 prompt 编辑指令（如 把猫换成狗）')
        out = p.get('out_path') or (os.path.splitext(p['image'])[0] + '_instruct.png')
        se.qwen_edit(p['image'], p['prompt'], out,
                     steps=int(p.get('steps') or 20),
                     cfg=float(p.get('cfg') or 2.5))
        return TaskResult(ok=True, artifacts={'image': out, 'op': 'instruct'})
    img = np.array(Image.open(p['image']).convert('RGB'))
    pts = se.parse_points(p.get('point') or '')
    boxes = se.parse_boxes(p.get('box') or '')
    labels = None
    if p.get('yolo'):
        dets = se.detect_objects(img,
                                 classes=[c for c in (p.get('classes') or '').split(',') if c] or None,
                                 conf=float(p.get('conf') or 0.25))
        boxes = [d[2] for d in dets]
        labels = [d[0] for d in dets]
    out = p.get('out_path') or (os.path.splitext(p['image'])[0] + '_edit.png')
    if p.get('op') == 'visualize':
        if boxes:
            masks, scores, labels = se.segment_from_boxes(img, boxes, labels=labels,
                                                          size=p.get('size', 'small'),
                                                          device=p.get('device', ''))
        else:
            masks, scores = se.segment_multi(img, points=pts or None,
                                             size=p.get('size', 'small'),
                                             device=p.get('device', ''))
            labels = ['物体%d' % (i + 1) for i in range(len(masks))]
        se.visualize(img, masks, out, labels=labels)
        return TaskResult(ok=True, artifacts={'image': out, 'objects': len(masks),
                                              'scores': [round(s, 2) for s in scores]})
    if boxes:
        masks, scores, _ = se.segment_from_boxes(img, boxes, size=p.get('size', 'small'),
                                                 device=p.get('device', ''))
        if not masks:
            return TaskResult(ok=False, error='SAM2 框提示未产出掩膜')
        mask, score = masks[0], scores[0]
    else:
        mask, score = se.segment_image(img, points=pts or None, size=p.get('size', 'small'),
                                       device=p.get('device', ''))
    op = p.get('op', 'mosaic')
    out = p.get('out_path') or (os.path.splitext(p['image'])[0] + '_edit.png')
    if op == 'segment':
        Image.fromarray(mask.astype(np.uint8) * 255).save(out)
    elif op == 'cutout':
        se.cutout(img, mask, out)
    elif op == 'replace_bg':
        bg = p.get('bg') or ''
        if p.get('engine') == 'flux':
            se.inpaint_flux(img, mask, p.get('prompt') or 'clean empty background', out,
                            invert=True, steps=int(p.get('steps') or 30),
                            guidance=float(p.get('guidance') or 30.0))
        elif bg == 'blur':
            se.replace_bg(img, mask, out, blur=True)
        elif bg:
            c = bg.lstrip('#')
            col = tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) >= 6 else (16, 18, 27)
            se.replace_bg(img, mask, out, color=col)
        else:
            se.replace_bg(img, mask, out)
    elif op == 'mosaic':
        se.mosaic(img, mask, out, mode=p.get('mode', 'pixel'),
                  strength=int(p.get('strength', 16)))
    elif op == 'inpaint':
        if p.get('engine') == 'flux':
            if not p.get('prompt'):
                return TaskResult(ok=False, error='flux 引擎需要 prompt 描述重绘内容（如 empty wooden floor）')
            se.inpaint_flux(img, mask, p['prompt'], out, steps=int(p.get('steps') or 30),
                            guidance=float(p.get('guidance') or 30.0),
                            controlnet=p.get('controlnet') or '',
                            controlnet_strength=float(p.get('controlnet_strength') or 0.5))
        else:
            se.inpaint(img, mask, out)
    else:
        return TaskResult(ok=False, error=f'未知 op: {op}')
    return TaskResult(ok=True, artifacts={'image': out, 'mask_score': round(score, 3)})
