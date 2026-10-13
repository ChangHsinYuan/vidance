#!/usr/bin/env python3
"""preflight 预检 — 借鉴 MoneyPrinterTurbo app/services/task.py::preflight

开跑前统一探测本次任务依赖的服务，避免"fast 爬 20 分钟图后才发现 I2V 挂了"
这类浪费。与 MPT 的差异：vidance 有降级兜底哲学（服务全关 fast 也能出片），
因此分两档——

  硬依赖（required=True）挂  → PreflightError，任务不启动（MPT 式 fail-fast）
  可降级依赖（required=False）挂 → ⚠ 警告继续，任务走降级路径（vidance 式兜底）

跳过：CLI 传 --no-preflight，或 Preflight.check(mode, skip=True)。

用法:
    from core.preflight import Preflight, PreflightError
    try:
        Preflight(config).check('auto', character=character)
    except PreflightError as e:
        print(e); sys.exit(1)
"""

import shutil
import time
import urllib.request

HARD = True
DEGRADABLE = False

# 模式 → [(name, check_key, required, desc)]，check_key 见 _CHECKS
_MODE_DEPS = {
    'auto': [
        ('llm', 'llm', HARD, 'LLM 编剧'),
        ('ffmpeg', 'ffmpeg', HARD, 'ffmpeg 合成'),
        ('wan', 'wan', HARD, 'Wan I2V 生成'),
        ('flux', 'flux', DEGRADABLE, 'FLUX 参考帧（缺则占位降级）'),
        ('tts', 'tts', DEGRADABLE, 'TTS 配音（缺则静音兜底）'),
    ],
    'quick': [
        ('ffmpeg', 'ffmpeg', HARD, 'ffmpeg 合成'),
        ('wan', 'wan', HARD, 'Wan T2V 生成'),
    ],
    'custom': [
        ('ffmpeg', 'ffmpeg', HARD, 'ffmpeg 合成'),
        ('h3', 'h3', HARD, 'H3 ref2va 生成'),
        ('tts', 'tts', DEGRADABLE, 'TTS 配音（缺则静音兜底）'),
    ],
    'fast': [
        ('llm', 'llm', HARD, 'LLM 旁白规划'),
        ('ffmpeg', 'ffmpeg', HARD, 'ffmpeg 合成'),
        ('tts', 'tts', DEGRADABLE, 'TTS 配音（缺则静音兜底）'),
        ('images', 'images', DEGRADABLE, '图源（缺则 FLUX/占位图降级）'),
    ],
    'hot': [
        ('crawler', 'crawler', HARD, '热点爬虫（无热点无法选题）'),
        ('llm', 'llm', HARD, 'LLM 选题+旁白'),
        ('ffmpeg', 'ffmpeg', HARD, 'ffmpeg 合成'),
        ('tts', 'tts', DEGRADABLE, 'TTS 配音（缺则静音兜底）'),
        ('images', 'images', DEGRADABLE, '图源（缺则 FLUX/占位图降级）'),
    ],
}


class PreflightError(RuntimeError):
    """硬依赖预检失败，任务不启动。"""


