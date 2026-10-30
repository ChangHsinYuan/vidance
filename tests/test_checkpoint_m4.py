"""v17 M4 断点续跑收尾单测：原子 ckpt / sha256 指纹 / 黑板 agent_runs 挂载（无 pytest，直接跑）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.pipeline import Pipeline

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


def main():
    # 1. 原子合并写/读
    d = tempfile.mkdtemp(prefix='m4_ckpt_')
    Pipeline._save_ckpt(d, {'a': 1})
    Pipeline._save_ckpt(d, {'b': {'x': 2}})
    data = Pipeline._load_ckpt(d)
    ok('原子合并写（不覆盖旧键）', data.get('a') == 1 and data.get('b', {}).get('x') == 2)
    ok('updated_at 时间戳存在', 'updated_at' in data)

    # 2. 坏 JSON（崩溃半文件）容错：下次 save 重建
    with open(os.path.join(d, 'checkpoint.json'), 'w') as f:
        f.write('{"a": 1,')
    try:
        bad = Pipeline._load_ckpt(d)
    except Exception:
        bad = None
    ok('坏 JSON 直接 load 会失败（预期行为）', bad is None)
    Pipeline._save_ckpt(d, {'c': 3})
    ok('坏 JSON 后 save 重建成功', Pipeline._load_ckpt(d).get('c') == 3)

    # 3. 空目录 load 返回 {}
    ok('无 checkpoint.json 返回 {}', Pipeline._load_ckpt(tempfile.mkdtemp()) == {})

    # 4. sha256 文件指纹
    f1 = os.path.join(d, 'clip0.mp4')
    with open(f1, 'wb') as f:
        f.write(b'\x00\x01fake-video-payload' * 1000)
    h1 = Pipeline._sha256_file(f1)
    ok('sha256 稳定可复算', h1 == Pipeline._sha256_file(f1) and len(h1) == 64)
    with open(f1, 'ab') as f:
        f.write(b'tamper')
    ok('文件被篡改 → 指纹变化', Pipeline._sha256_file(f1) != h1)

    # 5. clip 指纹（final_video + audio 双键）
    a1 = os.path.join(d, 'shot0.wav')
    with open(a1, 'wb') as f:
        f.write(b'fake-audio' * 100)
    ci = {'shot_id': 0, 'final_video': f1,
          'audio': {'audio_path': a1, 'duration': 3.2}}
    fp = Pipeline._fingerprint_clip(ci)
    ok('指纹含 final_video+audio_path 双键', set(fp) == {'final_video', 'audio_path'})
    ok('指纹值与 _sha256_file 一致', fp['final_video'] == Pipeline._sha256_file(f1))
    ok('文件缺失 → 键跳过不报错',
       'final_video' not in Pipeline._fingerprint_clip(
           {'final_video': os.path.join(d, 'nope.mp4'), 'audio': {}}))

    # 6. resume 校验语义：指纹拦截篡改、旧 checkpoint 向后兼容
    fp_good = Pipeline._fingerprint_clip(ci)
    ci_rec = dict(ci, sha256=fp_good)  # 已落 checkpoint 的 clip 记录

    def _verify(entry):
        fv = entry.get('final_video')
        ap = (entry.get('audio') or {}).get('audio_path')
        fpm = entry.get('sha256') or {}
        return [k for k, want in fpm.items()
                if want and Pipeline._sha256_file(fv if k == 'final_video' else ap) != want]

    ok('完好 clip 指纹校验通过', _verify(ci_rec) == [])
    with open(a1, 'ab') as f:
        f.write(b'x')  # 模拟磁盘变化（checkpoint 记录后文件被改）
    ok('篡改 clip 被指纹拦截', 'audio_path' in _verify(ci_rec))
    ok('旧 checkpoint 无 sha256 字段向后兼容',
       _verify({'shot_id': 9, 'final_video': f1, 'audio': {'audio_path': a1}}) == [])

    # 7. 黑板挂载：agent_runs 写入 + 回查（tmp 库隔离）
    from agents.blackboard import AgentBoard
    tmp_db = os.path.join(d, 'tasks.sqlite')
    board = AgentBoard(db_path=tmp_db)
    board.log('t_m4', 'pipeline', 'm4:clip:3', True, None,
              {'final_video': f1}, None, 0.5)
    runs = board.runs(task_id='t_m4')
    ok('agent_runs 写入可回查', len(runs) == 1 and runs[0]['agent'] == 'pipeline')
    ok('artifacts JSON 往返无损',
       (runs[0].get('artifacts') or {}).get('final_video') == f1)

    # 8. _board_log 全链路（含异常静默）——鸭子对象 + 直接注入 tmp board
    #    （_board_log 懒加载路径用模块导入时绑定的 DEFAULT_DB，会写真库，故不测该分支）
    class _Stub:
        _board = None
        _board_log = Pipeline._board_log
    stub = _Stub()
    stub._board = AgentBoard(db_path=tmp_db)
    stub._board_log('t_m4', 'script', True, {'shots': 3})
    stub._board_log('t_m4', 'bad_stage', False, {}, error='boom')
    runs2 = board.runs(task_id='t_m4')
    ok('_board_log 落库（3 条：clip+script+bad）', len(runs2) == 3)
    ok('ok=0 错误记录可区分', any(not r['ok'] for r in runs2))

    fails = [n for n, c in PASS if not c]
    print(f'\n{len(PASS) - len(fails)}/{len(PASS)} passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
