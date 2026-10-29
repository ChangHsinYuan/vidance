"""M6 档3 渲染 v2：根治 v1 三问题。

1. TTS 幻听 → 弃用 jieshuo1（参考文本泄漏），改 cosy-default（A/B 验证干净）
2. 衔接卡顿 → 长旁白镜头先慢放（≤2x，纪实感）+ 尾帧 Ken Burns 缓推替代死帧定格
              + 片间 xfade 0.5s 交叉溶解 + acrossfade 0.25s
3. 风格漂移 → 全局黑白纪实 STYLE；每镜先 FLUX 出同风格关键帧，一律 I2V（不再裸 T2V）

用法: python m6_render_v2.py [拆解json] [镜头号...]
输出: output/m6/v2/（kf/ 关键帧 clips/ 分镜 part/ 成品 kongyiji_v2.mp4）
幂等：各阶段产物存在即跳过。
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, '.')
from agents.generator.tools.comfy_api import ComfyClient
from core.narration import Narrator

BD = sys.argv[1] if len(sys.argv) > 1 else 'output/m6/breakdown_孔乙己.json'
SHOTS = [int(x) for x in sys.argv[2:]] or [1, 9, 11, 21, 24, 30, 34, 36]
VOICE = 'cosy-default'
STYLE = ('民国初年（1919年前后）浙江绍兴乡镇，黑白纪实影像，老照片胶片颗粒质感，'
         '自然光影，写实主义风格，photorealistic black and white film still, grainy')
MOTION = '缓慢平稳的固定机位微移，人物动作自然克制，节奏舒缓'
OUT = 'output/m6/v2'
KF = os.path.join(OUT, 'kf')
CLIPS = os.path.join(OUT, 'clips')
PARTS = os.path.join(OUT, 'part')
FINAL = os.path.join(OUT, 'kongyiji_v2.mp4')
for d in (KF, CLIPS, PARTS):
    os.makedirs(d, exist_ok=True)
W, H, FPS, FADE_V, FADE_A = 1280, 704, 24, 0.5, 0.25

bd = json.load(open(BD))
by_shot = {s['shot']: s for s in bd['storyboard']}
protagonist = bd['characters'][0]
protag_names = [protagonist['name'].split('（')[0], '孔乙己']

flux = ComfyClient(instance='flux')
wan = ComfyClient(instance='wan')
narr = Narrator()


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def probe_dur(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'csv=p=0', path], capture_output=True, text=True)
    return float(r.stdout.strip())


# ── 1) 每镜关键帧（FLUX，全局 STYLE；主角镜带人物 appearance）──
for n in SHOTS:
    s = by_shot[n]
    kf = os.path.join(KF, f'kf_{n:02d}.png')
    if os.path.isfile(kf):
        print(f'[关键帧] #{n} 已存在，跳过', flush=True)
        continue
    desc = s['visual']
    if any(nm in desc for nm in protag_names):
        desc = f'{protagonist["name"]}（{protagonist.get("appearance", "")}）。{desc}'
    prompt = f'{desc}。{STYLE}'
    print(f'[关键帧] #{n} {prompt[:56]}…', flush=True)
    flux.generate_flux_t2i(prompt, width=W, height=H, steps=20, guidance=3.5,
                           output_path=kf)
    print(f'[关键帧] #{n} ✓', flush=True)

# ── 2) 配音（cosy-default，无参考文本泄漏）──
wavs = {}
for n in SHOTS:
    wav = os.path.join(CLIPS, f'narr_{n:02d}.wav')
    if not os.path.isfile(wav):
        narr.say(by_shot[n].get('narration') or by_shot[n]['visual'], wav, voice=VOICE)
    wavs[n] = wav
    print(f'[TTS] #{n} ✓ ({probe_dur(wav):.1f}s)', flush=True)

# ── 3) 分镜视频：全部 I2V（关键帧首帧，风格 DNA 一致）──
for n in SHOTS:
    clip = os.path.join(CLIPS, f'shot_{n:02d}.mp4')
    if os.path.isfile(clip):
        print(f'[视频] #{n} 已存在，跳过', flush=True)
        continue
    kf = os.path.join(KF, f'kf_{n:02d}.png')
    prompt = f'{by_shot[n]["visual"]}。{MOTION}'
    print(f'[视频] #{n} I2V：{prompt[:50]}…', flush=True)
    wan.generate_i2v(prompt, kf, width=W, height=H, length=97, steps=20,
                     fps=FPS, output_path=clip)
    print(f'[视频] #{n} ✓', flush=True)

# ── 4) 单镜组装：慢放（≤2x）+ 尾段 Ken Burns 缓推 + 旁白对齐 ──
parts = []
for n in SHOTS:
    part = os.path.join(PARTS, f'part_{n:02d}.mp4')
    if os.path.isfile(part):
        parts.append(part)
        print(f'[组装] #{n} 已存在，跳过', flush=True)
        continue
    clip = os.path.join(CLIPS, f'shot_{n:02d}.mp4')
    wav = wavs[n]
    vdur, adur = probe_dur(clip), probe_dur(wav)
    target = adur + 0.4
    factor = min(2.0, target / vdur)
    slowed = os.path.join(PARTS, f'slow_{n:02d}.mp4')
    if not os.path.isfile(slowed):
        run(['ffmpeg', '-y', '-i', clip, '-vf',
             f'setpts=PTS*{factor:.4f},fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,'
             f'pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1', '-an',
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', slowed])
    vlen = probe_dur(slowed)
    rem = target - vlen
    # 尾段：>0.8s 用 Ken Burns 缓推；0-0.8s 简单冻结；负数裁到 target
    visual = os.path.join(PARTS, f'vis_{n:02d}.mp4')
    if rem > 0.8:
        still = os.path.join(PARTS, f'still_{n:02d}.mp4')
        if not os.path.isfile(still):
            last = os.path.join(PARTS, f'last_{n:02d}.png')
            run(['ffmpeg', '-y', '-sseof', '-0.2', '-i', slowed, '-update', '1',
                 '-frames:v', '1', last])
            frames = max(int(rem * FPS) + 1, 2)
            run(['ffmpeg', '-y', '-loop', '1', '-i', last, '-t', f'{rem:.3f}', '-vf',
                 f"zoompan=z='min(1+0.0011*on,1.14)':d={frames}:"
                 f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}",
                 '-r', str(FPS), '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
                 '-pix_fmt', 'yuv420p', still])
        run(['ffmpeg', '-y', '-i', slowed, '-i', still, '-filter_complex',
             f'[0:v]fps={FPS}[a];[1:v]fps={FPS}[b];'
             f'[a][b]xfade=transition=fade:duration=0.4:offset={max(vlen - 0.4, 0.05):.3f}',
             '-r', str(FPS), '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', visual])
        vlen_total = probe_dur(visual)
    elif rem > 0:
        run(['ffmpeg', '-y', '-i', slowed, '-vf',
             f'tpad=stop_mode=clone:stop_duration={rem + 0.2:.2f},fps={FPS}',
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', visual])
        vlen_total = probe_dur(visual)
    else:
        visual = slowed
        vlen_total = vlen
    part_dur = max(vlen_total, target)
    run(['ffmpeg', '-y', '-i', visual, '-i', wav, '-filter_complex',
         '[1:a]apad=pad_dur=1[a]', '-map', '0:v', '-map', '[a]', '-t', f'{part_dur:.3f}',
         '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
         '-c:a', 'aac', '-b:a', '128k', '-ar', '44100', part])
    parts.append(part)
    print(f'[组装] #{n} ✓ 慢放{factor:.2f}x 视频{vlen_total:.1f}s 旁白{adur:.1f}s '
          f'单镜{part_dur:.1f}s', flush=True)

# ── 5) 拼装：xfade 交叉溶解 + acrossfade，首尾黑场淡入淡出 ──
durs = [probe_dur(p) for p in parts]
inputs = []
for p in parts:
    inputs += ['-i', p]
fc = []
# 视频链
acc_len = durs[0]
prev = '[0:v]'
for i in range(1, len(parts)):
    off = acc_len - FADE_V
    out = f'[v{i}]'
    fc.append(f'{prev}[{i}:v]xfade=transition=fade:duration={FADE_V}:offset={off:.3f}{out}')
    acc_len = off + durs[i]
    prev = out
# 音频链
aprev = '[0:a]'
for i in range(1, len(parts)):
    aout = f'[a{i}]'
    fc.append(f'{aprev}[{i}:a]acrossfade=d={FADE_A}{aout}')
    aprev = aout
total = acc_len
fc.append(f'{prev}fade=t=in:st=0:d=0.6,fade=t=out:st={total - 1.0:.3f}:d=1.0[vf]')
fc.append(f'{aprev}afade=t=in:st=0:d=0.3,afade=t=out:st={total - 0.8:.3f}:d=0.8[af]')
lst = os.path.join(PARTS, 'fc.txt')
open(lst, 'w').write(';'.join(fc))
if os.path.isfile(FINAL):
    os.remove(FINAL)
run(['ffmpeg', '-y', '-loglevel', 'error'] + inputs +
    ['-filter_complex_script', lst, '-map', '[vf]', '-map', '[af]',
     '-r', str(FPS), '-c:v', 'libx264', '-preset', 'medium', '-crf', '19',
     '-pix_fmt', 'yuv420p', '-profile:v', 'high',
     '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', FINAL])
print(f'\n✓ 成片 {FINAL}（{probe_dur(FINAL):.1f}s，{len(parts)} 镜，xfade {FADE_V}s）',
      flush=True)
