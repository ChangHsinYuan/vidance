"""v17 M7 重试标准化单测（无 pytest，直接跑）。"""
import os
import sys
import time
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.retry import RetryableError, is_retryable, retry_net

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


class Flaky:
    """前 n-1 次抛指定异常，最后一次成功。"""
    def __init__(self, fails, exc):
        self.fails = fails
        self.exc = exc
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.fails:
            raise self.exc
        return 'ok'


def main():
    # is_retryable 判定
    ok('HTTPError 500 retryable', is_retryable(urllib.error.HTTPError(
        'u', 500, 'e', None, None)))
    ok('HTTPError 429 retryable', is_retryable(urllib.error.HTTPError(
        'u', 429, 'e', None, None)))
    ok('HTTPError 404 NOT retryable', not is_retryable(urllib.error.HTTPError(
        'u', 404, 'e', None, None)))
    ok('URLError retryable', is_retryable(urllib.error.URLError('conn')))
    ok('TimeoutError retryable', is_retryable(TimeoutError('t')))
    ok('ValueError NOT retryable', not is_retryable(ValueError('v')))
    ok('RetryableError retryable', is_retryable(RetryableError('x')))

    # llm 策略：2 失败 + 1 成功（指数退避 2+4s，实测 ~6s）
    t0 = time.time()
    f = Flaky(2, urllib.error.URLError('flaky'))

    @retry_net('llm')
    def call():
        return f()

    ok('llm 3 次尝试后成功', call() == 'ok')
    ok('llm 恰好 3 次调用', f.calls == 3)
    waited = time.time() - t0
    ok(f'llm 指数退避生效（{waited:.1f}s ∈ [5,20]）', 5 <= waited <= 20)

    # 4xx 不重试：1 次即抛
    f404 = Flaky(1, urllib.error.HTTPError('u', 404, 'nf', None, None))

    @retry_net('tts')
    def call404():
        return f404()

    try:
        call404()
        ok('4xx 应抛', False)
    except urllib.error.HTTPError as e:
        ok(f'4xx 不重试直抛（{e.code}，调用 {f404.calls} 次）', f404.calls == 1)

    # comfy 策略：2 次上限
    f2 = Flaky(2, ConnectionError('down'))

    @retry_net('comfy')
    def call2():
        return f2()

    try:
        call2()
        ok('comfy 超限应抛', False)
    except ConnectionError:
        ok(f'comfy 2 次上限（调用 {f2.calls} 次）', f2.calls == 2)

    # RetryableError 包装可重试
    fw = Flaky(1, RuntimeError('wrapped'))

    @retry_net('tts')
    def callw():
        return fw()

    try:
        callw()
        ok('不可重试异常包装后应抛', False)
    except RuntimeError:
        ok('RuntimeError 默认不重试（包装层职责）', fw.calls == 1)

    fails = [n for n, c in PASS if not c]
    print(f'\n{len(PASS) - len(fails)}/{len(PASS)} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
