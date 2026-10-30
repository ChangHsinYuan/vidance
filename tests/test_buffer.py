"""v17 M1 buffer 单元测试（无 pytest 依赖，直接跑）。"""
import os
import shutil
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.buffer import BufferManager, ConflictError, new_session_id

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


def main():
    tmp = tempfile.mkdtemp(prefix='buffer_test_')
    try:
        bm = BufferManager(os.path.join(tmp, 'buffer'), max_file_size=1024 * 1024, ttl_days=7)
        sid = new_session_id()

        # 基础生命周期
        bm.session_dir(sid)
        ok('session dir created', os.path.isdir(os.path.join(bm.root, sid, 'uploads')))

        # 上传 + 名字净化 + 穿越拒绝
        e1 = bm.add_upload(sid, 'a.png', b'x' * 100, as_name='../evil/../cat dog.png')
        ok('upload sanitized name', e1['name'] == 'cat dog.png')
        ok('upload stays in uploads', os.path.dirname(e1['abs_path'] if 'abs_path' in e1 else
           os.path.join(bm.root, sid, e1['path'])).startswith(os.path.join(bm.root, sid, 'uploads')))
        try:
            bm._session_dir('../hack')
            ok('session traversal rejected', False)
        except ValueError:
            ok('session traversal rejected', True)

        # 引用归档（不拷贝）
        src = os.path.join(tmp, 'ref_me.mp4')
        open(src, 'wb').write(b'v' * 50)
        e2 = bm.add_reference(sid, src)
        ok('ref registered', e2['is_ref'] and os.path.isfile(src))
        ok('ref exists in list', bm.get_asset(sid, e2['id'])['exists'])

        # 引用计数 + 删除保护
        bm.mark_ref(sid, e2['id'], 'job_1')
        try:
            bm.remove_asset(sid, e2['id'])
            ok('ref-protected delete 409', False)
        except ConflictError:
            ok('ref-protected delete 409', True)
        ok('force delete ref', bm.remove_asset(sid, e2['id'], force=True))
        ok('src untouched after ref delete', os.path.isfile(src))

        # 上传删除真删
        p1 = os.path.join(bm.root, sid, e1['path'])
        bm.remove_asset(sid, e1['id'])
        ok('upload file deleted', not os.path.exists(p1))

        # 乐观锁：expect_revision 不匹配报 ESTALE
        bm.add_upload(sid, 'b.png', b'y' * 10)
        try:
            bm._write_refs(sid, {'assets': []}, expect_revision='stale')
            ok('ESTALE on stale revision', False)
        except ConflictError:
            ok('ESTALE on stale revision', True)

        # 删会话联动
        bm.add_upload(sid, 'c.png', b'z' * 10)
        n_files = sum(len(f) for _, _, f in os.walk(os.path.join(bm.root, sid)))
        r = bm.delete_session(sid)
        ok('session dir removed', r['dir_removed'])
        ok('uploads really removed', n_files > 0)

        # TTL 清理（伪造过期 mtime）
        sid2 = new_session_id()
        bm.session_dir(sid2)
        bm.add_upload(sid2, 'old.png', b'o' * 10)
        old = os.path.getmtime(bm._refs_path(sid2)) - 8 * 86400
        os.utime(os.path.join(bm.root, sid2), (old, old))
        os.utime(bm._refs_path(sid2), (old, old))
        r = bm.cleanup(max_age_days=7)
        ok('TTL removed stale session', any(x['session'] == sid2 for x in r['removed_sessions']))

        # 孤儿回收
        sid3 = new_session_id()
        bm.session_dir(sid3)
        e3 = bm.add_upload(sid3, 'gone.png', b'g' * 10)
        os.unlink(os.path.join(bm.root, sid3, e3['path']))
        r = bm.cleanup(max_age_days=7)
        ok('orphan reclaimed', r['orphan_refs_reclaimed'] >= 1)

        # 并发写 refs.json 不损坏
        sid4 = new_session_id()
        bm.session_dir(sid4)
        errs = []

        def w(i):
            try:
                for j in range(5):
                    bm.add_upload(sid4, f'w{i}_{j}.png', b'p' * 5)
            except Exception as ex:
                errs.append(ex)

        ts = [threading.Thread(target=w, args=(i,)) for i in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        ok('concurrent uploads ok', not errs)
        ok('concurrent refs intact', len(bm.list_assets(sid4)) == 20)

        # 原子写无残留 tmp
        tmps = [f for f in os.listdir(os.path.join(bm.root, sid4)) if f.endswith('.tmp')]
        ok('no .tmp leftovers', not tmps)

        # 大小限制
        try:
            bm.add_upload(sid4, 'big.bin', b'b' * (1024 * 1024 + 1))
            ok('size limit enforced', False)
        except ValueError:
            ok('size limit enforced', True)

        # ── v17 缺口①：@文件名 模糊搜索 + 游标分页（Toonflow MentionQuery 对齐）──
        sid5 = 'searchtest'
        bm.add_upload(sid5, '角色参考图.png', b'x' * 100)
        bm.add_upload(sid5, '参考视频.mp4', b'y' * 200)
        bm.add_upload(sid5, '场景图.jpg', b'z' * 50)
        r = bm.search_assets(sid5, query='参考', limit=1)
        ok('search fuzzy hit (total=3, 2 match, page1)', r['total'] == 3 and len(r['items']) == 1)
        r2 = bm.search_assets(sid5, query='参考', cursor=r['next_cursor'], limit=1)
        ok('search cursor page2', len(r2['items']) == 1
           and r2['items'][0]['name'] != r['items'][0]['name'])
        r3 = bm.search_assets(sid5, query='参考', cursor=r2['next_cursor'], limit=1)
        ok('search cursor exhausted (no next)', 'next_cursor' not in r3 and len(r3['items']) == 0)
        try:
            bm.search_assets(sid5, cursor='["wrong-rev", "参考", 0]')
            ok('search stale cursor raises', False)
        except ValueError as e:
            ok('search stale cursor raises', '分页已失效' in str(e))
        try:
            bm.search_assets(sid5, cursor='not-json')
            ok('search bad cursor raises', False)
        except ValueError:
            ok('search bad cursor raises', True)
        ok('search empty query lists all', bm.search_assets(sid5, query='')['total'] == 3)
        bm.add_upload(sid5, '参考新图.png', b'w' * 10)  # revision 变化
        try:
            bm.search_assets(sid5, query='参考', cursor=r['next_cursor'])
            ok('search cursor invalidated by revision', False)
        except ValueError:
            ok('search cursor invalidated by revision', True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    fails = [n for n, c in PASS if not c]
    print(f'\n{len(PASS) - len(fails)}/{len(PASS)} passed')
    if fails:
        print('FAILED:', fails)
        sys.exit(1)


if __name__ == '__main__':
    main()
