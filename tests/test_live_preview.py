#!/usr/bin/env python3
"""v20 生成中审核 纯逻辑测试 — 不依赖 GPU/网络（10 项）

覆盖：二进制预览消息解析 / 进度与完成事件状态机 / 帧结构判定 /
粗审节流与 skip 逻辑（mock LLM）/ config 安全读取。
"""
import io
import json
import os
import struct
import sys
import time

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agents.generator.tools.comfy_preview import (PreviewListener,
                                                  interrupt_if_running,
                                                  parse_binary_preview)
from agents.audit.tools.live_auditor import LiveAuditor, frame_structured, load_cfg

PASS = []


def ok(name, cond, detail=''):
    PASS.append((name, bool(cond)))
    print(f'{"✓" if cond else "✗"} {name}' + (f' — {detail}' if detail else ''))


def _png(std_target=10.0, size=(64, 64)) -> bytes:
    rng = np.random.default_rng(0)
    base = rng.normal(128, std_target, (*size, 3))
    arr = np.clip(base, 0, 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format='PNG')
    return buf.getvalue()


# ── 1. 二进制消息解析 ──
payload = _png()
msg = struct.pack('>II', 1, 0) + payload
r = parse_binary_preview(msg)
ok('PREVIEW_IMAGE 解析出 PNG payload', r and r[0] == 1 and r[1] == payload)
ok('非预览类型（type=2）返回 None', parse_binary_preview(struct.pack('>II', 2, 0) + payload) is None)
ok('过短消息返回 None', parse_binary_preview(b'\x00\x01') is None)
ok('文本消息返回 None', parse_binary_preview(b'{"type":"progress"}') is None)

# ── 2. PreviewListener 状态机（直接喂事件，不起 WS）──
li = PreviewListener.__new__(PreviewListener)  # 跳过 start()，只测逻辑
import threading
li._lock = threading.Lock()
li._latest = None
li._progress = (0, 0)
li._done = threading.Event()
li._handle_text(json.dumps({'type': 'progress', 'data': {'value': 8, 'max': 20}}))
ok('progress 事件更新步数', li.progress() == (8, 20))
li._handle_text(json.dumps({'type': 'executing', 'data': {'node': '8'}}))
ok('节点 executing 不误判完成', not li._done.is_set())
li._handle_text(json.dumps({'type': 'executing', 'data': {'node': None}}))
ok('node=None 判定执行结束', li._done.is_set())
li._latest = {'step': 8, 'png': payload, 't': time.time()}
fr = li.latest_frame()
ok('latest_frame 返回帧且防篡改（拷贝）', fr and fr['step'] == 8 and fr['png'] == payload
   and fr is not li._latest)
li._done.clear()
li._handle_text('not-json')
ok('坏 JSON 不崩', not li._done.is_set())

# ── 3. 帧结构判定 ──
ok('噪声帧有结构', frame_structured(_png(std_target=60)))
ok('全白帧无结构（跳过不发 API）', not frame_structured(_png(std_target=1)))
ok('坏字节判无结构', not frame_structured(b'broken'))

# ── 4. 粗审逻辑（mock LLM）──
class MockLLM:
    def __init__(self, resp): self.resp, self.calls = resp, 0
    def chat_json(self, *a, **k):
        self.calls += 1
        if isinstance(self.resp, Exception): raise self.resp
        return self.resp

# 4.1 早期 step skip
au = LiveAuditor(llm_client=MockLLM({'score': 2, 'fail': True, 'reason': 'x'}))
v = au.review({'step': 2, 'png': _png(60)}, '雪地狐狸')
ok('step<min_step 跳过不调 API', v['verdict'] == 'skip' and not v['api'])

# 4.2 无结构帧 skip
v = au.review({'step': 8, 'png': _png(1)}, '雪地狐狸')
ok('无结构帧跳过', v['verdict'] == 'skip')

# 4.3 fail 判定（score 低）
v = au.review({'step': 8, 'png': _png(60)}, '雪地狐狸')
ok('score<4 判 fail', v['verdict'] == 'fail' and v['api'])

# 4.4 pass 判定（模糊不扣分）
au2 = LiveAuditor(llm_client=MockLLM({'score': 7, 'fail': False, 'reason': '主体吻合'}))
v = au2.review({'step': 10, 'png': _png(60)}, '雪地狐狸')
ok('score>=4 判 pass', v['verdict'] == 'pass')

# 4.5 fail=true 直接判死
au3 = LiveAuditor(llm_client=MockLLM({'score': 8, 'fail': True, 'reason': '花屏'}))
v = au3.review({'step': 10, 'png': _png(60)}, '雪地狐狸')
ok('fail=true 判死（即使分高）', v['verdict'] == 'fail')

# 4.6 节流：max_reviews 用尽
au4 = LiveAuditor(max_reviews=1, llm_client=MockLLM({'score': 9, 'fail': False}))
au4.review({'step': 8, 'png': _png(60)}, 'a')
v = au4.review({'step': 12, 'png': _png(60)}, 'a')
ok('max_reviews 节流生效', v['verdict'] == 'skip' and au4.reviews_used == 1)

# 4.7 API 异常放行（不阻塞生成）
au5 = LiveAuditor(llm_client=MockLLM(RuntimeError('timeout')))
v = au5.review({'step': 8, 'png': _png(60)}, 'a')
ok('粗审 API 异常放行', v['verdict'] == 'pass' and '异常' in v['reason'])

# 4.8 summary 落 meta
s = au3.summary()
ok('summary 记录 reviews/fails', s['reviews'] == 1 and s['fails'] == 1 and len(s['history']) == 1)

# ── 5. interrupt 归属校验（mock urlopen）──
import urllib.request
from unittest import mock
fake_q = json.dumps({'queue_running': [[0, 'pid-abc'], [1, 'pid-other']],
                     'queue_pending': []}).encode()
with mock.patch.object(urllib.request, 'urlopen') as mu:
    mu.return_value.__enter__.return_value.read.return_value = fake_q
    ok('目标在跑 → 发 interrupt',
       interrupt_if_running('pid-abc', 'http://x') is True)
    ok('目标不在跑 → 不发',
       interrupt_if_running('pid-missing', 'http://x') is False)

# ── 6. config 安全读取 ──
cfg = load_cfg({'v20_live_audit': {'enabled': True, 'max_reviews': 5}})
ok('config 读取覆盖默认', cfg['enabled'] and cfg['max_reviews'] == 5)
ok('config 缺省 = 关闭', load_cfg({})['enabled'] is False)

print(f'\n{sum(1 for _, c in PASS if c)}/{len(PASS)} passed')
sys.exit(0 if all(c for _, c in PASS) else 1)
