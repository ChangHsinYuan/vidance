#!/usr/bin/env python3
"""异步任务队列 — SQLite 持久化 + 并发调度

用法:
  from core.scheduler import TaskQueue, Scheduler
  
  # 提交任务
  queue = TaskQueue()
  task_id = queue.submit(concept="一只猫在月球上跳舞", options={...})
  
  # 查询
  task = queue.get_task(task_id)
  tasks = queue.list_tasks(status="running")
  
  # 调度器（后台进程）
  scheduler = Scheduler(queue, max_concurrent=2)
  scheduler.run()  # 阻塞，轮询队列

CLI:
  # 启动调度器
  python core/scheduler.py --max-concurrent 2
  
  # 提交任务
  python core/scheduler.py submit "一只猫在月球上跳舞" --character "红色小狐狸"
  
  # 查看队列
  python core/scheduler.py list
  python core/scheduler.py status <task_id>
"""
import json
import os
import sys
import time
import sqlite3
import threading
import subprocess
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'config.json')
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'output', 'tasks.sqlite')


def _now_iso():
    """带时区的本地时间 ISO 串（浏览器可正确解析；容器 UTC 环境下不再 8h 偏差）"""
    return datetime.now().astimezone().isoformat(timespec='seconds')

VALID_STATUSES = ('queued', 'running', 'completed', 'failed', 'cancelled')
VALID_STAGES = ('queued', 'generating', 'post_processing', 'completed', 'failed')


def load_config():
    from utils.config_loader import load_config as _load
    return _load()


