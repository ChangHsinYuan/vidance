"""任务明细日志的线程上下文（tid + agent 名）。

agents/base.run_agent 进入时 set_log(task_id, agent)，此后
core/pipeline 等被调方通过 log() 把明细追加到 output/{tid}/agent.log，
日志面板 /api/tasks/{tid}/log 直接可读。
"""
import os
import threading
from datetime import datetime

_local = threading.local()


def set_log(tid, agent=''):
    _local.tid = tid
    _local.agent = agent


def log(msg, out_dir='output'):
    """追加明细到 output/{tid}/agent.log（无 tid 上下文时静默跳过）。"""
    tid = getattr(_local, 'tid', None)
    if not tid:
        return
    agent = getattr(_local, 'agent', '') or ''
    line = '[%s] %s%s' % (datetime.now().strftime('%H:%M:%S'),
                          ('[%s] ' % agent) if agent else '', msg)
    try:
        d = os.path.join(out_dir, tid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'agent.log'), 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass
