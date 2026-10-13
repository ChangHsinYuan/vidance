"""v17 M1 会话资产缓冲区（buffer）。

设计参考：
- MoneyPrinterTurbo task_dir（per-task 目录归拢）+ task_artifacts.py（原子写 JSON）+
  cache_manager.py（按年龄 TTL 清理）+ 上传安全（basename 净化 + 路径围栏）
- Toonflow utils/assets（sha256 revision 乐观锁 409 ESTALE、100MB 硬限、相对路径统一 /）

目录：
    output/buffer/{session_id}/
        uploads/    用户上传真文件
        archive/    产物引用记录（kind=reference 不拷贝）
        refs.json   资产清单（原子写）
"""
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime
from typing import Any, Optional

_SESSION_RE = re.compile(r'^[0-9a-fA-F]{8,32}$|^[a-z][a-z0-9_-]{2,31}$')
_KINDS = ('image', 'video', 'audio', 'doc', 'other')
_MIME_MAP = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
    '.mp4': 'video/mp4', '.mov': 'video/quicktime', '.avi': 'video/x-msvideo',
    '.webm': 'video/webm', '.mkv': 'video/x-matroska',
    '.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.flac': 'audio/flac', '.m4a': 'audio/mp4',
    '.pdf': 'application/pdf', '.md': 'text/markdown', '.txt': 'text/plain',
    '.json': 'application/json',
}


def _mime_of(name: str) -> str:
    return _MIME_MAP.get(os.path.splitext(name)[1].lower(), 'application/octet-stream')


def kind_of(name: str, mime: str = '') -> str:
    m = mime or _mime_of(name)
    if m.startswith('image/'):
        return 'image'
    if m.startswith('video/'):
        return 'video'
    if m.startswith('audio/'):
        return 'audio'
    if m in ('application/pdf', 'text/markdown', 'text/plain') or m.startswith('text/'):
        return 'doc'
    return 'other'


def new_session_id() -> str:
    return uuid.uuid4().hex