class Preflight:
    def __init__(self, config: dict = None):
        if config is None:
            from utils.config_loader import load_config
            config = load_config()
        self.config = config

    # ── 单项探测 ──

    def _probe_http(self, url: str, timeout: float = 3.0) -> tuple:
        """GET url，返回 (ok, detail)。2xx/3xx 视为可达。"""
        try:
            t0 = time.time()
            req = urllib.request.Request(url, headers={'User-Agent': 'vidance-preflight'})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ms = (time.time() - t0) * 1000
                return True, f'HTTP {resp.status} ({ms:.0f}ms)'
        except Exception as e:
            return False, str(e)[:120]

    def check_llm(self) -> tuple:
        cfg = self.config.get('llm', {})
        base = cfg.get('base_url', '').rstrip('/')
        if not base:
            return False, 'llm.base_url 未配置'
        url = f'{base}/models'
        try:
            req = urllib.request.Request(url, headers={
                'Authorization': f'Bearer {cfg.get("api_key", "")}',
                'User-Agent': 'vidance-preflight',
            })
            with urllib.request.urlopen(req, timeout=6) as resp:
                return True, f'HTTP {resp.status}'
        except Exception as e:
            return False, str(e)[:120]

    def check_tts(self) -> tuple:
        cfg = self.config.get('tts', {})
        host, port = cfg.get('host', '127.0.0.1'), cfg.get('port', 9880)
        return self._probe_http(f'http://{host}:{port}/health')

    def check_comfy(self, key: str) -> tuple:
        cfg = self.config.get('comfyui', {}).get(key)
        if not cfg:
            return False, f'comfyui.{key} 未配置'
        host, port = cfg.get('host'), cfg.get('port')
        return self._probe_http(f'http://{host}:{port}/')

    def check_ffmpeg(self) -> tuple:
        ff, fp = shutil.which('ffmpeg'), shutil.which('ffprobe')
        if ff and fp:
            return True, ff
        return False, f'ffmpeg={ff} ffprobe={fp}'

    def check_crawler(self) -> tuple:
        # 热点源外网可达性（B 站 API 轻量探测）
        return self._probe_http('https://api.bilibili.com/x/web-interface/ranking/v2?ps=1', timeout=5)

    def check_images(self) -> tuple:
        # 图源可用性：Pexels key 配置或必应可达即算过
        if self.config.get('pexels', {}).get('api_key'):
            ok, detail = self._probe_http('https://api.pexels.com/v1/curated?per_page=1', timeout=5)
            if ok:
                return True, 'pexels'
        return self._probe_http('https://cn.bing.com/images/async?q=test&first=0&count=1', timeout=5)

    _CHECKS = {
        'llm': check_llm,
        'tts': check_tts,
        'ffmpeg': check_ffmpeg,
        'crawler': check_crawler,
        'images': check_images,
    }

    # ── 汇总 ──

    def check(self, mode: str, character: str = None, skip: bool = False,
              extra_hard: list = None) -> dict:
        """按模式跑预检。返回 {'ok', 'checks', 'hard_failures', 'warnings'}。

        - 硬依赖失败 → 抛 PreflightError（附完整清单）
        - character 为空时 auto 模式豁免 flux 检查（纯 T2V 不需要参考帧）
        - skip=True 直接返回 ok（--no-preflight）
        """
        if skip:
            return {'ok': True, 'checks': [], 'hard_failures': [], 'warnings': []}

        deps = list(_MODE_DEPS.get(mode, []))
        if mode == 'auto' and not character:
            deps = [(n, k, r, d) for (n, k, r, d) in deps if k != 'flux']
        if extra_hard:
            deps += [(n, k, HARD, n) for n in extra_hard]

        results = []
        for name, key, required, desc in deps:
            if key in self._CHECKS:
                ok, detail = self._CHECKS[key](self)
            else:
                ok, detail = self.check_comfy(key)
            results.append({'name': name, 'required': required, 'ok': ok,
                            'detail': detail, 'desc': desc})

        hard_failures = [r for r in results if not r['ok'] and r['required']]
        warnings = [r for r in results if not r['ok'] and not r['required']]

        print(f'\n=== [preflight] 预检（{mode}）===')
        for r in results:
            mark = '✓' if r['ok'] else ('✗' if r['required'] else '⚠')
            tag = '' if r['ok'] else (' [必需]' if r['required'] else ' [可降级]')
            print(f'  {mark} {r["desc"]}: {r["detail"]}{tag}')

        if warnings:
            print(f'  ⚠ {len(warnings)} 项可降级依赖不可用，任务将继续（走缺省兜底）')
        if hard_failures:
            names = ', '.join(r['desc'] for r in hard_failures)
            raise PreflightError(
                f'预检失败，任务未启动。必需依赖不可用: {names}。\n'
                f'  → 请检查服务是否在线（./start_services.sh status），'
                f'或用 --no-preflight 跳过预检强制运行')

        return {'ok': True, 'checks': results,
                'hard_failures': [], 'warnings': warnings}


if __name__ == '__main__':
    import argparse
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    parser = argparse.ArgumentParser(description='preflight 预检')
    parser.add_argument('mode', choices=sorted(_MODE_DEPS.keys()), nargs='?', default='fast')
    parser.add_argument('--character', default=None)
    args = parser.parse_args()
    try:
        Preflight().check(args.mode, character=args.character)
        print('preflight OK')
    except PreflightError as e:
        print(f'preflight FAILED:\n{e}')
        raise SystemExit(1)
