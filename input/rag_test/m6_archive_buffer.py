"""M6 产物归档 buffer（v17 M6 正式化：拆解/成片/字幕/prompt 清单/拼贴图 → output/buffer/{session}/）。

用法:
  python input/rag_test/m6_archive_buffer.py <session_id>            # 归档默认 OUT 全部产物
  python input/rag_test/m6_archive_buffer.py <session_id> extra.mp4  # 追加归档指定文件

引用式归档（不拷贝，output/ 铁律不破坏）；幂等：按 name+sha256 去重。
"""
import os
import sys

_ROOT = os.path.abspath(__file__)
for _ in range(3):  # input/rag_test/ → 仓根
    _ROOT = os.path.dirname(_ROOT)
sys.path.insert(0, _ROOT)
from utils.buffer import BufferManager

OUT = 'output/m6/v3'
DEFAULT_FILES = [
    'output/m6/breakdown_孔乙己.json',
    os.path.join(OUT, 'kongyiji_v3.mp4'),
    os.path.join(OUT, 'subs.srt'),
    os.path.join(OUT, 'prompts.md'),
    os.path.join(OUT, 'kf_contact.jpg'),
]


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    sid = sys.argv[1].strip()
    assert sid and '/' not in sid and '\\' not in sid and sid not in ('.', '..'), \
        f'非法 session_id: {sid!r}'
    paths = DEFAULT_FILES + [p for p in sys.argv[2:] if p]
    root = os.path.join('output', 'buffer')
    bm = BufferManager(root)
    existing = {a['name']: a['sha256'] for a in bm.list_assets(sid)}
    n = 0
    for p in paths:
        if not os.path.isfile(p):
            print(f'  跳过（不存在）: {p}')
            continue
        h = bm._sha256(p)  # 全文件 sha256（与 _register 记录口径一致，>1MB 文件去重才可靠）
        prev = existing.get(os.path.basename(p))
        if prev == h:
            print(f'  已归档（同 sha）: {os.path.basename(p)}')
            continue
        e = bm.add_reference(sid, p)
        print(f"  ✓ {e['id']} {e['name']}（{e['size'] // 1024}KB, ref）")
        n += 1
    print(f'\n✓ 归档 {n} 项 → {root}/{sid}/（引用式，会话删除仅清引用不动 output/）')


if __name__ == '__main__':
    main()
