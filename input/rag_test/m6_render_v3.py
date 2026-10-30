"""M6 渲染 v3：根治图片-旁白不对齐 + Windows 兼容 + 字幕 + prompt 可追溯。

v2→v3 变更：
1. 图片对齐：FLUX 中文理解弱（v2 跑偏根因）→ LLM 把每镜 visual 翻译成精准英文
   FLUX prompt（景别映射+本镜状态优先），关键帧全程英文出图
2. Windows 播放：终拼强制 -pix_fmt yuv420p -profile:v high（v2 是 yuv444p 放不了）
3. 字幕：按各镜实际时长生成 SRT，Noto Sans CJK SC 烧录
4. 可追溯：output/m6/v3/prompts.md 落盘全部 prompt

用法: python m6_render_v3.py
输出: output/m6/v3/{kf/,clips/,part/,subs.srt,kf_contact.jpg,prompts.md,kongyiji_v3.mp4}
幂等：各阶段产物存在即跳过。TTS 复用 v2 的 cosy-default 音频。
"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, '.')
from agents.generator.tools.comfy_api import ComfyClient
from core.narration import Narrator

BD = 'output/m6/breakdown_孔乙己.json'
# M6_ALL=1 → 全量渲染（拆解里全部镜头）；默认 8 关键镜子集
SHOTS = ([1, 9, 11, 21, 24, 30, 34, 36] if not os.environ.get('M6_ALL')
         else None)  # by_shot 加载后回填
VOICE = 'cosy-default'
STYLE_EN = ('1910s rural Zhejiang China, vintage black and white documentary photo, '
            'grainy film texture, soft natural window light, photorealistic, '
            'early republican era Chinese tavern interior, realistic period detail')
MOTION_EN = 'very subtle slow camera drift, minimal natural human motion, calm pacing'
OUT = 'output/m6/v3'
KF, CLIPS, PARTS = (os.path.join(OUT, d) for d in ('kf', 'clips', 'part'))
FINAL = os.path.join(OUT, 'kongyiji_v3.mp4')
SRT = os.path.join(OUT, 'subs.srt')
V2_CLIPS = 'output/m6/v2/clips'
for d in (KF, CLIPS, PARTS):
    os.makedirs(d, exist_ok=True)
W, H, FPS, FADE_V, FADE_A = 1280, 704, 24, 0.5, 0.25
SIZE_EN = {'远景': 'wide establishing shot', '全景': 'full shot', '中景': 'medium shot',
           '近景': 'medium close-up', '特写': 'extreme close-up'}

bd = json.load(open(BD))
by_shot = {s['shot']: s for s in bd['storyboard']}
if SHOTS is None:
    SHOTS = sorted(by_shot)  # M6_ALL=1：全量镜头
protagonist = bd['characters'][0]
flux = ComfyClient(instance='flux')
wan = ComfyClient(instance='wan')
narr = Narrator()


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def probe_dur(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'csv=p=0', path], capture_output=True, text=True)
    return float(r.stdout.strip())


# ── A) LLM 翻译：中文 visual → 英文 FLUX prompt（增量：缓存命中跳过，缺的镜补翻译）──
PROMPTS_EN = os.path.join(KF, 'prompts_en.json')
en_map = {}
if os.path.isfile(PROMPTS_EN):
    en_map = {int(k): v for k, v in json.load(open(PROMPTS_EN)).items()}  # JSON 键是字符串
missing = [n for n in SHOTS if n not in en_map]
if not missing:
    print(f'[翻译] 缓存齐全（{len(en_map)} 镜），跳过', flush=True)
else:
    from agents.common.tools.llm import LLMClient
    lc = LLMClient()
    items = []
    for n in missing:
        s = by_shot[n]
        items.append({'shot': n, 'size': SIZE_EN.get(s.get('size', ''), 'medium shot'),
                      'visual': s['visual']})
    sys_p = (
        '你是分镜美术指导。把每个镜头的中文画面描述改写成一句精准的英文 FLUX 文生图 prompt。\n'
        '规则：\n'
        '1. 只描述该镜头画面里可见的内容（人物姿态/服饰/环境/光线/构图），忠实原文\n'
        '2. size 字段给出景别，prompt 开头体现景别\n'
        '3. 该镜头里人物的状态以 visual 为准（如后期"黑瘦/破夹袄/坐蒲包"必须体现，'
        '不要套用早期形象"高大/穿长衫"）\n'
        '4. 每条 35-60 词，具象名词优先，不要抽象词，不要相机参数\n'
        f'输出 JSON: {{"prompts": [{{"shot": 1, "prompt": "..."}}, ...]}}，只输出 JSON')
    usr = json.dumps({'style_suffix': STYLE_EN, 'shots': items},
                     ensure_ascii=False, indent=1)
    msgs = [{'role': 'system', 'content': sys_p},
            {'role': 'user', 'content': usr}]
    print(f'[翻译] {len(missing)}/{len(SHOTS)} 镜需补翻译（流式）…', flush=True)
    for attempt in range(3):
        try:
            text = lc.chat_stream(msgs, model=lc.models['script'], temperature=0.2,
                                  max_tokens=8192, timeout=1800)
            r = lc._extract_json(text)
            new_map = {int(p['shot']): p['prompt'] for p in r['prompts']}
            assert set(new_map) == set(missing), f'镜头号不齐: 缺{sorted(set(missing)-set(new_map))} 多{sorted(set(new_map)-set(missing))}'
            en_map.update(new_map)
            break
        except Exception as e:
            print(f'[翻译] 第 {attempt + 1} 次失败: {e}', flush=True)
            if attempt == 2:
                raise
    json.dump(en_map, open(PROMPTS_EN, 'w'), ensure_ascii=False, indent=1)
    print(f'[翻译] ✓ {PROMPTS_EN}（共 {len(en_map)} 镜）', flush=True)

# ── B) 关键帧（英文 prompt + STYLE_EN）──
kf_prompts = {}
for n in SHOTS:
    kf = os.path.join(KF, f'kf_{n:02d}.png')
    p = f"{en_map[n]}, {STYLE_EN}"
    kf_prompts[n] = p
    if os.path.isfile(kf):
        print(f'[关键帧] #{n} 已存在，跳过', flush=True)
        continue
    print(f'[关键帧] #{n} {p[:70]}…', flush=True)
    flux.generate_flux_t2i(p, width=W, height=H, steps=20, guidance=3.5, output_path=kf)
    print(f'[关键帧] #{n} ✓', flush=True)

# ── C) 关键帧拼贴图（人工速查）──
contact = os.path.join(OUT, 'kf_contact.jpg')
if not os.path.isfile(contact):
    try:
        from PIL import Image, ImageDraw
        tw, th = 640, 352
        rows = (len(SHOTS) + 1) // 2  # 动态行数（每行 2 镜）
        sheet = Image.new('RGB', (tw * 2, th * rows), 'black')
        dr = ImageDraw.Draw(sheet)
        for i, n in enumerate(SHOTS):
            im = Image.open(os.path.join(KF, f'kf_{n:02d}.png')).resize((tw, th))
            x, y = (i % 2) * tw, (i // 2) * th
            sheet.paste(im, (x, y))
            dr.rectangle([x + 8, y + 8, x + 130, y + 44], fill='black')
            dr.text((x + 16, y + 14), f'#{n}', fill='white')
        sheet.save(contact, quality=88)
        print(f'[拼贴] ✓ {contact}', flush=True)
    except Exception as e:
        print(f'[拼贴] 跳过（{e}）', flush=True)

# ── D) 配音：复用 v2 cosy-default 音频 ──
wavs = {}
for n in SHOTS:
    wav = os.path.join(CLIPS, f'narr_{n:02d}.wav')
    src = os.path.join(V2_CLIPS, f'narr_{n:02d}.wav')
    if not os.path.isfile(wav):
        if os.path.isfile(src):
            shutil.copy(src, wav)
            print(f'[TTS] #{n} 复用 v2', flush=True)
        else:
            narr.say(by_shot[n].get('narration') or by_shot[n]['visual'], wav, voice=VOICE)
            print(f'[TTS] #{n} ✓ 新合成', flush=True)
    wavs[n] = wav

# ── E) 分镜 I2V（新关键帧）──
i2v_prompts = {}
for n in SHOTS:
    clip = os.path.join(CLIPS, f'shot_{n:02d}.mp4')
    i2v_prompts[n] = f"{by_shot[n]['visual']}。{MOTION_EN}"
    if os.path.isfile(clip):
        print(f'[视频] #{n} 已存在，跳过', flush=True)
        continue
    kf = os.path.join(KF, f'kf_{n:02d}.png')
    print(f'[视频] #{n} I2V…', flush=True)
    wan.generate_i2v(i2v_prompts[n], kf, width=W, height=H, length=97, steps=20,
                     fps=FPS, output_path=clip)
    print(f'[视频] #{n} ✓', flush=True)

# ── F) 单镜组装（慢放 + Ken Burns + 对齐旁白）──
parts = []
for n in SHOTS:
    part = os.path.join(PARTS, f'part_{n:02d}.mp4')
    if os.path.isfile(part):
        parts.append(part)
        print(f'[组装] #{n} 已存在', flush=True)
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
             '-r', str(FPS), '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
             '-pix_fmt', 'yuv420p', visual])
    elif rem > 0:
        run(['ffmpeg', '-y', '-i', slowed, '-vf',
             f'tpad=stop_mode=clone:stop_duration={rem + 0.2:.2f},fps={FPS}',
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
             visual])
    else:
        visual = slowed
    vlen_total = probe_dur(visual)
    part_dur = max(vlen_total, target)
    run(['ffmpeg', '-y', '-i', visual, '-i', wav, '-filter_complex',
         '[1:a]apad=pad_dur=1[a]', '-map', '0:v', '-map', '[a]', '-t', f'{part_dur:.3f}',
         '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-b:a', '128k', '-ar', '44100', part])
    parts.append(part)
    print(f'[组装] #{n} ✓ 慢放{factor:.2f}x 单镜{part_dur:.1f}s', flush=True)

# ── G) 字幕 SRT（按实际时间轴）──
durs = [probe_dur(p) for p in parts]


def fmt_ts(t):
    hh, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f'{hh:02d}:{m:02d}:{s:06.3f}'.replace('.', ',')


def wrap_cjk(text, width=18):
    return '\\N'.join(text[i:i + width] for i in range(0, len(text), width))


srt_lines, starts = [], []
acc = 0.0
for i, n in enumerate(SHOTS):
    starts.append(acc)
    acc += durs[i] - (FADE_V if i < len(SHOTS) - 1 else 0)
for i, n in enumerate(SHOTS):
    st = starts[i] + 0.25
    en = starts[i] + durs[i] - (FADE_V + 0.15 if i < len(SHOTS) - 1 else 0.4)
    txt = wrap_cjk(by_shot[n].get('narration') or by_shot[n]['visual'])
    srt_lines += [str(i + 1), f'{fmt_ts(st)} --> {fmt_ts(en)}', txt, '']
open(SRT, 'w').write('\n'.join(srt_lines))
print(f'[字幕] ✓ {SRT}', flush=True)

# ── H) 终拼：xfade + acrossfade + 烧字幕 + yuv420p ──
inputs = []
for p in parts:
    inputs += ['-i', p]
fc = []
acc_len = durs[0]
prev = '[0:v]'
for i in range(1, len(parts)):
    off = acc_len - FADE_V
    out = f'[v{i}]'
    fc.append(f'{prev}[{i}:v]xfade=transition=fade:duration={FADE_V}:offset={off:.3f}{out}')
    acc_len = off + durs[i]
    prev = out
aprev = '[0:a]'
for i in range(1, len(parts)):
    aout = f'[a{i}]'
    fc.append(f'{aprev}[{i}:a]acrossfade=d={FADE_A}{aout}')
    aprev = aout
total = acc_len
srt_esc = SRT.replace('\\', '/').replace(':', '\\:')
fc.append(f'{prev}fade=t=in:st=0:d=0.6,fade=t=out:st={total - 1.0:.3f}:d=1.0[vpre]')
fc.append(f"[vpre]subtitles=filename='{srt_esc}':fontsdir=/usr/share/fonts/opentype/noto:"
          "force_style='FontName=Noto Sans CJK SC Bold,FontSize=15,"
          "PrimaryColour=&Hffffff,OutlineColour=&H000000,BorderStyle=1,Outline=1.3,"
          "Shadow=0.6,MarginV=26'[vf]")
fc.append(f'{aprev}afade=t=in:st=0:d=0.3,afade=t=out:st={total - 0.8:.3f}:d=0.8[af]')
lst = os.path.join(PARTS, 'fc.txt')
open(lst, 'w').write(';'.join(fc))
if os.path.isfile(FINAL):
    os.remove(FINAL)
run(['ffmpeg', '-y', '-loglevel', 'error'] + inputs +
    ['-filter_complex_script', lst, '-map', '[vf]', '-map', '[af]',
     '-r', str(FPS), '-c:v', 'libx264', '-preset', 'medium', '-crf', '19',
     '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-level', '4.1',
     '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', FINAL])
print(f'\n✓ 成片 {FINAL}（{probe_dur(FINAL):.1f}s，{len(parts)} 镜，字幕+yuv420p）',
      flush=True)

# ── I) prompt 清单落盘 ──
md = ['# 孔乙己 v3 渲染 prompt 清单', '',
      f'- 拆解源: `{BD}`（shot.visual=画面描述，shot.narration=旁白/字幕）',
      f'- 关键帧 STYLE（全镜统一）: `{STYLE_EN}`',
      f'- I2V 运镜 MOTION: `{MOTION_EN}`',
      f'- 关键帧英文翻译（LLM 从 visual 生成）: `{PROMPTS_EN}`',
      f'- TTS: {VOICE}（cosy-default，无参考文本泄漏）', '',
      '| 镜 | 景别 | 关键帧 EN prompt | 旁白（字幕） | I2V prompt | 单镜时长 |',
      '|---|---|---|---|---|---|']
for i, n in enumerate(SHOTS):
    s = by_shot[n]
    md.append(f"| #{n} | {s.get('size', '')} | {kf_prompts[n]} | "
              f"{(s.get('narration') or '')[:60]} | {i2v_prompts[n][:60]} | {durs[i]:.1f}s |")
md += ['', '## 工程参数', '',
       f'- 分辨率 {W}x{H}@{FPS}fps， pix_fmt yuv420p / h264 High@4.1（Windows 兼容）',
       f'- 片间 xfade {FADE_V}s + acrossfade {FADE_A}s，首尾淡入淡出',
       '- 长旁白镜头慢放 ≤2x + 尾段 Ken Burns 缓推（替代死帧定格）',
       '- 字幕 Noto Sans CJK SC Bold 15px 白字黑边，按实际时间轴烧录']
open(os.path.join(OUT, 'prompts.md'), 'w').write('\n'.join(md))
print(f'[清单] ✓ {OUT}/prompts.md', flush=True)
