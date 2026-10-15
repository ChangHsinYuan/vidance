"""SKILL 风格技能单测（无 pytest，加载器纯本地 + plan_narration 文风注入 mock LLM）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.skills import SkillManager

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


def main():
    sm = SkillManager()

    # ── 1. 双维度加载器 ──
    keys = sm.list()
    ok('commands has fast/narrative', 'commands/fast/narrative' in keys)
    ok('agents has artist', 'agents/personas/artist' in keys)
    ok('list(kind=commands) filters',
       all(k.startswith('commands/') for k in sm.list(kind='commands')))

    sk = sm.get('narrative')
    ok('get narrative by name', sk is not None)
    ok('_meta kind=commands', sk['_meta']['kind'] == 'commands')
    ok('narrative defaults voice',
       sk['defaults'].get('voice') == 'cosy-xinwen1')
    ok('narrative transition rife',
       sk['defaults'].get('transition') == 'rife')
    ok('narration_style non-empty',
       bool(str(sk.get('narration_style', '')).strip()))

    art = sm.get('artist')
    ok('get agents persona', art is not None and art['_meta']['kind'] == 'agents')
    ok('artist fast params via params_for',
       SkillManager.params_for(art, 'fast').get('lut') == 'cinematic')
    ok('artist ppt params empty → {}',
       SkillManager.params_for(art, 'ppt') == {})
    ok('command params_for → defaults',
       SkillManager.params_for(sk, 'fast').get('transition') == 'rife')
    ok('artist post section', (art.get('post') or {}).get('grain') is True)

    ok('get by namespaced key', sm.get('fast/marketing') is not None)
    ok('get missing → None', sm.get('no-such-skill') is None)
    ok('get empty/None → None', sm.get('') is None and sm.get(None) is None)

    # ── 2. merge：skill 只填未传项，CLI 显式值优先 ──
    args = {'voice': None, 'bgm': 'calm', 'lut': None, 'n': None}
    merged = SkillManager.merge(args, {'defaults': {
        'voice': 'edge-moe', 'bgm': 'epic', 'lut': 'vivid', 'n': 3}})
    ok('merge fills None', merged['voice'] == 'edge-moe' and merged['lut'] == 'vivid')
    ok('merge keeps explicit', merged['bgm'] == 'calm')
    ok('merge no side-effect', args['voice'] is None)

    ok('merge None skill → unchanged',
       SkillManager.merge({'voice': None}, None) == {'voice': None})

    # ── 3. plan_narration 文风注入（mock LLM） ──
    from agents.generator.tools.fastline import FastLine
    fl = FastLine.__new__(FastLine)  # 跳过 __init__（不连服务）

    class _MockLLM:
        def __init__(self):
            self.captured = None

        def chat_json(self, prompt):
            self.captured = prompt
            return {'segments': [
                {'text': '云海翻涌如潮', 'motion': 'pan'},
                {'text': '晨光刺破天际', 'motion': 'zoom-in'},
            ]}

    m = _MockLLM()
    fl.llm = m
    # 3a. 默认（无 skill）：旧文案"押韵有冲击力"仍在，不回归
    segs = fl.plan_narration('黄山云海 日出', 2)
    sysc = m.captured[0]['content']
    ok('default prompt keeps old style', '押韵有冲击力' in sysc)
    ok('default segments ok',
       len(segs) == 2 and segs[0]['text'] == '云海翻涌如潮')

    # 3b. 带 skill 文风：新文风进 prompt，旧"押韵"字样消失
    m2 = _MockLLM()
    fl.llm = m2
    fl.plan_narration('黄山云海 日出', 2,
                      narration_style='纪录片解说词：完整长句，每句 15-25 字')
    sysc2 = m2.captured[0]['content']
    ok('skill style injected', '纪录片解说词' in sysc2)
    ok('old style replaced', '押韵有冲击力' not in sysc2)
    ok('n-count in prompt', '2' in sysc2)

    # ── 4. post_for：post 配方读取 ──
    ok('post_for artist dict', SkillManager.post_for(art) == (art.get('post')))
    ok('post_for researcher has sharpen',
       (SkillManager.post_for(sm.get('researcher')) or {}).get('sharpen') is True)
    ok('post_for commands-style → None', SkillManager.post_for(sk) is None)
    ok('post_for None → None', SkillManager.post_for(None) is None)
    ok('post_for empty post → None', SkillManager.post_for({'post': {}}) is None)

    # ── 5. apply_post_recipe：单次 ffmpeg 链（真跑 1s 测试视频） ──
    import tempfile
    import subprocess
    from agents.post.tools.effects import apply_post_recipe, POST_KEYS
    ok('POST_KEYS', POST_KEYS == ('grain', 'vignette', 'warmth', 'sharpen'))
    tmpd = tempfile.mkdtemp(prefix='post_recipe_')
    src = os.path.join(tmpd, 'src.mp4')
    subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'testsrc=duration=1:size=320x240:rate=12',
                    '-pix_fmt', 'yuv420p', src], capture_output=True, timeout=60)
    ok('testsrc created', os.path.isfile(src) and os.path.getsize(src) > 500)
    # 5a. artist 全链（warmth+sharpen 无关，grain+vignette）原地覆写
    dst = os.path.join(tmpd, 'artist.mp4')
    import shutil as _sh
    _sh.copy(src, dst)
    try:
        apply_post_recipe(dst, {'grain': True, 'vignette': True, 'warmth': 0.15,
                                'transition': 'rife'})
        ok('artist post applied in-place', os.path.getsize(dst) > 500
           and not os.path.exists(dst + '.post.mp4'))
    except Exception as e:
        ok(f'artist post applied in-place (raised {e})', False)
    # 5b. 只有命令层键 → 报错不误改
    dst2 = os.path.join(tmpd, 'only_trans.mp4')
    _sh.copy(src, dst2)
    try:
        apply_post_recipe(dst2, {'transition': 'cut'})
        ok('transition-only raises', False)
    except ValueError:
        ok('transition-only raises', True)
    except Exception as e:
        ok(f'transition-only raises (wrong exc {e})', False)
    ok('transition-only file untouched', os.path.getsize(dst2) == os.path.getsize(src))
    # 5c. researcher 链（sharpen only）另存 out
    dst3 = os.path.join(tmpd, 'sharpen_out.mp4')
    try:
        apply_post_recipe(src, {'sharpen': True}, out=dst3)
        ok('sharpen out-path', os.path.isfile(dst3) and os.path.getsize(dst3) > 500)
    except Exception as e:
        ok(f'sharpen out-path (raised {e})', False)
    # 5d. warmth 极值钳制不炸
    try:
        apply_post_recipe(src, {'warmth': 99.0}, out=os.path.join(tmpd, 'warm.mp4'))
        ok('warmth clamped ok', True)
    except Exception as e:
        ok(f'warmth clamped ok (raised {e})', False)

    # ── 6. yaml 结构完整（后续加 skill 的模板约束） ──
    for k in sm.list():
        s = sm.get(k)
        kind = s['_meta']['kind']
        d = SkillManager.params_for(s, k.split('/')[1] if kind == 'commands'
                                    else 'fast')
        ok(f'{k}: has name/display',
           s.get('name') and s.get('display_name'))
        if kind == 'templates':
            # 五维模板：five_dim_guide 五键齐全（M5a）
            g = SkillManager.five_dim_guide(s) or {}
            ok(f'{k}: five_dim_guide complete',
               all(g.get(x) for x in ('visual', 'motion', 'camera', 'audio', 'narrative')))
            continue
        ok(f'{k}: narration_style is str',
           isinstance(s.get('narration_style'), str) and len(s['narration_style']) > 20)

    # ── 7. 五维模板加载 + script_write 注入（mock LLM） ──
    tpl = sm.get('cinematic')
    ok('template cinematic loads', tpl is not None and tpl['_meta']['kind'] == 'templates')
    ok('template guide via five_dim_guide',
       '胶片' in str(SkillManager.five_dim_guide(tpl).get('visual', '')))
    ok('five_dim_guide non-template → None',
       SkillManager.five_dim_guide(sk) is None and SkillManager.five_dim_guide(None) is None)

    from agents.common.tools.llm import LLMClient
    lc = LLMClient.__new__(LLMClient)  # 跳过 __init__（不连服务）

    class _MockChat:
        def __init__(self):
            self.captured = None

        def chat_json(self, messages, **kw):
            self.captured = messages
            return {'title': 't', 'concept': 'c',
                    'shots': [{'id': 1, 'scene_desc': 's', 'narration': 'n',
                               'background_desc': 'b', 'duration': 5,
                               'five_dim': {'visual': 'v', 'motion': 'm',
                                            'camera': 'c', 'audio': 'a',
                                            'narrative': 'n'}}]}

    mc_ = _MockChat()
    lc.chat_json = mc_.chat_json
    lc.models = {'script': 'mock'}
    guide = SkillManager.five_dim_guide(tpl)
    lc.script_write('测试概念', five_dim_guide=guide)
    sysc = mc_.captured[0]['content']
    ok('five_dim guide injected to script_write',
       '五维提示词模板' in sysc and '胶片质感' in sysc)
    ok('five_dim schema in prompt', 'five_dim' in sysc and 'narrative' in sysc)
    lc.script_write('测试概念')  # 无模板不注入
    sysc2 = mc_.captured[0]['content']
    ok('no template → no guide injection', '五维提示词模板' not in sysc2)
    ok('five_dim schema always present', 'five_dim' in sysc2)

    # optimize_prompt 五维组装（mock chat）
    class _MockChat2:
        def __init__(self):
            self.captured = None

        def chat(self, messages, **kw):
            self.captured = messages
            return 'a cinematic shot'

    m2 = _MockChat2()
    lc.chat = m2.chat
    lc.models = {'prompt_opt': 'mock'}
    lc.optimize_prompt('场景', 'cinematic', five_dim={
        'visual': 'golden hour beach', 'motion': 'slow waves',
        'camera': 'slow dolly-in', 'audio': 'waves', 'narrative': 'opening'})
    up = m2.captured[1]['content']
    ok('optimize_prompt five-dim user block',
       '[Visual] golden hour beach' in up and '[Motion] slow waves' in up
       and '[Camera] slow dolly-in' in up)
    ok('optimize_prompt skips audio/narrative', 'waves audio' not in up and 'opening' not in up)
    ok('optimize_prompt system rule', '五维提示必须全部融入' in m2.captured[0]['content'])
    lc.optimize_prompt('场景', 'cinematic')  # 无五维走旧路径
    ok('optimize_prompt legacy path', '场景描述' in m2.captured[1]['content']
       and '[Visual]' not in m2.captured[1]['content'])

    fails = [n for n, c in PASS if not c]
    print(f'\n{len(PASS) - len(fails)}/{len(PASS)} passed')
    if fails:
        print('FAILED:', fails)
        sys.exit(1)


if __name__ == '__main__':
    main()
