"""v18 拆解迁移：旧拆解 JSON 补齐 world/costumes/anchor_en/costume/transition_out（M1）。

用法: python input/rag_test/m6_upgrade_breakdown.py output/m6/breakdown_孔乙己.json [--apply]
缺省 dry-run 打印预览；--apply 才写回（原文件备份 .v17.bak）。
"""
import json
import os
import shutil
import sys

_ROOT = os.path.abspath(__file__)
for _ in range(3):
    _ROOT = os.path.dirname(_ROOT)
sys.path.insert(0, _ROOT)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'output/m6/breakdown_孔乙己.json'
    apply = '--apply' in sys.argv
    bd = json.load(open(path))
    if bd.get('world') and all('costumes' in c for c in bd.get('characters', [])) \
            and all('anchor_en' in s for s in bd.get('scenes', [])):
        print('[迁移] 已是 v18 schema，无需处理')
        return

    from agents.common.tools.llm import LLMClient
    lc = LLMClient()
    slim = {'characters': bd.get('characters', []), 'scenes': bd.get('scenes', []),
            'storyboard': bd.get('storyboard', [])}
    msgs = [
        {'role': 'system', 'content':
         '你是影视剧本工程师。给已有的结构化拆解 JSON 补齐 v18 一致性字段，'
         '不改动任何已有字段，只新增：\n'
         '1. world: {era, region, style, taboos}（依据角色/场景推断时代地域与全片视觉风格）\n'
         '2. characters[].costumes: [{name, desc, stages}]——按 storyboard 时间线归纳每角色的'
         '服装/状态变化（stages 用镜号区间 [起,止]）；单状态角色给 1 套全区间；'
         'desc 是中文服装描述\n'
         '3. scenes[].anchor_en: 英文场景定妆描述（构图/光线/陈设稳定细节，60词内，'
         '同场景跨镜将逐字复用）\n'
         '4. storyboard[].costume: 本镜主角造型名（引用 costumes.name，取该镜 stages 命中者）\n'
         '5. storyboard[].transition_out: "fade"|"crossfade"|"cut"（按镜尾情绪/节奏）\n'
         '只输出完整补齐后的 JSON（原字段原样保留），不要 markdown 代码块。'},
        {'role': 'user', 'content': json.dumps(slim, ensure_ascii=False)},
    ]
    print(f'[迁移] LLM 补齐 v18 字段（{len(slim["storyboard"])} 镜，流式）…')
    text = lc.chat_stream(msgs, model=lc.models['script'], temperature=0.2,
                          max_tokens=16384, timeout=1800,
                          on_chunk=lambda d: print('.', end='', flush=True))
    print(flush=True)
    up = lc._extract_json(text)
    # 校验：原字段值不被改动（允许 LLM 往 storyboard 各镜新增 costume/transition_out 字段）
    for old, new in zip(bd.get('storyboard', []), up.get('storyboard', [])):
        for k, v in old.items():
            assert new.get(k) == v, f'storyboard 镜 {old.get("shot")} 字段 {k} 被改动，拒绝'
    for o_s, n_s in zip(bd.get('scenes', []), up.get('scenes', [])):
        for k, v in o_s.items():
            assert n_s.get(k) == v, f'scene {o_s.get("id")} 字段 {k} 被改动，拒绝'
    for o_c, n_c in zip(bd.get('characters', []), up.get('characters', [])):
        for k, v in o_c.items():
            if k != 'costumes':
                assert n_c.get(k) == v, f'角色 {o_c.get("name")} 字段 {k} 被改动，拒绝'
    assert len(up.get('storyboard', [])) == len(bd.get('storyboard', [])), '镜数变化，拒绝'
    n_cost = sum(len(c.get('costumes') or []) for c in up['characters'])
    n_anchor = sum(1 for s in up['scenes'] if s.get('anchor_en'))
    n_t = sum(1 for s in up['storyboard'] if s.get('transition_out'))
    print(f'[迁移] ✓ world={bool(up.get("world"))} costumes={n_cost} '
          f'anchor_en={n_anchor}/{len(up["scenes"])} transition_out={n_t}/{len(up["storyboard"])}')

    if not apply:
        for c in up['characters'][:2]:
            for co in (c.get('costumes') or [])[:3]:
                print(f'  预览 {c["name"]}/{co["name"]}: {co["desc"][:40]}… stages={co.get("stages")}')
        print('（--apply 写回，原文件备份 .v17.bak）')
        return
    shutil.copy(path, path + '.v17.bak')
    json.dump(up, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'[迁移] ✓ 已写回 {path}（备份 {path}.v17.bak）')


if __name__ == '__main__':
    main()
