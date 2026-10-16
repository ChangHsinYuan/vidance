"""M6 R-N 小说 RAG 单测（分章/检索元数据/format —— mock LLM 不连网）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.rag import RagIndex, split_novel_chapters

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


NOVEL = """雪夜灯塔

第1章 灯塔来客
林晚推开塔门，风雪灌了进来。守塔人陈拾正在修剪灯芯，抬头看了她一眼，没有说话。
他五十岁上下，花白短发，一件洗得发白的藏青色毛衣。林晚二十出头，黑色长直发，
背着画板，围一条酒红色围巾。
"我来看灯塔。"她说。陈拾指了指楼梯，示意她自己上去。

第2章 灯室的秘密
灯室里，菲涅尔透镜折射着烛光。林晚打开画板，开始速写。
陈拾端来两杯热茶。"你是第137个来看灯塔的人。"他说，"但你是第一个画它的。"
林晚这才知道，他是灯塔最后一任守塔人，1998年自动化后就留了下来。

第3章 暴风雨夜
风暴预警在傍晚响起。陈拾检查透镜旋转机构，林晚帮他固定百叶窗。
"走了137个人，只有你留到了暴风雨夜。"陈拾说。林晚看着窗外的巨浪，握紧了画笔。
"""


class _MockLLM:
    def __init__(self):
        self.captured = None

    def chat_json(self, messages, **kw):
        self.captured = messages
        return {'cards': [
            {'name': '陈拾', 'appearance': '五十岁男性，花白短发，藏青色旧毛衣',
             'personality': '沉默寡言', 'relations': '林晚的向导'},
            {'name': '林晚', 'appearance': '二十岁女性，黑色长直发，酒红色围巾，背画板',
             'personality': '好奇执着', 'relations': '来客'},
        ]}


def main():
    # ── 1. split_novel_chapters ──
    title, chapters = split_novel_chapters(NOVEL)
    ok('title extracted', title == '雪夜灯塔')
    ok('3 chapters split', len(chapters) == 3)
    ok('chapter titles', chapters[0]['title'].startswith('第1章')
       and chapters[2]['title'].startswith('第3章'))
    ok('chapter bodies non-empty', all(len(c['text']) > 50 for c in chapters))

    t2, ch2 = split_novel_chapters('没有章节标题的小说\n\n' + ('一段文字。' * 400))
    ok('fallback pseudo-chapters', len(ch2) >= 1 and ch2[0]['title'].startswith('片段'))
    t3, ch3 = split_novel_chapters('')
    ok('empty text → no chapters', ch3 == [])

    # ── 2. add_novel 全链（mock LLM 人物卡） ──
    tmpd = tempfile.mkdtemp(prefix='novel_test_')
    p = os.path.join(tmpd, 'lighthouse.txt')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(NOVEL)

    import utils.rag as rag_mod
    orig = rag_mod.RagIndex._extract_cards
    rag_mod.RagIndex._extract_cards = lambda self, t, chs, k: _MockLLM() and []
    # 先测 no-cards 路径（mock 掉 LLM 抽卡，验证索引本身）
    idx = RagIndex(index_dir=os.path.join(tmpd, 'rag_index'))
    r = idx.add_novel(p, extract_cards=False)
    ok('novel indexed', r['chapters'] == 3 and r['chunks'] >= 3 and not r['cached'])
    ok('novel meta kind', idx._load_meta(os.path.join(
        idx.index_dir, f'doc-{r["key"]}.meta.json')).get('kind') == 'novel')

    # 缓存命中
    r2 = idx.add_novel(p, extract_cards=False)
    ok('novel cached', r2['cached'] and r2['chapters'] == 3)

    # ── 3. search_novel 带章节归属 ──
    hits = idx.search_novel('守塔人陈拾的外貌', k=2, novel_key=r['key'])
    ok('novel search hits', len(hits) >= 1)
    ok('hit has chapter tag', all('chapter' in h and h['chapter'] for h in hits))

    # ── 4. format_novel_context：人物卡在前 ──
    cards = _MockLLM().chat_json(None)  # 直接用返回值
    cards = [{'name': '陈拾', 'appearance': '五十岁男性，花白短发',
              'personality': '沉默'}, {'name': '林晚', 'appearance': '黑色长直发'}]
    ctx = RagIndex.format_novel_context(hits, cards)
    ok('cards lead the context', ctx.index('主要人物设定') < ctx.index('[1]'))
    ok('card content present', '陈拾' in ctx and '花白短发' in ctx)
    ok('chapter tag in context', '第' in ctx)
    ok('truncation works',
       len(RagIndex.format_novel_context(hits, cards, max_chars=80)) <= 120)

    # ── 5. _extract_cards mock（真 LLM 层单独验证） ──
    rag_mod.RagIndex._extract_cards = orig

    fails = [n for n, c in PASS if not c]
    print(f'\n{len(PASS) - len(fails)}/{len(PASS)} passed')
    if fails:
        print('FAILED:', fails)
        sys.exit(1)


if __name__ == '__main__':
    main()
