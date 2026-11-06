#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v21 M3 面向用户细节测试（2026-11-05）
覆盖：core/diagnose.py 规则命中、core/cleanup.py 任务目录清理+保护、
VERSION 文件、config_loader.save_config 写回、vidance init 非交互。
直跑：python tests/test_m3_ux.py
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


class TestDiagnose(unittest.TestCase):
    def test_connection_refused(self):
        from core.diagnose import diagnose
        h = diagnose("HTTPConnectionPool(host='127.0.0.1', port=8189): Connection refused")
        self.assertTrue(any('未启动' in x for x in h))
        self.assertTrue(any('8189' in x and 'wan' in x for x in h), h)

    def test_oom(self):
        from core.diagnose import diagnose
        h = diagnose('torch.cuda.OutOfMemoryError: CUDA out of memory')
        self.assertTrue(any('显存不足' in x for x in h))

    def test_bad_key(self):
        from core.diagnose import diagnose
        h = diagnose('Error code: 401 - invalid_api_key')
        self.assertTrue(any('vidance.py init' in x for x in h))

    def test_edge_tts_net(self):
        from core.diagnose import diagnose
        h = diagnose('Connection timeout to speech.platform.bing.com')
        self.assertTrue(any('cosy-' in x for x in h))

    def test_disk_full(self):
        from core.diagnose import diagnose
        h = diagnose('[Errno 28] No space left on device')
        self.assertTrue(any('clean' in x for x in h))

    def test_websockets_missing(self):
        from core.diagnose import diagnose
        h = diagnose("RuntimeError: websockets 库不可用")
        self.assertTrue(any('重 build 镜像' in x for x in h))

    def test_exit_code(self):
        from core.diagnose import diagnose
        h = diagnose('任务退出 exit code 1')
        self.assertTrue(any('scheduler.log' in x for x in h))

    def test_timeout_7200(self):
        from core.diagnose import diagnose
        h = diagnose('timeout (7200s)')
        self.assertTrue(any('2 小时' in x for x in h))

    def test_no_match(self):
        from core.diagnose import diagnose
        self.assertEqual(diagnose('random gibberish'), [])
        self.assertEqual(diagnose(''), [])
        self.assertEqual(diagnose(None), [])

    def test_dedup_order(self):
        from core.diagnose import diagnose
        h = diagnose('Connection refused 8189 8189')
        self.assertEqual(len(h), len(set(h)))


class TestCleanup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='m3clean_')
        # 4 个任务目录（不同 mtime）+ 1 个非任务目录 + 1 个散文件
        for i, name in enumerate(['auto_1', 'fast_2', 'quick_3', '20260101_000000']):
            d = os.path.join(self.tmp, name)
            os.makedirs(d)
            open(os.path.join(d, 'meta.json'), 'w').write('{}')
            os.utime(d, (1000000 + i * 100, 1000000 + i * 100))
        os.makedirs(os.path.join(self.tmp, 'not_a_task'))
        open(os.path.join(self.tmp, 'dashboard.html'), 'w').write('x')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_find_task_dirs(self):
        from core.cleanup import find_task_dirs
        names = [os.path.basename(d) for d in find_task_dirs(self.tmp)]
        # mtime 新→旧（20260101 设了最晚时间）；非任务目录/散文件不入选
        self.assertEqual(names, ['20260101_000000', 'quick_3', 'fast_2', 'auto_1'])

    def test_clean_keep2(self):
        from core.cleanup import clean_task_dirs
        r = clean_task_dirs(keep=2, output_dir=self.tmp)
        self.assertEqual(r['removed'], ['fast_2', 'auto_1'])
        self.assertEqual(r['kept'], ['20260101_000000', 'quick_3'])
        self.assertFalse(os.path.isdir(os.path.join(self.tmp, 'auto_1')))
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, 'not_a_task')))

    def test_protect(self):
        from core.cleanup import clean_task_dirs
        r = clean_task_dirs(keep=0, output_dir=self.tmp, protected_ids=['auto_1', 'fast_2'])
        self.assertEqual(sorted(r['skipped']), ['auto_1', 'fast_2'])
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, 'auto_1')))

    def test_keep0_all(self):
        from core.cleanup import clean_task_dirs
        r = clean_task_dirs(keep=0, output_dir=self.tmp)
        self.assertEqual(r['freed_dirs'], 4)
        self.assertEqual(r['kept'], [])

    def test_bad_keep(self):
        from core.cleanup import clean_task_dirs
        with self.assertRaises(ValueError):
            clean_task_dirs(keep=-1, output_dir=self.tmp)


