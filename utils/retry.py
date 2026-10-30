"""v17 M7 重试标准化：llm/tts/comfy 三客户端统一重试封装（tenacity）。

ViMax 多级重试是同款需求背书。用法：

    from utils.retry import retry_net

    @retry_net('llm')                     # 或 @retry_net('tts') / @retry_net('comfy')
    def call_something(...): ...

策略（按服务特点分级）：
- llm   端点延迟波动大：3 次尝试，指数退避 2/8/32s（max 60），超时不抛（调用方自带 timeout）
- tts   本地 GPU 服务，失败多为瞬时：3 次，固定间隔 2s
- comfy 排队型长任务：2 次，间隔 10s（长任务失败重跑代价高，少试）

统一约定：只对网络/瞬时类异常重试（ConnectionError/TimeoutError/URLError/
HTTPError 5xx/429）；4xx 客户端错误不重试直接抛。
"""
import urllib.error
import urllib.request

from tenacity import (retry, retry_if_exception, stop_after_attempt,
                      wait_fixed, wait_exponential)

__all__ = ['retry_net', 'is_retryable', 'RetryableError']


class RetryableError(Exception):
    """包装非网络异常使其可重试（调用方把瞬时故障包进来）。"""


def is_retryable(e: BaseException) -> bool:
    """网络/瞬时类异常判定（4xx 客户端错误不重试）。"""
    if isinstance(e, RetryableError):
        return True
    if isinstance(e, urllib.error.HTTPError):
        return e.code >= 500 or e.code == 429
    if isinstance(e, (urllib.error.URLError, ConnectionError,
                      TimeoutError, OSError)):
        # HTTPError 是 URLError 子类，已在上面处理；OSError 兜底 socket 层
        return not isinstance(e, urllib.error.HTTPError)
    return False


def _policy(name: str):
    if name == 'llm':
        return dict(stop=stop_after_attempt(3),
                    wait=wait_exponential(multiplier=2, min=2, max=60))
    if name == 'tts':
        return dict(stop=stop_after_attempt(3), wait=wait_fixed(2))
    if name == 'comfy':
        return dict(stop=stop_after_attempt(2), wait=wait_fixed(10))
    raise ValueError(f'未知重试策略: {name}（llm/tts/comfy）')


def retry_net(service: str, reraise: bool = True):
    """统一网络重试装饰器。service ∈ {llm, tts, comfy}。"""
    policy = _policy(service)
    return retry(retry=retry_if_exception(is_retryable),
                 reraise=reraise, **policy)
