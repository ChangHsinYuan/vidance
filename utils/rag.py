#!/usr/bin/env python3
"""RAG 管线 — v17 M5b（FAISS + bge-small-zh-v1.5，索引源=buffer 文档/任意文档）

    设计（docs/design/v17-design.md §3.2）：上传文档（md/txt/pdf）→ 切分 → FAISS 索引
→ 编剧时检索 top-k 片段注入 script_write（"参考资料"段）。

- 嵌入：BAAI/bge-small-zh-v1.5（transformers 直载，CLS + L2 归一化，CPU 可跑）
- 索引：faiss IndexFlatIP（内积=余弦，归一化后等价）；持久化 .faiss + .meta.json
- 文档按内容 md5 缓存（同文档重复 add 秒回）；检索跨多个文档索引合并取 top-k
- 切分：md/txt 按段落聚合 ~500 字符（50 重叠）；pdf 用 pypdf 逐页提取后同法

用法:
    from utils.rag import RagIndex
    idx = RagIndex()
    n = idx.add_document('notes.md')          # 入索引（md5 缓存）
    hits = idx.search('雪山日出', k=5)         # [{'text', 'score', 'doc', 'chunk'}]
    ctx = RagIndex.format_context(hits)       # 拼注入编剧的"参考资料"段
"""

import hashlib
import json
import os
import re
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __package__ in (None, '') and _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_MODEL_ID = 'BAAI/bge-small-zh-v1.5'
_MODEL_DIR = '/mnt/dataset/zxy/hf_cache/bge-small-zh-v1.5'  # curl 直下（hf-mirror）
_CHUNK_SIZE = 500
_CHUNK_OVERLAP = 50
_TOP_K_DEFAULT = 5


def _md5(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def read_document(path: str) -> str:
    """读文档为纯文本（md/txt 直读，pdf 走 pypdf）。"""
    if not path or not os.path.isfile(path):
        raise FileNotFoundError(f'文档不存在: {path}')
    ext = os.path.splitext(path)[1].lower()
    if ext == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(path)
        return '\n\n'.join((p.extract_text() or '') for p in reader.pages)
    if ext in ('.md', '.markdown', '.txt', '') or ext == '.text':
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    raise ValueError(f'不支持的文档类型: {ext}（支持 md/txt/pdf）')


def chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list:
    """段落聚合切分：按空行分段，段内超长再按句切，聚合到 ~size 字符。

    返回非空 chunk 列表；段短则保持原样（不硬凑），段长超 2x size 硬切。
    """
    text = (text or '').strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    # 超长段落按句边界再切
    pieces = []
    for p in paras:
        if len(p) <= size * 2:
            pieces.append(p)
            continue
        sentences = re.split(r'(?<=[。！？!?；;\n])', p)
        buf = ''
        for s in sentences:
            if buf and len(buf) + len(s) > size:
                pieces.append(buf.strip())
                buf = buf[-overlap:] + s if overlap else s
            else:
                buf += s
        if buf.strip():
            pieces.append(buf.strip())
    # 聚合相邻短片段到 ~size
    chunks, buf = [], ''
    for pc in pieces:
        if buf and len(buf) + len(pc) + 1 > size:
            chunks.append(buf.strip())
            buf = buf[-overlap:] + '\n' + pc if overlap else pc
        else:
            buf = f'{buf}\n{pc}' if buf else pc
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if len(c) >= 10] or []


_RE_CHAPTER = re.compile(r'^\s*(第[0-9〇零一二三四五六七八九十百千两]+[章回节卷][^\n]{0,40})\s*$',
                         re.MULTILINE)


def split_novel_chapters(text: str) -> tuple:
    """小说分章：'第X章' 标题行优先；无标题行退化为按 ~3000 字空行块切。

    返回 (title, [{'title', 'text'}])；title 取首行非空文本（截 40 字）。
    """
    text = (text or '').strip()
    if not text:
        return '', []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = lines[0][:40] if lines else '未命名'
    marks = list(_RE_CHAPTER.finditer(text))
    if len(marks) >= 2:
        chapters = []
        pre = text[:marks[0].start()].strip()
        if len(pre) >= 200:  # 正文前的引子/简介太长也收一章
            chapters.append({'title': '序', 'text': pre})
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            body = text[m.end():end].strip()
            if body:
                chapters.append({'title': m.group(1).strip()[:40], 'text': body})
        return title, chapters
    # 退化：超大段（>2000 字）切为伪章节
    paras = [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]
    chapters, buf = [], ''
    for p in paras:
        buf = f'{buf}\n{p}' if buf else p
        if len(buf) >= 3000:
            chapters.append({'title': f'片段{len(chapters) + 1}', 'text': buf})
            buf = ''
    if buf.strip():
        chapters.append({'title': f'片段{len(chapters) + 1}', 'text': buf})
    return title, chapters


