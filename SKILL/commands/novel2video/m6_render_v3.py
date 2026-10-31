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
import random
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
# M6_OUT=v4 可覆盖输出目录（v18 对照渲染不覆盖 v17 证据）；裸名视为 output/m6/ 下的子目录
_m6_out = os.environ.get('M6_OUT', 'output/m6/v3')
OUT = _m6_out if '/' in _m6_out else f'output/m6/{_m6_out}'
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

# ── M4) 世界观注入：world.style → 英译缓存 → STYLE_EN 叠加；taboos 打印+落盘 ──
WORLD_JSON = BD.replace('breakdown_', 'world_')
world = bd.get('world') or {}
if world:
    if os.path.isfile(WORLD_JSON):
        world_en = json.load(open(WORLD_JSON))
    else:
        from agents.common.tools.llm import LLMClient
        wc = LLMClient()
        world_en = wc.chat_json(
            [{'role': 'system', 'content':
                '你是美术指导。把中文世界观设定译成英文 FLUX 风格短语（style 字段，逗号分隔的'
                '具象名词短语，含时代/地域/色调/质感）+ 全局禁则译成英文负面提示短语列表'
                '（taboos_en，每条一串逗号短语）。只输出 JSON：{"style_en":..., "taboos_en":[...]}。'},
             {'role': 'user', 'content': json.dumps(world, ensure_ascii=False)}],
            temperature=0.3)
        json.dump(world_en, open(WORLD_JSON, 'w'), ensure_ascii=False, indent=1)
        print(f'[world] ✓ 注册表落盘 {WORLD_JSON}', flush=True)
    STYLE_EN = f'{STYLE_EN}, {world_en["style_en"]}'
    print(f'[world] STYLE_EN += {world_en["style_en"][:80]}…', flush=True)
    for t in world.get('taboos', []):
        print(f'[world] 禁则: {t}', flush=True)

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


def flf_generate(out_clip, first_png, last_png, ctrl_mp4, prompt):
    """v18 M2：VACE 首尾帧驱动（control_video 序列=首帧→xfade→尾帧），832x480@16fps。"""
    comfy_input = '/mnt/disk_sdb/zxy/ComfyUI/input'
    os.makedirs(comfy_input, exist_ok=True)
    ctrl_name = os.path.basename(ctrl_mp4)
    shutil.copy(ctrl_mp4, os.path.join(comfy_input, ctrl_name))
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.1_vace_1.3B_fp16.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "4": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 8.0}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": NEG_EN, "clip": ["2", 0]}},
        "20": {"class_type": "LoadVideo", "inputs": {"file": ctrl_name}},
        "21": {"class_type": "GetVideoComponents", "inputs": {"video": ["20", 0]}},
        "8": {"class_type": "WanVaceToVideo", "inputs": {"positive": ["5", 0], "negative": ["6", 0],
                                                         "vae": ["3", 0], "width": FLF_W, "height": FLF_H,
                                                         "length": FLF_LEN, "batch_size": 1, "strength": 1.0,
                                                         "control_video": ["21", 0]}},
        "11": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "seed": random.randint(0, 2**31), "steps": 25, "cfg": 5.0,
                                                    "sampler_name": "uni_pc", "scheduler": "simple",
                                                    "positive": ["8", 0], "negative": ["8", 1],
                                                    "latent_image": ["8", 2], "denoise": 1.0}},
        "12": {"class_type": "VAEDecode", "inputs": {"samples": ["11", 0], "vae": ["3", 0]}},
        "13": {"class_type": "CreateVideo", "inputs": {"images": ["12", 0], "fps": FLF_FPS}},
        "14": {"class_type": "SaveVideo", "inputs": {"video": ["13", 0], "filename_prefix": "vidance/m6_flf",
                                                     "format": "mp4", "codec": "auto"}},
    }
    if not wan.wait_ready(timeout=60):
        raise RuntimeError('ComfyUI wan not ready')
    pid = wan.queue_prompt(wf)
    outs = wan.wait_result(pid)
    info = (outs.get('14', {}).get('videos') or outs.get('14', {}).get('images', [{}]))[0]
    if not info or not info.get('filename'):
        raise RuntimeError(f'FLF 无视频产出: {outs}')
    wan.download_file(info['filename'], info.get('subfolder', ''), info.get('type', 'output'), out_clip)


