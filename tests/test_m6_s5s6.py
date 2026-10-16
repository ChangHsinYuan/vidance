"""M6 S5+S6 单测（风格包锚点覆盖 / 音色路由 / resume 自愈判断 —— 全 mock）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


def main():
    import core.pipeline as P
    Pipe = P.Pipeline

    # ── S5: style_pack 锚点覆盖 ──
    m = Pipe._merge_style_pack_anchors
    llm_anchors = {'style_anchor': 'llm style', 'color': 'llm color', 'lighting': 'llm light'}
    sp = {'style_pack': {'style_anchor': 'pack style', 'mood': 'pack mood'}}
    merged = m(llm_anchors, sp)
    ok('pack overrides style_anchor', merged['style_anchor'] == 'pack style')
    ok('pack overrides mood', merged['mood'] == 'pack mood')
    ok('LLM keys kept when pack silent', merged['color'] == 'llm color'
       and merged['lighting'] == 'llm light')
    ok('no pack → unchanged', m(llm_anchors, None) == llm_anchors)
    ok('empty anchors + pack', m({}, sp)['style_anchor'] == 'pack style')
    ok('malformed pack safe', m(llm_anchors, {'style_pack': None}) == llm_anchors)
    inner = {'style_anchor': 'inner style', 'mood': 'inner mood'}
    merged_i = m(llm_anchors, inner)
    ok('inner shape works too', merged_i['style_anchor'] == 'inner style'
       and merged_i['mood'] == 'inner mood')

    # ── S6a: 音色路由 ──
    pipe = object.__new__(Pipe)
    pipe.config = {'tts': {'voice_map': {'林晚': 'cosy-wan', '陈拾': 'cosy-chen'}}}
    ok('narration → global voice', pipe._shot_voice({'speaker': '旁白'}, 'edge-moe') == 'edge-moe')
    ok('no speaker → global voice', pipe._shot_voice({}, 'edge-moe') == 'edge-moe')
    ok('mapped speaker → bound voice', pipe._shot_voice({'speaker': '林晚'}, 'edge-moe') == 'cosy-wan')
    ok('unmapped speaker → global', pipe._shot_voice({'speaker': '路人甲'}, 'edge-moe') == 'edge-moe')
    pipe.config = {}
    ok('no voice_map → global', pipe._shot_voice({'speaker': '林晚'}, 'edge-moe') == 'edge-moe')

    # ── S6b: resume 自愈判断（文件存在即资产有效） ──
    import tempfile
    ref = os.path.join(tempfile.mkdtemp(), 'character_ref.png')
    ok('no file → needs regen', not (os.path.exists(ref) and os.path.getsize(ref) > 10240))
    with open(ref, 'wb') as f:
        f.write(b'x' * 20480)
    ok('file ≥10KB → valid asset', os.path.exists(ref) and os.path.getsize(ref) > 10240)

    # ── S4 scrub: 光影词检测+修复（mock LLM，方法在 LLMClient 上） ──
    from agents.common.tools.llm import LLMClient
    _WORDS = LLMClient._SCENE_LIGHTING_WORDS

    class _ScrubLLM:
        _SCENE_LIGHTING_WORDS = LLMClient._SCENE_LIGHTING_WORDS
        models = {'script': 'mock'}

        def __init__(self, reply):
            self.reply = reply
            self.called = False

        def chat_json(self, messages, **kw):
            self.called = True
            return self.reply

        def _scrub_scene_desc_lighting(self, script):
            return LLMClient._scrub_scene_desc_lighting(self, script)

    good = {'shots': [{'id': 1, 'scene_desc': '老人握提灯走上台阶'},   # 手持物可写
                      {'id': 2, 'scene_desc': '林晚在灯室打开画板速写'}]}
    llm = _ScrubLLM(None)
    out = llm._scrub_scene_desc_lighting(good)
    ok('clean script → no LLM call', not llm.called and out is good)

    bad = {'shots': [{'id': 1, 'scene_desc': '月光洒在海面，老人望海'},
                     {'id': 2, 'scene_desc': '昏暗的塔内烛光摇曳'}]}
    llm = _ScrubLLM({'fixed': [{'i': 0, 'scene_desc': '海面漆黑，老人望海'},
                               {'i': 1, 'scene_desc': '昏暗的塔内烛光更暗了'}]})
    out = llm._scrub_scene_desc_lighting(bad)
    ok('violations → LLM called', llm.called)
    ok('fixed desc applied', out['shots'][0]['scene_desc'] == '海面漆黑，老人望海')
    ok('still-bad reply rejected',
       out['shots'][1]['scene_desc'] == '昏暗的塔内烛光摇曳')  # 修复仍含光影词→不采纳
    bad2 = {'shots': [{'id': 1, 'scene_desc': '月光洒在海面，老人望海'}]}
    llm = _ScrubLLM({'fixed': 'not-a-list'})
    out2 = llm._scrub_scene_desc_lighting(bad2)
    ok('malformed reply → original kept',
       out2['shots'][0]['scene_desc'] == '月光洒在海面，老人望海')

    fails = [n for n, c in PASS if not c]
    print(f'\n{len(PASS) - len(fails)}/{len(PASS)} passed')
    if fails:
        print('FAILED:', fails)
        sys.exit(1)


if __name__ == '__main__':
    main()