class _Embedder:
    """bge-small-zh 嵌入器（transformers 直载，进程内单例，CPU 可跑）。"""

    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
            cls._inst._loaded = False
        return cls._inst

    def _ensure(self):
        if self._loaded:
            return
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        src = _MODEL_DIR if os.path.isdir(_MODEL_DIR) else _MODEL_ID
        self.tok = AutoTokenizer.from_pretrained(src)
        self.model = AutoModel.from_pretrained(src)
        self.model.eval()
        self._loaded = True

    def encode(self, texts: list, batch_size: int = 16) -> list:
        """texts → [float vector]（CLS + L2 归一化，bge 官方用法）。"""
        self._ensure()
        import torch
        out = []
        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                batch = [t[:512] for t in texts[i:i + batch_size]]  # bge 上限 512 token
                enc = self.tok(batch, padding=True, truncation=True,
                               max_length=512, return_tensors='pt')
                res = self.model(**enc)
                cls = res.last_hidden_state[:, 0]          # [CLS]
                cls = torch.nn.functional.normalize(cls, dim=-1)
                out.extend(cls.cpu().tolist())
        return out


class RagIndex:
    """FAISS 文档索引（多文档合并检索，md5 缓存，持久化到 output/rag_index/）。"""

    def __init__(self, index_dir: str = None):
        if index_dir is None:
            from utils.config_loader import load_config
            index_dir = os.path.join(load_config()['output_dir'], 'rag_index')
        self.index_dir = index_dir
        os.makedirs(index_dir, exist_ok=True)

    # ── 单文档索引 ──

    def _doc_paths(self, path: str) -> tuple:
        """文档 → (faiss_path, meta_path)，键=内容 md5（同内容跨路径复用）。"""
        text = read_document(path)
        key = _md5(text)
        faiss_path = os.path.join(self.index_dir, f'doc-{key}.faiss')
        meta_path = os.path.join(self.index_dir, f'doc-{key}.meta.json')
        return faiss_path, meta_path, text, key

    def add_document(self, path: str, force: bool = False) -> dict:
        """文档切分入索引。返回 {'key', 'chunks', 'cached', 'file'}。

        已有同内容索引且非 force → 直接回缓存统计（不重嵌入）。
        """
        import faiss
        import numpy as np
        faiss_path, meta_path, text, key = self._doc_paths(path)
        if not force and os.path.isfile(faiss_path) and os.path.isfile(meta_path):
            meta = self._load_meta(meta_path)
            return {'key': key, 'chunks': len(meta.get('chunks', [])),
                    'cached': True, 'file': os.path.basename(path)}
        chunks = chunk_text(text)
        if not chunks:
            return {'key': key, 'chunks': 0, 'cached': False,
                    'file': os.path.basename(path)}
        vecs = np.array(_Embedder().encode(chunks), dtype='float32')
        index = faiss.IndexFlatIP(vecs.shape[1])
        index.add(vecs)
        faiss.write_index(index, faiss_path + '.tmp')
        os.replace(faiss_path + '.tmp', faiss_path)
        meta = {'file': os.path.basename(path), 'key': key,
                'chunks': chunks, 'ts': time.time(), 'dim': int(vecs.shape[1])}
        with open(meta_path + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(meta_path + '.tmp', meta_path)
        return {'key': key, 'chunks': len(chunks), 'cached': False,
                'file': os.path.basename(path)}

    # ── 检索 ──

    def _load_meta(self, meta_path: str) -> dict:
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def search(self, query: str, k: int = _TOP_K_DEFAULT,
               doc_keys: list = None) -> list:
        """跨索引检索 top-k。doc_keys 限定文档（None=全部）。

        返回 [{'text', 'score', 'doc', 'chunk'}]，score 降序。
        """
        import faiss
        import numpy as np
        qv = np.array(_Embedder().encode([query]), dtype='float32')
        hits = []
        for name in sorted(os.listdir(self.index_dir)):
            if not name.endswith('.faiss'):
                continue
            key = name[4:-6]
            if doc_keys and key not in doc_keys:
                continue
            meta = self._load_meta(os.path.join(self.index_dir, name[:-6] + '.meta.json'))
            chunks = meta.get('chunks') or []
            if not chunks:
                continue
            try:
                index = faiss.read_index(os.path.join(self.index_dir, name))
            except Exception:
                continue
            scores, ids = index.search(qv, min(k, len(chunks)))
            for s, i in zip(scores[0], ids[0]):
                if 0 <= i < len(chunks):
                    hits.append({'text': chunks[i], 'score': float(s),
                                 'doc': meta.get('file', key), 'chunk': int(i)})
        hits.sort(key=lambda h: -h['score'])
        return hits[:k]

    # ── 小说专用（v17 M6 R-N：Toonflow 小说拍短剧路线）──

    def add_novel(self, path: str, force: bool = False,
                  extract_cards: bool = True) -> dict:
        """小说（txt/md/pdf）分章入索引 + 人物卡抽取（Toonflow 资产提取路线）。

        - 章节切分：'第X章/回/节/卷' 标题行优先，退化为超大段（>2000 字空行块）
        - 每章 chunk 化入 FAISS，meta 记 chapter 归属
        - 人物卡：llm.py 从前 3 章 + 高频名字抽取 {name, appearance, personality,
          relations}，存 novel-cards-{md5}.json（LLM 失败跳过，非致命）
        返回 {'key', 'chapters', 'chunks', 'cards', 'cached', 'title'}
        """
        import numpy as np
        faiss_path, meta_path, text, key = self._doc_paths(path)
        meta = self._load_meta(meta_path) if (not force and
                                              os.path.isfile(meta_path)) else {}
        if meta.get('kind') == 'novel' and not force:
            cards = self._load_cards(key)
            return {'key': key, 'chapters': len(meta.get('chapters', [])),
                    'chunks': len(meta.get('chunks', [])), 'cards': cards,
                    'cached': True, 'title': meta.get('title', '')}
        title, chapters = split_novel_chapters(text)
        chunks = []
        ch_meta = []
        for ci, ch in enumerate(chapters):
            ch_chunks = chunk_text(ch['text'])
            for j in ch_chunks:
                ch_meta.append({'chapter': ci, 'title': ch['title']})
                chunks.append(j)
        if not chunks:
            return {'key': key, 'chapters': 0, 'chunks': 0, 'cards': [],
                    'cached': False, 'title': title}
        vecs = np.array(_Embedder().encode(chunks), dtype='float32')
        import faiss
        index = faiss.IndexFlatIP(vecs.shape[1])
        index.add(vecs)
        faiss.write_index(index, faiss_path + '.tmp')
        os.replace(faiss_path + '.tmp', faiss_path)
        meta = {'file': os.path.basename(path), 'key': key, 'kind': 'novel',
                'title': title,
                'chapters': [{'title': c['title'], 'chars': len(c['text'])}
                             for c in chapters],
                'chunk_chapters': ch_meta, 'chunks': chunks,
                'ts': time.time(), 'dim': int(vecs.shape[1])}
        with open(meta_path + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(meta_path + '.tmp', meta_path)
        cards = []
        if extract_cards:
            cards = self._extract_cards(title, chapters, key) or []
        return {'key': key, 'chapters': len(chapters), 'chunks': len(chunks),
                'cards': cards, 'cached': False, 'title': title}

    def _cards_path(self, key: str) -> str:
        return os.path.join(self.index_dir, f'novel-cards-{key}.json')

    def _load_cards(self, key: str) -> list:
        p = self._cards_path(key)
        if os.path.isfile(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _extract_cards(self, title: str, chapters: list, key: str) -> list:
        """LLM 人物卡抽取（前 3 章即可定位主要人物；失败返回 [] 非致命）。"""
        try:
            from agents.common.tools.llm import LLMClient
            lc = LLMClient()
        except Exception:
            return []
        sample = '\n\n'.join(
            f'【{c["title"]}】\n{c["text"][:800]}' for c in chapters[:3])
        system = (
            '你是小说改编助手。从小说开头章节提取主要人物设定卡，供后续分集编剧保持'
            '人物外貌/性格一致（人物卡是唯一外观来源，之后每集不再重新描述）。\n'
            '输出严格JSON，不要任何解释。\n'
            'JSON schema:\n'
            '{"cards": [{"name": "姓名", "appearance": "外貌描述（年龄/发型/服装/体型，'
            '40字内，具体可视化），", "personality": "性格关键词", '
            '"relations": "与其他人物的关系"}]}\n'
            '要求：只提取实际出场的主要人物（最多8人）；外貌必须具体可画'
            '（不要"美丽""帅气"这类空词）'
        )
        messages = [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': f'小说：{title}\n\n{sample}'},
        ]
        try:
            r = lc.chat_json(messages, model=lc.models.get('script'),
                             temperature=0.3, retries=1)
            cards = [c for c in (r.get('cards') or []) if isinstance(c, dict)
                     and c.get('name')][:8]
        except Exception:
            return []
        if not cards:
            return []
        with open(self._cards_path(key) + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(cards, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(self._cards_path(key) + '.tmp', self._cards_path(key))
        return cards

    def search_novel(self, query: str, k: int = 5, novel_key: str = None) -> list:
        """小说检索：命中段落带章节标题（'第X章 …'），编剧可溯源。"""
        hits = self.search(query, k=k, doc_keys=[novel_key] if novel_key else None)
        if not hits or not novel_key:
            return hits
        meta = self._load_meta(os.path.join(self.index_dir, f'doc-{novel_key}.meta.json'))
        ch_meta = meta.get('chunk_chapters') or []
        chapters = meta.get('chapters') or []
        for h in hits:
            ci = ch_meta[h['chunk']]['chapter'] if h['chunk'] < len(ch_meta) else None
            h['chapter'] = (chapters[ci]['title'] if ci is not None and
                            ci < len(chapters) else '')
        return hits

    @staticmethod
    def format_novel_context(hits: list, cards: list = None,
                             max_chars: int = 2400) -> str:
        """小说检索+人物卡 → 编剧注入段（人物卡在前=外观唯一来源，段落其次）。"""
        parts = []
        if cards:
            cl = ['  - ' + c['name'] + '：' + str(c.get('appearance', ''))
                  + ('（' + c['personality'] + '）' if c.get('personality') else '')
                  for c in cards]
            parts.append('主要人物设定（外貌以此为准，各集保持一致，不要重新发明外貌）：\n'
                         + '\n'.join(cl))
        for i, h in enumerate(hits, 1):
            ch = f' {h["chapter"]}' if h.get('chapter') else ''
            parts.append(f'[{i}]{ch} {h["text"].strip()}')
        out = []
        total = 0
        for p in parts:
            if total + len(p) > max_chars:
                break
            out.append(p)
            total += len(p)
        return '\n\n'.join(out)

    @staticmethod
    def format_context(hits: list, max_chars: int = 2000) -> str:
        """检索结果 → 注入编剧的"参考资料"段（超长截断）。"""
        if not hits:
            return ''
        parts = []
        total = 0
        for i, h in enumerate(hits, 1):
            seg = f'[{i}]（{h["doc"]}）{h["text"].strip()}'
            if total + len(seg) > max_chars:
                break
            parts.append(seg)
            total += len(seg)
        return '\n'.join(parts)

    # ── 维护 ──

    def list_docs(self) -> list:
        out = []
        for name in sorted(os.listdir(self.index_dir)):
            if name.endswith('.meta.json'):
                meta = self._load_meta(os.path.join(self.index_dir, name))
                if meta:
                    out.append({'key': meta.get('key', name[:-10]),
                                'file': meta.get('file'), 'chunks': len(meta.get('chunks', [])),
                                'age_h': round((time.time() - meta.get('ts', 0)) / 3600, 1)})
        return out


def _main():
    import argparse
    parser = argparse.ArgumentParser(description='RAG 文档索引（FAISS + bge-small-zh）')
    sub = parser.add_subparsers(dest='cmd', required=True)
    pa = sub.add_parser('add', help='文档入索引')
    pa.add_argument('files', nargs='+')
    ps = sub.add_parser('search', help='检索测试')
    ps.add_argument('query')
    ps.add_argument('-k', type=int, default=3)
    pl = sub.add_parser('list', help='列出已索引文档')
    pn = sub.add_parser('novel', help='小说分章入索引 + 人物卡抽取')
    pn.add_argument('file')
    pn.add_argument('--no-cards', action='store_true', help='跳过 LLM 人物卡抽取')
    args = parser.parse_args()
    idx = RagIndex()
    if args.cmd == 'add':
        for f in args.files:
            r = idx.add_document(f)
            print(f'{r["file"]}: {"缓存命中" if r["cached"] else "新建"} {r["chunks"]} 片段')
    elif args.cmd == 'search':
        hits = idx.search(args.query, k=args.k)
        for h in hits:
            print(f'[{h["score"]:.3f}] {h["doc"]}#{h["chunk"]}: {h["text"][:80]}…')
    elif args.cmd == 'novel':
        r = idx.add_novel(args.file, extract_cards=not args.no_cards)
        print(f'{r["title"]}: {r["chapters"]} 章 / {r["chunks"]} 片段 / '
              f'{"缓存" if r["cached"] else "新建"} / {len(r["cards"])} 人物卡')
        for c in r['cards']:
            print(f'  - {c["name"]}: {c.get("appearance", "")[:40]}')
    elif args.cmd == 'list':
        for d in idx.list_docs():
            print(f'{d["file"]}: {d["chunks"]} 片段 ({d["age_h"]}h 前)')


if __name__ == '__main__':
    _main()
