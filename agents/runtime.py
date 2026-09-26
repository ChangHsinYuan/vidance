"""v13 chain 运行器：按序执行 Agent，产物写入共享 ctx，支持 ${ctx.key} 模板引用。

步骤格式：
    {"agent": "post.fx", "with": {"video": "${video}", "effect": "zoom"},
     "as": "fxed", "optional": false}
- with 值中的 "${key}" 整体引用 → 原样传入（保留 dict/list 类型）；内嵌 ${key} → 字符串替换
- 每个 step 的 artifacts 以 f'{as或agent名}.{artifact名}' 与裸 artifact 名两种键并入 ctx
"""
import os
import re
import sys
import json
import time

_ROOT = os.path.abspath(__file__)
for _ in range(2):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agents.base import run_agent, REGISTRY, list_agents  # noqa: E402

_LOADED = False


def load_all():
    """导入各层 agents.py，填充 REGISTRY（幂等）。"""
    global _LOADED
    if _LOADED:
        return REGISTRY
    import importlib
    for layer in ('director', 'generator', 'post', 'audit'):
        try:
            importlib.import_module('agents.%s.agents' % layer)
        except ModuleNotFoundError as e:  # 层还没提供 agents.py 时容忍
            if 'agents' not in str(e):
                raise
    _LOADED = True
    return REGISTRY


_REF = re.compile(r'\$\{([\w.]+)\}')


def _lookup(key, ctx):
    if key not in ctx and key.startswith('ctx.'):
        key = key[4:]
    return ctx.get(key, _MISS)


_MISS = object()


def _resolve(v, ctx):
    if isinstance(v, str):
        m = _REF.fullmatch(v.strip())
        if m:
            val = _lookup(m.group(1), ctx)
            if val is _MISS:
                raise KeyError('chain: ${%s} 不在上下文中' % m.group(1))
            return val
        return _REF.sub(lambda mm: str(_lookup(mm.group(1), ctx)
                                      if _lookup(mm.group(1), ctx) is not _MISS
                                      else mm.group(0)), v)
    if isinstance(v, dict):
        return {k: _resolve(x, ctx) for k, x in v.items()}
    if isinstance(v, list):
        return [_resolve(x, ctx) for x in v]
    return v


def run_chain(steps, ctx=None, task_id='', board=None, on_event=None):
    """steps: [{agent, with?, as?, optional?}] → {ok, steps, ctx}"""
    load_all()
    from agents.blackboard import AgentBoard
    from agents.base import TaskResult
    board = board or AgentBoard()
    ctx = dict(ctx or {})
    results = []
    ok_all = True
    t0 = time.time()
    ev = (lambda **kw: on_event(kw)) if on_event else (lambda **kw: None)
    ev(event='start', total=len(steps))
    for i, step in enumerate(steps):
        name = step['agent']
        try:
            params = _resolve(step.get('with', {}), ctx)
        except KeyError as e:
            res = TaskResult(agent=name, ok=False, error=str(e))
        else:
            ev(event='step', i=i, name=name,
               args=json.dumps(step.get('with', {}), ensure_ascii=False, default=str)[:200])
            t1 = time.time()
            res = run_agent(name, params, board=board, task_id=task_id)
            ev(event='done', i=i, name=name, ok=res.ok,
               secs=round(time.time() - t1, 1), error=res.error or None,
               arts={k: str(v) for k, v in res.artifacts.items()})
        key = step.get('as') or name
        results.append({'i': i, 'key': key, **res.to_dict()})
        if res.ok:
            for ak, av in res.artifacts.items():
                ctx['%s.%s' % (key, ak)] = av
                ctx.setdefault(ak, av)
        else:
            ok_all = False
            if not step.get('optional'):
                break
    return {'ok': ok_all, 'task_id': task_id, 'steps': results, 'ctx': ctx,
            't_dur': round(time.time() - t0, 2)}


if __name__ == '__main__':
    ap = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(run_chain(ap.get('steps', ap.get('chain', [])),
                               ctx=ap.get('ctx'), task_id=ap.get('task_id', 'cli')),
                     ensure_ascii=False, indent=2, default=str))
