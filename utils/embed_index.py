"""v17 M7 嵌入检索：all-MiniLM-L6-v2 ONNX（CPU）语义匹配。

用途（v17-design §3.4）：
- buffer 资产语义检索："那张雪山的图" → 按嵌入相似度找资产
- 镜头间场景关联（M6 拆解 storyboard 语义聚类/去重）

模型：sentence-transformers/all-MiniLM-L6-v2 量化 ONNX（23MB，384 维，
英文为主中文弱——资产描述建议英文；中文语义检索走 RagIndex/bge）。
模型目录 /mnt/dataset/zxy/hf_cache/all-MiniLM-L6-v2（curl 直下 hf-mirror），
缺失时延迟报错（不阻塞 import）。

用法：
    from utils.embed_index import EmbedIndex
    ei = EmbedIndex()
    ei.build([{'id': 'a1', 'text': 'snow mountain at dusk'}, ...])
    ei.search('mountain photo', k=3)   # → [{'id','text','score'},...]
    ei.save(path) / EmbedIndex.load(path)   # npz 持久化（向量+元数据）
"""
import json
import os

import numpy as np

_MODEL_DIR = '/mnt/dataset/zxy/hf_cache/all-MiniLM-L6-v2'
_MODEL_PATH = os.path.join(_MODEL_DIR, 'onnx', 'model_qint8.onnx')
_MAX_LEN = 256  # MiniLM 上限 512；资产描述短文本 256 足够


def _l2n(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    return v / np.clip(n, 1e-10, None)


class EmbedIndex:
    """轻量语义索引：ONNX 编码 + 暴力余弦（资产量级 <1e4 无需 faiss）。"""

    def __init__(self):
        self.sess = None
        self.tok = None
        self.items = []   # [{'id','text',...extra}]
        self.vecs = None  # (N, 384) L2 归一化

    # ── 模型（惰性加载）──
    def _ensure_model(self):
        if self.sess is not None:
            return
        if not os.path.isfile(_MODEL_PATH):
            raise FileNotFoundError(
                f'MiniLM ONNX 不存在: {_MODEL_PATH}（curl 直下 hf-mirror，见 README）')
        import onnxruntime as ort
        from transformers import AutoTokenizer
        self.sess = ort.InferenceSession(
            _MODEL_PATH, providers=['CPUExecutionProvider'])
        self.tok = AutoTokenizer.from_pretrained(_MODEL_DIR)

    def encode(self, texts: list) -> np.ndarray:
        """文本列表 → (N, 384) L2 归一化向量。"""
        self._ensure_model()
        enc = self.tok(texts, padding=True, truncation=True,
                       max_length=_MAX_LEN, return_tensors='np')
        feeds = {k: enc[k].astype(np.int64)
                 for k in ('input_ids', 'attention_mask', 'token_type_ids')
                 if k in enc}
        out = self.sess.run(None, feeds)[0]          # (B, L, 384)
        mask = enc['attention_mask'][:, :, None].astype(np.float32)
        emb = (out * mask).sum(1) / np.clip(mask.sum(1), 1e-10, None)  # mean-pool
        return _l2n(emb.astype(np.float32))

    # ── 索引操作 ──
    def build(self, items: list, text_key: str = 'text'):
        """全量建索引。items: [{'id','text',...任意附加字段}]。"""
        if not items:
            self.items, self.vecs = [], np.zeros((0, 384), dtype='float32')
            return
        self.items = [dict(it) for it in items]
        self.vecs = self.encode([it[text_key] for it in self.items])

    def add(self, items: list, text_key: str = 'text'):
        """增量追加。"""
        if not items:
            return
        v = self.encode([it[text_key] for it in items])
        self.items = (self.items or []) + [dict(it) for it in items]
        self.vecs = v if self.vecs is None or len(self.vecs) == 0 \
            else np.vstack([self.vecs, v])

    def search(self, query: str, k: int = 5) -> list:
        """语义检索 top-k：[{**item 元数据, 'score': 余弦相似度}]。"""
        if self.vecs is None or len(self.items) == 0:
            return []
        q = self.encode([query])[0]
        scores = self.vecs @ q
        order = np.argsort(-scores)[:k]
        return [{**self.items[i], 'score': float(scores[i])} for i in order]

    # ── 持久化（npz：向量+元数据一文件）──
    def save(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
        np.savez_compressed(path,
                            vecs=self.vecs if self.vecs is not None else np.zeros((0, 384), 'float32'),
                            meta=json.dumps(self.items, ensure_ascii=False))

    @classmethod
    def load(cls, path: str) -> 'EmbedIndex':
        z = np.load(path, allow_pickle=False)
        ei = cls()
        ei.vecs = z['vecs']
        ei.items = json.loads(str(z['meta']))
        return ei
