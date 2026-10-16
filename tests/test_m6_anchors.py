"""M6.1 一致性锚点 + 外观解耦单测（mock LLM，不连网）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.common.tools.llm import LLMClient

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


def make_lc():
    lc = LLMClient.__new__(LLMClient)  # 跳过 __init__（不连服务）
    lc.models = {'script': 'mock', 'prompt_opt': 'mock'}
    return lc


def main():
    script = {
        'title': '灯塔夜语', 'style': 'cinematic, warm sunset tone',
        'shots': [{'id': 1, 'scene_desc': '白发老人提油灯沿石阶上行'},
                  {'id': 2, 'scene_desc': '灯塔光束扫过海面'}],
    }

    # ── 1. consistency_anchors ──
    lc = make_lc()
    captured = {}

    def mock_cj(messages, **kw):
        captured['s'] = messages[0]['content']
        captured['u'] = messages[1]['content']
        return {'style_anchor': '35mm film, muted blue-grey palette',
                'color': 'muted blue-grey, warm amber accent', 'lighting': 'moonlight',
                'mood': 'lonely, serene'}

    lc.chat_json = mock_cj
    a = lc.consistency_anchors(script)
    ok('anchors schema returned', set(a) == {'style_anchor', 'color', 'lighting', 'mood'})
    ok('anchors prompt has title', '灯塔夜语' in captured['u'])
    ok('anchors prompt has shots', '白发老人' in captured['u'])
    ok('anchors prompt has schema', 'style_anchor' in captured['s'])

    def mock_cj_fail(messages, **kw):
        raise RuntimeError('timeout')

    lc.chat_json = mock_cj_fail
    ok('anchors non-fatal on error', lc.consistency_anchors(script) == {})

    # ── 2. optimize_prompt: ref_frame + anchors ──
    lc = make_lc()
    cap = {}

    def mock_chat(messages, **kw):
        cap['s'] = messages[0]['content']
        cap['u'] = messages[1]['content']
        return 'a cinematic shot'

    lc.chat = mock_chat
    anchors = {'style_anchor': '35mm film, muted palette', 'lighting': 'moonlight'}
    lc.optimize_prompt('老人提灯上行', 'cinematic',
                       five_dim={'visual': 'old man', 'motion': 'slow walk',
                                 'camera': 'low-angle tracking', 'audio': 'x',
                                 'narrative': 'y'},
                       ref_frame=True, anchors=anchors)
    s, u = cap['s'], cap['u']
    ok('ref_frame rule in system', '首帧参考图已包含角色完整外观' in s and '简短代称' in s)
    ok('anchors block in user', '35mm film, muted palette' in u and '一致性锚点' in u)
    ok('five_dim still injected', '[Visual] old man' in u and '[Camera] low-angle tracking' in u)
    ok('anchors rule in system', '一致性锚点必须融入' in s)

    lc.optimize_prompt('场景', 'cinematic')
    s2, u2 = cap['s'], cap['u']
    ok('no ref_frame → no rule', '首帧参考图' not in s2)
    ok('no anchors → no block', '一致性锚点' not in s2 and '一致性锚点' not in u2)

    # ── 3. optimize_scene_prompt: 外观唯一来源 + anchors ──
    lc.optimize_scene_prompt('a white-haired old man, wool coat', '灯塔石阶', 'cinematic',
                             anchors=anchors)
    s3, u3 = cap['s'], cap['u']
    ok('canonical appearance rule', '唯一外观来源' in s3 and '逐字保留' in s3)
    ok('anchors injected to scene', '35mm film, muted palette' in u3)
    lc.optimize_scene_prompt('char', 'scene', 'style')
    ok('no anchors → clean scene prompt', '一致性锚点' not in cap['u'])

    # ── 4. optimize_background_prompt: anchors ──
    lc.optimize_background_prompt('海边石阶与灯塔', 'cinematic', anchors=anchors)
    s4, u4 = cap['s'], cap['u']
    ok('bg anchors block', '35mm film, muted palette' in u4)
    ok('bg anchors rule', '一致性锚点必须融入' in s4)
    ok('bg no-char suffix kept', 'no character, no person' in s4)

    # ── 5. _anchors_block 边界 ──
    ok('empty anchors → empty block', LLMClient._anchors_block({}) == '')
    ok('None → empty block', LLMClient._anchors_block(None) == '')
    ok('blank values filtered', LLMClient._anchors_block({'color': '', 'mood': 'x'}) != '')

    fails = [n for n, c in PASS if not c]
    print(f'\n{len(PASS) - len(fails)}/{len(PASS)} passed')
    if fails:
        print('FAILED:', fails)
        sys.exit(1)


if __name__ == '__main__':
    main()