class TaskQueue:
    """SQLite 持久化任务队列"""

    def __init__(self, db_path=None):
        self.db_path = db_path or DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()
        self._lock = threading.Lock()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    concept TEXT NOT NULL,
                    status TEXT DEFAULT 'queued',
                    stage TEXT DEFAULT 'queued',
                    progress REAL DEFAULT 0,
                    options TEXT DEFAULT '{}',
                    output TEXT,
                    error TEXT,
                    created_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    pid INTEGER
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS scout_batches (
                    batch_id TEXT PRIMARY KEY,
                    scraped_at TEXT,
                    topics_json TEXT,
                    candidates_json TEXT,
                    selected_json TEXT
                )
            ''')

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def submit(self, concept, options=None, task_id=None):
        """提交新任务到队列（task_id 缺省 {task_prefixes[mode]}_{时间戳}）"""
        if task_id is None:
            from agents.common.tools.config_loader import task_id_for
            task_id = task_id_for((options or {}).get('mode', 'auto'))
        opts = json.dumps(options or {}, ensure_ascii=False)
        now = _now_iso()

        with self._lock, self._get_conn() as conn:
            conn.execute(
                'INSERT INTO tasks (task_id, concept, status, stage, options, created_at) '
                'VALUES (?, ?, "queued", "queued", ?, ?)',
                (task_id, concept, opts, now),
            )
            conn.commit()
        print(f'  [queue] submitted: {task_id} — {concept[:40]}')
        return task_id

    def get_task(self, task_id):
        """查询单个任务"""
        with self._get_conn() as conn:
            row = conn.execute(
                'SELECT * FROM tasks WHERE task_id = ?', (task_id,)
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_tasks(self, status=None, limit=50):
        """列出任务"""
        with self._get_conn() as conn:
            if status:
                rows = conn.execute(
                    'SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?',
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    'SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?', (limit,)
                ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_task(self, task_id, **fields):
        """更新任务字段"""
        valid = {'status', 'stage', 'progress', 'output', 'error',
                 'started_at', 'completed_at', 'pid'}
        updates = {k: v for k, v in fields.items() if k in valid}
        if not updates:
            return

        set_clause = ', '.join(f'{k} = ?' for k in updates)
        values = list(updates.values()) + [task_id]

        with self._lock, self._get_conn() as conn:
            conn.execute(
                f'UPDATE tasks SET {set_clause} WHERE task_id = ?', values
            )
            conn.commit()

    def cancel_task(self, task_id):
        """取消任务（仅 queued 状态可取消）"""
        task = self.get_task(task_id)
        if not task:
            return False, 'task not found'
        if task['status'] != 'queued':
            return False, f'cannot cancel task in {task["status"]} state'
        self.update_task(task_id, status='cancelled')
        return True, 'cancelled'

    def get_next_queued(self):
        """获取下一个排队任务（FIFO）"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM tasks WHERE status = 'queued' "
                "ORDER BY created_at ASC LIMIT 1"
            ).fetchone()
        return self._row_to_dict(row) if row else None

    def count_by_status(self, status):
        with self._get_conn() as conn:
            row = conn.execute(
                'SELECT COUNT(*) FROM tasks WHERE status = ?', (status,)
            ).fetchone()
        return row[0] if row else 0

    @staticmethod
    def _row_to_dict(row):
        if not row:
            return None
        cols = ['task_id', 'concept', 'status', 'stage', 'progress', 'options',
                'output', 'error', 'created_at', 'started_at', 'completed_at', 'pid']
        d = dict(zip(cols, row))
        try:
            d['options'] = json.loads(d.get('options') or '{}')
        except (json.JSONDecodeError, TypeError):
            d['options'] = {}
        return d

    def save_scout_batch(self, batch_id, topics, candidates, selected=None):
        """保存选题批次记录"""
        now = _now_iso()
        with self._get_conn() as conn:
            conn.execute(
                'INSERT OR REPLACE INTO scout_batches '
                '(batch_id, scraped_at, topics_json, candidates_json, selected_json) '
                'VALUES (?, ?, ?, ?, ?)',
                (batch_id, now,
                 json.dumps(topics, ensure_ascii=False),
                 json.dumps(candidates, ensure_ascii=False),
                 json.dumps(selected or [], ensure_ascii=False)),
            )
            conn.commit()

    def get_scout_batch(self, batch_id):
        with self._get_conn() as conn:
            row = conn.execute(
                'SELECT * FROM scout_batches WHERE batch_id = ?', (batch_id,)
            ).fetchone()
        if not row:
            return None
        return {
            'batch_id': row[0],
            'scraped_at': row[1],
            'topics': json.loads(row[2]),
            'candidates': json.loads(row[3]),
            'selected': json.loads(row[4]),
        }


class Scheduler:
    """并发任务调度器"""

    def __init__(self, queue=None, max_concurrent=2, config=None):
        self.queue = queue or TaskQueue()
        self.max_concurrent = max_concurrent
        self.config = config or load_config()
        self._running_threads = {}
        self._lock = threading.Lock()

    def run(self, poll_interval=5):
        """主调度循环（阻塞）"""
        print(f'  [scheduler] started, max_concurrent={self.max_concurrent}')
        self._fail_orphans()
        while True:
            self._cleanup_finished()
            running = self.queue.count_by_status('running')

            while running < self.max_concurrent:
                task = self.queue.get_next_queued()
                if not task:
                    break
                self._start_task(task)
                running += 1

            time.sleep(poll_interval)

    def _fail_orphans(self):
        """启动清扫：status=running 但进程已死的僵尸任务（服务重启/容器重建中断）标记失败。

        按 pid 存活判断——避免误杀另一个 API 实例（8894/9401 共库）正在跑的任务。
        pid=NULL 的历史僵尸不自动清理（无法判活，人工取消），新任务起 _start_task 已记录 pid。
        """
        import os as _os
        with self.queue._lock, self.queue._get_conn() as conn:
            rows = conn.execute(
                "SELECT task_id, pid FROM tasks WHERE status='running'").fetchall()
            for task_id, pid in rows or []:
                alive = False
                try:
                    if pid:
                        _os.kill(int(pid), 0)
                        alive = True
                except (ValueError, ProcessLookupError, PermissionError):
                    alive = False
                except OSError:
                    alive = True  # pid 存在但无权限（EPERM）= 活着
                if pid and not alive:
                    conn.execute(
                        "UPDATE tasks SET status='failed', error=?, completed_at=? "
                        "WHERE task_id=? AND status='running'",
                        ('服务重启中断（原进程已死），请重新提交', _now_iso(), task_id))
                    print(f'  [scheduler] orphan cleaned: {task_id}')

    def _cleanup_finished(self):
        """清理已完成的线程"""
        finished = [tid for tid, t in self._running_threads.items() if not t.is_alive()]
        for tid in finished:
            del self._running_threads[tid]

    def _start_task(self, task):
        """启动一个任务线程"""
        now = _now_iso()
        self.queue.update_task(task['task_id'], status='running', stage='generating',
                               started_at=now, pid=os.getpid())

        t = threading.Thread(target=self._run_task, args=(task,), daemon=True)
        self._running_threads[task['task_id']] = t
        t.start()
        print(f'  [scheduler] started: {task["task_id"]} — {task["concept"][:40]}')

    def _watch_progress(self, task_id, log_path, stop_evt):
        """tail scheduler.log 解析阶段标记 → 实时回写 task.stage（任务卡片轮询可见）。

        识别：=== [1] 编剧 === / ▸ [1] … / ▶ … / [S1] … 等标记行，取最后一条。
        """
        import re
        while not stop_evt.is_set():
            stop_evt.wait(2.0)
            if stop_evt.is_set():
                break
            try:
                if not os.path.isfile(log_path):
                    continue
                with open(log_path, 'r', errors='replace') as f:
                    lines = f.read().splitlines()
                stage = None
                for ln in reversed(lines):
                    m = re.match(r'=+\s*(.+?)\s*=+\s*$', ln)  # === [1] 编剧 ===
                    if m:
                        stage = m.group(1)
                        break
                    m = re.match(r'[▸▶]\s*(.+)', ln)          # ▸ / ▶
                    if m:
                        stage = m.group(1)
                        break
                    m = re.match(r'\[(S\d+)\]\s*(.+)', ln)    # [S1] LLM 生成 SVG
                    if m:
                        stage = m.group(1) + ' ' + m.group(2)
                        break
                if not stage:
                    continue
                cur = self.queue.get_task(task_id)
                if cur and cur.get('status') == 'running':
                    self.queue.update_task(task_id, stage=stage[:80])
            except Exception:
                pass

    def _run_task(self, task):
        """执行单个任务（子进程调用 vidance.py {auto|fast|hot}，v7 加 mode 分发）"""
        task_id = task['task_id']
        opts = task['options']
        concept = task['concept']
        mode = opts.get('mode', 'auto')
        if mode == 'chain':
            return self._run_chain_task(task)
        if mode not in ('auto', 'fast', 'hot', 'quick'):
            mode = 'auto'

        cmd = [sys.executable, '-u', os.path.join(os.path.dirname(__file__), 'vidance.py'),
               mode, concept]

        if mode == 'quick':
            if opts.get('voice'):
                cmd += ['--voice', opts['voice']]
        elif mode == 'auto':
            if opts.get('character'):
                cmd += ['--character', opts['character']]
            if opts.get('character_mode'):
                cmd += ['--character-mode', opts['character_mode']]
            if opts.get('voice'):
                cmd += ['--voice', opts['voice']]
            if opts.get('duration'):
                cmd += ['--duration', str(opts['duration'])]
            if opts.get('slowmo'):
                cmd += ['--slowmo', str(opts['slowmo'])]
            if opts.get('lut'):
                cmd += ['--lut', opts['lut']]
            if opts.get('bgm'):
                cmd += ['--bgm', opts['bgm']]
            if opts.get('no_rife'):
                cmd += ['--no-rife']
            if opts.get('no_color'):
                cmd += ['--no-color']
            if opts.get('no_bgm'):
                cmd += ['--no-bgm']
            if opts.get('live_audit'):
                cmd += ['--live-audit']  # v20 生成中审核
        elif mode == 'fast':
            if opts.get('images_source'):
                cmd += ['--images-source', opts['images_source']]
            if opts.get('images_count'):
                cmd += ['-n', str(opts['images_count'])]
            if opts.get('effects'):
                cmd += ['--effects', opts['effects']]
            if opts.get('voice'):
                cmd += ['--voice', opts['voice']]
            if opts.get('motion'):
                cmd += ['--motion', opts['motion']]
            if opts.get('lut'):
                cmd += ['--lut', opts['lut']]
            if opts.get('bgm'):
                cmd += ['--bgm', opts['bgm']]
            if opts.get('slowmo'):
                cmd += ['--slowmo', str(opts['slowmo'])]
            if opts.get('stt'):
                cmd += ['--stt']
            if opts.get('no_bgm'):
                cmd += ['--no-bgm']
        else:  # hot
            if opts.get('images_count'):
                cmd += ['-n', str(opts['images_count'])]
            if opts.get('top_each'):
                cmd += ['--top-each', str(opts['top_each'])]
            if opts.get('account'):
                cmd += ['--account', opts['account']]
            if opts.get('images_source'):
                cmd += ['--images-source', opts['images_source']]
            if opts.get('effects'):
                cmd += ['--effects', opts['effects']]
            if opts.get('voice'):
                cmd += ['--voice', opts['voice']]
            if opts.get('lut'):
                cmd += ['--lut', opts['lut']]
            if opts.get('bgm'):
                cmd += ['--bgm', opts['bgm']]
            if opts.get('stt'):
                cmd += ['--stt']

        cmd += ['--task-id', task_id]

        log_path = os.path.join(self.config['output_dir'], task_id, 'scheduler.log')
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        try:
            with open(log_path, 'w') as logf:
                proc = subprocess.Popen(
                    cmd, stdout=logf, stderr=subprocess.STDOUT,
                )
                stop_evt = threading.Event()
                watcher = threading.Thread(target=self._watch_progress,
                                           args=(task_id, log_path, stop_evt),
                                           daemon=True)
                watcher.start()
                try:
                    rc = proc.wait(timeout=7200)
                finally:
                    stop_evt.set()
                    watcher.join(timeout=1)

            if rc == 0:
                final_path = os.path.join(self.config['output_dir'], task_id, 'final.mp4')
                now = _now_iso()
                self.queue.update_task(
                    task_id, status='completed', stage='completed',
                    progress=1.0, output=final_path, completed_at=now,
                )
                print(f'  [scheduler] completed: {task_id}')
            else:
                now = _now_iso()
                self.queue.update_task(
                    task_id, status='failed', stage='failed',
                    error=f'exit code {rc}', completed_at=now,
                )
                print(f'  [scheduler] failed: {task_id} (exit {rc})')

        except subprocess.TimeoutExpired:
            try:
                if proc and proc.poll() is None:
                    proc.kill()
                    proc.wait()
            except Exception:
                pass
            now = _now_iso()
            self.queue.update_task(
                task_id, status='failed', stage='failed',
                error='timeout (7200s)', completed_at=now,
            )
            print(f'  [scheduler] timeout: {task_id}')
        except Exception as e:
            now = _now_iso()
            self.queue.update_task(
                task_id, status='failed', stage='failed',
                error=str(e), completed_at=now,
            )
            print(f'  [scheduler] error: {task_id} — {e}')

    def _run_chain_task(self, task):
        """v11（原 v13）mode=chain：进程内运行 agent 链（agents.runtime.run_chain）。"""
        import io
        import json as _json
        from contextlib import redirect_stdout
        task_id = task['task_id']
        opts = task['options']
        steps = opts.get('chain') or []
        ctx = opts.get('ctx') or {}
        log_path = os.path.join(self.config['output_dir'], task_id, 'scheduler.log')
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        now = _now_iso()
        self.queue.update_task(task_id, status='running', stage='chain',
                               progress=0.0, started_at=now)
        try:
            from agents.runtime import run_chain
            buf = io.StringIO()
            with redirect_stdout(buf):
                out = run_chain(steps, ctx=ctx, task_id=task_id,
                                board=_board())
            with open(log_path, 'w') as f:
                f.write(buf.getvalue())
                f.write('\n===== chain result =====\n')
                f.write(_json.dumps({k: v for k, v in out.items() if k != 'ctx'},
                                    ensure_ascii=False, indent=2, default=str))
            video = out.get('ctx', {}).get('video')
            now = _now_iso()
            if out.get('ok'):
                self.queue.update_task(task_id, status='completed', stage='completed',
                                       progress=1.0, output=video, completed_at=now)
                print(f'  [scheduler] chain completed: {task_id} — {video}')
            else:
                err = next((s.get('error') for s in out.get('steps', [])
                            if not s.get('ok')), 'chain failed')
                self.queue.update_task(task_id, status='failed', stage='failed',
                                       error=err, completed_at=now)
                print(f'  [scheduler] chain failed: {task_id} — {err}')
        except Exception as e:
            now = _now_iso()
            self.queue.update_task(task_id, status='failed', stage='failed',
                                   error=str(e), completed_at=now)
            print(f'  [scheduler] chain error: {task_id} — {e}')


def _board():
    from agents.blackboard import AgentBoard
    return AgentBoard()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Vidance 任务队列 + 调度器')
    sub = parser.add_subparsers(dest='command')

    # 启动调度器
    run_p = sub.add_parser('run', help='启动调度器')
    run_p.add_argument('--max-concurrent', '-c', type=int, default=2)
    run_p.add_argument('--poll', type=float, default=5)

    # 提交任务
    submit_p = sub.add_parser('submit', help='提交任务')
    submit_p.add_argument('concept', help='视频概念')
    submit_p.add_argument('--character', '-ch', default=None)
    submit_p.add_argument('--character-mode', '-cm', default='flux')
    submit_p.add_argument('--voice', '-v', default=None)
    submit_p.add_argument('--duration', '-d', type=float, default=None)
    submit_p.add_argument('--no-rife', action='store_true')
    submit_p.add_argument('--no-color', action='store_true')
    submit_p.add_argument('--no-bgm', action='store_true')

    # 列表
    list_p = sub.add_parser('list', help='列出任务')
    list_p.add_argument('--status', '-s', default=None)
    list_p.add_argument('--limit', '-n', type=int, default=20)

    # 状态
    status_p = sub.add_parser('status', help='查看任务状态')
    status_p.add_argument('task_id')

    # 取消
    cancel_p = sub.add_parser('cancel', help='取消任务')
    cancel_p.add_argument('task_id')

    # 仪表盘
    dash_p = sub.add_parser('dashboard', help='生成仪表盘 HTML')
    dash_p.add_argument('-o', '--output', default=None)

    args = parser.parse_args()

    queue = TaskQueue()

    if args.command == 'run':
        scheduler = Scheduler(queue, max_concurrent=args.max_concurrent)
        scheduler.run(poll_interval=args.poll)

    elif args.command == 'submit':
        opts = {}
        if args.character:
            opts['character'] = args.character
        if args.character_mode:
            opts['character_mode'] = args.character_mode
        if args.voice:
            opts['voice'] = args.voice
        if args.duration:
            opts['duration'] = args.duration
        if args.no_rife:
            opts['no_rife'] = True
        if args.no_color:
            opts['no_color'] = True
        if args.no_bgm:
            opts['no_bgm'] = True
        task_id = queue.submit(args.concept, options=opts)
        print(f'Task ID: {task_id}')

    elif args.command == 'list':
        tasks = queue.list_tasks(status=args.status, limit=args.limit)
        print(f'{"Task ID":<25} {"Status":<12} {"Concept":<40} {"Created"}')
        print('-' * 100)
        for t in tasks:
            print(f'{t["task_id"]:<25} {t["status"]:<12} {t["concept"][:40]:<40} {t.get("created_at","")}')

    elif args.command == 'status':
        t = queue.get_task(args.task_id)
        if not t:
            print('Task not found')
            sys.exit(1)
        print(json.dumps(t, ensure_ascii=False, indent=2))

    elif args.command == 'cancel':
        ok, msg = queue.cancel_task(args.task_id)
        print(f'{msg}')

    elif args.command == 'dashboard':
        from core.dashboard import generate_dashboard
        out = args.output or os.path.join(
            os.path.dirname(__file__), '..', 'output', 'dashboard.html')
        generate_dashboard(queue, out)
        print(f'Dashboard: {out}')

    else:
        parser.print_help()
