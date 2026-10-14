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

    # ── 1. 加载器 ──
    names = sm.list()
    ok('list has marketing+narrative',
       'marketing' in names and 'narrative' in names)

    sk = sm.get('narrative')
    ok('get narrative by name', sk is not None)
    ok('narrative defaults voice',
       sk['defaults'].get('voice') == 'cosy-jilupian1')
    ok('narrative transition rife',
       sk['defaults'].get('transition') == 'rife')
    ok('narration_style non-empty',
       bool(str(sk.get('narration_style', '')).strip()))
    ok('_dir attached', str(sk.get('_dir', '')).endswith('.yaml'))

    ok('get by filename alias', sm.get('marketing') is not None)
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

    # ── 4. 两个 yaml 结构完整（后续加 skill 的模板约束） ──
    for n in sm.list():
        s = sm.get(n)
        d = s.get('defaults') or {}
        ok(f'{n}: has name/display/defaults',
           s.get('name') and s.get('display_name') and d)
        ok(f'{n}: narration_style is str',
           isinstance(s.get('narration_style'), str) and len(s['narration_style']) > 20)
        ok(f'{n}: transition valid',
           d.get('transition') in (None, 'cut', 'crossfade', 'rife'))

    fails = [n for n, c in PASS if not c]
    print(f'\n{len(PASS) - len(fails)}/{len(PASS)} passed')
    if fails:
        print('FAILED:', fails)
        sys.exit(1)


if __name__ == '__main__':
    main()
