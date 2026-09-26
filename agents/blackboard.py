"""v11（原 v13）黑板：Agent 运行记录落 SQLite（复用 output/tasks.sqlite，新表 agent_runs）。"""
import os
import sys
import json
import sqlite3
import time

_ROOT = os.path.abspath(__file__)
for _ in range(2):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

DEFAULT_DB = os.path.join(_ROOT, 'output', 'tasks.sqlite')

_SCHEMA = '''CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT DEFAULT '',
    agent TEXT NOT NULL,
    layer TEXT NOT NULL,
    ok INTEGER NOT NULL,
    score REAL,
    artifacts_json TEXT,
    error TEXT,
    t_start REAL,
    t_dur REAL
);
CREATE INDEX IF NOT EXISTS idx_agent_runs_task ON agent_runs(task_id);'''


class AgentBoard:
    def __init__(self, db_path=DEFAULT_DB):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=30)

    def log(self, task_id, agent, layer, ok, score, artifacts, error, t_dur, t_start=None):
        with self._conn() as c:
            c.execute(
                'INSERT INTO agent_runs(task_id,agent,layer,ok,score,artifacts_json,error,'
                't_start,t_dur) VALUES(?,?,?,?,?,?,?,?,?)',
                (task_id, agent, layer, 1 if ok else 0, score,
                 json.dumps(artifacts, ensure_ascii=False, default=str),
                 (error or '')[:2000], t_start or time.time(), t_dur))

    def runs(self, task_id=None, limit=100):
        q = 'SELECT id,task_id,agent,layer,ok,score,artifacts_json,error,t_start,t_dur ' \
            'FROM agent_runs'
        args = []
        if task_id:
            q += ' WHERE task_id=?'
            args.append(task_id)
        q += ' ORDER BY id DESC LIMIT ?'
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        out = []
        for r in rows:
            try:
                art = json.loads(r[6]) if r[6] else {}
            except Exception:
                art = {'raw': r[6]}
            out.append({'id': r[0], 'task_id': r[1], 'agent': r[2], 'layer': r[3],
                        'ok': bool(r[4]), 'score': r[5], 'artifacts': art,
                        'error': r[7], 't_start': r[8], 't_dur': r[9]})
        return out


if __name__ == '__main__':
    b = AgentBoard()
    import pprint
    pprint.pprint(b.runs(limit=10))
