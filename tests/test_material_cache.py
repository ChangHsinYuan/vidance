"""A3+A4 素材缓存单元测试（不依赖外网，URL 下载用 file:// 与 mock 数据）。"""
import io
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.material_cache import MaterialCache, verify_image, _md5

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


def _png_bytes(w=8, h=8) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (200, 30, 30)).save(buf, format='PNG')
    return buf.getvalue()


def _truncate(data: bytes) -> bytes:
    return data[:len(data) // 2]


def main():
    tmp = tempfile.mkdtemp(prefix='matcache_test_')
    cache_dir = os.path.join(tmp, 'material_cache')
    mc = MaterialCache(cache_dir=cache_dir, ttl_days=30)

    png = _png_bytes()
    url = 'https://example.com/pic?v=1'

    # ── A3 素材缓存 ──
    ok('miss on empty cache', mc.get(url) is None)

    # put 有效图 → 命中，URL 带查询参数也命中（query 剥离）
    p = mc.put(url, png)
    ok('put returns path', p and os.path.isfile(p))
    ok('naming img-{md5}.png', os.path.basename(p) == f'img-{_md5("https://example.com/pic")}.png')
    ok('get hit', mc.get(url) is not None)
    ok('get hit with query variant', mc.get(url + '&x=2') is not None)

    # fetch 命中：不发起网络（file 假 URL 也能命中缓存）
    hit, data = mc.fetch(url)
    ok('fetch cache hit', hit and data == png)

    # 坏图拒收：截断 PNG 不入缓存
    bad = 'https://example.com/bad.png'
    ok('put bad image rejected', mc.put(bad, _truncate(png)) is None)
    ok('bad not cached', mc.get(bad) is None)

    # fetch 未命中 + 下载失败 → (False, None)，不抛异常
    ok('fetch download fail', mc.fetch('https://127.0.0.1:1/nothing.png', timeout=1) == (False, None))

    # 本地 file:// 走真实下载路径 + 验证 + 入缓存
    src = os.path.join(tmp, 'src.png')
    with open(src, 'wb') as f:
        f.write(png)
    ok('fetch file:// download+cache', not mc.fetch('file://' + src)[0] and mc.get('file://' + src) is not None)
    hit2, data2 = mc.fetch('file://' + src)
    ok('second fetch hits cache', hit2 and data2 == png)

    # ── A4 搜索缓存 ──
    kw = '雪山日出 小狐狸'
    ok('search miss empty', mc.search_get(kw) == [])
    results = [{'murl': 'https://a/1.jpg', 'turl': 'https://a/t1.jpg', 'md5': ''},
               {'murl': 'https://a/2.jpg', 'turl': 'https://a/t2.jpg', 'md5': ''}]
    mc.search_put(kw, results)
    ok('search hit', mc.search_get(kw) == results)
    ok('search file naming', os.path.isfile(os.path.join(cache_dir, 'search', f'search-{_md5(kw)}.json')))

    # TTL 过期 → 回空 + 删文件
    p = os.path.join(cache_dir, 'search', f'search-{_md5(kw)}.json')
    d = json.load(open(p, encoding='utf-8'))
    d['ts'] = time.time() - 25 * 3600
    json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    ok('search ttl expired', mc.search_get(kw) == [] and not os.path.exists(p))

    # 空结果不缓存（避免抖动固化）
    mc.search_put('空词', [])
    ok('empty results not cached', mc.search_get('空词') == [])

    # ── TTL 清理 + 白名单 ──
    old_png = os.path.join(cache_dir, f'img-{"a" * 32}.png')
    with open(old_png, 'wb') as f:
        f.write(png)
    os.utime(old_png, (time.time() - 40 * 86400, time.time() - 40 * 86400))
    stranger = os.path.join(cache_dir, 'my_notes.txt')
    open(stranger, 'w').write('keep me')
    fresh = os.path.join(cache_dir, f'img-{"b" * 32}.jpg')
    open(fresh, 'wb').write(png)
    r = mc.cleanup(ttl_days=30)
    ok('expired removed', not os.path.exists(old_png) and r['removed'] >= 1)
    ok('fresh kept', os.path.exists(fresh))
    ok('non-cache file untouched', os.path.exists(stranger))

    # asset_crawler 集成冒烟：类方法可达 + 门面转发
    from agents.common.tools.asset_crawler import AssetCrawler
    ok('crawler integrates cache', AssetCrawler._material_cache() is not None)

    shutil.rmtree(tmp, ignore_errors=True)
    failed = [n for n, c in PASS if not c]
    print(f"\n{len(PASS) - len(failed)}/{len(PASS)} passed")
    if failed:
        print('FAILED:', failed)
        sys.exit(1)


if __name__ == '__main__':
    main()
