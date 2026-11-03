#!/usr/bin/env python3
"""v19（原 v16）视频链接二创 — 链接 → 解说向二创成片

设计（docs/design/v19-design.md）：M1 下载+理解（yt-dlp 合流 + STT/抽帧多模态并行 → source.json）
→ M2 改写解说词+重配音（防复述断言 + 时间轴映射 script.json）→ M3 画面二创（改写强度 0-5 档，
组装走 v10 compose）→ M4 一条命令端到端。零新模型，全部现成基建接线。

用法（M1，独立冒烟）:
    python utils/rework.py source "<B站链接>" --out output/rework/rw-test
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TMP_DL = '/tmp/opencode/rework_dl'
_FRAME_EVERY = 5.0      # 抽帧间隔（秒）
_FRAME_SIZE = 512       # 多模态缩图（审片铁律）
_MAX_BATCH = 8          # 多模态每批帧数


# ── [1] 下载 ──

def _probe(path: str) -> dict:
    """ffprobe → {duration, width, height}"""
    cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', path]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    info = json.loads(out.stdout or '{}')
    v = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), {})
    return {'duration': float(info.get('format', {}).get('duration', 0) or 0),
            'width': v.get('width', 0), 'height': v.get('height', 0)}


def download_video(url: str, out_dir: str, timeout: int = 900) -> dict:
    """yt-dlp 合流下载（bestvideo+bestaudio→mp4）+ 抽 16k mono wav。

    复用 voice_clone 惯例：tag 隔离防同名跳过 / .part 过滤 / 大小下限。
    返回 {video, audio, duration, title, platform}。
    """
    os.makedirs(out_dir, exist_ok=True)
    video_path = os.path.join(out_dir, 'source.mp4')
    if not (os.path.isfile(video_path) and os.path.getsize(video_path) > 100000):
        out_tpl = os.path.join(out_dir, 'source.%(ext)s')
        cmd = ['yt-dlp', '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
               '--merge-output-format', 'mp4', '--no-playlist', '--write-info-json', '-q',
               '-o', out_tpl, url]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        files = [f for f in glob.glob(os.path.join(out_dir, 'source.mp4'))
                 if os.path.getsize(f) > 100000]
        if proc.returncode != 0 or not files:
            raise RuntimeError(f'yt-dlp 下载失败: {proc.stderr.strip()[-300:]}')
    info = {}
    ij = glob.glob(os.path.join(out_dir, 'source.info.json'))
    if ij:
        try:
            with open(ij[0], encoding='utf-8') as f:
                full = json.load(f)
            info = {'title': full.get('title', ''), 'uploader': full.get('uploader', '')}
        except Exception:
            pass
    audio_path = os.path.join(out_dir, 'audio.wav')
    if not (os.path.isfile(audio_path) and os.path.getsize(audio_path) > 10000):
        subprocess.run(['ffmpeg', '-y', '-i', video_path, '-vn', '-ac', '1', '-ar', '16000',
                        audio_path], capture_output=True, timeout=600)
    meta = _probe(video_path)
    m = re.search(r'bilibili\.com/video/(BV\w+)', url)
    return {'video': os.path.abspath(video_path), 'audio': os.path.abspath(audio_path),
            'duration': meta['duration'], 'width': meta['width'], 'height': meta['height'],
            'platform': 'bilibili' if m else ('other'),
            'bvid': m.group(1) if m else '', **info}


# ── [2] 抽帧 ──

def extract_frames(video: str, out_dir: str, every: float = _FRAME_EVERY,
                   size: int = _FRAME_SIZE) -> list:
    """每 every 秒抽一帧（512px JPEG，审片铁律），返回 [{'t', 'path'}]（含绝对时间）"""
    kf_dir = os.path.join(out_dir, 'frames')
    os.makedirs(kf_dir, exist_ok=True)
    existing = sorted(glob.glob(os.path.join(kf_dir, 'frame_*.jpg')))
    if existing:
        return [{'t': round(i * every, 2), 'path': p} for i, p in enumerate(existing)]
    subprocess.run(['ffmpeg', '-y', '-i', video, '-vf',
                    f'fps=1/{every},scale={size}:-2', '-q:v', '4',
                    os.path.join(kf_dir, 'frame_%04d.jpg')],
                   capture_output=True, timeout=600)
    frames = sorted(glob.glob(os.path.join(kf_dir, 'frame_*.jpg')))
    return [{'t': round(i * every, 2), 'path': p} for i, p in enumerate(frames)]


# ── [3] 转写（GPU→CPU 兜底） ──

def transcribe(audio_path: str) -> list:
    """faster-whisper 转写（v2 STT），cuda 失败回退 cpu。返回 [{'start','end','text'}]"""
    from agents.post.tools.stt import transcribe_audio
    for dev, ctype in (('cuda', 'int8_float16'), ('cpu', 'int8')):
        try:
            segs = transcribe_audio(audio_path, language='zh', device=dev, compute_type=ctype)
            if segs:
                return [{'start': s['start'], 'end': s['end'], 'text': s['text']} for s in segs]
        except Exception as e:
            print(f'[STT] {dev} 失败: {e}', flush=True)
    return []


# ── [4] 帧理解（多模态批量，失败 safe fallback 置空） ──

def understand_frames(frames: list, every: float = _FRAME_EVERY) -> list:
    """批量多模态描述：每 _MAX_BATCH 帧一次调用。返回与 frames 对齐的 visual 文本列表。

    铁律（v0 审片）：512px 缩图 / 180s timeout / 失败 safe fallback（visual=''不阻塞）。
    """
    llm = None
    try:
        from agents.common.tools.llm import LLMClient
        llm = LLMClient()
    except Exception as e:
        print(f'[视觉] LLM 初始化失败，visual 全置空: {e}', flush=True)
        return [''] * len(frames)
    system = (
        '你是视频理解助手。给你一批按时间顺序抽帧的图片（间隔约 %g 秒）。'
        '对每张图输出一行，格式严格为："[序号] 画面内容"，描述主体/场景/动作/出现的文字，'
        '中文，每行不超过 40 字。不要输出其他内容。' % every
    )
    visuals = [''] * len(frames)
    for b0 in range(0, len(frames), _MAX_BATCH):
        batch = frames[b0:b0 + _MAX_BATCH]
        content = [{'type': 'text',
                    'text': f'这批帧的序号是 {b0} 到 {b0 + len(batch) - 1}（从 0 计）。'}]
        for fr in batch:
            content.append({'type': 'image_url',
                            'image_url': {'url': llm._image_to_base64(fr['path'])}})
        try:
            text = llm.chat([{'role': 'system', 'content': system},
                             {'role': 'user', 'content': content}],
                            model=llm.models['review'], temperature=0.2,
                            timeout=180, retries=1).strip()
            for line in text.splitlines():
                m = re.match(r'\s*\[?(\d+)\]?\s*[.、:：]?\s*(.+)', line.strip())
                if m:
                    idx = int(m.group(1))
                    if b0 <= idx < b0 + len(batch):
                        visuals[idx] = m.group(2).strip()[:60]
        except Exception as e:
            print(f'[视觉] 批 {b0}~{b0 + len(batch) - 1} 失败（safe fallback）: {e}', flush=True)
    return visuals


# ── [5] M1 汇总：source.json ──

def build_source(url: str, out_dir: str) -> dict:
    """M1 主流程：下载 + STT/抽帧并行 + 帧理解 → source.json（幂等缓存）"""
    src_path = os.path.join(out_dir, 'source.json')
    if os.path.isfile(src_path):
        with open(src_path, encoding='utf-8') as f:
            return json.load(f)
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    dl = download_video(url, out_dir)
    print(f'[下载] {dl["title"] or url} · {dl["duration"]:.0f}s · {dl["platform"]}', flush=True)
    frames = extract_frames(dl['video'], out_dir)
    print(f'[抽帧] {len(frames)} 帧（every={_FRAME_EVERY}s）', flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_stt = pool.submit(transcribe, dl['audio'])
        fut_vis = pool.submit(understand_frames, frames)
        segments = fut_stt.result()
        visuals = fut_vis.result()
    for fr, vis in zip(frames, visuals):
        fr['visual'] = vis
    src = {**dl, 'url': url, 'segments': segments, 'frames': frames,
           'stt_chars': sum(len(s['text']) for s in segments),
           'build_seconds': round(time.time() - t0, 1)}
    with open(src_path, 'w', encoding='utf-8') as f:
        json.dump(src, f, ensure_ascii=False, indent=1)
    print(f'[M1] source.json 落盘：{len(segments)} 段转写/{src["stt_chars"]} 字 · '
          f'{len(frames)} 帧 · {src["build_seconds"]}s', flush=True)
    return src


# ── [5] M2 解说词改写 + 重配音 ──

# 音色黑名单（SKILL 踩坑结晶）：零样本克隆音色 prompt_text 是幻听源，句首泄漏参考文本
_VOICE_BLACKLIST = {'cosy-jieshuo1': '句首泄漏"街道…"（50 字参考文本被当上文续写）'}

_STYLES = {
    '解说': '影视解说风格：先抛悬念钩子，再按时间线讲清事件，结尾点评升华。口语化、有节奏感。',
    '盘点': '盘点清单风格：分点罗列亮点，每点独立成段，信息密度高。',
    '吐槽': '犀利吐槽风格：玩梗、反转、带情绪，但事实准确不造谣。',
}


def _digest_source(src: dict, block_sec: float = 30.0) -> tuple:
    """转写段聚合成 ~block_sec 块 + 抽稀帧视觉，压缩成 LLM 可读摘要。返回 (blocks, visuals)"""
    blocks, buf, t0 = [], [], None
    for s in src['segments']:
        if t0 is None:
            t0 = s['start']
        buf.append(s['text'])
        if s['end'] - t0 >= block_sec:
            blocks.append({'start': t0, 'end': s['end'], 'text': ''.join(buf)})
            buf, t0 = [], None
    if buf:
        blocks.append({'start': t0 or 0, 'end': src['segments'][-1]['end'],
                       'text': ''.join(buf)})
    step = max(1, int(30 / _FRAME_EVERY))
    visuals = [f"t={fr['t']:.0f}s {fr['visual']}" for fr in src['frames'][::step] if fr['visual']]
    return blocks, visuals


def _sim_max(narration: str, blocks: list) -> float:
    """narration 与原文所有块的最大相似度（防复述断言，复用 v17 Levenshtein）"""
    from utils.subtitle_correct import similarity
    return max((similarity(narration, b['text']) for b in blocks), default=0.0)


def rewrite_script(src: dict, style: str = '解说', target_duration: int = 60,
                   max_similarity: float = 0.55) -> dict:
    """LLM 改写解说词 + 时间轴映射（引用原片画面区间）。防复述断言：retry 一次仍超阈→警告放行。"""
    from agents.common.tools.llm import LLMClient
    llm = LLMClient()
    blocks, visuals = _digest_source(src)
    n_target = int(target_duration * 4)  # 4 字/秒铁律
    n_lo, n_hi = int(n_target * 0.8), int(n_target * 1.15)
    src_text = '\n'.join(f"[{i}] {b['start']:.0f}-{b['end']:.0f}s: {b['text']}"
                         for i, b in enumerate(blocks))
    vis_text = '\n'.join(visuals) or '（无画面描述）'
    system = (
        f'你是二创视频编剧。基于原视频的旁白转写与画面描述，写一条全新的{style}解说词。\n'
        f'{_STYLES.get(style, _STYLES["解说"])}\n'
        '硬约束：\n'
        '1. 全部解说词总字数必须在 %d~%d 字之间（硬性时长约束，4 字/秒），分成 4-12 段，每段 20-80 字\n'
        '2. 严禁复述原文：不得出现与原文连续 15 字以上相同的句子，必须用自己的话重写\n'
        '3. 每段配 ref_start（原片引用起点秒）与 ref_dur（引用时长秒 5-25）——'
        '选该段解说对应的原片画面最有信息量的区间\n'
        '4. 第一段是钩子（悬念/反差），最后一段收束点评\n'
        '5. 事实以转写为准，不得编造原文没有的信息\n'
        '输出严格 JSON：{"title": "二创标题", '
        '"segments": [{"narration": "...", "ref_start": 数字, "ref_dur": 数字}]}'
        % (n_lo, n_hi)
    )
    user = f'== 原片旁白转写（按时间块）==\n{src_text}\n\n== 画面描述（抽稀）==\n{vis_text}'
    msgs = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    blocks_texts = [b['text'] for b in blocks]

    def _stream_json(m):
        # 铁律（SKILL LLM 调用 #1）：非流式长 reasoning 零字节 → read timeout 必死；
        # 流式 delta 持续到达不超时，收全后 _extract_json（带 2 次畸形自修回喂）
        from agents.common.tools.llm import LLMClient
        for attempt in range(2):
            text = llm.chat_stream(m, model=llm.models['script'], temperature=0.6,
                                   max_tokens=16384, timeout=1800)
            try:
                return llm._extract_json(text)
            except (json.JSONDecodeError, ValueError) as e:
                print(f'[改写] JSON 解析失败（{e}），回喂重修 {attempt + 1}/2', flush=True)
                m = m + [{'role': 'assistant', 'content': text},
                         {'role': 'user', 'content':
                             f'你的输出不是合法 JSON（错误：{e}）。请重新输出，'
                             '严格 JSON 格式，不要加任何解释文字或 markdown 代码块。'}]
        raise ValueError('LLM JSON parse failed after stream retries')

    for attempt in (1, 2):
        r = _stream_json(msgs)
        segs = r.get('segments') or []
        segs = [s for s in segs if (s.get('narration') or '').strip()]
        if not segs:
            raise ValueError('LLM 返回空解说词')
        # 防复述断言
        sims = [_sim_max(s['narration'], blocks) for s in segs]
        worst = max(sims)
        if worst < max_similarity:
            break
        print(f'[改写] 相似度超阈（max={worst:.2f} ≥ {max_similarity}），'
              f'{"警告放行" if attempt == 2 else "回喂重写 1/1"}', flush=True)
        if attempt == 1:
            bad = [i for i, sm in enumerate(sims) if sm >= max_similarity]
            msgs = msgs + [
                {'role': 'assistant', 'content': json.dumps(r, ensure_ascii=False)},
                {'role': 'user', 'content':
                    f'第 {bad} 段与原文过于相似（复述嫌疑），请重写这几段：更口语化、'
                    '换句式、加评论观点，不得复述原句。其余段保留，重新输出完整 JSON。'}]
    dur_total = src['duration']
    for s in segs:
        s['ref_dur'] = float(min(max(float(s.get('ref_dur') or 8), 3.0), 30.0))
        s['ref_start'] = float(min(max(float(s.get('ref_start') or 0), 0.0),
                                   max(0.0, dur_total - s['ref_dur'] - 0.5)))
    return {'title': (r.get('title') or '')[:40], 'style': style,
            'target_duration': target_duration, 'max_similarity': round(worst, 3),
            'segments': segs}


def voiceover(script: dict, out_dir: str, voice: str = 'cosy-default') -> dict:
    """逐段 TTS（串行，CosyVoice 惯例）→ 每段 audio/duration；生成 subs.srt（同源）"""
    if voice in _VOICE_BLACKLIST:
        print(f'⚠ [音色黑名单] {voice}: {_VOICE_BLACKLIST[voice]}——建议 --voice cosy-default',
              flush=True)
    from agents.common.tools.tts import TTSClient
    tts = TTSClient()
    os.makedirs(os.path.join(out_dir, 'vo'), exist_ok=True)
    t = 0.0
    srt_lines = []
    for i, s in enumerate(script['segments']):
        wav = os.path.join(out_dir, 'vo', f'seg_{i:02d}.wav')
        r = tts.synthesize(s['narration'], output_path=wav, voice=voice)
        s['audio'] = os.path.abspath(wav)
        s['narr_dur'] = round(float(r.get('duration') or 0) or
                              len(s['narration']) / 4.0, 2)
        s['start'] = round(t, 2)
        t += s['narr_dur']
        srt_lines.append((s['start'], t, s['narration']))
    script['total_duration'] = round(t, 2)
    _write_srt(srt_lines, os.path.join(out_dir, 'subs.srt'))
    return script


def _write_srt(items: list, path: str):
    def ts(sec):
        ms = int(round(sec * 1000))
        return f'{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}'
    with open(path, 'w', encoding='utf-8') as f:
        for i, (a, b, txt) in enumerate(items, 1):
            f.write(f'{i}\n{ts(a)} --> {ts(b)}\n{txt}\n\n')


# ── [6] M3 画面二创 + 组装 ──

def _preclip(src_path: str, s: dict, out_path: str, level: int, width: int = 1280,
             height: int = 704) -> None:
    """单段画面改写：trim + 变速(rate=ref_dur/narr_dur 贴合旁白) + 档位处理 + 画布归一。

    档位（组合式，0-5）：0 原样裁引 / 1 +变速 / 2 +LUT(终拼统一) / 3 +镜像裁剪构图 /
    4 +光流插帧(minterpolate，rate>1.25 加速抖动平滑) / 5 +v5 特效(compose effects)。
    """
    rate = min(max(s['ref_dur'] / max(s['narr_dur'], 1.0), 0.75), 1.6)
    s['rate'] = round(rate, 3)
    vf = [f'scale={width}:{height}:force_original_aspect_ratio=decrease',
          f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2']
    if level >= 3:
        # 构图改写：偶数段镜像 + 全段微裁（zoom 1.08）
        if s.get('_i', 0) % 2 == 0:
            vf.insert(0, 'hflip')
        vf.insert(0, 'crop=iw/1.08:ih/1.08')
    if level >= 4 and rate > 1.25:
        vf.append('minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc:vsbmc=1')
    else:
        vf.append(f'setpts=PTS/{rate:.4f}')
    af = f'atempo={min(max(rate, 0.5), 2.0):.4f},volume=0.35'  # 原声当环境床
    cmd = ['ffmpeg', '-y', '-ss', f'{s["ref_start"]:.3f}', '-t', f'{s["ref_dur"]:.3f}',
           '-i', src_path, '-vf', ','.join(vf), '-af', af, '-r', '24',
           '-t', f'{s["narr_dur"] + 0.2:.3f}',
           '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
           '-c:a', 'aac', out_path]
    subprocess.run(cmd, capture_output=True, timeout=600)
    if not os.path.isfile(out_path) or os.path.getsize(out_path) < 10000:
        raise RuntimeError(f'preclip 失败 seg{s.get("_i")}: '
                           f'{subprocess.list2cmdline(cmd)[-200:]}')


_REWORK_EFFECTS = ['punch_in', 'zoom', 'grain_vignette']


def assemble(script: dict, src: dict, out_dir: str, level: int = 2,
             lut: str = '', bgm: str = '', remove_sub: str = 'off',
             boxes_norm: list = None) -> str:
    """预改写各段 → compose 时间线（主轨+转场+旁白轨）→ 终拼（BGM ducking+LUT+字幕+yuv420p）

    remove_sub: off=不消除；auto=有 OCR 框才消除；force=无框也按底部带消除。
    boxes_norm: run_rework 一次 OCR 检测的归一化框（subtitle.json），各 part 复用零 OCR。
    消除在 part 粒度（preclip 后、组装前）：每段独立幂等缓存（raw_XX → part_XX）。
    """
    from agents.post.tools.compose import run_timeline
    work = os.path.join(out_dir, 'parts')
    os.makedirs(work, exist_ok=True)
    main, audio, t = [], [], 0.0
    for i, s in enumerate(script['segments']):
        s['_i'] = i
        part = os.path.join(work, f'part_{i:02d}.mp4')
        if remove_sub in ('auto', 'force'):
            raw = os.path.join(work, f'raw_{i:02d}.mp4')
            if os.path.isfile(part) and not os.path.isfile(raw):
                os.rename(part, raw)
            if not (os.path.isfile(raw) and os.path.getsize(raw) > 10000):
                _preclip(src['video'], s, raw, level)
            if not (os.path.isfile(part) and os.path.getsize(part) > 10000):
                from agents.post.tools.sam_edit import video_remove_subtitle
                print(f'[消除字幕] part_{i:02d}（mode={remove_sub}，'
                      f'{"OCR 框" if boxes_norm else "底部带回退"}）', flush=True)
                video_remove_subtitle(raw, part, mode=remove_sub,
                                      boxes_norm=boxes_norm)
        elif not (os.path.isfile(part) and os.path.getsize(part) > 10000):
            _preclip(src['video'], s, part, level)
        if remove_sub in ('auto', 'force'):
            raw = os.path.join(work, f'raw_{i:02d}.mp4')
            if os.path.isfile(part) and not os.path.isfile(raw):
                os.rename(part, raw)
            if not (os.path.isfile(part) and os.path.getsize(part) > 10000):
                from agents.post.tools.sam_edit import video_remove_subtitle
                print(f'[消除字幕] part_{i:02d}（mode={remove_sub}）', flush=True)
                video_remove_subtitle(raw, part, mode=remove_sub, n_samples=3)
        main.append({'id': f'c{i}', 'type': 'video', 'source': part,
                     'trim_start': 0, 'duration': s['narr_dur'] + 0.2,
                     'transition_in': ({'kind': 'fade', 'duration': 0.4} if i else None),
                     'volume': 0.35,
                     **({'effects': [{'name': _REWORK_EFFECTS[i % len(_REWORK_EFFECTS)]}]}
                        if level >= 5 else {})})
        audio.append({'id': f'n{i}', 'type': 'audio', 'source': s['audio'],
                      'start': round(t, 2), 'duration': s['narr_dur'], 'volume': 1.0})
        t += s['narr_dur'] + 0.2
    tl = {'output': os.path.join(out_dir, 'base.mp4'), 'width': 1280, 'height': 704,
          'main': main, 'audio': audio}
    base = run_timeline(tl)
    total = script['total_duration'] + 0.2 * len(script['segments'])
    # 终拼：BGM ducking + LUT + 烧字幕 + yuv420p（Windows 铁律）
    final = os.path.join(out_dir, 'final.mp4')
    vf = []
    if lut:
        lut_path = lut if os.path.isabs(lut) else os.path.join(ROOT, 'utils/luts', f'{lut}.cube')
        if os.path.isfile(lut_path):
            vf.append(f'lut3d={lut_path}')
    vf.append(f'subtitles={os.path.join(out_dir, "subs.srt")}:'
              f"force_style='FontName=Noto Sans CJK SC Bold,FontSize=15,"
              f"PrimaryColour=&Hffffff,OutlineColour=&H80000000,BorderStyle=1,"
              f"Outline=1.2,MarginV=26'")
    fc = ''
    bgm_path = ''
    if bgm:
        cand = bgm if os.path.isabs(bgm) else os.path.join(ROOT, 'bgm', f'{bgm}.wav')
        if os.path.isfile(cand):
            bgm_path = cand
    if bgm_path:
        fc = (f'[1:a]atrim=0:{total:.2f},volume=0.22[bg];'
              f'[0:a]asplit[keep][sc];'
              f'[bg][sc]sidechaincompress=threshold=0.03:ratio=6:attack=80:release=400[d];'
              f'[keep][d]amix=inputs=2:duration=first[mix]')
        cmd = ['ffmpeg', '-y', '-i', base, '-i', bgm_path,
               '-filter_complex', fc, '-map', '0:v', '-map', '[mix]',
               '-vf', ','.join(vf), '-t', f'{total:.2f}',
               '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
               '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-level', '4.1',
               '-c:a', 'aac', '-shortest', final]
    else:
        cmd = ['ffmpeg', '-y', '-i', base, '-vf', ','.join(vf), '-t', f'{total:.2f}',
               '-c:v', 'libx264', '-preset', 'medium', '-crf', '20',
               '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-level', '4.1',
               '-c:a', 'copy', final]
    subprocess.run(cmd, capture_output=True, timeout=900)
    if not os.path.isfile(final) or os.path.getsize(final) < 50000:
        raise RuntimeError('终拼失败: ' + (cmd and ' '.join(cmd))[-300:])
    return final


# ── [7] M4 端到端 ──

def run_rework(url: str, out_dir: str, style: str = '解说', duration: int = 60,
               voice: str = 'cosy-default', level: int = 2, lut: str = '',
               bgm: str = '', stage_cb=None, remove_sub: str = 'off') -> str:
    """v19 主入口：链接 → source.json → script.json → final.mp4（每级幂等缓存）

    remove_sub: off（默认）/ auto（OCR 检出烧录字幕才消除）/ force（底部带强制消除）。
    检测一次（unlimited-ocr，3 帧采样）落 subtitle.json，各 part 复用零 OCR。
    """
    _stage = (lambda s: stage_cb(s)) if stage_cb else (lambda s: None)
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    _stage('下载+理解（yt-dlp/STT/多模态）')
    src = build_source(url, out_dir)
    boxes_norm = None
    if remove_sub in ('auto', 'force'):
        sub_path = os.path.join(out_dir, 'subtitle.json')
        if os.path.isfile(sub_path):
            with open(sub_path, encoding='utf-8') as f:
                boxes_norm = json.load(f).get('boxes_norm') or []
        else:
            from agents.post.tools.sam_edit import detect_subtitle_boxes
            _stage('OCR 检测烧录字幕（unlimited-ocr）')
            d = detect_subtitle_boxes(src['video'], n_samples=3)
            json.dump({'boxes_norm': d['boxes_norm'], 'detected': d['detected']},
                      open(sub_path, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
            boxes_norm = d['boxes_norm']
            print(f'[字幕检测] {"检出 " + str(len(boxes_norm)) + " 框" if d["detected"] else "未检出（回退底部带）"}',
                  flush=True)
        if remove_sub == 'auto' and not boxes_norm:
            remove_sub = 'off'  # 检出前不知道有没有字幕：auto+无框=不消除
            # 注意：OCR 空响应与真无字幕不可分，auto 模式保守放行
    script_path = os.path.join(out_dir, 'script.json')
    _stage('LLM 改写解说词')
    if os.path.isfile(script_path):
        with open(script_path, encoding='utf-8') as f:
            script = json.load(f)
        print('[M2] script.json 缓存命中，跳过改写', flush=True)
    else:
        script = rewrite_script(src, style=style, target_duration=duration)
        _stage(f'TTS 配音（{voice}）')
        script = voiceover(script, out_dir, voice=voice)
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump(script, f, ensure_ascii=False, indent=1)
    print(f'[M2] script.json：{len(script["segments"])} 段 · '
          f'相似度 max={script.get("max_similarity")} · 总时长 {script["total_duration"]}s',
          flush=True)
    _stage(f'画面改写 L{level} + compose 组装')
    final = assemble(script, src, out_dir, level=level, lut=lut, bgm=bgm,
                     remove_sub=remove_sub, boxes_norm=boxes_norm)
    meta = {'url': url, 'source_title': src.get('title', ''),
            'style': style, 'rewrite_level': level, 'lut': lut, 'bgm': bgm,
            'voice': voice, 'script_title': script.get('title', ''),
            'n_segments': len(script['segments']),
            'final_duration': script['total_duration'],
            'source_duration': src['duration'],
            'max_similarity': script.get('max_similarity'),
            'remove_sub': remove_sub,
            'elapsed': round(time.time() - t0, 1), 'ts': time.time()}
    with open(os.path.join(out_dir, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f'[M4] ✓ {final}（{meta["final_duration"]}s，改写强度 L{level}，'
          f'{meta["elapsed"]}s）——发布前请人工审核', flush=True)
    return final


# ── CLI ──

def main():
    ap = argparse.ArgumentParser(description='v19（原 v16）视频链接二创')
    ap.add_argument('action', choices=['source', 'rework'])
    ap.add_argument('url')
    ap.add_argument('--out', default='output/rework/rw-test')
    ap.add_argument('--style', default='解说', choices=list(_STYLES))
    ap.add_argument('--duration', type=int, default=60, help='目标时长秒')
    ap.add_argument('--voice', default='cosy-default')
    ap.add_argument('--visual-rewrite', type=int, default=2, choices=range(6),
                    help='画面改写强度 0-5')
    ap.add_argument('--lut', default='', help='cinematic/warm/cool/vintage/vivid/soft')
    ap.add_argument('--bgm', default='', help='calm/uplifting/mysterious/dramatic/playful/epic')
    ap.add_argument('--remove-sub', default='off', choices=['off', 'auto', 'force'],
                    help='消除原片烧录字幕（ProPainter）：off/auto=检出才消/force=底部带强制')
    a = ap.parse_args()
    out = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
    if a.action == 'source':
        src = build_source(a.url, out)
        print(json.dumps({k: src[k] for k in ('url', 'title', 'duration', 'stt_chars')
                          if k in src}, ensure_ascii=False))
        return
    final = run_rework(a.url, out, style=a.style, duration=a.duration,
                       voice=a.voice, level=a.visual_rewrite, lut=a.lut, bgm=a.bgm,
                       remove_sub=a.remove_sub)
    print(final)


if __name__ == '__main__':
    main()
