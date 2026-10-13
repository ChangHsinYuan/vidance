"""A2 preflight 单元测试（无 pytest，探测函数全部 mock，不依赖真实服务）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.preflight import Preflight, PreflightError, _MODE_DEPS

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


def main():
    pf = Preflight(config={'llm': {'base_url': 'http://x', 'api_key': 'k'},
                           'tts': {'host': '127.0.0.1', 'port': 1},
                           'comfyui': {'wan': {'host': '127.0.0.1', 'port': 1},
                                       'h3': {'host': '127.0.0.1', 'port': 1}}})

    # 探测函数 mock：按名字返回 (ok, detail)
    MOCK = {
        'llm': (True, 'mock-ok'),
        'ffmpeg': (True, '/usr/bin/ffmpeg'),
        'tts': (False, 'down'),
        'wan': (False, 'down'),
        'crawler': (True, 'mock-ok'),
        'images': (False, 'down'),
    }
    pf._CHECKS = {k: (lambda self, _k=k: MOCK[_k]) for k in MOCK.keys()}
    pf.check_comfy = lambda key: MOCK.get(key, (False, 'unmocked'))

    # 1. skip 直接放行
    r = pf.check('auto', skip=True)
    ok('skip returns ok', r['ok'] and not r['checks'])

    # 2. fast：llm/ffmpeg 硬依赖 ✓，tts/images 可降级 ⚠ → 放行
    r = pf.check('fast')
    ok('fast passes with degradable down', r['ok'] and len(r['warnings']) == 2)

    # 3. auto：wan 硬依赖挂 → PreflightError
    try:
        pf.check('auto', character='猫')
        ok('auto raises on wan down', False)
    except PreflightError as e:
        ok('auto raises on wan down', 'Wan' in str(e) and '--no-preflight' in str(e))

    # 4. auto 无 character：flux 豁免（不探测）
    called = []
    orig = pf.check_comfy
    pf.check_comfy = lambda key: (called.append(key), MOCK.get(key, (False, 'x')))[1]
    try:
        pf.check('auto', character=None)
        ok('auto without character raises on wan', False)
    except PreflightError:
        pass
    ok('flux exempted without character', 'flux' not in called)
    pf.check_comfy = orig

    # 5. hot 依赖表包含 crawler
    ok('hot deps include crawler', any(k == 'crawler' for _, k, _, _ in _MODE_DEPS['hot']))

    # 6. hard 标记正确：fast 里 llm/ffmpeg 是硬依赖，tts/images 是可降级
    deps = {k: r for _, k, r, _ in _MODE_DEPS['fast']}
    ok('fast llm hard', deps['llm'] is True and deps['tts'] is False)

    failed = [n for n, c in PASS if not c]
    print(f"\n{len(PASS) - len(failed)}/{len(PASS)} passed")
    if failed:
        print('FAILED:', failed)
        sys.exit(1)


if __name__ == '__main__':
    main()
