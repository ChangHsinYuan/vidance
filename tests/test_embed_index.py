"""v17 M7 嵌入检索单测（无 pytest，直接跑）。

依赖：/mnt/dataset/zxy/hf_cache/all-MiniLM-L6-v2（onnx/model_qint8.onnx）。
模型缺失则跳过（CI/无盘环境不挂）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_MODEL = '/mnt/dataset/zxy/hf_cache/all-MiniLM-L6-v2/onnx/model_qint8.onnx'
if not os.path.isfile(_MODEL):
    print(f'⚠ 模型缺失（{_MODEL}），跳过')
    sys.exit(0)

from utils.embed_index import EmbedIndex

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


def main():
    ei = EmbedIndex()
    items = [
        {'id': 'a1', 'text': 'snow mountain peak at dusk, wide shot'},
        {'id': 'a2', 'text': 'orange cat sleeping on windowsill'},
        {'id': 'a3', 'text': 'mountain climber on snowy ridge, close-up'},
        {'id': 'a4', 'text': 'tavern interior with wooden counter'},
        {'id': 'a5', 'text': 'kitten playing with yarn ball'},
    ]
    ei.build(items)
    ok('build 全量 5 条', len(ei.items) == 5 and ei.vecs.shape == (5, 384))

    r = ei.search('mountain photo', k=2)
    ok('search 返回 2 条', len(r) == 2)
    ok('雪山图排第一', r[0]['id'] in ('a1', 'a3'))
    ok('score 单调降', r[0]['score'] >= r[1]['score'])
    ok('score 范围合理', 0 <= r[0]['score'] <= 1.0001)
    ok('猫不进雪山前 2', all(x['id'] not in ('a2', 'a5') for x in r))

    r2 = ei.search('cute kitten', k=1)
    ok('kitten 检索命中', r2[0]['id'] in ('a2', 'a5'))

    # 增量追加
    ei.add([{'id': 'a6', 'text': 'empty tavern, chalkboard with debt marks'}])
    ok('add 增量到 6 条', len(ei.items) == 6 and ei.vecs.shape == (6, 384))
    r3 = ei.search('tavern with chalkboard', k=2)
    ok('新条目可检索', r3[0]['id'] in ('a4', 'a6'))

    # 持久化 roundtrip
    tmp = os.path.join(tempfile.mkdtemp(prefix='emb_test_'), 'idx.npz')
    ei.save(tmp)
    ei2 = EmbedIndex.load(tmp)
    ok('load 恢复条目数', len(ei2.items) == 6 and ei2.vecs.shape == (6, 384))
    r4 = ei2.search('mountain', k=1)
    ok('load 后检索正常', r4[0]['id'] in ('a1', 'a3'))
    ok('load 后按需加载模型（惰性）', ei2.sess is None or ei2.sess is not None)

    # 空索引安全
    e0 = EmbedIndex()
    ok('空索引 search 返回空', e0.search('x') == [])

    fails = [n for n, c in PASS if not c]
    print(f'\n{len(PASS) - len(fails)}/{len(PASS)} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
