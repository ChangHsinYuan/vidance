"""v13 Agent 契约（薄包装）+ 全局注册表。

每个层目录下的 agents.py 用 @register 把已有能力包装成 Agent：
    @register(name="audit.review_shot", layer="audit", desc="大模型审片")
    def review_shot(params: dict) -> TaskResult: ...

约定：run(params) 内部只做「参数适配 → 调既有能力 → 产物归集」，不重写业务逻辑。
"""
import os
import sys
import time
import traceback

_ROOT = os.path.abspath(__file__)
for _ in range(2):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

LAYERS = ('director', 'generator', 'post', 'audit')


class TaskResult:
    """一次 Agent 运行的统一返回。"""

    def __init__(self, agent='', ok=True, artifacts=None, trace=None, score=None, error=''):
        self.agent = agent
        self.ok = ok
        self.artifacts = artifacts or {}   # 产物: {key: path/dict}
        self.trace = trace or []           # [{step, detail, t}]
        self.score = score                 # audit 层产出的 0-1 评分（可 None）
        self.error = error

    def to_dict(self):
        return {'agent': self.agent, 'ok': self.ok, 'artifacts': self.artifacts,
                'trace': self.trace, 'score': self.score, 'error': self.error}

    @classmethod
    def from_dict(cls, d):
        return cls(agent=d.get('agent', ''), ok=d.get('ok', True),
                   artifacts=d.get('artifacts', {}), trace=d.get('trace', []),
                   score=d.get('score'), error=d.get('error', ''))


REGISTRY = {}


def register(name, layer, desc='', inputs='', needs_gpu=False):
    """装饰器：把 run(params)->TaskResult 的函数注册为 Agent。"""
    assert layer in LAYERS, 'layer must be one of %s' % (LAYERS,)

    def deco(fn):
        if name in REGISTRY:
            raise ValueError('duplicate agent: %s' % name)
        REGISTRY[name] = {'name': name, 'layer': layer, 'desc': desc,
                          'inputs': inputs, 'needs_gpu': needs_gpu, 'fn': fn}
        return fn
    return deco


def get(name):
    return REGISTRY.get(name)


def list_agents():
    return sorted(REGISTRY.values(), key=lambda a: (a['layer'], a['name']))


def default_out(name, stem='out', ext='mp4'):
    """缺省产出路径：{output_dir}/agent_{时间戳}_{agent短名}/stem.ext（成片不落 tmp/cwd）。"""
    import time
    from agents.common.tools.config_loader import load_config
    root = load_config().get('output_dir', 'output')
    d = os.path.join(root, 'agent_%s_%s' % (time.strftime('%Y%m%d_%H%M%S'),
                                            name.split('.')[-1]))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, '%s.%s' % (stem, ext))


def run_agent(name, params, board=None, task_id=''):
    """统一入口：计时 + trace + 黑板落盘 + 异常兜底。未加载时自举 load_all。"""
    spec = REGISTRY.get(name)
    if spec is None:
        try:
            from agents.runtime import load_all
            load_all()
            spec = REGISTRY.get(name)
        except Exception:
            pass
    if spec is None:
        return TaskResult(agent=name, ok=False, error='unknown agent: %s' % name)
    t0 = time.time()
    try:
        res = spec['fn'](params or {})
        if not isinstance(res, TaskResult):
            res = TaskResult(agent=name, ok=True,
                            artifacts=res if isinstance(res, dict) else {'out': res})
        res.agent = name
    except Exception as e:
        res = TaskResult(agent=name, ok=False, error='%s: %s' % (e, traceback.format_exc(limit=3)))
    dur = round(time.time() - t0, 2)
    if board is not None:
        try:
            board.log(task_id=task_id, agent=name, layer=spec['layer'],
                      ok=res.ok, score=res.score, artifacts=res.artifacts,
                      error=res.error, t_dur=dur)
        except Exception:
            pass  # 黑板失败不影响主流程
    return res
