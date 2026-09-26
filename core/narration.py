#!/usr/bin/env python3
"""P0/P1 配音与字幕（v12（原 v17）三排正交·后期层单一实现）

fastline / svg_pipeline / pipeline 原各自维护一份"TTS+降级链+SRT"，本模块收口：
  - Narrator.say   逐段 TTS：目标音色重试 → cosy-default → 静音兜底（出片不崩）
  - Narrator.silence  ffmpeg 静音 wav（24kHz mono 16bit，与 TTS 输出一致）
  - Narrator.srt   字幕条目 [{start,end,text}] → SRT 文件
用法：
  from core.narration import Narrator
  n = Narrator()
  n.say('你好', 'seg_1.wav', voice='cosy-default')
  n.srt([{'start': 0, 'end': 2.5, 'text': '你好'}], 'subtitle.srt')
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Narrator:
    def __init__(self, config=None):
        from utils.config_loader import load_config
        from utils.tts import TTSClient
        self.config = config or load_config()
        self.tts = TTSClient(self.config)
        self.default_voice = self.config.get('tts', {}).get('default_voice', 'cosy-default')

    def say(self, text, out_path, voice=None, speed=1.0, fallback_seconds=4.0, retries=3):
        """合成一段配音。降级链：目标音色(重试) → cosy-default → 静音。返回音频路径。"""
        import time as _time
        voice = voice or self.default_voice
        last = None
        for attempt in range(1, retries + 1):
            try:
                r = self.tts.synthesize(text, output_path=out_path, voice=voice, speed=speed)
                if attempt > 1:
                    print(f'    [TTS 重试成功] 第 {attempt} 次（{voice}）')
                return r.get('audio_path', out_path)
            except Exception as e:
                last = e
                if attempt < retries:
                    print(f'    ⚠ TTS 第 {attempt}/{retries} 次失败（{voice}）: {e}，重试…')
                    _time.sleep(1.5 * attempt)
        if voice != 'cosy-default':
            try:
                print(f'  ⚠ [TTS 降级] {voice} 不可用（{last}），改用本地 cosy-default')
                r = self.tts.synthesize(text, output_path=out_path, voice='cosy-default',
                                        speed=speed)
                return r.get('audio_path', out_path)
            except Exception as e:
                last = e
        print(f'  ⚠ [TTS 缺省] TTS 服务不可用（{last}），静音 {fallback_seconds}s 兜底')
        print('    （启动 TTS: CUDA_VISIBLE_DEVICES=2 TTS_FP16=1 python utils/tts_server.py）')
        self.silence(out_path, fallback_seconds)
        return out_path

    @staticmethod
    def silence(out_path, seconds):
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
        subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=24000:cl=mono',
                        '-t', str(seconds), '-c:a', 'pcm_s16le', out_path],
                       capture_output=True, timeout=30, check=True)

    @staticmethod
    def srt_time(seconds):
        ms = int(round(seconds * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'

    @staticmethod
    def srt(entries, out_path):
        """entries: [{'start','end','text'}] → SRT 文件。返回路径。"""
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            for i, x in enumerate(entries, 1):
                f.write(f"{i}\n{Narrator.srt_time(x['start'])} --> "
                        f"{Narrator.srt_time(x['end'])}\n{x['text']}\n\n")
        return out_path
