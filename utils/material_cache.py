#!/usr/bin/env python3
"""素材全局缓存 — 借鉴 MoneyPrinterTurbo material.py::save_video + material_cache.py

A3 素材缓存：URL md5 命名（img-{md5}.jpg），同 URL 跨任务秒回，不再重复下载；
下载后 PIL 完整性验证（截断/坏图即删，MPT 用 VideoFileClip 验证视频同思路）。
A4 搜索缓存：同关键词搜索结果 24h TTL 缓存，连跑不重复打搜索引擎接口。

缓存目录 output/material_cache/（全局共享，任务目录内仍是真实拷贝，不用软链）。
原子写（tempfile+os.replace）与项目 checkpoint 同款。

用法:
    from utils.material_cache import MaterialCache
    mc = MaterialCache()                      # 默认 output/material_cache/
    hit, data = mc.fetch(url, kind='img')     # (True=缓存命中, bytes or None)
    results = mc.search_get('雪山日出')        # 24h 内同关键词直接回上次的搜索结果
"""

import hashlib
import io
import json
import os
import re
import tempfile
import time
import urllib.request

IMG_MAGIC_EXTS = [
    (b'\x89PNG\r\n\x1a\n', '.png'),
    (b'\xff\xd8\xff', '.jpg'),
    (b'RIFF', '.webp'),
    (b'GIF8', '.gif'),
    (b'BM', '.bmp'),
]

# 缓存文件名白名单（清理时防误删，借鉴 MPT cache_manager 正则白名单）
_ENTRY_RE = re.compile(r'^(img|vid)-[0-9a-f]{32}\.(jpg|png|webp|gif|bmp|mp4)$')
_SEARCH_RE = re.compile(r'^search-[0-9a-f]{32}\.json$')


def _md5(text: str) -> str:
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def _ext_from_magic(data: bytes, default: str = '.jpg') -> str:
    for magic, ext in IMG_MAGIC_EXTS:
        if data.startswith(magic):
            return ext
    return default


def verify_image(data: bytes) -> bool:
    """PIL 完整性验证：能解码且数据读完不报错（截断图/坏图返回 False）。"""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.load()
        return img.size[0] > 0 and img.size[1] > 0
    except Exception:
        return False