# ── A0) v18 一致性资产：场景锚段 + 衣橱段 + 镜头 prompt 组装器 ──
# 场景段：同场景跨镜逐字复用 anchor_en（v18 拆解）；旧拆解无该字段 → 回退空段（行为同 v17）
SCENE_ANCHOR = {s['id']: s.get('anchor_en') for s in bd.get('scenes', []) if s.get('anchor_en')}
# 衣橱：角色 → [(name, desc, stages)]；stages 归一为区间列表（兼容 [起,止] 与 [[起,止],…] 两种 LLM 形态）
def _norm_stages(st, n_shots):
    if not isinstance(st, list) or not st:
        return [(0, 10 ** 6)]
    # 嵌套形态 [[8,28],[30,34]] 或混合
    if isinstance(st[0], list):
        out = []
        for iv in st:
            if isinstance(iv, list) and len(iv) == 2 and all(isinstance(x, int) for x in iv):
                out.append((iv[0], iv[1]))
        return out or [(0, 10 ** 6)]
    # 扁平形态 [8,28]
    if len(st) == 2 and all(isinstance(x, int) for x in st):
        return [(st[0], st[1])]
    # 事件标签（字符串）或畸形 → 全区间兜底
    return [(0, 10 ** 6)]


WARDROBE = {}
for _c in bd.get('characters', []):
    _lst = []
    for _co in (_c.get('costumes') or []):
        _lst.append((_co.get('name', ''), _co.get('desc', ''),
                     _norm_stages(_co.get('stages'), len(by_shot))))
    WARDROBE[_c.get('name', '')] = _lst


def costume_for(shot_n, char_name):
    """镜头 n 时角色的当前造型（区间命中；多个命中取镜号上限最大者=最新状态）。"""
    hit = None
    for name, desc, ivs in WARDROBE.get(char_name, []):
        if any(lo <= shot_n <= hi for lo, hi in ivs):
            # 命中多个造型时取区间最窄者（最具体），并列取后者
            span = min(hi - lo for lo, hi in ivs if lo <= shot_n <= hi)
            if hit is None or span <= hit[0]:
                hit = (span, (name, desc))
    return hit[1] if hit else None


def build_shot_prompt(shot_n):
    """v18 prompt 组装：景别 + 场景锚段（逐字复用）+ 服装段 + 翻译增量。

    旧拆解（无 anchor_en/costumes）→ 两段为空，输出与 v17 翻译产物一致（向后兼容）。
    服装段英文走 KF/costumes_en.json 缓存（键=造型名），重跑零 LLM 调用。
    """
    s = by_shot[shot_n]
    parts = [SIZE_EN.get(s.get('size', ''), 'medium shot')]
    anchor = SCENE_ANCHOR.get(s.get('scene'))
    if anchor:
        parts.append(anchor)
    co = costume_for(shot_n, protagonist.get('name', ''))
    if co:
        co_en = _costume_en(co)
        if co_en:
            parts.append(co_en)
    parts.append(en_map[shot_n])
    return ', '.join(p for p in parts if p)


_COSTUME_EN_FILE = os.path.join(KF, 'costumes_en.json')
_COSTUME_EN = {}
if os.path.isfile(_COSTUME_EN_FILE):
    _COSTUME_EN = json.load(open(_COSTUME_EN_FILE))


def _costume_en(co):
    """造型 (name, desc) → 英文服装段（缓存命中零调用；LLM 失败回退中文原文不阻塞）。"""
    name, desc = co
    if name in _COSTUME_EN:
        return _COSTUME_EN[name]
    try:
        from agents.common.tools.llm import LLMClient
        en = LLMClient().optimize_character_prompt(desc)
        en = en.replace('standing upright on the ground, full body, front view, '
                        'plain white background, high detail, character reference sheet',
                        '').strip().rstrip(',')
        _COSTUME_EN[name] = en
        json.dump(_COSTUME_EN, open(_COSTUME_EN_FILE, 'w'), ensure_ascii=False, indent=1)
        print(f'[衣橱] 造型英译缓存 {name}: {en[:60]}…', flush=True)
        return en
    except Exception as e:
        print(f'[衣橱] ⚠ 造型 {name} 英译失败（{e}），回退中文描述', flush=True)
        return desc


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

# ── B) 关键帧（英文 prompt + STYLE_EN；v18=组装器产物，旧拆解回退纯翻译）──
kf_prompts = {}
for n in SHOTS:
    kf = os.path.join(KF, f'kf_{n:02d}.png')
    p = build_shot_prompt(n) if SCENE_ANCHOR or WARDROBE.get(protagonist.get('name', '')) \
        else f"{en_map[n]}, {STYLE_EN}"
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

