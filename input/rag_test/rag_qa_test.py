import sys
sys.path.insert(0, '.')
from utils.rag import RagIndex
from agents.common.tools.llm import LLMClient

KEY = '454eb1f2826b56685bf7ab155c6eb06e'
idx = RagIndex()
lc = LLMClient()

QUESTIONS = [
    '孔乙己喝的什么酒？他的长衫有什么特点？',
    '阿Q最后因为什么被处决？画押时画了什么？',
    '《药》里华老栓买的是什么药？给谁治病？',
]
if len(sys.argv) > 1 and sys.argv[1] != '-i':
    QUESTIONS = sys.argv[1:]  # 用法: python rag_qa_test.py "你的问题" "第二个问题"
elif len(sys.argv) > 1 and sys.argv[1] == '-i':
    QUESTIONS = None  # 交互模式: python rag_qa_test.py -i

def ask(q):
    hits = idx.search_novel(q, k=5, novel_key=KEY)
    cards = idx._load_cards(KEY)
    ctx = RagIndex.format_novel_context(hits, cards)
    msgs = [
        {'role': 'system', 'content':
         '你是原著问答助手。只根据下面的小说原文片段回答，引用关键细节；'
         '原文没有的信息就明说"原文未提及"。\n\n' + ctx},
        {'role': 'user', 'content': q},
    ]
    r = lc.chat(msgs, temperature=0.2)
    print('Q:', q)
    print('A:', r.strip()[:400])
    print('hits:', ['%.2f %s' % (h['score'], h.get('chapter', '?')) for h in hits])
    print('─' * 60)

if QUESTIONS is None:
    print('交互模式，输入问题（q 退出）')
    while True:
        try:
            q = input('问> ').strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q or q.lower() in ('q', 'quit', 'exit'):
            break
        ask(q)
else:
    for q in QUESTIONS:
        ask(q)
