"""D 层 Agent（薄包装）：选题、编剧、风格/音效/特效决策。"""
import os
import sys

_ROOT = os.path.abspath(__file__)
for _ in range(3):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agents.base import TaskResult, register

EFFECTS = ['none', 'flash', 'punch_in', 'glitch', 'grain_vignette',
           'speed_ramp', 'freeze_zoom', 'wipe', 'zoom']
TRANSITIONS = ['fade', 'fadeblack', 'fadewhite', 'wipeleft', 'slideleft',
               'circleopen', 'dissolve']
LUT_STYLES = ['cinematic', 'warm', 'cool', 'vintage', 'vivid', 'soft']
BGM_MOODS = ['calm', 'uplifting', 'mysterious', 'dramatic', 'playful']


@register(name='director.scriptwrite', layer='director',
          desc='概念 → 分镜脚本 JSON（含角色锚/运镜/时长拆解）',
          inputs='{concept, character_desc?, target_duration?}')
def scriptwrite(p):
    from agents.common.tools.llm import LLMClient
    llm = LLMClient()
    script = llm.script_write(p['concept'], p.get('character_desc'),
                              p.get('target_duration'))
    return TaskResult(ok=True, artifacts={'script': script},
                      trace=[{'step': 'script_write', 'shots': len(script.get('shots', []))}])


@register(name='director.scout', layer='director',
          desc='热榜抓取 → LLM 选题评分', inputs='{account_type?, top_per_source?}')
def scout(p):
    from agents.common.tools.llm import LLMClient
    from agents.common.tools.crawler import HotTopicCrawler
    topics = HotTopicCrawler().fetch_hot_topics(
        top_per_source=p.get('top_per_source', 20))
    scored = LLMClient().scout_topics(topics, p.get('account_type', ''))
    return TaskResult(ok=True, artifacts={'topics': scored},
                      trace=[{'step': 'scout', 'raw': len(topics)}])


@register(name='director.select_lut', layer='director',
          desc='按脚本情绪选 LUT 风格', inputs='{concept?, script}')
def select_lut(p):
    from agents.common.tools.llm import LLMClient
    lut = LLMClient().select_lut(p.get('concept', ''), p['script'], LUT_STYLES)
    ok = lut in LUT_STYLES
    return TaskResult(ok=ok, artifacts={'lut': lut}, score=None,
                      error='' if ok else '未知 LUT: %s' % lut)


@register(name='director.select_bgm', layer='director',
          desc='按脚本情绪选 BGM 情绪标签', inputs='{concept?, script}')
def select_bgm(p):
    from agents.common.tools.llm import LLMClient
    mood = LLMClient().select_bgm_mood(p.get('concept', ''), p['script'], BGM_MOODS)
    ok = mood in BGM_MOODS
    return TaskResult(ok=ok, artifacts={'bgm_mood': mood},
                      error='' if ok else '未知 BGM mood: %s' % mood)


@register(name='director.select_effects', layer='director',
          desc='LLM 逐镜选特效 + 镜间转场', inputs='{script}')
def select_effects(p):
    from agents.common.tools.llm import LLMClient
    picks = LLMClient().select_effects(p['script'], EFFECTS, TRANSITIONS)
    return TaskResult(ok=True, artifacts={'effect_picks': picks})


@register(name='director.brain', layer='director',
          desc='智囊：任意 LLM API 一问一答（model 可换，剧本/文案/决策通用）',
          inputs='{prompt|question, system?, model?, temperature?, json?}')
def brain(p):
    from agents.common.tools.llm import LLMClient
    from agents.common.tools.config_loader import load_config
    llm = LLMClient(load_config())
    msgs = []
    if p.get('system'):
        msgs.append({'role': 'system', 'content': p['system']})
    msgs.append({'role': 'user', 'content': p.get('prompt') or p.get('question') or ''})
    kw = {'model': p.get('model'), 'temperature': p.get('temperature', 0.7)}
    kw = {k: v for k, v in kw.items() if v is not None}
    try:
        if p.get('json'):
            ans = llm.chat_json(msgs, **kw)
        else:
            ans = llm.chat(msgs, **kw)
        if not ans:
            return TaskResult(ok=False, error='LLM 空回复')
        import json as _json
        return TaskResult(ok=True, artifacts={
            'answer': _json.dumps(ans, ensure_ascii=False) if p.get('json') else ans})
    except Exception as e:
        return TaskResult(ok=False, error='brain: %s' % str(e)[:200])
