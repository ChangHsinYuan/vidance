#!/usr/bin/env python3
"""v20 生成中审核：ComfyUI WS 预览帧监听 + 早停 interrupt

ComfyUI 服务端需以 --preview-method latent2rgb 启动（start_services.sh wan 已加）。
WS 二进制消息格式：u32 BE 事件类型（1=PREVIEW_IMAGE）+ u32 padding + PNG payload。
事件为全连接广播（M0 spike 实证：随机 clientId 可收到任意任务的预览/progress）。
"""
import json
import struct
import threading
import time
import urllib.request

BASE_PROMPT = 'http://127.0.0.1:8189'

try:
    import asyncio
    import websockets
except ImportError:  # pragma: no cover
    websockets = None


def parse_binary_preview(msg: bytes):
    """解析 WS 二进制消息 → (事件类型, payload)；非预览图返回 None"""
    if not isinstance(msg, bytes) or len(msg) <= 8:
        return None
    etype = struct.unpack('>I', msg[:4])[0]
    if etype != 1:  # 1 = PREVIEW_IMAGE
        return None
    return etype, msg[8:]


def interrupt_if_running(prompt_id: str, base_url: str = BASE_PROMPT,
                         timeout: float = 5.0) -> bool:
    """早停：先查 /queue 确认正在跑的是自己的 prompt_id（8189 同实例共存
    RIFE 等任务，防止误杀），再 POST /interrupt。返回是否真的发起。"""
    try:
        with urllib.request.urlopen(f'{base_url}/queue', timeout=timeout) as r:
            q = json.loads(r.read())
        running = q.get('queue_running') or []
        if not any(isinstance(e, (list, tuple)) and len(e) > 1
                   and e[1] == prompt_id for e in running):
            return False
        req = urllib.request.Request(f'{base_url}/interrupt', data=b'')
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception:
        return False


class PreviewListener:
    """后台线程收 WS 预览帧/进度。用法：
        li = PreviewListener(); li.start()
        prompt_id = client.queue_prompt(workflow)
        ... 采样中：li.latest_frame() → {'step': 8, 'png': bytes} | None
        li.interrupt() → 早停（内部校验归属）；li.close() 收尾
    """

    def __init__(self, base_url: str = BASE_PROMPT):
        self.base_url = base_url.replace('http', 'ws', 1)
        self.ws_base = base_url
        self._lock = threading.Lock()
        self._latest = None        # {'step': int, 'png': bytes, 't': float}
        self._progress = (0, 0)    # (value, max)
        self._done = threading.Event()
        self._thread = None

    def start(self):
        if websockets is None:
            raise RuntimeError('websockets 库不可用（pip install websockets）')
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        asyncio.run(self._listen())

    async def _listen(self):
        uri = f'{self.base_url}/ws?clientId=vidance_v20_{int(time.time()*1000)}'
        try:
            async with websockets.connect(uri, max_size=64 * 2 ** 20) as ws:
                while not self._done.is_set():
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    except Exception:
                        break
                    if isinstance(msg, bytes):
                        parsed = parse_binary_preview(msg)
                        if parsed:
                            with self._lock:
                                self._latest = {
                                    'step': self._progress[0],
                                    'png': parsed[1],
                                    't': time.time(),
                                }
                    else:
                        self._handle_text(msg)
        except Exception:
            pass  # 8189 重启/网络抖动：监听静默退出，主流程 wait_result 兜底

    def _handle_text(self, raw: str):
        try:
            d = json.loads(raw)
        except (ValueError, TypeError):
            return
        t = d.get('type')
        if t == 'progress':
            data = d.get('data', {})
            with self._lock:
                self._progress = (int(data.get('value', 0)),
                                  int(data.get('max', 0)) or 1)
        elif t == 'executing' and d.get('data', {}).get('node') is None:
            self._done.set()
        elif t == 'execution_error':
            self._done.set()

    def latest_frame(self):
        """当前最新预览帧 {'step', 'png', 't'}；尚无帧返回 None"""
        with self._lock:
            return dict(self._latest) if self._latest else None

    def progress(self):
        with self._lock:
            return self._progress

    def interrupt(self, prompt_id: str) -> bool:
        """校验归属后早停当前执行（见 interrupt_if_running）"""
        ok = interrupt_if_running(prompt_id, self.ws_base)
        self._done.set()
        return ok

    def mark_done(self):
        self._done.set()

    def close(self):
        self._done.set()
        if self._thread:
            self._thread.join(timeout=3)


