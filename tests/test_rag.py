"""RAG 管线单测（chunk/read_document/format_context 纯本地 + 索引检索 mock 嵌入）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.rag import RagIndex, chunk_text, read_document, _md5

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


class _FakeEmbedder:
    """确定性假嵌入：文本哈希 → 单位向量（同文同向量，无关文近正交）。"""
    dim = 64

    def encode(self, texts, batch_size=16):
        import math
        out = []
        for t in texts:
            h = int(_md5(t[:100]), 16)
            v = [((h >> (i % 60)) & 1) * 1.0 for i in range(self.dim)]
            if all(x == 0 for x in v):
                v[0] = 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


def main():
    # ── 1. chunk_text ──
    ok('empty → []', chunk_text('') == [] and chunk_text(None) == [])
    ok('short para single chunk', len(chunk_text('短文本，直接一片。' * 2)) == 1)
    long_doc = '\n\n'.join(f'第{i}段：' + '守塔人在风暴夜记录风速，维护透镜机构，等待补给船。' * 8
                           for i in range(10))
    chunks = chunk_text(long_doc)
    ok('long doc multi-chunk', len(chunks) >= 3)
    ok('chunk size bounds', all(10 <= len(c) <= 1100 for c in chunks))
    ok('chunk content preserved', '第3段' in ''.join(chunks))
    # 超长无空行段落按句切
    wall = '一句话测试。' * 300
    wall_chunks = chunk_text(wall)
    ok('wall-of-text splits', len(wall_chunks) >= 2)

    # ── 2. read_document ──
    ok('missing file raises', _raises(lambda: read_document('/no/such.md'), FileNotFoundError))
    ok('bad ext raises', _raises_doc('.xyz'))
    tmpd = tempfile.mkdtemp(prefix='rag_test_')
    md = os.path.join(tmpd, 'a.md')
    with open(md, 'w', encoding='utf-8') as f:
        f.write('# 标题\n\n正文内容，守塔人与灯塔。')
    ok('md reads back', '守塔人' in read_document(md))

    # ── 3. RagIndex：mock 嵌入全链 ──
    import utils.rag as rag_mod
    orig_embedder = rag_mod._Embedder
    rag_mod._Embedder = _FakeEmbedder
    try:
        idx = RagIndex(index_dir=os.path.join(tmpd, 'rag_index'))
        doc = os.path.join(tmpd, 'lighthouse.md')
        with open(doc, 'w', encoding='utf-8') as f:
            f.write('\n\n'.join(f'第{i}节：灯塔守塔人{i}号在风暴夜维护透镜，记录风速，'
                                f'等待补给船送来淡水蜡烛与灯油。' * 3 for i in range(8)))
        r1 = idx.add_document(doc)
        ok('add new index', r1['cached'] is False and r1['chunks'] >= 3)
        r2 = idx.add_document(doc)
        ok('add cached by md5', r2['cached'] is True and r2['chunks'] == r1['chunks'])
        ok('faiss+meta persisted',
           os.path.isfile(os.path.join(idx.index_dir, f'doc-{r1["key"]}.faiss'))
           and os.path.isfile(os.path.join(idx.index_dir, f'doc-{r1["key"]}.meta.json')))

        hits = idx.search('守塔人维护透镜', k=3, doc_keys=[r1['key']])
        ok('search returns hits', len(hits) == 3)
        ok('hit fields', all({'text', 'score', 'doc', 'chunk'} <= set(h) for h in hits))
        ok('score sorted desc', hits[0]['score'] >= hits[-1]['score'])
        ok('doc_keys filter', idx.search('任意', k=3, doc_keys=['ffff']) == [])

        ctx = RagIndex.format_context(hits)
        ok('format_context non-empty', '守塔人' in ctx and ctx.startswith('[1]'))
        ok('format_context truncates',
           len(RagIndex.format_context(hits, max_chars=50)) <= 60)

        # 新进程式重载（持久化回读）
        idx2 = RagIndex(index_dir=idx.index_dir)
        hits2 = idx2.search('守塔人维护透镜', k=3, doc_keys=[r1['key']])
        ok('reload index works', [h['text'] for h in hits2] == [h['text'] for h in hits])

        docs = idx.list_docs()
        ok('list_docs', len(docs) == 1 and docs[0]['chunks'] == r1['chunks'])

        # force 重建
        r3 = idx.add_document(doc, force=True)
        ok('force rebuild', r3['cached'] is False)
    finally:
        rag_mod._Embedder = orig_embedder

    fails = [n for n, c in PASS if not c]
    print(f'\n{len(PASS) - len(fails)}/{len(PASS)} passed')
    if fails:
        print('FAILED:', fails)
        sys.exit(1)


def _raises(fn, exc):
    try:
        fn()
        return False
    except exc:
        return True
    except Exception:
        return False


def _raises_doc(ext):
    p = os.path.join(tempfile.mkdtemp(prefix='rag_test_'), f'f{ext}')
    open(p, 'w').write('x')
    try:
        read_document(p)
        return False
    except ValueError:
        return True


if __name__ == '__main__':
    main()
