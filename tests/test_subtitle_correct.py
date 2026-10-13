"""A1 字幕纠正单元测试（无 pytest 依赖，直接跑）。借鉴 MPT subtitle.correct。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.subtitle_correct import correct_srt, similarity, split_script_lines, _parse_srt

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


def _write_srt(path, items):
    with open(path, 'w', encoding='utf-8') as f:
        for i, (start, end, text) in enumerate(items):
            f.write(f"{i + 1}\n{start} --> {end}\n{text}\n\n")


def main():
    tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tmp_subtitle_test')
    os.makedirs(tmp, exist_ok=True)
    srt_path = os.path.join(tmp, 'test.srt')

    # 1. 切句
    lines = split_script_lines("在遥远的雪山之巅，住着一只小狐狸。它每天看日出！")
    ok('split zh punctuation', lines == ['在遥远的雪山之巅', '住着一只小狐狸', '它每天看日出'])
    ok('split decimal keep', split_script_lines("价格是2.5元") == ['价格是2.5元'])

    # 2. 相似度
    ok('similarity identical', similarity('小狐狸看日出', '小狐狸看日出') == 1.0)
    ok('similarity typo close', similarity('小狐狸看日出', '小孤狸看日出') > 0.8)

    # 3. 错字替换：STT 把"小狐狸"转成"小孤狸"
    script = "在遥远的雪山之巅，住着一只小狐狸。它每天清晨都会看日出。"
    _write_srt(srt_path, [
        ('00:00:00,000', '00:00:03,000', '在遥远的雪山之巅'),
        ('00:00:03,000', '00:00:06,000', '住着一只小孤狸'),        # 错字
        ('00:00:06,000', '00:00:10,000', '它每天清晨都会看日出'),
    ])
    changed = correct_srt(srt_path, script)
    items = _parse_srt(srt_path)
    ok('typo corrected flag', changed)
    ok('typo replaced with script', items[1][2] == '住着一只小狐狸')
    ok('timing preserved', items[1][1] == '00:00:03,000 --> 00:00:06,000')

    # 4. 合并：STT 把一句拆成两段字幕
    script2 = "小狐狸爬上山顶看到了壮丽的日出"
    _write_srt(srt_path, [
        ('00:00:00,000', '00:00:02,000', '小狐狸爬上山顶'),
        ('00:00:02,000', '00:00:05,000', '看到了壮丽的日出'),
    ])
    correct_srt(srt_path, script2)
    items = _parse_srt(srt_path)
    ok('merge two segments into one', len(items) == 1 and items[0][2] == script2)
    ok('merge keeps full span', items[0][1] == '00:00:00,000 --> 00:00:05,000')

    # 5. 幻觉丢弃：BGM 噪声被识别成多余段
    script3 = "夜晚的灯塔照亮海面"
    _write_srt(srt_path, [
        ('00:00:00,000', '00:00:03,000', '夜晚的灯塔照亮海面'),
        ('00:00:03,500', '00:00:05,000', '音乐 呜呜'),             # 幻觉
    ])
    correct_srt(srt_path, script3)
    items = _parse_srt(srt_path)
    ok('hallucination dropped', len(items) == 1 and items[0][2] == script3)

    # 6. STT 漏句：剧本 2 句 STT 只出 1 段（漏的不留零时长字幕）
    script4 = "第一句话讲完了。第二句话被漏掉了。"
    _write_srt(srt_path, [
        ('00:00:00,000', '00:00:03,000', '第一句话讲完了'),
    ])
    correct_srt(srt_path, script4)
    items = _parse_srt(srt_path)
    ok('missing line not fabricated', len(items) == 1)

    # 7. 完全一致时不动
    script5 = "完全一致的一句"
    _write_srt(srt_path, [('00:00:00,000', '00:00:02,000', '完全一致的一句')])
    changed = correct_srt(srt_path, script5)
    ok('identical no change', not changed)

    # 8. CLI 入口
    import subprocess
    r = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                      'utils', 'subtitle_correct.py'), srt_path, srt_path],
        capture_output=True, text=True)
    ok('cli runs', r.returncode == 0)

    # 清理
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for n, c in PASS if not c]
    print(f"\n{len(PASS) - len(failed)}/{len(PASS)} passed")
    if failed:
        print('FAILED:', failed)
        sys.exit(1)


if __name__ == '__main__':
    main()
