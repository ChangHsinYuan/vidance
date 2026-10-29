"""M6 档3 渲染原型：拆解 JSON → 定妆照 → 关键分镜视频 → 配音 → 拼装。

用法: python m6_render_test.py [拆解json] [镜头号...]
默认: breakdown_孔乙己.json + 关键 8 镜（1 9 11 21 24 30 34 36）
输出: output/m6/{portrait_孔乙己.png, clips/, kongyiji_proto.mp4}
特性: 幂等（已有 clip/wav 跳过），可中断续跑
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, '.')
from agents.generator.tools.comfy_api import ComfyClient
from core.narration import Narrator

BD = sys.argv[1] if len(sys.argv) > 1 else 'output/m6/breakdown_孔乙己.json'
SHOTS = [int(x) for x in sys.argv[2:]] or [1, 9, 11, 21, 24, 30, 34, 36]
OUT = 'output/m6'
CLIPS = os.path.join(OUT, 'clips')
PORTRAIT = os.path.join(OUT, 'portrait_孔乙己.png')
FINAL = os.path.join(OUT, 'kongyiji_proto.mp4')
os.makedirs(CLIPS, exist_ok=True)

bd = json.load(open(BD))
by_shot = {s['shot']: s for s in bd['storyboard']}
protagonist = bd['characters'][0]  # 孔乙己

flux = ComfyClient(instance='flux')
wan = ComfyClient(instance='wan')
narr = Narrator()

# 1) 定妆照（人物卡 appearance；已有跳过）
if not os.path.isfile(PORTRAIT):
    app = protagonist.get('appearance', '')
    p_prompt = (f"民国初年江南小镇酒馆内，{protagonist['name']}：{app}。"
                "站在曲尺形大柜台外，写实主义电影剧照，冷灰色调，柔和顶光，胶片质感")
    print(f'[定妆照] {p_prompt[:60]}…', flush=True)
    flux.generate_flux_t2i(p_prompt, width=1024, height=1024,
                           output_path=PORTRAIT)
    print('[定妆照] ✓', PORTRAIT, flush=True)
else:
    print('[定妆照] 已存在，跳过', flush=True)

# 2) 逐镜：TTS + T2V（无主角）/ I2V（有主角，定妆照做首帧）
todo = []
for n in SHOTS:
    s = by_shot[n]
    wav = os.path.join(CLIPS, f'narr_{n:02d}.wav')
    if not os.path.isfile(wav):
        narr.say(s.get('narration') or s['visual'], wav, voice='cosy-jieshuo1')
    print(f'[TTS] #{n} ✓', flush=True)
    todo.append((n, s, wav))

for n, s, wav in todo:
    clip = os.path.join(CLIPS, f'shot_{n:02d}.mp4')
    if os.path.isfile(clip):
        print(f'[视频] #{n} 已存在，跳过', flush=True)
        continue
    visual = s['visual']
    has_protag = protagonist['name'].split('（')[0] in visual or '孔乙己' in visual
    motion = '缓慢镜头运动，人物自然动作，电影感，民国初年江南小镇酒馆'
    if has_protag and os.path.isfile(PORTRAIT):
        print(f'[视频] #{n} I2V（定妆照首帧）：{visual[:50]}…', flush=True)
        r = wan.generate_i2v(f'{visual}。{motion}', PORTRAIT,
                             length=97, steps=20, output_path=clip)
    else:
        print(f'[视频] #{n} T2V：{visual[:50]}…', flush=True)
        r = wan.generate_t2v(f'{visual}。{motion}',
                             length=97, steps=20, output_path=clip)
    print(f'[视频] #{n} ✓ ({r["video_path"]})', flush=True)

# 3) 每镜：视频 tpad 冻结尾帧到旁白长度 → 统一 1280x704/24fps → concat
parts = []
for n in SHOTS:
    wav = os.path.join(CLIPS, f'narr_{n:02d}.wav')
    clip = os.path.join(CLIPS, f'shot_{n:02d}.mp4')
    part = os.path.join(CLIPS, f'part_{n:02d}.mp4')
    if not os.path.isfile(part):
        subprocess.run([
            'ffmpeg', '-y', '-loglevel', 'error', '-i', clip, '-i', wav,
            '-filter_complex',
            '[0:v]scale=1280:704:force_original_aspect_ratio=decrease,'
            'pad=1280:704:(ow-iw)/2:(oh-ih)/2,fps=24,'
            'tpad=stop_mode=clone:stop_duration=12[v]',
            '-map', '[v]', '-map', '1:a', '-shortest',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
            '-c:a', 'aac', '-b:a', '128k', part], check=True)
    parts.append(part)
    print(f'[拼装] part #{n} ✓', flush=True)

lst = os.path.join(CLIPS, 'concat.txt')
with open(lst, 'w') as f:
    for p in parts:
        f.write(f"file '{os.path.abspath(p)}'\n")
subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat',
                '-safe', '0', '-i', lst, '-c', 'copy', FINAL], check=True)
d = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                    '-of', 'csv=p=0', FINAL], capture_output=True, text=True).stdout.strip()
print(f'\n✓ 成片 {FINAL}（{float(d):.1f}s，{len(parts)} 镜）', flush=True)