class BufferManager:
    """会话资产缓冲区管理器（api_server 持有单例；CLI 也可独立用）。"""

    def __init__(self, root: str, max_file_size: int = 200 * 1024 * 1024,
                 ttl_days: int = 7):
        self.root = os.path.abspath(root)
        self.max_file_size = max_file_size
        self.ttl_days = ttl_days
        os.makedirs(self.root, exist_ok=True)

    # ── 路径安全（MPT _sanitize_upload_filename + resolve_path_within_directory） ──

    @staticmethod
    def sanitize_name(filename: str) -> str:
        name = (filename or '').replace('\\', '/').split('/')[-1].strip()
        if not name or name in {'.', '..'}:
            raise ValueError('invalid filename')
        name = re.sub(r'[<>:"|?*\x00-\x1f]', '_', name)
        return name[:180]

    def _session_dir(self, session_id: str) -> str:
        if not _SESSION_RE.match(session_id or ''):
            raise ValueError(f'invalid session_id: {session_id!r}')
        return os.path.join(self.root, session_id)

    def _resolve_within(self, base: str, rel: str) -> str:
        rel = (rel or '').replace('\\', '/').strip('/')
        p = os.path.abspath(os.path.join(base, rel))
        if os.path.commonpath([p, os.path.abspath(base)]) != os.path.abspath(base):
            raise PermissionError('path escapes buffer')
        return p

    # ── 目录 ──

    def session_dir(self, session_id: str) -> str:
        d = self._session_dir(session_id)
        os.makedirs(os.path.join(d, 'uploads'), exist_ok=True)
        os.makedirs(os.path.join(d, 'archive'), exist_ok=True)
        return d

    def sessions(self) -> list:
        if not os.path.isdir(self.root):
            return []
        return [n for n in sorted(os.listdir(self.root))
                if os.path.isdir(os.path.join(self.root, n)) and _SESSION_RE.match(n)]

    # ── refs.json 原子写（MPT _write_json_atomic 移植） ──

    def _refs_path(self, session_id: str) -> str:
        return os.path.join(self._session_dir(session_id), 'refs.json')

    def _read_refs(self, session_id: str) -> dict:
        p = self._refs_path(session_id)
        if not os.path.exists(p):
            return {'assets': []}
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
            if not isinstance(d, dict) or not isinstance(d.get('assets'), list):
                raise ValueError('refs.json must be {assets:[...]}')
            return d
        except Exception:
            # 清单损坏：改名留存现场，从空清单恢复（不阻断主流程）
            try:
                shutil.copyfile(p, p + f'.corrupt.{int(time.time())}')
            except OSError:
                pass
            return {'assets': []}

    def _write_refs(self, session_id: str, data: dict, expect_revision: str = '') -> str:
        target = self._refs_path(session_id)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if expect_revision and expect_revision != self.revision_of(session_id):
            raise ConflictError('refs.json has been modified (ESTALE), reload and retry')
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8', dir=os.path.dirname(target),
                    prefix=f'.{os.path.basename(target)}.', suffix='.tmp',
                    delete=False) as tf:
                tmp_path = tf.name
                json.dump(data, tf, ensure_ascii=False, indent=2)
                tf.write('\n')
                tf.flush()
                os.fsync(tf.fileno())
            os.replace(tmp_path, target)
            tmp_path = None
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        return self.revision_of(session_id)

    def revision_of(self, session_id: str) -> str:
        p = self._refs_path(session_id)
        if not os.path.exists(p):
            return ''
        st = os.stat(p)
        return f'{st.st_mtime_ns}:{st.st_size}'

    # ── 上传 ──

    def add_upload(self, session_id: str, filename: str, data: bytes,
                   as_name: str = '') -> dict:
        name = self.sanitize_name(as_name or filename)
        if len(data) > self.max_file_size:
            raise ValueError(f'file too large (>{self.max_file_size // (1024 * 1024)}MB)')
        self.session_dir(session_id)
        # 顶层目录名映射到 kind 子目录，保持 uploads 平铺 + 时间戳前缀防覆盖
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        fname = f'{ts}_{name}'
        dst = self._resolve_within(os.path.join(self._session_dir(session_id), 'uploads'), fname)
        with open(dst, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        return self._register(session_id, dst, kind=kind_of(name), name=name)

    def add_reference(self, session_id: str, path: str, name: str = '') -> dict:
        """归档产物为引用（不拷贝）。path 必须真实存在。"""
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        name = self.sanitize_name(name or os.path.basename(path))
        return self._register(session_id, path,
                              kind=kind_of(name), name=name, is_ref=True)

    def _register(self, session_id: str, path: str, kind: str, name: str,
                  is_ref: bool = False) -> dict:
        d = self._session_dir(session_id)
        rel = os.path.relpath(path, d).replace(os.sep, '/')
        sha = self._sha256(path)
        with _refs_lock:
            refs = self._read_refs(session_id)
            asset_id = uuid.uuid4().hex[:12]
            entry = {'id': asset_id, 'name': name, 'path': rel, 'kind': kind,
                     'mime': _mime_of(name), 'size': os.path.getsize(path),
                     'sha256': sha, 'is_ref': is_ref, 'created': datetime.now().isoformat(),
                     'refs': []}
            if is_ref:
                entry['abs_path'] = path
            refs['assets'].append(entry)
            self._write_refs(session_id, refs)
        return entry

    @staticmethod
    def _sha256(path: str) -> str:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(1 << 20), b''):
                h.update(chunk)
        return h.hexdigest()

    # ── 查询 / 删除 ──

    def list_assets(self, session_id: str) -> list:
        refs = self._read_refs(session_id)
        out = []
        for a in refs['assets']:
            p = self._abs_asset(session_id, a)
            exists = bool(p) and os.path.exists(p)
            url_path = p if a.get('is_ref') else os.path.join(self.root, session_id, a['path'])
            out.append({**a, 'exists': exists, 'abs_file': p,
                        'url': '/api/file?path=' + os.path.abspath(url_path).replace(os.sep, '/')})
        return out

    def _abs_asset(self, session_id: str, asset: dict) -> str:
        """返回资产绝对路径：is_ref 记录的是 buffer 外原路径。"""
        d = self._session_dir(session_id)
        if asset.get('is_ref'):
            return asset.get('abs_path', '')
        return self._resolve_within(d, asset['path'])

    def get_asset(self, session_id: str, asset_id: str) -> Optional[dict]:
        for a in self.list_assets(session_id):
            if a['id'] == asset_id:
                return a
        return None

    def remove_asset(self, session_id: str, asset_id: str, force: bool = False) -> bool:
        with _refs_lock:
            refs = self._read_refs(session_id)
            keep = [a for a in refs['assets'] if a['id'] != asset_id]
            if len(keep) == len(refs['assets']):
                return False
            hit = next(a for a in refs['assets'] if a['id'] == asset_id)
            if hit['refs'] and not force:
                raise ConflictError(f'asset referenced by jobs: {hit["refs"]}')
            if not hit.get('is_ref'):
                try:
                    os.unlink(self._resolve_within(self._session_dir(session_id), hit['path']))
                except OSError:
                    pass
            refs['assets'] = keep
            self._write_refs(session_id, refs)
        return True

    def delete_session(self, session_id: str) -> dict:
        """删会话=删整目录。uploads 真删；archive 只是引用记录（output/ 成片不动）。"""
        d = self._session_dir(session_id)
        n_up = n_ref = 0
        if os.path.isdir(d):
            refs = self._read_refs(session_id)
            for a in refs['assets']:
                if a.get('is_ref'):
                    n_ref += 1
                else:
                    n_up += 1
            shutil.rmtree(d, ignore_errors=True)
        return {'session_id': session_id, 'uploads_removed': n_up,
                'references_removed': n_ref, 'dir_removed': not os.path.isdir(d)}

    def mark_ref(self, session_id: str, asset_id: str, job_id: str) -> bool:
        with _refs_lock:
            refs = self._read_refs(session_id)
            for a in refs['assets']:
                if a['id'] == asset_id:
                    if job_id not in a['refs']:
                        a['refs'].append(job_id)
                    self._write_refs(session_id, refs)
                    return True
        return False

    # ── TTL 清理 + 孤儿回收（MPT cache_manager 思路） ──

    def cleanup(self, max_age_days: Optional[float] = None) -> dict:
        """扫描 buffer/，会话目录 mtime 超 TTL 即整目录删除；顺带回收悬空引用。"""
        days = self.ttl_days if max_age_days is None else max_age_days
        cutoff = time.time() - days * 86400
        removed, reclaimed = [], 0
        for sid in self.sessions():
            d = os.path.join(self.root, sid)
            latest = os.path.getmtime(d)
            refs = self._refs_path(sid)
            if os.path.exists(refs):
                latest = max(latest, os.path.getmtime(refs))
            if latest < cutoff:
                n_assets = len(self._read_refs(sid)['assets'])
                shutil.rmtree(d, ignore_errors=True)
                removed.append({'session': sid, 'assets': n_assets})
                continue
            # 孤儿回收：refs.json 里有但磁盘没有（且非引用型）
            refs = self._read_refs(sid)
            keep = []
            for a in refs['assets']:
                if a.get('is_ref'):
                    keep.append(a)
                    continue
                p = self._abs_asset(sid, a)
                if p and os.path.exists(p):
                    keep.append(a)
                else:
                    reclaimed += 1
            if reclaimed and len(keep) != len(refs['assets']):
                refs['assets'] = keep
                try:
                    self._write_refs(sid, refs)
                except Exception:
                    pass
        return {'removed_sessions': removed, 'orphan_refs_reclaimed': reclaimed,
                'ttl_days': days}