# ── E) 分镜 I2V（新关键帧）；M6_FLF=1 走 VACE 首尾帧驱动（v18 M2，832x480@16fps 组装段自适配）──
FLF = bool(os.environ.get('M6_FLF'))
FLF_FPS, FLF_LEN, FLF_W, FLF_H, FLF_XFADE = 16, 81, 832, 480, 1.2
NEG_EN = ('blurry, low quality, distorted, extra limbs, text, watermark, '
          'static image, no motion')
i2v_prompts = {}
for n in SHOTS:
    clip = os.path.join(CLIPS, f'shot_{n:02d}.mp4')
    i2v_prompts[n] = f"{by_shot[n]['visual']}。{MOTION_EN}"
    if os.path.isfile(clip):
        print(f'[视频] #{n} 已存在，跳过', flush=True)
        continue
    kf = os.path.join(KF, f'kf_{n:02d}.png')
    if FLF:
        nxt = SHOTS[SHOTS.index(n) + 1] if SHOTS.index(n) + 1 < len(SHOTS) else n
        kf_last = os.path.join(KF, f'kf_{nxt:02d}.png')
        ctrl = os.path.join(PARTS, f'ctrl_{n:02d}.mp4')
        if not os.path.isfile(ctrl):
            run(['ffmpeg', '-y', '-loglevel', 'error',
                 '-loop', '1', '-t', '2.0', '-i', kf,
                 '-loop', '1', '-t', '3.1', '-i', kf_last,
                 '-filter_complex',
                 f'[0:v]scale={FLF_W}:{FLF_H}:force_original_aspect_ratio=increase,'
                 f'crop={FLF_W}:{FLF_H},setsar=1,fps={FLF_FPS}[a];'
                 f'[1:v]scale={FLF_W}:{FLF_H}:force_original_aspect_ratio=increase,'
                 f'crop={FLF_W}:{FLF_H},setsar=1,fps={FLF_FPS}[b];'
                 f'[a][b]xfade=transition=fade:duration={FLF_XFADE}:offset=1.9,'
                 f'trim=duration={FLF_LEN / FLF_FPS:.3f}[v]',
                 '-map', '[v]', '-pix_fmt', 'yuv420p', '-c:v', 'libx264', ctrl])
        last_png = kf_last if nxt != n else kf
        print(f'[视频] #{n} FLF(VACE 首帧#{n}→尾帧#{nxt})…', flush=True)
        flf_generate(clip, kf, last_png, ctrl, i2v_prompts[n])
        print(f'[视频] #{n} ✓ FLF', flush=True)
        continue
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
                 f"zoompan=z='min(1+{0.0005 if FLF else 0.0011}*on,{1.06 if FLF else 1.14})':d={frames}:"
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

# ── H) 终拼：xfade（v18：transition_out 按镜选型，旧拆解回退 fade）+ acrossfade + 烧字幕 + yuv420p ──
# xfade 可用 kind 白名单（v5 effects 库对齐子集，跨镜语义安全）
XF_KIND = {'cut': 'fade', 'fade': 'fade', 'crossfade': 'fade', 'wipeleft': 'wipeleft',
           'wiperight': 'wiperight', 'slideleft': 'slideleft', 'slideright': 'slideright',
           'circleopen': 'circleopen', 'circleclose': 'circleclose', 'dissolve': 'dissolve',
           'pixelize': 'pixelize', 'radial': 'radial', 'smoothleft': 'smoothleft',
           'smoothright': 'smoothright', 'fadeblack': 'fadeblack', 'fadewhite': 'fadewhite'}
inputs = []
for p in parts:
    inputs += ['-i', p]
fc = []
acc_len = durs[0]
prev = '[0:v]'
for i in range(1, len(parts)):
    off = acc_len - FADE_V
    out = f'[v{i}]'
    kind = XF_KIND.get(str(by_shot[SHOTS[i - 1]].get('transition_out', 'fade')), 'fade')
    fc.append(f'{prev}[{i}:v]xfade=transition={kind}:duration={FADE_V}:offset={off:.3f}{out}')
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