class MaterialCache:
    def __init__(self, cache_dir: str = None, ttl_days: int = 30):
        if cache_dir is None:
            from utils.config_loader import load_config
            cache_dir = os.path.join(load_config()['output_dir'], 'material_cache')
        self.cache_dir = cache_dir
        self.search_dir = os.path.join(cache_dir, 'search')
        self.ttl_days = ttl_days

    # ══ A3 素材缓存（URL md5 全局去重 + 下载后验证） ══

    def _entry_path(self, url: str, kind: str = 'img') -> str:
        url_no_query = url.split('?')[0]
        return os.path.join(self.cache_dir, f'{kind}-{_md5(url_no_query)}{".mp4" if kind == "vid" else ".jpg"}')

    def _atomic_write(self, path: str, data: bytes):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix='.tmp')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _entry_candidates(self, url: str, kind: str = 'img') -> list:
        """同 URL 的所有扩展名候选（put 按真实 magic 定扩展名，get 需全扫）。"""
        stem = os.path.splitext(self._entry_path(url, kind))[0]
        if kind == 'vid':
            return [stem + '.mp4']
        return [stem + ext for _, ext in IMG_MAGIC_EXTS]

    def get(self, url: str, kind: str = 'img') -> str:
        """缓存命中且文件有效 → 返回缓存路径；否则 None。"""
        for path in self._entry_candidates(url, kind):
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path
        return None

    def put(self, url: str, data: bytes, kind: str = 'img') -> str:
        """验证后入缓存，返回缓存路径；坏数据返回 None（即下即删，不留坏文件）。"""
        if kind == 'img' and not verify_image(data):
            return None
        path = self._entry_path(url, kind)
        if kind == 'img':
            # 按真实 magic 定扩展名（覆盖默认 .jpg）
            path = os.path.splitext(path)[0] + _ext_from_magic(data)
        self._atomic_write(path, data)
        return path

    def fetch(self, url: str, kind: str = 'img', timeout: int = 15,
              headers: dict = None) -> tuple:
        """带缓存的下载。返回 (cache_hit: bool, data: bytes or None)。

        命中 → (True, bytes)；未命中 → 下载 + 验证 + 入缓存 → (False, bytes)；
        下载失败或验证不过 → (False, None)。
        """
        hit_path = self.get(url, kind)
        if hit_path:
            try:
                with open(hit_path, 'rb') as f:
                    return True, f.read()
            except Exception:
                pass  # 缓存读失败当未命中
        try:
            req = urllib.request.Request(url, headers=headers or {'User-Agent': 'Mozilla/5.0'})
            data = urllib.request.urlopen(req, timeout=timeout).read()
        except Exception:
            return False, None
        if not self.put(url, data, kind):
            return False, None
        return False, data

    # ══ A4 搜索结果 TTL 缓存 ══

    def search_get(self, keyword: str, ttl_hours: int = 24) -> list:
        """同关键词 24h 内的搜索结果直接回缓存（[{murl, turl, md5}, ...]）。"""
        path = os.path.join(self.search_dir, f'search-{_md5(keyword.strip())}.json')
        if not os.path.isfile(path):
            return []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            if time.time() - d.get('ts', 0) > ttl_hours * 3600:
                os.unlink(path)
                return []
            results = d.get('results', [])
            return results if isinstance(results, list) else []
        except Exception:
            return []

    def search_put(self, keyword: str, results: list):
        """写入搜索结果缓存（空结果不缓存，避免把一次抖动固化 24h）。"""
        if not results:
            return
        path = os.path.join(self.search_dir, f'search-{_md5(keyword.strip())}.json')
        self._atomic_write(path, json.dumps(
            {'ts': time.time(), 'keyword': keyword, 'results': results},
            ensure_ascii=False).encode('utf-8'))

    # ══ TTL 清理（正则白名单防误删） ══

    def cleanup(self, ttl_days: int = None) -> dict:
        """按 mtime 清理超龄缓存文件。返回 {'removed': n, 'kept': n}。"""
        ttl = (ttl_days or self.ttl_days) * 86400
        now = time.time()
        removed = kept = 0
        for d in (self.cache_dir, self.search_dir):
            if not os.path.isdir(d):
                continue
            for name in os.listdir(d):
                path = os.path.join(d, name)
                if not os.path.isfile(path):
                    continue
                # 白名单外一律不动（防误删用户放的文件）
                if not (_ENTRY_RE.match(name) or _SEARCH_RE.match(name)):
                    kept += 1
                    continue
                try:
                    if now - os.path.getmtime(path) > ttl:
                        os.unlink(path)
                        removed += 1
                    else:
                        kept += 1
                except OSError:
                    pass
        return {'removed': removed, 'kept': kept}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='素材缓存维护')
    parser.add_argument('--cleanup', action='store_true', help='清理超龄缓存（默认 30 天）')
    parser.add_argument('--ttl-days', type=int, default=30)
    parser.add_argument('--stats', action='store_true', help='统计缓存')
    args = parser.parse_args()
    mc = MaterialCache()
    if args.stats or not args.cleanup:
        n = len([f for f in os.listdir(mc.cache_dir) if os.path.isfile(os.path.join(mc.cache_dir, f))]) \
            if os.path.isdir(mc.cache_dir) else 0
        s = len(os.listdir(mc.search_dir)) if os.path.isdir(mc.search_dir) else 0
        print(f'缓存目录: {mc.cache_dir}\n素材: {n}  搜索缓存: {s}')
    if args.cleanup:
        r = mc.cleanup(args.ttl_days)
        print(f"清理完成: 删 {r['removed']} 留 {r['kept']}")