class ConflictError(Exception):
    """sha256/revision 乐观锁冲突（Toonflow ESTALE 同语义）。"""


_refs_lock = __import__('threading').RLock()


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='v17 M1 buffer CLI（测试/运维用）')
    ap.add_argument('--root', default=os.path.join('output', 'buffer'))
    sub = ap.add_subparsers(dest='cmd')
    p_new = sub.add_parser('new'); p_new.add_argument('--session', default='')
    sub.add_parser('sessions')
    p_ls = sub.add_parser('list'); p_ls.add_argument('session')
    p_up = sub.add_parser('upload'); p_up.add_argument('session'); p_up.add_argument('file')
    p_ref = sub.add_parser('ref'); p_ref.add_argument('session'); p_ref.add_argument('path')
    p_rm = sub.add_parser('rm-asset'); p_rm.add_argument('session'); p_rm.add_argument('asset_id')
    p_rm.add_argument('--force', action='store_true')
    p_del = sub.add_parser('rm-session'); p_del.add_argument('session')
    p_clean = sub.add_parser('cleanup'); p_clean.add_argument('--days', type=float, default=None)
    args = ap.parse_args()
    bm = BufferManager(args.root)
    if args.cmd == 'new':
        sid = args.session or bm.new_session_id() if hasattr(bm, 'new_session_id') else new_session_id()
        bm.session_dir(sid)
        print(sid)
    elif args.cmd == 'sessions':
        print('\n'.join(bm.sessions()) or '(empty)')
    elif args.cmd == 'list':
        for a in bm.list_assets(args.session):
            print(a['id'], a['kind'], a['name'], a['size'], 'ref' if a['is_ref'] else 'file',
                  '' if a['exists'] else 'MISSING')
    elif args.cmd == 'upload':
        with open(args.file, 'rb') as f:
            print(json.dumps(bm.add_upload(args.session, os.path.basename(args.file), f.read()),
                             ensure_ascii=False))
    elif args.cmd == 'ref':
        print(json.dumps(bm.add_reference(args.session, args.path), ensure_ascii=False))
    elif args.cmd == 'rm-asset':
        print(bm.remove_asset(args.session, args.asset_id, force=args.force))
    elif args.cmd == 'rm-session':
        print(json.dumps(bm.delete_session(args.session), ensure_ascii=False))
    elif args.cmd == 'cleanup':
        print(json.dumps(bm.cleanup(args.days), ensure_ascii=False))
    else:
        ap.print_help()