class TestVersionAndConfig(unittest.TestCase):
    def test_version_file(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, 'VERSION')))
        v = open(os.path.join(ROOT, 'VERSION'), encoding='utf-8').read().strip()
        self.assertRegex(v, r'^\d+\.\d+\.\d+$')

    def test_save_config_roundtrip(self):
        from agents.common.tools.config_loader import load_config, save_config, user_config_path
        target = user_config_path()
        before = load_config()
        old_keep = (before.get('cleanup') or {}).get('keep', 10)
        try:
            save_config({'cleanup': {'keep': 42}})
            after = load_config()
            self.assertEqual((after.get('cleanup') or {}).get('keep'), 42)
            # 其他段未被破坏
            self.assertEqual(after.get('llm', {}).get('base_url'),
                             before.get('llm', {}).get('base_url'))
        finally:
            save_config({'cleanup': {'keep': old_keep}})
        self.assertEqual((load_config().get('cleanup') or {}).get('keep'), old_keep)

    def test_init_show(self):
        import subprocess
        env = dict(os.environ)
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'core', 'vidance.py'),
                            'init', '--show'], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('llm.base_url', r.stdout)
        self.assertIn('cleanup.keep', r.stdout)

    def test_init_noninteractive(self):
        import subprocess
        from agents.common.tools.config_loader import load_config, save_config, user_config_path
        old = (load_config().get('cleanup') or {}).get('keep', 10)
        try:
            r = subprocess.run([sys.executable, os.path.join(ROOT, 'core', 'vidance.py'),
                                'init', '--cleanup-keep', '7'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('已写入', r.stdout)
            self.assertEqual((load_config().get('cleanup') or {}).get('keep'), 7)
        finally:
            save_config({'cleanup': {'keep': old}})

    def test_init_bad_keep(self):
        import subprocess
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'core', 'vidance.py'),
                            'init', '--cleanup-keep', '999'], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('1-200', r.stderr + r.stdout)


class TestApiM3(unittest.TestCase):
    """端点层（不起 uvicorn，直接调函数）"""
    def test_version_endpoint(self):
        from core.api_server import _version_str, api_version
        self.assertRegex(_version_str(), r'^\d+\.\d+\.\d+$')
        d = api_version()
        self.assertIn('tier', d)
        self.assertEqual(d['version'], _version_str())

    def test_settings_endpoint(self):
        from core.api_server import api_settings
        d = api_settings()
        for k in ('output_dir', 'disk_free_gb', 'task_dir_count', 'cleanup_keep', 'version'):
            self.assertIn(k, d)

    def test_with_hints(self):
        from core.api_server import _with_hints
        t = {'status': 'failed', 'error': 'Connection refused port 8189'}
        self.assertTrue(_with_hints(t)['hints'])
        t2 = {'status': 'completed'}
        self.assertNotIn('hints', _with_hints(t2))
        t3 = {'status': 'failed', 'error': 'gibberish'}
        self.assertEqual(_with_hints(t3)['hints'], [])

    def test_clean_endpoint_dry(self):
        # 走真函数但不删真 output：monkeypatch clean_task_dirs
        import core.api_server as srv
        from core import cleanup as cl
        orig = cl.clean_task_dirs
        calls = {}
        def fake(keep=10, output_dir=None, protected_ids=(), dry_run=False):
            calls['keep'] = keep
            return {'removed': [], 'kept': [], 'skipped': [], 'freed_dirs': 0}
        cl.clean_task_dirs = fake
        try:
            d = srv.api_clean({'keep': 3})
            self.assertEqual(calls['keep'], 3)
            self.assertIn('message', d)
        finally:
            cl.clean_task_dirs = orig


if __name__ == '__main__':
    unittest.main(verbosity=1)