class EarlyStopError(RuntimeError):
    """粗审判死提前止损（携带该次 verdict 信息）"""

    def __init__(self, verdict: dict):
        super().__init__(f'live-audit early stop: {verdict}')
        self.verdict = verdict


class live_audit_patch:
    """实例级补丁：临时给 ComfyClient 挂上"边生边审"，退出时还原。

    generate_i2v/generate_t2v 内部调用 self.queue_prompt/self.wait_result，
    实例属性遮蔽类方法 → 生成调用方代码零改动。用法：
        with live_audit_patch(vendor.client, scene_desc, cfg) as la:
            vendor.i2v(...)
        la.auditor.summary()  # {'reviews', 'fails', 'history'}
        la.interrupted        # 是否发生过早停
    粗审判死 → interrupt + 抛 EarlyStopError（调用方 continue 换 seed 重生成）。
    """

    def __init__(self, client, scene_desc: str, cfg: dict = None,
                 poll: float = 6.0, on_event=None):
        self.client = client
        self.scene_desc = scene_desc
        self.poll = poll
        self.on_event = on_event  # 回调（M3 前端 SSE 挂载点）: fn(event_dict)
        cfg = cfg or {}
        from agents.audit.tools.live_auditor import LiveAuditor
        self.auditor = LiveAuditor(max_reviews=int(cfg.get('max_reviews', 3)),
                                   min_step=int(cfg.get('min_step', 4)),
                                   timeout=float(cfg.get('timeout', 60)))
        self.listener = None
        self.prompt_id = None
        self.interrupted = False
        self._orig_queue = None
        self._orig_wait = None

    def __enter__(self):
        c = self.client
        self._orig_queue = c.queue_prompt
        self._orig_wait = c.wait_result
        c.queue_prompt = self._queue_prompt
        c.wait_result = self._wait_result
        return self

    def __exit__(self, *exc):
        c = self.client
        c.queue_prompt = self._orig_queue
        c.wait_result = self._orig_wait
        if self.listener:
            self.listener.close()
        return False

    def _emit(self, ev: dict):
        if self.on_event:
            try:
                self.on_event(ev)
            except Exception:
                pass

    def _queue_prompt(self, workflow):
        self.listener = PreviewListener(base_url=self.client.base_url)
        self.listener.start()
        self.prompt_id = self._orig_queue(workflow)
        self._emit({'kind': 'queued', 'prompt_id': self.prompt_id})
        return self.prompt_id

    def _wait_result(self, prompt_id: str, timeout: int = 3600):
        import threading
        box = {}

        def _wait():
            try:
                box['outputs'] = self._orig_wait(prompt_id, timeout)
            except Exception as e:
                box['err'] = e

        th = threading.Thread(target=_wait, daemon=True)
        th.start()
        last_step = -1
        while th.is_alive():
            fr = self.listener.latest_frame() if self.listener else None
            if fr and fr['step'] > last_step:
                last_step = fr['step']
                v = self.auditor.review(fr, self.scene_desc)
                if v['api']:
                    print(f'  [live-audit] step {fr["step"]}: {v["verdict"]} '
                          f'score={v["score"]} {str(v["reason"])[:48]}')
                    self._emit({'kind': 'review', 'step': fr['step'],
                                'verdict': v['verdict'], 'score': v['score'],
                                'reason': v['reason'], 'png': fr['png']})
                if v['verdict'] == 'fail':
                    self.interrupted = (self.listener.interrupt(prompt_id)
                                        if self.listener else False)
                    th.join(timeout=15)
                    raise EarlyStopError(v)
            time.sleep(self.poll)
        if self.listener:
            self.listener.mark_done()
        th.join(timeout=5)
        if 'err' in box:
            raise box['err']
        return box.get('outputs')
