#!/usr/bin/env python3
"""TTS 客户端 — 调用双引擎 TTS 服务（CosyVoice2 + edge-tts, 9880）

音色命名:
  edge-*    → edge-tts 引擎（微软神经语音, 自然, 在线）
  cosy-*    → CosyVoice 引擎（本地 zero-shot 克隆）
  cosy-<名> → 自定义音色（voices/<名>/prompt.wav）

用法:
  from utils.tts import TTSClient
  client = TTSClient()
  result = client.synthesize("你好世界", output_path="output/clips/shot_1.wav")
  # result = {audio_path, duration, timestamps, engine, voice}
"""

import os as _os
import sys as _sys
_ROOT = _os.path.abspath(__file__)
for _ in range(4):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
import json
import os
import sys
import base64
import threading
import urllib.request
import urllib.error

# CosyVoice 服务端并行推理不安全（fp16 采样 inf/nan → 0.6s 废音频，2026-10-15 E2E 实锤），
# 客户端全局锁串行化所有 /tts 请求
_TTS_LOCK = threading.Lock()

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'config', 'config.json')


def load_config():
    from utils.config_loader import load_config as _load
    return _load()


class TTSClient:
    def __init__(self, config=None):
        self.config = config or load_config()
        tts_cfg = self.config['tts']
        self.base_url = f"http://{tts_cfg['host']}:{tts_cfg['port']}"
        self.default_voice = tts_cfg.get('default_voice', 'default')

    def health(self) -> dict:
        url = f'{self.base_url}/health'
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())

    def list_voices(self) -> dict:
        url = f'{self.base_url}/voices'
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())

    def synthesize(self, text: str, output_path: str = None,
                   voice: str = None, speed: float = 1.0,
                   prompt_wav: str = None, prompt_text: str = None) -> dict:
        """合成语音，保存到 output_path，返回 {audio_path, duration, timestamps}

        M6 修复：CosyVoice 服务端并行请求会采样崩坏（probability tensor inf/nan，
        返回 200 但音频 0.6s 废片）——客户端全局串行 + 时长合理性校验，
        过短（< max(0.5s, 期望时长×0.4)，中文≈4字/秒）自动重试一次。
        2026-10-16：克隆音色（cosy-*）会在句首/句尾幻觉出杂音音节（用户实测
        'zu'/'ri'，whisper 词级转写实锤为多余音节如 '煮血液' 前缀）——
        加 STT 首尾音节校验（pinyin 比对）+ 不合格重试一次 + 首尾静音裁剪。
        """
        voice = voice or self.default_voice
        payload = {'text': text, 'voice': voice, 'speed': speed}
        if prompt_wav:
            payload['prompt_wav'] = prompt_wav
        if prompt_text is not None:
            payload['prompt_text'] = prompt_text

        data = json.dumps(payload).encode('utf-8')
        expected = max(1.0, len(text) / 4.0)  # 中文≈4字/秒
        need_validate = voice.startswith('cosy')
        result = {}
        for attempt in (1, 2):
            with _TTS_LOCK:
                req = urllib.request.Request(
                    f'{self.base_url}/tts',
                    data=data,
                    headers={'Content-Type': 'application/json'},
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    result = json.loads(resp.read())
            dur = float(result.get('duration') or 0)
            bounds = None
            if dur < min(0.5, expected) and dur < expected * 0.4:
                print(f'  [tts] 音频过短 ({dur:.2f}s < 期望~{expected:.1f}s)，'
                      f'疑似 CosyVoice 并发采样崩坏，重试 {attempt}/1（串行）')
                continue
            if need_validate:
                ok, why, bounds = self._validate_boundaries(text, result)
                if not ok and attempt == 1:
                    print(f'  [tts] 首尾杂音检测不通过（{why}），重试 1/1')
                    continue
            break

        if need_validate:
            result = self._trim_edges(result, bounds, text)

        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            audio_bytes = base64.b64decode(result['audio'])
            with open(output_path, 'wb') as f:
                f.write(audio_bytes)
            result['audio_path'] = output_path
            del result['audio']

        return result

    # ── 首尾杂音护栏（2026-10-16）：whisper 词级转写 + pinyin 首尾音节比对 ──

    _WHISPER = None  # 惰性单例

    def _get_whisper(self):
        if TTSClient._WHISPER is None:
            from agents.post.tools.stt import _get_model, _resolve_model_path
            TTSClient._WHISPER = _get_model(
                _resolve_model_path({}), device='cuda', compute_type='int8_float16')
        return TTSClient._WHISPER

    @staticmethod
    def _word_syllables(word: str) -> list:
        from pypinyin import lazy_pinyin
        import re as _re
        cn = _re.sub(r'[^\u4e00-\u9fff]', '', word)
        return lazy_pinyin(cn) if cn else []

    def _validate_boundaries(self, text: str, result: dict):
        """校验合成音频首尾音节与文本一致。返回 (ok, 原因, 词界或None)。异常一律放行。

        词界 = (first_word_start, last_word_end)，仅在首词音节匹配时可信
        （whisper 偶发漏掉首词，此时词界不可信，回退能量裁剪）。
        """
        try:
            import io as _io
            from pypinyin import lazy_pinyin
            clean = ''.join(c for c in text if '\u4e00' <= c <= '\u9fff')
            if len(clean) < 2:
                return True, '', None
            audio = base64.b64decode(result['audio'])
            m = self._get_whisper()
            segs, _ = m.transcribe(_io.BytesIO(audio), language='zh', word_timestamps=True)
            words = [(wd.start, wd.end, wd.word) for s in segs for wd in s.words]
            if not words:
                return True, '', None
            first = TTSClient._word_syllables(words[0][2])
            last2 = []
            for wd in words[-2:]:
                last2 += TTSClient._word_syllables(wd[2])
            exp_first = lazy_pinyin(clean[0])[0]
            exp_last = lazy_pinyin(clean[-1])[0]
            bounds = None
            head_ok = bool(first) and first[0] == exp_first
            tail_ok = bool(last2) and exp_last in last2
            if head_ok and tail_ok:
                bounds = (words[0][0], words[-1][1])
            if not head_ok:
                return False, f'句首音节 {first[0] if first else "?"}≠{exp_first}（转写 {words[0][2]!r}）', None
            if not tail_ok:
                return False, f'句尾音节 {last2}不含{exp_last}（转写 {words[-1][2]!r}）', None
            return True, '', bounds
        except Exception:
            return True, '', None

    def _trim_edges(self, result: dict, bounds=None, text: str = '') -> dict:
        """裁剪首尾非语音（whisper 词界优先，能量阈值兜底），同步修正 timestamps。"""
        try:
            import io as _io
            import numpy as _np
            import wave as _wave
            audio = base64.b64decode(result['audio'])
            w = _wave.open(_io.BytesIO(audio))
            sr, n = w.getframerate(), w.getnframes()
            ch, sw = w.getsampwidth(), w.getsampwidth()
            ch = w.getnchannels()
            frames = _np.frombuffer(w.readframes(n), dtype=_np.int16)
            w.close()
            if sw != 2 or n == 0:
                return result
            if bounds is not None:
                head = max(0, int((bounds[0] - 0.03) * sr))
                tail = min(len(frames), int((bounds[1] + 0.08) * sr))
            else:
                frame = max(1, sr // 50)  # 20ms
                rms = _np.sqrt(_np.convolve(frames.astype(_np.float32) ** 2,
                                            _np.ones(frame) / frame, mode='valid') + 1e-9)
                thr = max(120.0, float(rms.max()) * 0.04)
                voiced = _np.where(rms > thr)[0]
                if len(voiced) == 0:
                    return result
                head = max(0, int(voiced[0]) - sr // 20)   # 保留 50ms 余量
                tail = min(len(frames), int(voiced[-1]) + frame + sr // 12)  # 尾留 80ms
            if head < sr // 25 and tail > len(frames) - sr // 25:
                return result  # 首尾都干净，不动
            cut = frames[head:tail]
            buf = _io.BytesIO()
            out = _wave.open(buf, 'wb')
            out.setnchannels(ch); out.setsampwidth(sw); out.setframerate(sr)
            out.writeframes(cut.tobytes()); out.close()
            result['audio'] = base64.b64encode(buf.getvalue()).decode('ascii')
            result['duration'] = round(len(cut) / sr, 3)
            shift = head / sr
            if bounds is not None:
                # 词界可信 → timestamps 直接对齐真实语音（整条调用=一句字幕）
                sp_end = max(0.0, bounds[1] - shift)
                ts0 = (result.get('timestamps') or [{}])[0]
                result['timestamps'] = [{**ts0, 'text': ts0.get('text', text),
                                         'start': 0.0, 'end': round(sp_end, 3),
                                         'duration': round(sp_end, 3)}]
            else:
                ts = []
                for t in (result.get('timestamps') or []):
                    s, e = max(0.0, t['start'] - shift), max(0.0, t['end'] - shift)
                    if e - s > 0.05:
                        ts.append({**t, 'start': round(s, 3), 'end': round(e, 3),
                                   'duration': round(e - s, 3)})
                result['timestamps'] = ts
            return result
        except Exception:
            return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Vidance TTS client (CosyVoice + edge-tts)')
    parser.add_argument('text', nargs='?', default=None, help='Text to synthesize')
    parser.add_argument('-o', '--output', default='/tmp/tts_cli_output.wav', help='Output wav path')
    parser.add_argument('-v', '--voice', default=None, help='Voice name (edge-* or cosy-*)')
    parser.add_argument('-s', '--speed', type=float, default=1.0, help='Speech speed')
    parser.add_argument('--list-voices', action='store_true', help='List all available voices')
    args = parser.parse_args()

    client = TTSClient()
    if args.list_voices:
        voices = client.list_voices()
        for engine, vdict in voices.items():
            print(f'\n[{engine}]')
            for vname, vinfo in vdict.items():
                desc = vinfo.get('desc', '')
                print(f'  {vname:30s} {desc}')
        sys.exit(0)

    if not args.text:
        parser.error('text is required (or use --list-voices)')

    print(f'health: {client.health()}')
    result = client.synthesize(args.text, output_path=args.output, voice=args.voice, speed=args.speed)
    print(f'engine: {result.get("engine")}, voice: {result.get("voice")}')
    print(f'duration: {result["duration"]}s')
    print(f'saved: {result.get("audio_path")}')
    print(f'timestamps: {json.dumps(result["timestamps"], ensure_ascii=False, indent=2)}')
