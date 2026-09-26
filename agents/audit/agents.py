"""V 层 Agent（薄包装）：大模型审片/评分。M2 在此扩展 ensemble 多票投票。"""
import os
import sys

_ROOT = os.path.abspath(__file__)
for _ in range(3):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agents.base import TaskResult, register


@register(name='audit.review_shot', layer='audit',
          desc='抽帧审片：画面质量/一致性打分',
          inputs='{scene_desc, frame_paths, char_ref?, model?}')
def review_shot(p):
    from agents.common.tools.llm import LLMClient
    r = LLMClient().review_shot(p['scene_desc'], p['frame_paths'],
                                model=p.get('model'),
                                character_ref=p.get('char_ref'))
    return TaskResult(ok=True, artifacts={'review': r},
                      score=r.get('score'), trace=[{'step': 'review_shot'}])


@register(name='audit.review_character', layer='audit',
          desc='角色一致性审片（参考图 vs 预览图）',
          inputs='{character_ref, preview_paths}')
def review_character(p):
    from agents.common.tools.llm import LLMClient
    r = LLMClient().review_character(p['character_ref'], p['preview_paths'])
    return TaskResult(ok=True, artifacts={'review': r}, score=r.get('score'))


@register(name='audit.relevance', layer='audit',
          desc='图文相关性评估', inputs='{image_path, query, model?}')
def relevance(p):
    from agents.common.tools.llm import LLMClient
    r = LLMClient().assess_image_relevance(p['image_path'], p['query'],
                                           model=p.get('model'))
    return TaskResult(ok=True, artifacts={'relevance': r}, score=r.get('score'))


@register(name='audit.describe_character', layer='audit',
          desc='图片 → 角色外观描述（可入库做锚）', inputs='{image_path, name?}')
def describe(p):
    from agents.common.tools.llm import LLMClient
    desc = LLMClient().describe_character(p['image_path'], p.get('name'))
    return TaskResult(ok=bool(desc), artifacts={'description': desc})


DEFAULT_ENSEMBLE = ['qwen3.8-chat']


@register(name='audit.review_ensemble', layer='audit',
          desc='多模型投票审片（默认单票，可扩 models 列表）',
          inputs='{scene_desc, frame_paths, models?, char_ref?}')
def review_ensemble(p):
    from agents.common.tools.llm import LLMClient
    models = p.get('models') or DEFAULT_ENSEMBLE
    client = LLMClient()
    votes, trace = [], []
    for m in models:
        try:
            r = client.review_shot(p['scene_desc'], p['frame_paths'],
                                   model=m, character_ref=p.get('char_ref'))
            votes.append({'model': m, 'score': r.get('score'),
                          'pass': r.get('pass'), 'feedback': r.get('feedback', '')})
            trace.append({'step': 'vote', 'model': m, 'score': r.get('score')})
        except Exception as e:
            votes.append({'model': m, 'score': None, 'error': str(e)[:200]})
            trace.append({'step': 'vote', 'model': m, 'error': str(e)[:100]})
    scored = [v['score'] for v in votes if isinstance(v.get('score'), (int, float))]
    # 归一（USTC 池评分 1-10）→ 0-1
    norm = [s / 10.0 for s in scored]
    score = round(sum(norm) / len(norm), 3) if norm else None
    passes = [v.get('pass') for v in votes if 'pass' in v]
    passed = all(passes) if passes else False
    return TaskResult(ok=bool(scored), score=score,
                      artifacts={'votes': votes, 'passed': passed},
                      trace=trace,
                      error='' if scored else '所有评审模型均失败')
