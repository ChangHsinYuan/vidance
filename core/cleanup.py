#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v21 M3 输出目录清理（2026-11-05）
按 mtime 保留最近 N 个任务目录，其余连目录删除。
任务目录判定：目录内含 meta.json / scheduler.log，或名字是老时间戳格式 2*_。
保护：queued/running 的任务目录不删（protected_ids 传入）。
CLI:  python core/cleanup.py --keep 5 [--dry-run]
"""
import glob
import os
import re
import shutil

TASK_DIR_SIG = ('meta.json', 'scheduler.log')
TS_PAT = re.compile(r'^2\d{6}[_-]')


def find_task_dirs(output_dir):
    """output_dir 下的任务目录（含产物签名或时间戳命名），mtime 新→旧排序"""
    out = []
    for d in glob.glob(os.path.join(output_dir, '*')):
        if not os.path.isdir(d):
            continue
        if any(os.path.isfile(os.path.join(d, s)) for s in TASK_DIR_SIG) or TS_PAT.match(os.path.basename(d)):
            out.append(d)
    return sorted(out, key=os.path.getmtime, reverse=True)


def clean_task_dirs(keep=10, output_dir=None, protected_ids=(), dry_run=False):
    """删 keep 名之后的旧任务目录；返回 {removed, kept, skipped}（skipped=受保护未删）"""
    if keep < 0:
        raise ValueError('keep 须 >= 0')
    dirs = find_task_dirs(output_dir)
    removed, skipped = [], []
    for d in dirs[keep:]:
        name = os.path.basename(d)
        if name in set(protected_ids or ()):
            skipped.append(name)
            continue
        if not dry_run:
            shutil.rmtree(d, ignore_errors=True)
        removed.append(name)
    return {
        'removed': removed,
        'kept': [os.path.basename(d) for d in dirs[:keep]],
        'skipped': skipped,
        'freed_dirs': len(removed),
    }


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='清理旧任务输出目录')
    ap.add_argument('--keep', type=int, default=10, help='保留最近 N 个（默认 10）')
    ap.add_argument('--output-dir', default=None, help='缺省读 config output_dir')
    ap.add_argument('--dry-run', action='store_true', help='只列出将删除的目录')
    a = ap.parse_args()
    od = a.output_dir
    if od is None:
        from agents.common.tools.config_loader import load_config
        od = load_config().get('output_dir', 'output')
    r = clean_task_dirs(keep=a.keep, output_dir=od, dry_run=a.dry_run)
    tag = '[dry-run] ' if a.dry_run else ''
    print(f"{tag}删除 {len(r['removed'])} 个，保留 {len(r['kept'])} 个，保护 {len(r['skipped'])} 个")
    for n in r['removed']:
        print('  -', n)
    for n in r['skipped']:
        print('  (保护)', n)