# ── J) 事件线（v18 M4）：拆解 JSON 事件序列 → 长片分段摘要卡（RAG 人物卡路子延伸；缓存幂等）──
EVENTS_JSON = BD.replace('breakdown_', 'events_')
if not os.path.isfile(EVENTS_JSON):
    from agents.common.tools.llm import LLMClient
    arcs_in = [{'shot': s['shot'], 'scene': s['scene'], 'narration': s.get('narration', ''),
                'visual': s['visual']} for s in bd['storyboard']]
    events = LLMClient().chat_json(
        [{'role': 'system', 'content':
            '你是剧本医生。把分镜序列按剧情弧线分组（每弧 3-6 镜），生成摘要卡供长片导航与续写检索。\n'
            '只输出 JSON：{"arcs":[{"arc": 弧名(短), "shots": [镜号...], '
            '"summary": 弧线摘要(60-100字), "characters": [出场角色]}]}。'},
         {'role': 'user', 'content': json.dumps(
             {'world': world, 'arcs_input': arcs_in}, ensure_ascii=False)}],
        temperature=0.4)
    for a in events.get('arcs', []):
        a['shots'] = sorted(a.get('shots', []))
    json.dump(events, open(EVENTS_JSON, 'w'), ensure_ascii=False, indent=1)
    print(f'[事件线] ✓ {len(events.get("arcs", []))} 弧 → {EVENTS_JSON}', flush=True)
else:
    events = json.load(open(EVENTS_JSON))
    print(f'[事件线] 缓存 {len(events.get("arcs", []))} 弧（{EVENTS_JSON}）', flush=True)

# 事件线摘要卡 → markdown 落盘 + RAG 索引（best-effort：挂了不阻塞渲染；md5 缓存幂等）
EVENTS_MD = EVENTS_JSON.replace('.json', '.md')
if not os.path.isfile(EVENTS_MD):
    lines = [f'# 事件线摘要卡（{os.path.basename(BD).replace("breakdown_", "").replace(".json", "")}）', '']
    for a in events.get('arcs', []):
        lines += [f'## {a["arc"]}（镜 {a["shots"][0]}-{a["shots"][-1]}）',
                  a.get('summary', ''), f'出场：{"/".join(a.get("characters", []))}', '']
    open(EVENTS_MD, 'w').write('\n'.join(lines))
    print(f'[事件线] ✓ 摘要卡 markdown {EVENTS_MD}', flush=True)
try:
    from utils.rag import RagIndex
    r = RagIndex().add_document(EVENTS_MD)
    print(f'[事件线] RAG 索引 {"缓存命中" if r.get("cached") else "新建"}'
          f'（key={r["key"][:8]}，{r.get("chunks", "?")} 片段）', flush=True)
except Exception as e:
    print(f'[事件线] ⚠ RAG 索引失败（忽略，JSON 产物仍可用）: {e}', flush=True)

# ── I) prompt 清单落盘 ──
md = ['# 孔乙己 v3 渲染 prompt 清单', '',
      f'- 拆解源: `{BD}`（shot.visual=画面描述，shot.narration=旁白/字幕）',
      f'- 关键帧 STYLE（全镜统一）: `{STYLE_EN}`',
      f'- I2V 运镜 MOTION: `{MOTION_EN}`',
      f'- 关键帧英文翻译（LLM 从 visual 生成）: `{PROMPTS_EN}`',
      '- 场景锚与服装（v18 M1）: 关键帧 EN prompt = 景别 + **场景锚**（scenes[].anchor_en，'
      '同场景镜头逐字复用，防布景漂移）+ **服装段**（costumes[].stages 区间命中，'
      '如镜9=破旧长衫/镜30=破夹袄蒲包）+ LLM 翻译增量（visual）三层叠加；'
      '溯源拆解 JSON 的 world/scenes/characters 字段',
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
if world:
    md += ['', '## 世界观（v18 M4 注册表）', '',
           f'- world: `{WORLD_JSON}`（style_en 英译缓存，已叠加进 STYLE_EN）']
    for t in world.get('taboos', []):
        md.append(f'- 禁则: {t}')
    md.append('')
    for a in events.get('arcs', []):
        md.append(f'- **{a["arc"]}**（镜 {a["shots"][0]}-{a["shots"][-1]}）: '
                  f'{a.get("summary", "")}（{"/".join(a.get("characters", []))}）')
open(os.path.join(OUT, 'prompts.md'), 'w').write('\n'.join(md))
print(f'[清单] ✓ {OUT}/prompts.md', flush=True)
