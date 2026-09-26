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

from agents.base import TaskResult, register


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
    out = p.get('out_path') or os.path.join(os.getcwd(), 'tts_%d.wav' % abs(hash(p['text']) % 10**8))
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
    out = p.get('out_path') or os.path.join(os.getcwd(), 'merged.mp4')
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
    out = p.get('out_path') or os.path.join(
        os.getcwd(), 'voice_%d.wav' % abs(hash(p['text']) % 10 ** 8))
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
