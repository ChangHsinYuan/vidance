#!/usr/bin/env python3
"""FastAPI 异步任务队列服务 — HTTP API 提交/查询/管理视频生成任务

启动:
  python core/api_server.py                     # 默认 0.0.0.0:8894
  python core/api_server.py --port 9000         # 自定义端口

API:
  POST   /api/tasks          提交任务
  GET    /api/tasks          列出任务 (?status=queued&limit=20)
  GET    /api/tasks/{id}     查询任务详情
  DELETE /api/tasks/{id}     取消任务
  GET    /api/dashboard      HTML 仪表盘
  GET    /api/health         健康检查
  POST   /api/scout          选题（爬热点→概念候选）
  GET    /api/scout/{id}     查询选题结果
  POST   /api/clone_voice    音色克隆（爬人声→CosyVoice，异步）
  GET    /api/clone_voice/{id}  查询克隆任务
  GET    /api/voices         已注册自定义音色
  POST   /api/clip           FunClip 长素材语义裁剪（异步）
  GET    /api/clip/{id}      查询裁剪任务
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import StreamingResponse
from fastapi.responses import HTMLResponse, FileResponse, Response
from pydantic import BaseModel
from typing import Optional

from core.scheduler import TaskQueue, Scheduler, load_config

from agents.common.tools.config_loader import capabilities

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'config.json')

app = FastAPI(title='Vidance Task Queue', version='4.2.0')
queue = TaskQueue()
scheduler = None


class TaskSubmit(BaseModel):
    concept: str
    mode: str = 'auto'  # v7: auto|fast|hot；v11（原 v13）: chain（agent 链编排）
    chain: Optional[list] = None   # v11（原 v13）: mode=chain 时的 agent 步骤 [{agent, with, as?, optional?}]
    ctx: Optional[dict] = None     # v11（原 v13）: mode=chain 的初始上下文
    character: Optional[str] = None
    character_mode: str = 'flux'
    voice: Optional[str] = None
    duration: Optional[float] = None
    slowmo: Optional[int] = None
    lut: Optional[str] = None
    bgm: Optional[str] = None
    no_rife: bool = False
    no_color: bool = False
    no_bgm: bool = False
    # v7 fast/hot 参数
    images_source: Optional[str] = None
    images_count: Optional[int] = None
    effects: Optional[str] = None
    motion: Optional[str] = None
    stt: bool = False
    top_each: Optional[int] = None
    account: Optional[str] = None


class ScoutRequest(BaseModel):
    top_per_source: int = 15
    account_type: str = '影视解说'
    n_candidates: int = 5


class CloneVoiceRequest(BaseModel):
    keyword: str = '新闻播报'
    name: str = ''
    index: int = 0
    desc: Optional[str] = None
    reload_tts: bool = True


class ClipRequest(BaseModel):
    input: str
    instructions: str
    output: Optional[str] = None
    use_llm: bool = True


@app.on_event('startup')
def startup():
    global scheduler
    scheduler = Scheduler(queue, max_concurrent=1)
    t = threading.Thread(target=scheduler.run, kwargs={'poll_interval': 5}, daemon=True)
    t.start()
    print(f'  [api] scheduler started (max_concurrent=1)')


@app.get('/api/health')
def health():
    cfg = load_config()
    return {
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'tier': cfg.get('tier', 'full'),
        'tier_desc': cfg.get('tier_desc', ''),
        'capabilities': cfg.get('tier_capabilities'),
        'llm': _llm_health(),
        'queue': {
            'queued': queue.count_by_status('queued'),
            'running': queue.count_by_status('running'),
            'completed': queue.count_by_status('completed'),
            'failed': queue.count_by_status('failed'),
        },
    }


_LLM_HL = {'ts': 0.0, 'ok': None, 'latency_ms': None}
_LLM_HL_TTL = 30.0


def _llm_health() -> dict:
    """LLM 探活（GET /models，2s 超时，30s 缓存——不阻塞健康检查）"""
    now = time.time()
    if _LLM_HL['ok'] is not None and now - _LLM_HL['ts'] < _LLM_HL_TTL:
        return {'ok': _LLM_HL['ok'], 'latency_ms': _LLM_HL['latency_ms'],
                'cached': True}
    ok, lat = False, None
    try:
        base_url, api_key, _m = llm_health_target()
        t0 = time.time()
        req = urllib.request.Request(
            f'{base_url}/models', headers={'Authorization': f'Bearer {api_key}'})
        urllib.request.urlopen(req, timeout=2).read()
        ok, lat = True, int((time.time() - t0) * 1000)
    except Exception:
        pass
    _LLM_HL.update(ts=now, ok=ok, latency_ms=lat)
    return {'ok': ok, 'latency_ms': lat, 'cached': False}


def llm_health_target():
    """健康灯用：取 LLM base_url/key（复用 LLMClient 配置，不发起对话）"""
    from agents.common.tools.llm import LLMClient
    c = LLMClient(load_config())
    return c._resolve(c.models['script'])


@app.post('/api/tasks')
def submit_task(req: TaskSubmit):
    opts = {
        k: v for k, v in req.model_dump().items()
        if k != 'concept' and v is not None and v is not False
    }
    task_id = queue.submit(req.concept, options=opts)
    return {'task_id': task_id, 'status': 'queued', 'concept': req.concept}


@app.get('/api/tasks')
def list_tasks(
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    tasks = queue.list_tasks(status=status, limit=limit)
    return {'tasks': tasks, 'count': len(tasks)}


@app.delete('/api/tasks/{task_id}')
def delete_task(task_id: str):
    """删除历史记录：tasks 行 + agent_runs 台账行 + output 下同名目录。"""
    import shutil
    import sqlite3
    if not re.fullmatch(r'[\w.\-]{1,120}', task_id):
        raise HTTPException(status_code=400, detail='bad task_id')
    try:
        queue.cancel_task(task_id)
    except Exception:
        pass
    rows = 0
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), '..',
                                        'output', 'tasks.sqlite'), timeout=30)
    try:
        rows += conn.execute('DELETE FROM tasks WHERE task_id=?',
                             (task_id,)).rowcount
        try:
            rows += conn.execute('DELETE FROM agent_runs WHERE task_id=?',
                                 (task_id,)).rowcount
        except sqlite3.OperationalError:
            pass
        conn.commit()
    finally:
        conn.close()
    roots = [os.path.realpath(load_config().get('output_dir', 'output')),
             os.path.realpath(os.path.join(os.path.dirname(__file__), '..', 'output'))]
    dir_removed = False
    for oroot in dict.fromkeys(roots):
        d = os.path.realpath(os.path.join(oroot, task_id))
        if d.startswith(oroot + os.sep) and os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            dir_removed = not os.path.isdir(d)
            if dir_removed:
                break
    return {'deleted': task_id, 'rows': rows, 'dir_removed': bool(dir_removed)}


@app.get('/api/tasks/{task_id}')
def get_task(task_id: str):
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    return task


@app.post('/api/tasks/{task_id}/cancel')
def cancel_task(task_id: str):
    ok, msg = queue.cancel_task(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {'task_id': task_id, 'status': 'cancelled'}


@app.post('/api/scout')
def scout(req: ScoutRequest):
    from utils.crawler import Crawler
    from utils.llm import LLMClient

    config = load_config()
    crawler = Crawler()
    llm = LLMClient(config)

    topics = crawler.fetch_hot_topics(top_per_source=req.top_per_source)
    candidates = llm.scout_topics(
        topics, account_type=req.account_type, n_candidates=req.n_candidates)

    batch_id = datetime.now().strftime('%Y%m%d_%H%M%S')
    queue.save_scout_batch(batch_id, topics, candidates)
    return {
        'batch_id': batch_id,
        'topics_count': len(topics),
        'candidates': candidates,
    }


@app.get('/api/scout/{batch_id}')
def get_scout(batch_id: str):
    batch = queue.get_scout_batch(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail='Scout batch not found')
    return batch


@app.get('/api/dashboard', response_class=HTMLResponse)
def dashboard():
    from core.dashboard import generate_dashboard_html
    return generate_dashboard_html(queue)


# ── v4 M3: 音色克隆（异步线程，下载+VAD+转写约 1-3 分钟） ──
_voice_jobs = {}
_voice_jobs_lock = threading.Lock()


def _run_clone_voice(job_id: str, req: CloneVoiceRequest):
    from utils.voice_clone import VoiceCloner
    try:
        vc = VoiceCloner()
        name = req.name or f'clone_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        report = vc.clone(req.keyword, name, index=req.index, desc=req.desc)

        if req.reload_tts:
            try:
                import urllib.request
                urllib.request.urlopen(
                    urllib.request.Request('http://127.0.0.1:9880/voices/reload',
                                           method='POST'), timeout=10)
            except Exception:
                pass

        with _voice_jobs_lock:
            _voice_jobs[job_id].update({
                'status': 'completed', 'voice': f'cosy-{name}',
                'report': {k: v for k, v in report.items() if k != 'steps'},
                'sample': report.get('steps', {}).get('test', {}).get('sample'),
                'completed_at': datetime.now().isoformat(),
            })
    except Exception as e:
        with _voice_jobs_lock:
            _voice_jobs[job_id].update({
                'status': 'failed', 'error': str(e),
                'completed_at': datetime.now().isoformat(),
            })


@app.post('/api/clone_voice')
def clone_voice(req: CloneVoiceRequest):
    job_id = f'voice_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    with _voice_jobs_lock:
        _voice_jobs[job_id] = {
            'job_id': job_id, 'keyword': req.keyword, 'name': req.name,
            'status': 'running', 'created_at': datetime.now().isoformat(),
        }
    threading.Thread(target=_run_clone_voice, args=(job_id, req), daemon=True).start()
    return {'job_id': job_id, 'status': 'running'}


@app.get('/api/clone_voice/{job_id}')
def get_clone_voice(job_id: str):
    with _voice_jobs_lock:
        job = _voice_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    return job


@app.get('/api/voices')
def list_voices():
    from utils.voice_clone import VoiceCloner
    return {'custom': VoiceCloner().list_voices()}


# ── v4 M4: FunClip 长素材语义裁剪（异步线程，ASR+LLM 约 30s-2min） ──
_clip_jobs = {}
_clip_jobs_lock = threading.Lock()


def _run_clip(job_id: str, req: ClipRequest):
    from utils.funclip import FunClip
    try:
        out = req.output
        if out and not os.path.isabs(out):
            out = os.path.join(load_config().get('output_dir', 'output'), out)
        if not out:
            base, ext = os.path.splitext(req.input)
            out = base + '_clipped' + (ext or '.wav')

        llm = None
        if req.use_llm:
            from utils.llm import LLMClient
            llm = LLMClient()

        fc = FunClip()
        r = fc.smart_clip(req.input, req.instructions, out, llm=llm)
        with _clip_jobs_lock:
            _clip_jobs[job_id].update({
                'status': 'completed', 'output': out,
                'segments': r['segments'], 'keep': r['keep'],
                'sentences': r['sentences'],
                'completed_at': datetime.now().isoformat(),
            })
    except Exception as e:
        with _clip_jobs_lock:
            _clip_jobs[job_id].update({
                'status': 'failed', 'error': str(e),
                'completed_at': datetime.now().isoformat(),
            })


@app.post('/api/clip')
def clip(req: ClipRequest):
    job_id = f'clip_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    with _clip_jobs_lock:
        _clip_jobs[job_id] = {
            'job_id': job_id, 'input': req.input,
            'instructions': req.instructions,
            'status': 'running', 'created_at': datetime.now().isoformat(),
        }
    threading.Thread(target=_run_clip, args=(job_id, req), daemon=True).start()
    return {'job_id': job_id, 'status': 'running'}


@app.get('/api/clip/{job_id}')
def get_clip(job_id: str):
    with _clip_jobs_lock:
        job = _clip_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    return job


# ══ 整段式 prompt → H3 ref2va 单镜（异步，长耗时 15-20min/镜）══

class H3ShotRequest(BaseModel):
    prompt: str
    refs: list = []            # 参考图路径列表（顺序对应 <Picture i>）
    names: list = []           # 角色名（与 refs 对齐，可空）
    output: Optional[str] = None
    seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    steps: Optional[int] = None
    fast: bool = False         # 快速档：steps=14 + 1024x576
    ref_image_size: str = 'match'
    no_describe: bool = False


_h3_jobs = {}
_h3_jobs_lock = threading.Lock()


def _run_h3shot(job_id: str, req: H3ShotRequest):
    try:
        from utils.h3_prompt_video import (
            load_prompt_text, prepare_refs, build_h3_prompt, parse_seconds,
        )
        from utils.comfy_api import ComfyClient
        from utils.llm import LLMClient

        config = load_config()
        output_dir = config['output_dir']
        if req.output:
            output_path = req.output if os.path.isabs(req.output) \
                else os.path.join(output_dir, req.output)
        else:
            output_path = os.path.join(output_dir, f'h3_{job_id}', 'clip.mp4')
        task_dir = os.path.dirname(os.path.abspath(output_path))
        clips_dir = os.path.join(task_dir, 'clips')
        os.makedirs(clips_dir, exist_ok=True)

        prompt_text = load_prompt_text(req.prompt)
        seconds = req.seconds if req.seconds is not None else parse_seconds(prompt_text)
        length = int(round(seconds * 24))
        refs = prepare_refs(req.refs, req.names, clips_dir)

        # 速度档位（--fast 基线，显式参数优先）
        d_w, d_h, d_steps = (1024, 576, 14) if req.fast else (1344, 768, 20)
        width = req.width if req.width is not None else d_w
        height = req.height if req.height is not None else d_h
        steps = req.steps if req.steps is not None else d_steps

        descs = [''] * len(refs)
        if not req.no_describe:
            try:
                llm = LLMClient(config)
                descs = []
                for tmp_path, name, _cn in refs:
                    try:
                        descs.append(llm.describe_character(tmp_path, name=name))
                    except Exception:
                        descs.append('')
            except Exception:
                descs = [''] * len(refs)

        h3_prompt = build_h3_prompt(prompt_text, refs, descs)
        h3 = ComfyClient(config=config, instance='h3')
        result = h3.generate_h3_ref2v(
            prompt=h3_prompt, ref_image_paths=[r[0] for r in refs],
            seed=None, width=width, height=height, length=length,
            steps=steps, ref_image_size=req.ref_image_size,
            filename_prefix=f'vidance/h3_{job_id}', output_path=output_path,
        )
        out_rel = os.path.relpath(output_path, output_dir)
        with _h3_jobs_lock:
            _h3_jobs[job_id].update({
                'status': 'completed', 'output': output_path,
                'video_url': '/api/file?path=' + output_path,
                'seed': result.get('seed'), 'seconds': seconds,
                'completed_at': datetime.now().isoformat(),
            })
    except Exception as e:
        with _h3_jobs_lock:
            _h3_jobs[job_id].update({
                'status': 'failed', 'error': str(e),
                'completed_at': datetime.now().isoformat(),
            })


def _run_custom_job(job_id: str, rr: dict):
    """参考图 + 多镜分镜脚本 → H3 ref2va 逐镜生成（异步，复用 core/custom_gen.run_custom）"""
    try:
        from core.custom_gen import run_custom
        flags = rr.get('flags', {})
        refs = rr['rep'].get('ref', [])
        post_kwargs = {
            'no_rife': bool(flags.get('no_rife')),
            'lut_override': flags.get('lut'),
            'no_color': False,
            'bgm_override': flags.get('bgm'),
            'no_bgm': False,
            'use_stt': bool(flags.get('stt')),
        }
        meta = run_custom(
            ref_images=refs,
            script_path=flags.get('script'),
            output_path=flags.get('o') or flags.get('output'),
            ref_image_size=flags.get('ref_image_size', 'match'),
            post_kwargs=post_kwargs,
        )
        out = meta.get('output')
        with _h3_jobs_lock:
            _h3_jobs[job_id].update({
                'status': 'completed', 'output': out,
                'video_url': ('/api/file?path=' + out) if out else '',
                'task_id': meta.get('task_id'),
                'completed_at': datetime.now().isoformat(),
            })
    except Exception as e:
        with _h3_jobs_lock:
            _h3_jobs[job_id].update({
                'status': 'failed', 'error': str(e),
                'completed_at': datetime.now().isoformat(),
            })


def _run_svgjob(job_id: str, concept, n: int, say: list, flags: dict, voiced: bool):
    """SVG 短片（异步 job，复用 h3shot 轮询通道；回执 output/video_url）。

    voiced=有声（narrate_to_mp4）/无声（concept_to_mp4）。阶段/LLM 流式/帧进度
    写 job 字段（stage/llm_text/frames）+ agent.log，前端 pollH3 有得显示。
    """
    def _num(k, d):
        v = flags.get(k)
        try:
            return int(v)
        except (TypeError, ValueError):
            return d

    def _scb(s):
        with _h3_jobs_lock:
            if job_id in _h3_jobs:
                _h3_jobs[job_id]['stage'] = s
        _agent_log(job_id, '▶ ' + s)

    def _on_chunk(delta):
        with _h3_jobs_lock:
            if job_id in _h3_jobs:
                _h3_jobs[job_id]['llm_text'] = ((_h3_jobs[job_id].get('llm_text') or '')
                                                + delta)[-600:]

    def _on_frame(done, total):
        with _h3_jobs_lock:
            if job_id in _h3_jobs:
                _h3_jobs[job_id]['frames'] = f'{done}/{total}'

    try:
        if voiced:
            from utils.svg_pipeline import narrate_to_mp4
            meta = narrate_to_mp4(
                concept=concept, n=n, say=say or None,
                out_path=flags.get('o') or flags.get('output'),
                voice=flags.get('voice') or None,
                width=_num('width', 800), height=_num('height', 450), fps=_num('fps', 24),
                lut=flags.get('lut'), bgm=flags.get('bgm'),
                stage_cb=_scb, on_chunk=_on_chunk, on_frame=_on_frame)
        else:
            from utils.svg_pipeline import concept_to_mp4
            meta = concept_to_mp4(
                concept=concept, out_path=flags.get('o') or flags.get('output'),
                duration=float(flags.get('duration') or 3),
                width=_num('width', 800), height=_num('height', 450), fps=_num('fps', 24),
                stage_cb=_scb, on_chunk=_on_chunk, on_frame=_on_frame)
        out = meta.get('output') or meta.get('mp4')
        with _h3_jobs_lock:
            _h3_jobs[job_id].update({
                'status': 'completed', 'output': out,
                'video_url': ('/api/file?path=' + out) if out else '',
                'completed_at': datetime.now().isoformat(),
            })
        _agent_log(job_id, '■ 完成 %s' % (out or ''))
    except Exception as e:
        with _h3_jobs_lock:
            _h3_jobs[job_id].update({
                'status': 'failed', 'error': str(e),
                'completed_at': datetime.now().isoformat(),
            })
        _agent_log(job_id, '✗ 失败: %s' % str(e)[:300])


def _run_pptjob(job_id: str, concept, n: int, say: list, flags: dict,
                want_video: bool, want_pdf: bool, want_pngs: bool):
    """PPT 短片/deck（异步 job，复用 h3shot 轮询通道；回执 output/video_url）。

    阶段/LLM 流式/帧进度写 job 字段（stage/llm_text/frames）+ agent.log。
    """
    def _pnum(k, d):
        v = flags.get(k)
        try:
            return float(v) if k == 'duration' else int(v)
        except (TypeError, ValueError):
            return d

    def _scb(s):
        with _h3_jobs_lock:
            if job_id in _h3_jobs:
                _h3_jobs[job_id]['stage'] = s
        _agent_log(job_id, '▶ ' + s)

    def _on_chunk(delta):
        with _h3_jobs_lock:
            if job_id in _h3_jobs:
                _h3_jobs[job_id]['llm_text'] = ((_h3_jobs[job_id].get('llm_text') or '')
                                                + delta)[-600:]

    def _on_frame(done, total):
        with _h3_jobs_lock:
            if job_id in _h3_jobs:
                _h3_jobs[job_id]['frames'] = f'{done}/{total}'

    try:
        from agents.generator.tools.ppt_pipeline import PptLine
        meta = PptLine().run(
            concept or (say[0] if say else 'PPT'),
            n=n, say=say or None,
            voice=flags.get('voice') or None,
            video=want_video or not (want_pdf or want_pngs),
            html_out=flags.get('no-html') is None,
            pdf=want_pdf, pngs=want_pngs,
            out_path=flags.get('o') or flags.get('output'),
            duration=_pnum('duration', 3.0),
            transition=flags.get('transition') or 'fade',
            lut=flags.get('lut'), bgm=flags.get('bgm'),
            stage_cb=_scb, on_chunk=_on_chunk, on_frame=_on_frame)
        out = meta.get('output') or meta.get('html') or meta.get('pdf')
        with _h3_jobs_lock:
            _h3_jobs[job_id].update({
                'status': 'completed', 'output': out,
                'video_url': ('/api/file?path=' + out) if out and out.endswith('.mp4') else '',
                'completed_at': datetime.now().isoformat(),
            })
        _agent_log(job_id, '■ 完成 %s' % (out or ''))
    except Exception as e:
        with _h3_jobs_lock:
            _h3_jobs[job_id].update({
                'status': 'failed', 'error': str(e),
                'completed_at': datetime.now().isoformat(),
            })
        _agent_log(job_id, '✗ 失败: %s' % str(e)[:300])


        _agent_log(job_id, '✗ 失败: %s' % str(e)[:300])


def _run_blenderjob(job_id: str, concept, n: int, say: list, flags: dict):
    """3D 短片（blender 线，异步 job，复用 h3shot 轮询通道；回执 output/video_url）。

    阶段/LLM 流式/帧进度写 job 字段（stage/llm_text/frames）+ agent.log。
    """
    def _scb(s):
        with _h3_jobs_lock:
            if job_id in _h3_jobs:
                _h3_jobs[job_id]['stage'] = s
        _agent_log(job_id, '▶ ' + s)

    def _on_chunk(delta):
        with _h3_jobs_lock:
            if job_id in _h3_jobs:
                _h3_jobs[job_id]['llm_text'] = ((_h3_jobs[job_id].get('llm_text') or '')
                                                + delta)[-600:]

    def _on_frame(done, total):
        with _h3_jobs_lock:
            if job_id in _h3_jobs:
                _h3_jobs[job_id]['frames'] = f'{done}/{total}'

    try:
        from agents.generator.tools.blender_pipeline import BlenderLine
        meta = BlenderLine().run(
            concept or (say[0] if say else '3D 短片'),
            n=n, say=say or None,
            voice=flags.get('voice') or None,
            duration=float(flags.get('duration') or 8.0),
            model=flags.get('model') or None,
            stage_cb=_scb, on_chunk=_on_chunk, on_frame=_on_frame)
        out = meta.get('output') or meta.get('clip')
        with _h3_jobs_lock:
            _h3_jobs[job_id].update({
                'status': 'completed', 'output': out,
                'video_url': ('/api/file?path=' + out) if out else '',
                'completed_at': datetime.now().isoformat(),
            })
        _agent_log(job_id, '■ 完成 %s' % (out or ''))
    except Exception as e:
        with _h3_jobs_lock:
            _h3_jobs[job_id].update({
                'status': 'failed', 'error': str(e),
                'completed_at': datetime.now().isoformat(),
            })
        _agent_log(job_id, '✗ 失败: %s' % str(e)[:300])


def _run_editimagejob(job_id: str, inp: str, cmd: str, fl: dict):
    """图编辑统一异步（agent post.edit）：CV 秒级 op / flux 生成式 / instruct 全走 job。

    阶段/结果写 job 字段（stage/output/image_url）+ agent.log，前端 pollH3 有得显示。
    """
    try:
        from agents.post.tools import sam_edit as se
        import numpy as _np
        from PIL import Image as _Image

        def _stage(s):
            with _h3_jobs_lock:
                if job_id in _h3_jobs:
                    _h3_jobs[job_id]['stage'] = s

        out = fl.get('output') or fl.get('o') or (
            os.path.splitext(inp)[0] + '_edit.png')

        # M8 指令式编辑：整图自然语言修改，无需 SAM mask
        if cmd == 'instruct':
            _stage('Qwen-Image-Edit 生成中（约 1-2 分钟）')
            se.qwen_edit(inp, fl.get('prompt'), out,
                         steps=int(fl.get('steps') or 20),
                         cfg=float(fl.get('cfg') or 2.5))
            with _h3_jobs_lock:
                _h3_jobs[job_id].update({
                    'status': 'completed', 'output': out,
                    'image_url': '/api/file?path=' + out,
                    'completed_at': datetime.now().isoformat(),
                })
            _agent_log(job_id, '■ 完成 %s（instruct）' % out)
            return

        _stage('SAM2 分割中')
        img = _np.array(_Image.open(inp).convert('RGB'))
        pts = []
        for tok in (fl.get('point') or '').replace(';', ' ').split():
            parts = tok.split(',')
            if len(parts) == 2:
                try:
                    pts.append((int(float(parts[0])), int(float(parts[1]))))
                except ValueError:
                    pass
        boxes = []
        labels = None
        for tok in (fl.get('box') or '').replace(';', ' ').split():
            parts = tok.split(',')
            if len(parts) == 4:
                try:
                    boxes.append(tuple(int(float(v)) for v in parts))
                except ValueError:
                    pass
        if str(fl.get('yolo') or '').lower() in ('true', '1', 'yes') or fl.get('classes'):
            _stage('YOLO 检测中')
            dets = se.detect_objects(img,
                                     classes=[c for c in (fl.get('classes') or '').split(',') if c] or None,
                                     conf=float(fl.get('conf') or 0.25))
            boxes = [d[2] for d in dets]
            labels = [d[0] for d in dets]
            _agent_log(job_id, '▶ YOLO 检出 %d 目标' % len(boxes))
        if boxes:
            masks, scores, labels = se.segment_from_boxes(img, boxes, labels=labels,
                                                          size=fl.get('size') or 'small',
                                                          device=fl.get('device') or '')
            if not masks:
                raise ValueError('SAM2 框提示未产出掩膜')
            mask, score = masks[0], scores[0]
        else:
            mask, score = se.segment_image(img, points=pts or None,
                                           size=fl.get('size') or 'small',
                                           device=fl.get('device') or '')

        def _done(extra=None):
            with _h3_jobs_lock:
                _h3_jobs[job_id].update({
                    'status': 'completed', 'output': out,
                    'image_url': '/api/file?path=' + out,
                    'completed_at': datetime.now().isoformat(),
                    **(extra or {})})
            _agent_log(job_id, '■ 完成 %s' % out)

        if cmd == 'visualize':
            if not boxes:
                masks, scores = se.segment_multi(img, points=pts or None,
                                                 size=fl.get('size') or 'small',
                                                 device=fl.get('device') or '')
                labels = ['物体%d' % (i + 1) for i in range(len(masks))]
            se.visualize(img, masks, out, labels=labels)
            _done({'objects': len(masks), 'labels': labels,
                   'scores': [round(s, 2) for s in scores]})
            return
        if cmd == 'segment':
            _Image.fromarray(mask.astype(_np.uint8) * 255).save(out)
        elif cmd == 'cutout':
            se.cutout(img, mask, out)
        elif cmd == 'replace_bg':
            bg = fl.get('bg') or ''
            if (fl.get('engine') or 'cv') == 'flux':
                _stage('FLUX Fill 生成中（约 1-2 分钟）')
                se.inpaint_flux(img, mask, fl.get('prompt') or 'clean empty background', out,
                                invert=True, steps=int(fl.get('steps') or 30),
                                guidance=float(fl.get('guidance') or 30.0))
            elif bg == 'blur':
                se.replace_bg(img, mask, out, blur=True)
            elif bg:
                c = bg.lstrip('#')
                col = tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) if len(c) >= 6 else (16, 18, 27)
                se.replace_bg(img, mask, out, color=col)
            else:
                se.replace_bg(img, mask, out)
        elif cmd == 'mosaic':
            se.mosaic(img, mask, out, mode=fl.get('mode') or 'pixel',
                      strength=int(fl.get('strength') or 16))
        elif cmd == 'inpaint':
            if (fl.get('engine') or 'cv') == 'flux':
                if not fl.get('prompt'):
                    raise ValueError('flux 引擎需要 --prompt 描述重绘内容')
                _stage('FLUX Fill 生成中（约 1-2 分钟）')
                se.inpaint_flux(img, mask, fl['prompt'], out,
                                steps=int(fl.get('steps') or 30),
                                guidance=float(fl.get('guidance') or 30.0),
                                controlnet=fl.get('controlnet') or '',
                                controlnet_strength=float(fl.get('controlnet_strength') or 0.5))
            else:
                se.inpaint(img, mask, out)
        else:
            raise ValueError('未知 op: %s' % cmd)
        _done({'score': round(score, 3)})
    except Exception as e:
        with _h3_jobs_lock:
            _h3_jobs[job_id].update({
                'status': 'failed', 'error': str(e)[:400],
                'completed_at': datetime.now().isoformat(),
            })
        _agent_log(job_id, '✗ 失败: %s' % str(e)[:300])


def _run_editjob(job_id: str, video: str, points: list, op: str, flags: dict):
    """SAM2 视频编辑（异步 job，复用 h3shot 轮询通道；回执 output/video_url）。"""
    def _on_frame(done, total):
        with _h3_jobs_lock:
            if job_id in _h3_jobs:
                _h3_jobs[job_id]['frames'] = f'{done}/{total}'

    try:
        _agent_log(job_id, '▶ 调用 agent post.edit · video（SAM2 双向传播）')
        from agents.post.tools import sam_edit as se
        fr_idx = int(flags.get('frame') or 0)
        boxes = []
        for tok in (flags.get('box') or '').replace(';', ' ').split():
            parts = tok.split(',')
            if len(parts) == 4:
                try:
                    boxes.append(tuple(int(float(v)) for v in parts))
                except ValueError:
                    pass
        with _h3_jobs_lock:
            if job_id in _h3_jobs:
                _h3_jobs[job_id]['stage'] = 'SAM2 视频传播中'
        if op == 'color':
            r = se.video_color(video, os.path.splitext(video)[0] + '_edit.mp4',
                               points, size=flags.get('size') or 'small',
                               device=flags.get('device') or '', on_frame=_on_frame,
                               prompt_frame=fr_idx, boxes=boxes or None)
            out = r['output']
            with _h3_jobs_lock:
                _h3_jobs[job_id].update({
                    'status': 'completed', 'output': out,
                    'video_url': '/api/file?path=' + out,
                    'objects': r.get('objects'),
                    'completed_at': datetime.now().isoformat(),
                })
            _agent_log(job_id, '■ 完成 %s（%s 物体彩色）' % (out, r.get('objects')))
            return
        r = se.video_edit(video, os.path.splitext(video)[0] + '_edit.mp4',
                          points, op=op, size=flags.get('size') or 'small',
                          device=flags.get('device') or '',
                          mode=flags.get('mode') or 'pixel',
                          strength=int(flags.get('strength') or 16),
                          on_frame=_on_frame, prompt_frame=fr_idx,
                          boxes=boxes or None)
        out = r['output']
        with _h3_jobs_lock:
            _h3_jobs[job_id].update({
                'status': 'completed', 'output': out,
                'video_url': '/api/file?path=' + out,
                'completed_at': datetime.now().isoformat(),
            })
        _agent_log(job_id, '■ 完成 %s' % out)
    except Exception as e:
        with _h3_jobs_lock:
            _h3_jobs[job_id].update({
                'status': 'failed', 'error': str(e),
                'completed_at': datetime.now().isoformat(),
            })
        _agent_log(job_id, '✗ 失败: %s' % str(e)[:300])


@app.post('/api/h3shot')
def h3shot(req: H3ShotRequest):
    if not req.prompt or not req.refs:
        raise HTTPException(status_code=400, detail='需要 prompt 与至少一个 refs')
    job_id = f'h3_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    with _h3_jobs_lock:
        _h3_jobs[job_id] = {
            'job_id': job_id, 'prompt': req.prompt, 'refs': req.refs,
            'status': 'running', 'created_at': datetime.now().isoformat(),
        }
    threading.Thread(target=_run_h3shot, args=(job_id, req), daemon=True).start()
    return {'job_id': job_id, 'status': 'running', 'poll': f'/api/h3shot/{job_id}'}


@app.get('/api/h3shot/{job_id}')
def get_h3shot(job_id: str):
    with _h3_jobs_lock:
        job = _h3_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail='Job not found')
    return job


# ══ v6 prompt 多轮核实 dialog 端点 ══

class DialogStart(BaseModel):
    concept: str


class DialogReply(BaseModel):
    text: str


class ChatReq(BaseModel):
    text: str
    history: Optional[list] = None  # [{role, content}]，前端可带上下文


@app.post('/api/chat')
def chat_endpoint(req: ChatReq):
    """闲聊/意图识别：普通对话由 LLM 回复；若用户想生成视频则返回 concept 交 v6 dialog。

    返回 {reply, want_video, concept}。want_video=True 时前端转 /api/dialog/start。
    """
    from utils.llm import LLMClient
    llm = LLMClient(load_config())
    system = (
        '你是 Vidance（AI 有声短片生成助手）的前台助理。用户可以随便聊天，也可以让你帮它做视频。\n'
        '规则：\n'
        '1. 若用户只是打招呼/闲聊/问你能做什么 → 用中文友好简短回复（1-3 句）。\n'
        '2. 若用户表达了"想生成/制作某个视频"的意图 → 只输出一行：[[VIDEO:<提炼后的视频概念>]]\n'
        '   例如用户说"帮我做个深海探险的视频" → 输出 [[VIDEO:深海探险]]\n'
        '   用户只是描述主题但没说要做视频时不要触发。\n'
        '3. 不要输出多余解释。'
    )
    msgs = [{'role': 'system', 'content': system}]
    if req.history:
        for m in req.history[-8:]:
            if isinstance(m, dict) and m.get('role') in ('user', 'assistant'):
                msgs.append({'role': m['role'], 'content': str(m.get('content', ''))})
    msgs.append({'role': 'user', 'content': req.text})
    try:
        reply = llm.chat(msgs, temperature=0.7)
    except Exception as e:
        return {'reply': '（LLM 暂时不可用，请稍后再试）', 'want_video': False,
                'concept': None, 'error': str(e)[:200]}
    reply = (reply or '').strip()
    m = re.search(r'\[\[VIDEO:\s*(.+?)\s*\]\]', reply)
    if m:
        return {'reply': '', 'want_video': True, 'concept': m.group(1)}
    return {'reply': reply, 'want_video': False, 'concept': None}


class T2CReq(BaseModel):
    text: str


@app.post('/api/t2c')
def t2c_endpoint(req: T2CReq):
    """text→command：把（v6 核实后的）详细中文需求翻译成 Vidance 命令。

    返回 {text, command}。command 形如 `python core/vidance.py auto "..."`。
    """
    try:
        from utils.t2c_server import translate
        cmd = translate(req.text)
    except Exception as e:
        return {'text': req.text, 'command': '', 'error': str(e)[:200]}
    return {'text': req.text, 'command': cmd,
            'runnable': bool(cmd and cmd.startswith('python core/vidance.py'))}


@app.post('/api/dialog/start')
def dialog_start(req: DialogStart):
    """启动多轮需求核实会话 → {dialog_id, status, missing, questions, concept}"""
    from utils.dialog import DialogManager
    dm = DialogManager()
    s = dm.start(req.concept)
    return {'dialog_id': s['dialog_id'], 'status': s['status'],
            'dimensions': s['dimensions'], 'missing': s['missing'],
            'questions': s['questions'], 'concept': s['concept']}


@app.get('/api/dialog/{dialog_id}')
def dialog_get(dialog_id: str):
    from utils.dialog import DialogManager
    dm = DialogManager()
    s = dm.get(dialog_id)
    if not s:
        raise HTTPException(status_code=404, detail='dialog not found')
    return s


@app.post('/api/dialog/{dialog_id}/reply')
def dialog_reply(dialog_id: str, req: DialogReply):
    from utils.dialog import DialogManager
    dm = DialogManager()
    s = dm.reply(dialog_id, req.text)
    if 'error' in s:
        raise HTTPException(status_code=404, detail=s['error'])
    return s


# ══ v7 前端：只读端点 + / 斜杠命令统一分发 + 静态 UI ══

# ── /api/video/{task_id}：成片视频流 ──
@app.get('/api/video/{task_id}')
def video_stream(task_id: str):
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    output = task.get('output')
    if not output or not os.path.exists(output):
        # 兜底：output/{task_id}/final.mp4 或 final_slow.mp4
        for name in ('final.mp4', 'final_slow.mp4'):
            cand = os.path.join(load_config().get('output_dir', 'output'), task_id, name)
            if os.path.exists(cand):
                output = cand
                break
    if not output or not os.path.exists(output):
        raise HTTPException(status_code=404, detail='Video not found (task may still be running)')
    return FileResponse(output, media_type='video/mp4', filename=os.path.basename(output))


# ── /api/file?path=...：通用本地文件流（限制在 output_dir 与项目目录内）──
@app.get('/api/file')
def file_stream(path: str):
    import os as _os
    cfg = load_config()
    out_root = _os.path.realpath(cfg.get('output_dir', 'output'))
    proj_root = _os.path.realpath(_os.path.join(_os.path.dirname(__file__), '..'))
    real = _os.path.realpath(path)
    allowed = real.startswith(out_root) or real.startswith(proj_root)
    if not allowed:
        raise HTTPException(status_code=403, detail='path not allowed')
    if not _os.path.isfile(real):
        raise HTTPException(status_code=404, detail='file not found')
    ext = _os.path.splitext(real)[1].lower()
    media = 'video/mp4' if ext in ('.mp4', '.mov', '.webm') else             'image/png' if ext == '.png' else             'image/jpeg' if ext in ('.jpg', '.jpeg') else 'application/octet-stream'
    return FileResponse(real, media_type=media, filename=_os.path.basename(real))


# ── /api/tasks/{task_id}/log：任务详细日志（v7 折叠日志面板用）──
@app.get('/api/tasks/{task_id}/log')
def task_log(task_id: str, tail: int = Query(400, ge=1, le=5000)):
    """返回任务目录下日志文件的内容（默认末尾 400 行）。

    日志来源优先级：scheduler.log → 任意 *.log → 无。任务运行中会实时增长，
    前端轮询此端点即可看到实时日志。
    """
    out_root = load_config().get('output_dir', 'output')
    task_dir = os.path.join(out_root, task_id)
    if not os.path.isdir(task_dir):
        raise HTTPException(status_code=404, detail='Task dir not found')
    log_files = sorted(glob.glob(os.path.join(task_dir, '*.log')))
    # scheduler.log 优先放最前
    log_files.sort(key=lambda p: (os.path.basename(p) != 'scheduler.log', p))
    if not log_files:
        return {'task_id': task_id, 'log': '', 'files': []}
    chunks = []
    for lf in log_files:
        try:
            with open(lf, 'r', errors='replace') as f:
                lines = f.readlines()
            body = ''.join(lines[-tail:])
            if len(log_files) > 1:
                chunks.append(f'===== {os.path.basename(lf)} =====\n{body}')
            else:
                chunks.append(body)
        except Exception as e:
            chunks.append(f'[读取 {os.path.basename(lf)} 失败: {e}]')
    return {'task_id': task_id, 'log': '\n'.join(chunks),
            'files': [os.path.basename(p) for p in log_files],
            'mtime': max(os.path.getmtime(p) for p in log_files)}


# ── /api/options：枚举（音色/LUT/BGM/特效/运镜），供前端下拉 ──
@app.get('/api/options')
def options():
    voices = []
    try:
        from utils.voice_clone import VoiceCloner
        voices = [v.get('name') if isinstance(v, dict) else str(v)
                  for v in VoiceCloner().list_voices()]
    except Exception:
        pass
    return {
        'voices': voices,
        'character_modes': ['auto', 'flux', '3dgs', 'mesh'],
        'luts': ['cinematic', 'warm', 'cool', 'vintage', 'vivid', 'soft'],
        'bgms': ['calm', 'uplifting', 'mysterious', 'dramatic', 'playful', 'epic'],
        'effects': ['auto', 'off'],
        'motions': ['pan', 'zoom-in', 'zoom-out'],
        'images_sources': ['crawl', 'flux'],
        'accounts': ['热门资讯', '影视解说', '萌宠', '情感'],
    }


# ── /api/tools：/ 斜杠命令清单（前端补全渲染） ──
TOOLS = [
    {'name': 'auto', 'help': '概念→LLM编剧→生成→后处理（完整流水线）',
     'params': [
         {'key': 'concept', 'type': 'text', 'required': True, 'desc': '视频概念（中文）'},
         {'key': '--character', 'type': 'text', 'desc': '角色描述'},
         {'key': '--character-mode', 'type': 'choice', 'choices': ['auto', 'flux', '3dgs', 'mesh'], 'desc': '角色锚模式'},
         {'key': '--voice', 'type': 'text', 'desc': 'TTS 音色'},
         {'key': '--duration', 'type': 'number', 'desc': '目标时长（秒）'},
         {'key': '--lut', 'type': 'choice', 'choices': ['cinematic', 'warm', 'cool', 'vintage', 'vivid', 'soft'], 'desc': '调色风格'},
         {'key': '--bgm', 'type': 'choice', 'choices': ['calm', 'uplifting', 'mysterious', 'dramatic', 'playful', 'epic'], 'desc': 'BGM mood'},
         {'key': '--slowmo', 'type': 'number', 'desc': '慢动作倍率'},
     ]},
    {'name': 'arch', 'help': '架构总览：编排→D/G/P/V 四层 Agent + 服务在线状态',
     'params': []},
    {'name': 'agent', 'help': 'Agent：list 注册表 / run 单跑 / chain 链式 / board 查台账',
     'params': [
         {'key': 'sub', 'type': 'choice', 'choices': ['list', 'run', 'chain', 'board'],
          'required': True, 'desc': '子命令'},
         {'key': 'name/steps', 'type': 'text', 'desc': 'run: agent 名；chain: steps JSON'},
         {'key': '--with', 'type': 'text', 'desc': "run 参数 JSON，如 '{\"video\":\"a.mp4\"}'"},
         {'key': '--steps', 'type': 'text', 'desc': 'chain 步骤 JSON 或文件'},
     ]},
    {'name': 'fast', 'help': '快速营销号链路：爬图+运镜+TTS（分钟级出片）',
     'params': [
         {'key': 'concept', 'type': 'text', 'required': True, 'desc': '热点概念/旁白主题（中文）'},
         {'key': '--images-source', 'type': 'choice', 'choices': ['crawl', 'flux'], 'desc': '图片来源'},
         {'key': '-n', 'type': 'number', 'desc': '图片/段落数（≤5）'},
         {'key': '--effects', 'type': 'choice', 'choices': ['auto', 'off'], 'desc': 'v5 特效'},
         {'key': '--lut', 'type': 'choice', 'choices': ['cinematic', 'warm', 'cool', 'vintage', 'vivid', 'soft'], 'desc': '调色风格'},
         {'key': '--bgm', 'type': 'choice', 'choices': ['calm', 'uplifting', 'mysterious', 'dramatic', 'playful', 'epic'], 'desc': 'BGM mood'},
         {'key': '--stt', 'type': 'flag', 'desc': 'STT 字幕对齐'},
     ]},
    {'name': 'hot', 'help': '爬实时热点→LLM选题→出片（一步到位）',
     'params': [
         {'key': '-n', 'type': 'number', 'desc': '图片/段落数（≤5）'},
         {'key': '--account', 'type': 'text', 'desc': '账号定位（热门资讯/影视解说/萌宠/情感）'},
         {'key': '--images-source', 'type': 'choice', 'choices': ['crawl', 'flux'], 'desc': '图片来源'},
         {'key': '--effects', 'type': 'choice', 'choices': ['auto', 'off'], 'desc': 'v5 特效'},
     ]},
    {'name': 'ask', 'help': 'v6 多轮核实：补齐概念缺失维度 → 增强概念',
     'params': [
         {'key': 'concept', 'type': 'text', 'required': True, 'desc': '原始概念（中文）'},
     ]},
    {'name': 'compose', 'help': 'v10 时间线拼接：JSON 时间线合成（特效/转场/画中画/文字/混音）',
     'params': [
         {'key': 'timeline', 'type': 'text', 'required': True, 'desc': '时间线 JSON 路径'},
         {'key': '--output', 'type': 'text', 'desc': '输出路径（覆盖 JSON 内）'},
     ]},
    {'name': 'h3shot', 'help': '整段式 prompt + 参考图 → H3 单镜（原生音频，异步）',
     'params': [
         {'key': '--prompt', 'type': 'text', 'required': True, 'desc': '整段式 prompt 文件（如 input/prompt1.txt）'},
         {'key': '--ref', 'type': 'text', 'required': True, 'desc': '参考图（--ref 路径 --name 角色名，可重复）'},
         {'key': '--name', 'type': 'text', 'desc': '角色名（与 --ref 对齐）'},
         {'key': '-o', 'type': 'text', 'desc': '输出路径（相对→output_dir，如 prompt01/01.mp4）'},
         {'key': '--fast', 'type': 'flag', 'desc': '快速档：steps=14 + 1024x576（约省一半时间）'},
         {'key': '--seconds', 'type': 'number', 'desc': '时长（秒）；缺省从 prompt「约N秒」解析'},
         {'key': '--ref-image-size', 'type': 'choice', 'choices': ['match', 'max'], 'desc': '参考图尺寸'},
         {'key': '--no-describe', 'type': 'flag', 'desc': '跳过 LLM 看图描述'},
     ]},
    {'name': 'custom', 'help': '参考图 + 多镜分镜脚本 → H3 ref2va 逐镜生成（旧脚本格式）',
     'params': [
         {'key': '--ref', 'type': 'text', 'required': True, 'desc': '角色参考图（可重复）'},
         {'key': '--script', 'type': 'text', 'required': True, 'desc': '分镜脚本路径（旧多镜格式）'},
         {'key': '--ref-image-size', 'type': 'choice', 'choices': ['match', 'max'], 'desc': '参考图尺寸'},
         {'key': '--lut', 'type': 'choice', 'choices': ['cinematic', 'warm', 'cool', 'vintage', 'vivid', 'soft'], 'desc': '调色'},
         {'key': '--bgm', 'type': 'choice', 'choices': ['calm', 'uplifting', 'mysterious', 'dramatic', 'playful', 'epic'], 'desc': 'BGM'},
         {'key': '--stt', 'type': 'flag', 'desc': 'STT 字幕'},
     ]},
    {'name': 'quick', 'help': '纯 T2V：一句概念→Wan 生成，无角色锚无后处理（最快出素材）',
     'params': [
         {'key': 'concept', 'type': 'text', 'required': True, 'desc': '视频概念（中文）'},
         {'key': '--voice', 'type': 'text', 'desc': 'TTS 音色（可选）'},
     ]},
    {'name': 'concat', 'help': '多视频拼接：cut 硬切 / crossfade 交叉淡化 / rife 光流过渡',
     'params': [
         {'key': 'videos', 'type': 'text', 'required': True, 'desc': '待拼接视频路径（空格分隔，可多个）'},
         {'key': '-o', 'type': 'text', 'desc': '输出路径'},
         {'key': '--transition', 'type': 'choice', 'choices': ['cut', 'crossfade', 'rife'], 'desc': '转场方式'},
         {'key': '--crossfade-duration', 'type': 'number', 'desc': '交叉淡化时长（秒，默认 0.5）'},
     ]},
    {'name': 'make', 'help': 'v12（原 v17）统一入口：--director llm|manual|scout × --generator wan|fast|svg|h3 排列组合',
     'params': [
         {'key': 'concept', 'type': 'text', 'required': True, 'desc': '概念（--director scout 时可省，自动选题）'},
         {'key': '--director', 'type': 'text', 'desc': '导演层：llm 自动 / manual 人肉 / scout 爬热点',
          'choices': ['llm', 'manual', 'scout']},
         {'key': '--generator', 'type': 'text', 'desc': '生成层：wan 视频模型 / fast 爬图生图 / svg 矢量 / h3 参考图直出',
          'choices': ['wan', 'fast', 'svg', 'h3']},
         {'key': '--say', 'type': 'text', 'desc': 'manual 导演：手给旁白段（可重复）'},
         {'key': '--character', 'type': 'text', 'desc': 'generator=wan：角色描述，给了走 auto 全管线'},
         {'key': '--voice', 'type': 'text', 'desc': '配音音色'},
         {'key': '--n', 'type': 'number', 'desc': '段数'},
         {'key': '--lut', 'type': 'text', 'desc': '调色风格'},
         {'key': '--bgm', 'type': 'text', 'desc': 'BGM mood'},
     ]},
    {'name': 'svg', 'help': 'SVG 流水线：概念→LLM 生成 SVG→逐帧渲染→mp4（纯 CPU，秒级）',
     'params': [
         {'key': '--concept', 'type': 'text', 'desc': '概念（一键：LLM 生成 SVG→mp4）'},
         {'key': '--svg', 'type': 'text', 'desc': 'SVG 文件路径（渲染模式）'},
         {'key': '-o', 'type': 'text', 'desc': '输出 mp4 路径'},
         {'key': '--duration', 'type': 'number', 'desc': '动画时长（秒，默认 3）'},
         {'key': '--width', 'type': 'number', 'desc': '宽（默认 800）'},
         {'key': '--height', 'type': 'number', 'desc': '高（默认 450）'},
         {'key': '--fps', 'type': 'number', 'desc': '帧率（默认 24）'},
         {'key': '--voice', 'type': 'text', 'desc': 'S5 有声模式：配音音色（给定即出有声片）'},
         {'key': '--say', 'type': 'text', 'desc': 'S5 有声模式：手动旁白段（可重复多个）'},
         {'key': '--n', 'type': 'number', 'desc': 'S5：LLM 规划旁白段数（默认 3）'},
         {'key': '--lut', 'type': 'text', 'desc': 'S5：调色风格'},
         {'key': '--bgm', 'type': 'text', 'desc': 'S5：BGM mood'},
     ]},
    {'name': 'ppt', 'help': 'PPT 流水线：概念→LLM 规划 deck→HTML/PDF/mp4（纯 CPU，秒级）',
     'params': [
         {'key': 'concept', 'type': 'text', 'required': True, 'desc': '主题/大纲（一键模式）'},
         {'key': '-o', 'type': 'text', 'desc': '输出路径（缺省 output/ppt*/final.mp4）'},
         {'key': '--video', 'type': 'text', 'desc': '渲染成 mp4（有声旁白）'},
         {'key': '--pdf', 'type': 'text', 'desc': '导出 PDF'},
         {'key': '--pngs', 'type': 'text', 'desc': '导出每页 PNG'},
         {'key': '-n', 'type': 'number', 'desc': '页数（默认 5）'},
         {'key': '--duration', 'type': 'number', 'desc': '无声页时长（秒，默认 3）'},
         {'key': '--transition', 'type': 'text', 'desc': '页间转场 fade/slide/wipe/circleopen/crossfade/cut'},
         {'key': '--voice', 'type': 'text', 'desc': '有声 mp4：配音音色'},
         {'key': '--say', 'type': 'text', 'desc': '手动大纲（每元素一页标题，可重复多个）'},
         {'key': '--lut', 'type': 'text', 'desc': '调色风格（mp4）'},
         {'key': '--bgm', 'type': 'text', 'desc': 'BGM mood（mp4）'},
      ]},
     {'name': 'blender3d', 'help': '3D 短片：概念→LLM 规划场景→bpy EEVEE 渲染→mp4（GPU 加速）',
      'params': [
          {'key': 'concept', 'type': 'text', 'required': True, 'desc': '主题（中文）'},
          {'key': '--duration', 'type': 'number', 'desc': '时长（秒，默认 8，4-20）'},
          {'key': '--voice', 'type': 'text', 'desc': '配音音色'},
          {'key': '--say', 'type': 'text', 'desc': '手动旁白（副标题+旁白）'},
          {'key': '-n', 'type': 'number', 'desc': '物体数提示（约 n*4 个）'},
      ]},
     {'name': 'edit', 'help': 'v16 SAM2 编辑：分割/抠图/换底/打码/inpaint（图同步）/视频传播（异步）/YOLO 自动/框提示/FLUX Fill 生成式重绘',
      'params': [
          {'key': 'input', 'type': 'text', 'required': True, 'desc': '图/视频路径'},
          {'key': 'op', 'type': 'text', 'desc': 'segment/cutout/replace_bg/mosaic/inpaint/visualize/video（位置参数，缺省 mosaic）'},
          {'key': '--point', 'type': 'text', 'desc': '点提示 x,y（省略=自动主体；video 必填）'},
          {'key': '--box', 'type': 'text', 'desc': '框提示 x1,y1,x2,y2（分号分隔多框，大物体更准）'},
          {'key': '--yolo', 'type': 'bool', 'desc': 'YOLO 自动检测→SAM 框提示（Grounded-SAM）'},
          {'key': '--classes', 'type': 'text', 'desc': 'YOLO 类别过滤（逗号分隔，如 cat,dog）'},
          {'key': '--conf', 'type': 'number', 'desc': 'YOLO 置信度阈值（默认 0.25）'},
          {'key': '--frame', 'type': 'number', 'desc': 'video 提示帧号（双向传播，默认 0）'},
          {'key': '--op', 'type': 'text', 'desc': 'video 模式：mosaic/blur_bg/cutout/color'},
          {'key': '--bg', 'type': 'text', 'desc': 'replace_bg：hex 色（101827）或 blur'},
           {'key': '--engine', 'type': 'text', 'desc': 'inpaint/replace_bg 引擎：cv=TELEA / flux=FLUX.1 Fill 生成式重绘'},
           {'key': '--prompt', 'type': 'text', 'desc': 'flux 引擎重绘内容描述（如 empty wooden floor）'},
           {'key': '--steps', 'type': 'number', 'desc': 'flux Fill 采样步数（默认 30）'},
           {'key': '--guidance', 'type': 'number', 'desc': 'flux Fill guidance（默认 30）'},
           {'key': '--controlnet', 'type': 'text', 'desc': 'flux 联动 ControlNet：canny=结构保持重绘（v16.x M6）'},
           {'key': '--controlnet-strength', 'type': 'number', 'desc': 'ControlNet 强度（默认 0.5）'},
           {'key': '--mode', 'type': 'text', 'desc': 'mosaic：pixel/blur'},
           {'key': '--strength', 'type': 'number', 'desc': '打码强度（默认 16）'},
           {'key': '--size', 'type': 'text', 'desc': 'SAM2 权重 tiny/small/base（默认 small）'},
       ]},
     {'name': 'vace', 'help': 'v16.x（M7）Wan2.1 VACE：参考图 + prompt → 主体一致视频（异步）',
      'params': [
          {'key': 'ref', 'type': 'text', 'required': True, 'desc': '参考图路径（VACE 主体参考）'},
          {'key': 'prompt', 'type': 'text', 'required': True, 'desc': '视频 prompt（英文推荐）'},
          {'key': '--length', 'type': 'number', 'desc': '帧数（默认 81@16fps≈5s）'},
          {'key': '--width', 'type': 'number', 'desc': '宽（默认 480）'},
          {'key': '--height', 'type': 'number', 'desc': '高（默认 832）'},
          {'key': '--steps', 'type': 'number', 'desc': '采样步数（默认 25）'},
          {'key': '--cfg', 'type': 'number', 'desc': 'CFG（默认 5.0）'},
          {'key': '--vace-strength', 'type': 'number', 'desc': 'VACE 控制强度（默认 1.0）'},
          {'key': '-o', 'type': 'text', 'desc': '输出路径（缺省 output/vace_*.mp4）'},
      ]},
    {'name': 'clip', 'help': 'FunClip：长素材 ASR 转写+语义裁剪',
     'params': [
         {'key': 'input', 'type': 'text', 'required': True, 'desc': '音频/视频路径'},
         {'key': '-i', 'type': 'text', 'required': True, 'desc': '保留什么（自然语言指令）'},
     ]},
    {'name': 'scout', 'help': '爬热点→概念候选排序',
     'params': [
         {'key': '--account', 'type': 'text', 'desc': '账号定位'},
         {'key': '-n', 'type': 'number', 'desc': '候选数'},
     ]},
    {'name': 'voices', 'help': '列出已注册音色', 'params': []},
    {'name': 'luts', 'help': '列出可用的调色风格（LUT）', 'params': []},
    {'name': 'moods', 'help': '列出可用的 BGM 配乐情绪', 'params': []},
    {'name': 'video', 'help': '播放成片',
     'params': [
         {'key': 'task_id', 'type': 'text', 'required': True, 'desc': '任务 ID'},
     ]},
    {'name': 'tasks', 'help': '列出最近任务',
     'params': [
         {'key': '-n', 'type': 'number', 'desc': '条数（默认 10）'},
         {'key': '--status', 'type': 'text', 'desc': '按状态筛选：queued/running/completed/failed'},
     ]},
    {'name': 'status', 'help': '查询单个任务详情',
     'params': [
         {'key': 'task_id', 'type': 'text', 'required': True, 'desc': '任务 ID'},
     ]},
    {'name': 'trends', 'help': '爬取实时热点（不选题，直接看热榜）',
     'params': [
         {'key': '--top', 'type': 'number', 'desc': '每源条数（默认 10）'},
     ]},
    {'name': 'clean', 'help': '清理旧任务输出（默认保留最近 10 个，--keep 可改）',
     'params': [
         {'key': '--keep', 'type': 'number', 'desc': '保留最近 N 个（默认 10）'},
     ]},
    {'name': 'help', 'help': '列出全部 / 命令', 'params': []},
]


@app.get('/api/instructions')
def instructions():
    """v10 剪辑指令模式库（docs/instructions/compose-commands.json）"""
    import json as _json
    path = os.path.join(os.path.dirname(__file__), '..', 'docs', 'instructions', 'compose-commands.json')
    try:
        with open(path, encoding='utf-8') as f:
            return _json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'instructions load failed: {e}')


@app.get('/api/tools')
def tools():
    # v18 分档过滤：能力不足的命令不进补全清单（auto/quick/hot 需 wan；custom/h3shot 需 h3）
    from agents.common.tools.config_loader import load_config as _lc
    caps = capabilities()
    cfg = _lc()
    need = {'auto': 'auto', 'quick': 'auto', 'hot': 'auto', 'custom': 'custom', 'h3shot': 'h3shot'}
    hidden = {n for n, cap in need.items() if caps.get(cap) is False}
    return {'tools': [t for t in TOOLS if t['name'] not in hidden],
            'tier': cfg.get('tier', 'full')}


class ToolRequest(BaseModel):
    args: str = ''


def _parse_tool_args(argstr: str) -> dict:
    """解析命令参数串 → {positional: [...], flags: {key: value}}

    支持：`"概念" --key value --flag` / `概念 --key value`（首 token 或引号内为位置参数）
    """
    import shlex
    try:
        tokens = shlex.split(argstr)
    except ValueError:
        tokens = argstr.split()
    out = {'positional': [], 'flags': {}}
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.startswith('--'):
            key = t[2:].replace('-', '_')
            if i + 1 < len(tokens) and not tokens[i + 1].startswith('--'):
                out['flags'][key] = tokens[i + 1]
                i += 2
            else:
                out['flags'][key] = True
                i += 1
        elif t.startswith('-') and len(t) == 2:  # 短参数如 -n
            key = t[1:]
            if i + 1 < len(tokens) and not tokens[i + 1].startswith('-'):
                out['flags'][key] = tokens[i + 1]
                i += 2
            else:
                out['flags'][key] = True
                i += 1
        else:
            out['positional'].append(t)
            i += 1
    return out


def _task_id_from_response(resp: dict) -> Optional[str]:
    return resp.get('task_id') if isinstance(resp, dict) else None


def _parse_repeated(argstr: str, repeat_keys: set) -> dict:
    """解析参数串，支持重复 flag（如 --ref a --ref b）。

    返回 {pos: [...], rep: {key: [values...]}, flags: {key: value}}；
    repeat_keys 命中的 flag 收集为列表，其余与 _parse_tool_args 一致。
    """
    import shlex
    try:
        tokens = shlex.split(argstr)
    except ValueError:
        tokens = argstr.split()
    pos, flags, rep = [], {}, {}
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t.startswith('--'):
            key = t[2:].replace('-', '_')
            val = tokens[i + 1] if (i + 1 < len(tokens) and not tokens[i + 1].startswith('--')) else True
            if key in repeat_keys:
                rep.setdefault(key, []).append(val)
            else:
                flags[key] = val
            i += 2 if val is not True else 1
        elif t.startswith('-') and len(t) == 2:
            key = t[1:]
            val = tokens[i + 1] if (i + 1 < len(tokens) and not tokens[i + 1].startswith('-')) else True
            if key in repeat_keys:
                rep.setdefault(key, []).append(val)
            else:
                flags[key] = val
            i += 2 if val is not True else 1
        else:
            pos.append(t)
            i += 1
    return {'pos': pos, 'rep': rep, 'flags': flags}


def _agent_log(tid, *lines):
    """agent 运行日志落 output/{tid}/agent.log，与任务日志面板同体系。"""
    import datetime
    try:
        d = os.path.join(load_config().get('output_dir', 'output'), tid)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'agent.log'), 'a', encoding='utf-8') as f:
            for s in lines:
                f.write('[%s] %s\n' % (datetime.datetime.now().strftime('%H:%M:%S'), s))
    except OSError:
        pass


ACTIVE_RUNS = {}  # 正在执行/刚结束的 agent 运行（board 实时区）


# 执行前硬约束：out_path 越界（output_dir 之外）直接改写进本次运行目录，/tmp 不留正本
def _out_roots():
    """output 的全部合法根（config 指向的目录 + 仓库 output 目录），双根都认。"""
    return [os.path.realpath(load_config().get('output_dir', 'output')),
            os.path.realpath(os.path.join(os.path.dirname(__file__), '..', 'output'))]


def _inside_out(path, roots=None):
    roots = roots or _out_roots()
    rp = os.path.realpath(path)
    return any(rp == r or rp.startswith(r + os.sep) for r in roots)


def _enforce_out(params, tid):
    try:
        roots = _out_roots()
        oroot = roots[0]
        changed = False
        for k in ('out_path', 'out', 'output_path'):
            v = params.get(k)
            if not (isinstance(v, str) and v) or v.startswith('${'):
                continue
            if v.startswith('output/'):
                params[k] = os.path.join(oroot, v[7:])
                os.makedirs(os.path.dirname(params[k]), exist_ok=True)
                continue
            if os.path.isabs(v) and _inside_out(v, roots):
                continue
            if not os.path.isabs(v):
                params[k] = os.path.join(oroot, v)
                os.makedirs(os.path.dirname(params[k]), exist_ok=True)
                continue
            params[k] = os.path.join(oroot, tid, os.path.basename(v))
            changed = True
        if changed:
            os.makedirs(os.path.dirname(params.get('out_path')
                                    or params.get('out') or oroot), exist_ok=True)
        return changed
    except OSError:
        return False


def _vault_final(tid, fin):
    """成片/产物归仓到 output/{tid}/final.ext，返回 (路径, 是否归仓)。

    output 外 → 复制归仓；output 内但不在 {tid} 目录（如 fast 的 f<ts>/、wan 的
    2026<ts>/）→ 复制进 {tid} 目录，链目录/记录里直接可预览。
    """
    moved = False
    try:
        if fin and os.path.isfile(fin):
            if not _inside_out(fin):
                _or = _out_roots()[0]
                import shutil as _sh
                dest = os.path.join(_or, tid, 'final' + (os.path.splitext(fin)[1] or '.mp4'))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                _sh.copy2(fin, dest)
                _agent_log(tid, '⤓ 成片归仓 output: %s' % dest)
                fin, moved = dest, True
            else:
                _or = _out_roots()[0]
                dest = os.path.join(_or, tid, 'final' + (os.path.splitext(fin)[1] or '.mp4'))
                if os.path.normpath(fin) != os.path.normpath(dest) \
                        and not os.path.exists(dest):
                    import shutil as _sh
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    try:
                        _sh.copy2(fin, dest)
                        _agent_log(tid, '⤓ 成片并入链目录: %s' % dest)
                        fin, moved = dest, True
                    except OSError:
                        pass
    except OSError:
        pass
    return fin, moved


def _v13_board():
    from agents.blackboard import AgentBoard
    return AgentBoard()


@app.post('/api/tool/{name}')
def tool_dispatch(name: str, req: ToolRequest):
    """统一 / 命令分发：解析 args → 调对应后端 → {result, task_id?, message}"""
    spec = next((t for t in TOOLS if t['name'] == name), None)
    if not spec:
        raise HTTPException(status_code=404, detail=f'Unknown tool: {name}')
    # v18 分档守卫：当前档能力不足的命令直接拒绝并提示换档
    need = {'auto': 'auto', 'quick': 'auto', 'hot': 'auto', 'custom': 'custom', 'h3shot': 'h3shot'}
    cap = need.get(name)
    if cap and capabilities().get(cap) is False:
        tier = load_config().get('tier', 'full')
        raise HTTPException(status_code=400, detail=(
            f'当前部署档 {tier} 不支持 /{name}（能力见 GET /api/health）；'
            f'换档：VIDANCE_TIER=<none|flux|wan|h3|full>，或用该档可用命令（/svg /fast 等）'))
    a = _parse_tool_args(req.args or '')
    pos = a['positional']
    flags = a['flags']

    # ── help（两级：/help 概览，/help 命令名 详情）──
    if name == 'help':
        import json as _json

        def _load_cmds():
            ip = os.path.join(os.path.dirname(__file__), '..', 'docs', 'instructions', 'commands.json')
            with open(ip, encoding='utf-8') as f:
                return _json.load(f).get('commands', [])

        # 详情模式：/help auto
        if pos:
            target = pos[0].lstrip('/')
            try:
                cmds = _load_cmds()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f'commands load failed: {e}')
            c = next((x for x in cmds if x['name'] == target), None)
            if not c:
                return {'message': f'未找到命令 /{target}（输入 /help 看全部）'}
            lines = [f'/{c["name"]}  [{c.get("version", "")}]  {c["brief"]}', '', c.get('detail', '')]
            if c.get('params'):
                lines.append('')
                lines.append('参数：')
                for p_ in c['params']:
                    req = '（必填）' if p_.get('required') else ''
                    ch = f' 可选值：{"/".join(p_["choices"])}' if p_.get('choices') else ''
                    lines.append(f'  {p_["key"]}  {p_.get("desc", "")}{req}{ch}')
            if c.get('examples'):
                lines.append('')
                lines.append('示例：')
                for ex in c['examples']:
                    lines.append(f'  {ex}')
            return {'message': f'/{c["name"]} 用法', 'command': c, 'help_lines': lines}

        # 概览模式：/help
        lines = []
        try:
            cmds = _load_cmds()
            for c in cmds:
                lines.append(f'/{c["name"]}  —  {c["brief"]}')
        except Exception as _e:
            lines = [f'/{t["name"]}  —  {t["help"]}' for t in TOOLS]
            print('  help fallback:', _e)
        # 附 v10 剪辑效果分类（压缩为一行索引）
        effects_lines = []
        try:
            ip2 = os.path.join(os.path.dirname(__file__), '..', 'docs', 'instructions', 'compose-commands.json')
            lib = _json.load(open(ip2, encoding='utf-8'))
            for cat in lib.get('categories', []):
                ids = ' '.join(it['id'] for it in cat.get('items', []))
                effects_lines.append(f'  {cat["name"]}（{len(cat.get("items", []))}）：{ids}')
        except Exception:
            pass
        return {'message': 'Vidance 命令一览（/help 命令名 看详情）',
                'tools': TOOLS, 'help_lines': lines,
                'help_hint': '输入 /help 命令名 查看详细参数与示例',
                'effects_index': effects_lines,
                'instruction_lines': lines}

    # ── voices ──
    if name == 'voices':
        from utils.voice_clone import VoiceCloner
        vs = VoiceCloner().list_voices()
        return {'message': f'共 {len(vs)} 个自定义音色', 'voices': vs}

    # ── video ──
    if name == 'video':
        if not pos:
            raise HTTPException(status_code=400, detail='用法: /video {task_id}')
        task_id = pos[0]
        task = queue.get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail='Task not found')
        return {'message': f'任务 {task_id} 状态 {task["status"]}',
                'task': task, 'video_url': f'/api/video/{task_id}'}

    # ── luts / moods / tasks / status / trends / clean ──
    if name == 'luts':
        cfg = load_config()
        return {'message': '可用 LUT 风格', 'luts': cfg.get('color', {}).get('styles', ['cinematic'])}
    if name == 'moods':
        cfg = load_config()
        return {'message': '可用 BGM 情绪', 'moods': cfg.get('bgm', {}).get('moods', ['calm'])}
    if name == 'tasks':
        st = flags.get('status')
        n = int(flags.get('n', 10))
        rows = queue.list_tasks(status=st, limit=n)
        return {'message': f'共 {len(rows)} 个任务', 'tasks': rows}
    if name == 'status':
        if not pos:
            raise HTTPException(status_code=400, detail='用法: /status {task_id}')
        task = queue.get_task(pos[0])
        if not task:
            raise HTTPException(status_code=404, detail='Task not found')
        return {'message': f'任务 {pos[0]} 状态 {task["status"]}', 'task': task}
    if name == 'trends':
        from utils.crawler import Crawler
        top = int(flags.get('top', 10))
        topics = Crawler().fetch_hot_topics(top_per_source=top)
        return {'message': f'抓取到 {len(topics)} 条热点', 'topics': topics}
    if name == 'clean':
        keep = int(flags.get('keep', 10))
        import glob as _glob
        out_root = os.path.join(os.path.dirname(__file__), '..', 'output')
        dirs = sorted(_glob.glob(os.path.join(out_root, '2*')), key=os.path.getmtime, reverse=True)
        to_del = dirs[keep:]
        removed = []
        for d in to_del:
            try:
                import shutil as _sh
                _sh.rmtree(d)
                removed.append(os.path.basename(d))
            except Exception as e:
                print(f'  ⚠ clean failed {d}: {e}')
        return {'message': f'清理 {len(removed)} 个旧任务，保留 {keep} 个', 'removed': removed}

    # ── ask（v6 dialog）──
    if name == 'ask':
        if not pos:
            raise HTTPException(status_code=400, detail='用法: /ask 概念')
        from utils.dialog import DialogManager
        dm = DialogManager()
        s = dm.start(' '.join(pos))
        return {'message': f'评估 {s["status"]}，缺失 {len(s["missing"])} 项', 'dialog': s}

    # ── compose（v10 时间线拼接，纯 ffmpeg 后处理）──
    if name == 'compose':
        if not pos:
            raise HTTPException(status_code=400, detail='用法: /compose timeline.json [--output out]')
        from utils.compose import run_timeline
        out = run_timeline(pos[0], flags.get('output'))
        return {'message': '成片已生成', 'output': out,
                'compose_output': out,
                'video_url': ('/api/file?path=' + out) if out else ''}

    # ── svg（v13（原 v15）流水线：全部异步 job（无声 concept_to_mp4 / 有声 narrate_to_mp4），前端 pollH3 复用）──
    if name == 'svg':
        rr = _parse_repeated(req.args or '', {'say'})
        fl, pos2 = rr['flags'], rr['pos']
        say = rr['rep'].get('say') or []
        concept = fl.get('concept') or (' '.join(pos2) if pos2 else None)

        def _num(k, d):
            try:
                return int(fl.get(k))
            except (TypeError, ValueError):
                return d

        if not concept and not say:
            raise HTTPException(status_code=400,
                                detail='用法: /svg 概念 [--voice 音色 --n 3] | /svg --say "文本" --say …')
        voiced = bool(say or fl.get('voice'))
        job_id = f'svg_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        with _h3_jobs_lock:
            _h3_jobs[job_id] = {'job_id': job_id,
                                'concept': concept or (say[0][:20] if say else ''),
                                'status': 'running',
                                'created_at': datetime.now().isoformat()}
        threading.Thread(target=_run_svgjob,
                         args=(job_id, concept, _num('n', 3), say, fl, voiced),
                         daemon=True).start()
        return {'message': 'SVG 任务已提交（异步，LLM 生成中，可看日志面板跟踪）',
                'job_id': job_id, 'poll': f'/api/h3shot/{job_id}', 'h3_job_id': job_id}

    # ── ppt（LLM 生成 PPT/幻灯片，异步 job，复用 h3shot 轮询通道）──
    if name == 'ppt':
        rr = _parse_repeated(req.args or '', {'say'})
        fl, pos2 = rr['flags'], rr['pos']
        say = rr['rep'].get('say') or []
        concept = fl.get('concept') or (' '.join(pos2) if pos2 else None)

        def _pnum(k, d):
            try:
                return int(fl.get(k))
            except (TypeError, ValueError):
                return d

        if not concept and not say:
            raise HTTPException(status_code=400,
                                detail='用法: /ppt 主题 [-n 5 --voice 音色 --video --pdf] | /ppt --say "页标题" --say …')
        # 布尔形态：--video/--pdf/--pngs 传了就 True（值随意）
        want_video = fl.get('video') is not None
        want_pdf = fl.get('pdf') is not None
        want_pngs = fl.get('pngs') is not None
        job_id = f'ppt_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        with _h3_jobs_lock:
            _h3_jobs[job_id] = {'job_id': job_id,
                                'concept': concept or (say[0][:20] if say else ''),
                                'status': 'running',
                                'created_at': datetime.now().isoformat()}
        threading.Thread(target=_run_pptjob,
                         args=(job_id, concept, _pnum('n', 5), say, fl,
                               want_video, want_pdf, want_pngs),
                         daemon=True).start()
        return {'message': 'PPT 任务已提交（异步，LLM 规划中，可看日志面板跟踪）',
                'job_id': job_id, 'poll': f'/api/h3shot/{job_id}', 'h3_job_id': job_id}

    # ── blender3d（LLM 3D 场景 + bpy 渲染，异步 job，复用 h3shot 轮询通道）──
    if name == 'blender3d':
        rr = _parse_repeated(req.args or '', {'say'})
        fl, pos2 = rr['flags'], rr['pos']
        say = rr['rep'].get('say') or []
        concept = fl.get('concept') or (' '.join(pos2) if pos2 else None)
        if not concept and not say:
            raise HTTPException(status_code=400,
                                detail='用法: /blender3d 主题 [--duration 8 --voice 音色] | /blender3d --say "旁白"')
        job_id = f'b3d_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        with _h3_jobs_lock:
            _h3_jobs[job_id] = {'job_id': job_id,
                                'concept': concept or (say[0][:20] if say else ''),
                                'status': 'running',
                                'created_at': datetime.now().isoformat()}
        threading.Thread(target=_run_blenderjob,
                         args=(job_id, concept,
                               int(fl.get('n') or 1), say, fl),
                         daemon=True).start()
        return {'message': '3D 任务已提交（异步，LLM 规划中，可看日志面板跟踪）',
                'job_id': job_id, 'poll': f'/api/h3shot/{job_id}', 'h3_job_id': job_id}

    # ── edit（v16 SAM2 编辑：图同步 / 视频异步 job，复用 h3shot 轮询通道）──
    if name == 'edit':
        rr = _parse_repeated(req.args or '', {})
        fl, pos2 = rr['flags'], rr['pos']
        if not pos2:
            raise HTTPException(status_code=400,
                                detail='用法: /edit 图.jpg [segment|cutout|replace_bg|mosaic|inpaint] [--point x,y] | /edit 视频.mp4 video --point x,y')
        inp = pos2[0]
        cmd = pos2[1] if len(pos2) > 1 else fl.get('op') or 'mosaic'
        # 兼容 CLI 参数序（edit instruct 图.jpg / edit video in.mp4）：首 token 是已知命令名时交换
        _EDIT_CMDS = ('segment', 'cutout', 'replace_bg', 'mosaic', 'inpaint',
                      'visualize', 'video', 'instruct')
        if inp in _EDIT_CMDS and cmd not in _EDIT_CMDS:
            inp, cmd = cmd, inp
        # M8 指令式编辑：整图自然语言修改，无需 SAM mask（异步 job）
        if cmd == 'instruct':
            if not fl.get('prompt'):
                raise HTTPException(status_code=400,
                                    detail='instruct 需要 --prompt 编辑指令（如 把猫换成狗）')
            if not os.path.exists(inp):
                raise HTTPException(status_code=400, detail=f'文件不存在: {inp}')
            job_id = f'edit_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            with _h3_jobs_lock:
                _h3_jobs[job_id] = {'job_id': job_id, 'concept': fl['prompt'][:40],
                                    'status': 'running',
                                    'created_at': datetime.now().isoformat()}
            _agent_log(job_id, '▶ 调用 agent post.edit · instruct（Qwen-Image-Edit）')
            threading.Thread(target=_run_editimagejob,
                             args=(job_id, inp, 'instruct', fl),
                             daemon=True).start()
            return {'message': '编辑任务已提交（agent post.edit · Qwen-Image-Edit，约 1-2 分钟）',
                    'job_id': job_id, 'h3_job_id': job_id,
                    'poll': f'/api/h3shot/{job_id}'}
        if cmd == 'video':
            pts = []
            for tok in (fl.get('point') or '').replace(';', ' ').split():
                parts = tok.split(',')
                if len(parts) == 2:
                    try:
                        pts.append((int(float(parts[0])), int(float(parts[1]))))
                    except ValueError:
                        pass
            boxes = []
            for tok in (fl.get('box') or '').replace(';', ' ').split():
                parts = tok.split(',')
                if len(parts) == 4:
                    try:
                        boxes.append(tuple(int(float(v)) for v in parts))
                    except ValueError:
                        pass
            # YOLO 自动检测（Grounded-SAM：YOLO 框 → SAM2 精分割）
            if str(fl.get('yolo') or '').lower() in ('true', '1', 'yes') or fl.get('classes'):
                import cv2 as _cv2
                from agents.post.tools import sam_edit as _se_probe
                probe = _cv2.VideoCapture(inp)
                probe.set(_cv2.CAP_PROP_POS_FRAMES, max(0, int(fl.get('frame') or 0)))
                ok, fr = probe.read()
                if not ok:
                    raise HTTPException(status_code=400, detail='提示帧读取失败（--frame 超出帧数？）')
                dets = _se_probe.detect_objects(
                    fr[:, :, ::-1],
                    classes=[c for c in (fl.get('classes') or '').split(',') if c] or None,
                    conf=float(fl.get('conf') or 0.25))
                boxes = [d[2] for d in dets]
                if not boxes:
                    raise HTTPException(status_code=400, detail='YOLO 未检出目标（调低 --conf 或换 --frame）')
                # 检出框注入 flags，异步 job 直接复用（_run_editjob 只认 box）
                fl['box'] = ';'.join('%d,%d,%d,%d' % b for b in boxes)
                fl.pop('yolo', None)
            if not pts and not boxes:
                raise HTTPException(status_code=400,
                                    detail='video 需要 --point x,y / --box x1,y1,x2,y2 / --yolo')
            job_id = f'edit_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
            with _h3_jobs_lock:
                _h3_jobs[job_id] = {'job_id': job_id, 'concept': os.path.basename(inp),
                                    'status': 'running',
                                    'created_at': datetime.now().isoformat()}
            threading.Thread(target=_run_editjob,
                             args=(job_id, inp, pts, fl.get('op') or 'mosaic', fl),
                             daemon=True).start()
            return {'message': '视频编辑任务已提交（异步，SAM2 传播中）',
                    'job_id': job_id, 'poll': f'/api/h3shot/{job_id}', 'h3_job_id': job_id}
        # 图编辑：统一异步 job（CV 秒级 / flux 生成式，前端 pollH3 转圈 + 日志面板）
        if not os.path.exists(inp):
            raise HTTPException(status_code=400, detail=f'文件不存在: {inp}')
        job_id = f'edit_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        with _h3_jobs_lock:
            _h3_jobs[job_id] = {'job_id': job_id, 'concept': os.path.basename(inp),
                                'status': 'running',
                                'created_at': datetime.now().isoformat()}
        _agent_log(job_id, '▶ 调用 agent post.edit · %s' % cmd)
        threading.Thread(target=_run_editimagejob,
                         args=(job_id, inp, cmd, fl),
                         daemon=True).start()
        return {'message': f'编辑任务已提交（agent post.edit · {cmd}）',
                'job_id': job_id, 'h3_job_id': job_id,
                'poll': f'/api/h3shot/{job_id}'}

    # ── vace（v16.x M7：Wan2.1 VACE 参考图生视频，异步）──
    if name == 'vace':
        if len(pos) < 2:
            raise HTTPException(status_code=400,
                                detail='用法: /vace 参考图.png "prompt" [--length 81] [-o out.mp4]')
        vref, vprompt = pos[0], ' '.join(pos[1:])
        if not os.path.exists(vref):
            raise HTTPException(status_code=400, detail=f'参考图不存在: {vref}')
        out = flags.get('o') or flags.get('output') or os.path.join(
            load_config()['output_dir'],
            'vace_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.mp4')
        job_id = f'vace_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        with _h3_jobs_lock:
            _h3_jobs[job_id] = {'job_id': job_id, 'concept': vprompt[:40],
                                'status': 'running', 'stage': 'Wan2.1 VACE 生成中',
                                'created_at': datetime.now().isoformat()}
        _agent_log(job_id, '▶ 调用 Wan2.1 VACE（wan 8189，约 5-10 分钟）')

        def _run_vacejob():
            try:
                from agents.generator.tools.comfy_api import ComfyClient
                c = ComfyClient(instance='wan')
                r = c.generate_vace_video(vref, vprompt,
                                          length=int(flags.get('length') or 81),
                                          width=int(flags.get('width') or 480),
                                          height=int(flags.get('height') or 832),
                                          steps=int(flags.get('steps') or 25),
                                          cfg=float(flags.get('cfg') or 5.0),
                                          vace_strength=float(
                                              flags.get('vace-strength')
                                              or flags.get('vace_strength') or 1.0),
                                          output_path=out)
                vout = r['video_path']
                with _h3_jobs_lock:
                    _h3_jobs[job_id].update({'status': 'completed',
                                             'output': vout,
                                             'video_url': '/api/file?path=' + vout})
                _agent_log(job_id, '■ 完成 %s' % vout)
            except Exception as e:
                with _h3_jobs_lock:
                    _h3_jobs[job_id].update({'status': 'failed', 'error': str(e)[:400]})
                _agent_log(job_id, '✗ 失败: %s' % str(e)[:300])

        threading.Thread(target=_run_vacejob, daemon=True).start()
        return {'message': 'VACE 视频生成任务已提交（Wan2.1 VACE，约 5-10 分钟）',
                'job_id': job_id, 'h3_job_id': job_id,
                'poll': f'/api/h3shot/{job_id}'}

    # ── concat（多视频拼接，同步子进程）──
    if name == 'concat':
        if len(pos) < 2:
            raise HTTPException(status_code=400,
                                detail='用法: /concat A.mp4 B.mp4 [...] -o out.mp4 [--transition cut|crossfade|rife]')
        out = flags.get('o') or flags.get('output')
        if not out:
            out = os.path.join(load_config()['output_dir'],
                               'concat_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.mp4')
        cmd = [sys.executable, os.path.join(os.path.dirname(__file__), 'vidance.py'),
               'concat', *pos, '-o', out]
        if flags.get('transition'):
            cmd += ['--transition', str(flags['transition'])]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=500, detail='concat 超时（30 min）')
        if r.returncode != 0:
            raise HTTPException(status_code=500,
                                detail='concat 失败: ' + ((r.stderr or '') + (r.stdout or ''))[-400:])
        return {'message': '拼接完成', 'output': out, 'compose_output': out,
                'video_url': '/api/file?path=' + out}

    # ── arch（架构总览：层/Agent/服务 数据驱动 + 端口在线探测）──
    if name == 'arch':
        import socket
        from agents.runtime import load_all
        reg = load_all()
        by_layer = {}
        for a in reg.values():
            by_layer.setdefault(a['layer'], []).append(
                {'name': a['name'], 'desc': a['desc'], 'gpu': a['needs_gpu'],
                 'inputs': a['inputs']})

        def _up(port, host='127.0.0.1'):
            try:
                with socket.create_connection((host, port), timeout=0.3):
                    return True
            except OSError:
                return False

        services = [
            {'name': 'ComfyUI · H3', 'port': 8188, 'gpu': 'GPU0', 'for': 'custom/H3 生成'},
            {'name': 'ComfyUI · Wan+RIFE', 'port': 8189, 'gpu': 'GPU2', 'for': 'T2V/I2V/插帧'},
            {'name': 'ComfyUI · FLUX', 'port': 8192, 'gpu': 'GPU3', 'for': '生图/美术师'},
            {'name': 'ComfyUI · SDXL', 'port': 8191, 'gpu': '—', 'for': '生图备选'},
            {'name': 'ComfyUI · Hunyuan3D', 'port': 8193, 'gpu': 'GPU1', 'for': '3D 重建'},
            {'name': 'TTS 双引擎', 'port': 9880, 'gpu': 'GPU2', 'for': 'edge/CosyVoice/克隆'},
            {'name': 'Vidance API · UI', 'port': 8894, 'gpu': 'CPU', 'for': '/ui /api /agent'},
        ]
        for s in services:
            s['online'] = _up(s['port'])
        skeleton = [
            ('core', '编排宿主', 'core/',
             'CLI vidance.py / FastAPI / scheduler 队列 / pipeline 主链', []),
            ('director', 'D · 决策层', 'agents/director/',
             '选题·编剧·风格/BGM/特效决策·智囊', ['dialog']),
            ('generator', 'G · 生成层', 'agents/generator/',
             '视频/图像/3D/SVG 生成与渲染', ['comfy_api', 'fastline', 'svg_pipeline',
                                          'rife', 'mesh_render', 'vendor', 'model_router']),
            ('post', 'P · 后期层', 'agents/post/',
             '时间线拼接·调色·BGM·字幕·特效·配音', ['compose', 'effects', 'music',
                                                 'stt', 'ffmpeg_tools']),
            ('audit', 'V · 审核层', 'agents/audit/',
             '多模态审片·ensemble 多票', []),
            ('common', '共享基础设施', 'agents/common/',
             'LLM·TTS·配置·爬虫·资产·声音克隆·t2c',
             ['llm', 'tts', 'config_loader', 'crawler', 'asset_registry']),
        ]
        layers = []
        for key, title, path, note, tools in skeleton:
            if key == 'common':
                for r in [
                    {'role': '🧠 智囊团', 'impl': 'llm', 'by': 'director.brain；各层编剧/选风格/审片都调它'},
                    {'role': '🎙️ 配音师', 'impl': 'tts + voice_clone', 'by': 'post.voice / post.tts；edge·CosyVoice·克隆音色'},
                    {'role': '📡 情报员', 'impl': 'crawler + asset_crawler', 'by': 'director.scout / generator.artist(crawl)'},
                    {'role': '🗄️ 资产管家', 'impl': 'asset_registry', 'by': '角色/场景 3D 资产查重复用'},
                    {'role': '🧰 勤务管家', 'impl': 'config_loader + tts/t2c 服务', 'by': '配置加载 / 自然语言→命令'},
                ]:
                    layers.append({'layer': 'common', 'title': r['role'], 'path': r['impl'],
                                   'note': r['by'], 'tools': [], 'agents': []})
                continue
            layers.append({'layer': key, 'title': title, 'path': path, 'note': note,
                           'tools': tools,
                           'agents': sorted(by_layer.get(key, []), key=lambda x: x['name'])})
        return {'message': 'Vidance 多智能体架构',
                'flow': '概念 → D 决策 → G 生成 → P 后期 → V 审核（不过回 G 重做）→ 成片',
                'layers': layers, 'services': services,
                'board': '每张卡片/每次运行都记入台账（output/tasks.sqlite 的 agent_runs 表），'
                         'chain 任务的时间线即从此读取',
                'entry': 'vidance.py agent {list|run|chain} · POST /api/agents/chain · '
                         "POST /api/tasks {mode:'chain'}"}

    # ── agent（v11（原 v13）：子分发 list/run/chain）──
    if name == 'agent':
        import json as _json
        import shlex as _shq
        import time as _time
        from agents.runtime import load_all, run_chain
        from agents.base import run_agent as _ra, REGISTRY
        load_all()
        sub = pos[0] if pos else 'list'
        if sub == 'list':
            return {'message': f'共 {len(REGISTRY)} 个 Agent（D/G/P/V 四层薄包装）',
                    'agents': [{k: v for k, v in a.items() if k != 'fn'}
                               for a in sorted(REGISTRY.values(),
                                               key=lambda x: (x['layer'], x['name']))]}
        def _greedy(key):
            """--steps/--with 贪婪捕获：JSON 含空格被 shlex 切碎时，取 flag 后整段。"""
            a = req.args or ''
            i = a.find('--' + key)
            if i < 0:
                return None
            v = a[i + len(key) + 2:].lstrip()
            if v[:1] in ('"', "'") and v[-1:] == v[:1]:
                v = v[1:-1].replace('\\"', '"').replace("\\'", "'")
            elif v[:1] in ('"', "'"):
                v = v[1:]
            return v

        if sub == 'run':
            if len(pos) < 2:
                raise HTTPException(status_code=400,
                                    detail='用法: /agent run <name> --with \'<参数JSON>\'')
            agen = pos[1]
            if agen not in REGISTRY:
                raise HTTPException(status_code=404, detail='unknown agent: %s' % agen)
            pj = _greedy('with') or flags.get('with') or flags.get('w')
            if not pj:
                a2 = req.args or ''
                k = a2.find('{')
                pj = a2[k:] if k >= 0 else '{}'
            try:
                params = _json.loads(pj) if isinstance(pj, str) else pj
            except ValueError as e:
                raise HTTPException(status_code=400, detail='--with 非法 JSON: %s' % e)
            tid = 'agent_' + _time.strftime('%Y%m%d_%H%M%S') + '_run'
            ACTIVE_RUNS[tid] = {'kind': 'run:' + agen, 'steps': 1, 'done': 0,
                                'status': 'run', 't0': _time.time()}
            if _enforce_out(params, tid):
                _agent_log(tid, '\u26d4 out_path \u8d8a\u754c\uff0c\u5df2\u6539\u5199\u8fdb\u8fd0\u884c\u76ee\u5f55')
            _agent_log(tid, '▶ run %s %s' % (
                agen, _json.dumps(params, ensure_ascii=False, default=str)[:300]))
            res = _ra(agen, params, board=_v13_board(), task_id=tid)
            _agent_log(tid, ('✓ 完成 产物: ' if res.ok else '✗ 失败: %s 产物: ' % res.error)
                       + ', '.join(str(p) for p in list(res.artifacts.values())[:3]))
            dd = res.to_dict()
            dd['task_id'] = tid
            fin0 = next((res.artifacts[k] for k in ('video', 'video_path', 'glb_path',
                                                    'ply_path', 'audio', 'wav_path')
                         if res.artifacts.get(k)), None)
            fin0, mv0 = _vault_final(tid, fin0)
            ACTIVE_RUNS[tid] = {**ACTIVE_RUNS.get(tid, {}), 'status': 'ended',
                                'done': 1, 't1': _time.time()}
            dd['final'] = fin0
            dd['message'] = ('✓ %s 完成%s' % (agen, '（已归仓 output）' if mv0 else '')
                             if res.ok else ('✗ %s 失败' % agen))
            return dd
        if sub == 'chain':
            raw = _greedy('steps') or flags.get('steps') or flags.get('f')
            if not raw:
                a = req.args or ''
                cuts = [j for j in (a.find('['), a.find('{')) if j >= 0]
                raw = a[min(cuts):] if cuts else (
                    ' '.join(pos[1:]) if len(pos) > 1 else '')
            if not raw:
                raise HTTPException(status_code=400,
                                    detail='用法: /agent chain --steps \'{"steps":[...]}\'')
            try:
                data = _json.loads(raw)
            except ValueError as e:
                raise HTTPException(status_code=400, detail='steps 非法 JSON: %s' % e)
            steps = data.get('steps', data.get('chain', data)) if isinstance(data, dict) else data
            tid = 'agent_' + _time.strftime('%Y%m%d_%H%M%S') + '_chain'
            ACTIVE_RUNS[tid] = {'kind': 'chain', 'steps': len(steps), 'done': 0,
                                'status': 'run', 't0': _time.time()}

            _n = sum(1 for _st in steps if isinstance(_st, dict)
                     and isinstance(_st.get('with'), dict) and _enforce_out(_st['with'], tid))
            if _n:
                _agent_log(tid, '\u26d4 %d \u5904 out_path \u8d8a\u754c\uff0c\u5df2\u6539\u5199\u8fdb\u8fd0\u884c\u76ee\u5f55' % _n)

            def _log_ev(e, _tid=tid):
                ar = ACTIVE_RUNS.get(_tid)
                if ar and e['event'] == 'done':
                    ar['done'] += 1
                if e['event'] == 'start':
                    _agent_log(_tid, '▶ chain %d 步' % e['total'])
                elif e['event'] == 'step':
                    _agent_log(_tid, '⏳ [%d] %s %s' % (e['i'] + 1, e['name'], (e.get('args') or '')[:200]))
                elif e['event'] == 'done':
                    _agent_log(_tid, '%s [%d] %s %.1fs %s' % (
                        '✓' if e['ok'] else '✗ %s' % e.get('error'), e['i'] + 1, e['name'],
                        e['secs'], (e.get('arts') or {}).get('video') or (e.get('arts') or {}).get('audio') or ''))

            out = run_chain(steps, ctx=data.get('ctx') if isinstance(data, dict) else None,
                            task_id=tid, board=_v13_board(), on_event=_log_ev)
            ACTIVE_RUNS[tid] = {**ACTIVE_RUNS.get(tid, {}), 'status': 'ended', 't1': _time.time()}
            _agent_log(tid, '■ 结束 ok=%s %.1fs' % (out['ok'], out['t_dur']))
            la = (out['steps'][-1].get('artifacts') or {}) if out['steps'] else {}
            fin0 = next((la[k] for k in ('video', 'video_path', 'glb_path', 'ply_path',
                                         'audio', 'wav_path') if la.get(k)),
                        out['ctx'].get('video'))
            fin0, mv0 = _vault_final(tid, fin0)
            out['final'] = fin0
            out['message'] = ('✓ 链完成（%d 步，%.1fs%s）'
                              % (len(out['steps']), out['t_dur'], '，已归仓' if mv0 else '')
                              if out['ok'] else '✗ 链中断')
            out.pop('ctx', None)
            return out
        if sub == 'board':
            from agents.blackboard import AgentBoard
            n = int(flags.get('n', 15))
            tid = flags.get('task') or flags.get('t') or ''
            runs = AgentBoard().runs(task_id=tid or None, limit=n)
            return {'board': True, 'runs': runs,
                    'message': '运行台账最近 %d 条%s' % (len(runs), ('（任务 %s）' % tid) if tid else '')}
        raise HTTPException(status_code=400, detail='/agent 子命令: list | run | chain | board')

    # ── h3shot（整段式 prompt + 参考图 → H3 单镜，异步）──
    if name == 'h3shot':
        rr = _parse_repeated(req.args or '', {'ref', 'name'})
        refs = rr['rep'].get('ref', [])
        names = rr['rep'].get('name', [])
        prompt_file = rr['flags'].get('prompt') or (rr['pos'][0] if rr['pos'] else None)
        if not prompt_file or not refs:
            raise HTTPException(status_code=400,
                                detail='用法: /h3shot --prompt <prompt.txt> --ref <图> [--name 名] ... [-o out]')
        try:
            req2 = H3ShotRequest(
                prompt=prompt_file, refs=refs, names=names,
                output=rr['flags'].get('o') or rr['flags'].get('output'),
                seconds=float(rr['flags']['seconds']) if rr['flags'].get('seconds') not in (None, True) else None,
                fast=bool(rr['flags'].get('fast')),
                ref_image_size=rr['flags'].get('ref_image_size', 'match'),
                no_describe=bool(rr['flags'].get('no_describe')),
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f'参数错误: {e}')
        job_id = f'h3_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        with _h3_jobs_lock:
            _h3_jobs[job_id] = {'job_id': job_id, 'prompt': prompt_file, 'refs': refs,
                                'status': 'running', 'created_at': datetime.now().isoformat()}
        threading.Thread(target=_run_h3shot, args=(job_id, req2), daemon=True).start()
        return {'message': 'H3 单镜任务已提交（异步，约 15-20 分钟）',
                'job_id': job_id, 'poll': f'/api/h3shot/{job_id}',
                'h3_job_id': job_id}

    # ── custom（参考图 + 多镜分镜脚本 → H3，异步）──
    if name == 'custom':
        rr = _parse_repeated(req.args or '', {'ref'})
        refs = rr['rep'].get('ref', [])
        script = rr['flags'].get('script')
        if not refs or not script:
            raise HTTPException(status_code=400,
                                detail='用法: /custom --ref <图> --script <脚本> [...]')
        job_id = f'custom_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        with _h3_jobs_lock:
            _h3_jobs[job_id] = {'job_id': job_id, 'script': script, 'refs': refs,
                                'status': 'running', 'created_at': datetime.now().isoformat()}
        threading.Thread(target=_run_custom_job, args=(job_id, rr), daemon=True).start()
        return {'message': 'custom 生成任务已提交（异步）',
                'job_id': job_id, 'poll': f'/api/h3shot/{job_id}'}

    # ── scout ──
    if name == 'scout':
        from utils.crawler import Crawler
        from utils.llm import LLMClient
        crawler = Crawler()
        llm = LLMClient(load_config())
        account = flags.get('account', '影视解说')
        n = int(flags.get('n', 5))
        topics = crawler.fetch_hot_topics(top_per_source=15)
        candidates = llm.scout_topics(topics, account_type=account, n_candidates=n)
        batch_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        queue.save_scout_batch(batch_id, topics, candidates)
        return {'message': f'{len(topics)} 条热点 → {len(candidates)} 候选',
                'batch_id': batch_id, 'candidates': candidates}

    # ── clip（FunClip 异步）──
    if name == 'clip':
        if not pos:
            raise HTTPException(status_code=400, detail='用法: /clip 输入路径 -i "指令"')
        req2 = ClipRequest(input=pos[0], instructions=flags.get('i', flags.get('instructions', '')))
        job_id = f'clip_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        with _clip_jobs_lock:
            _clip_jobs[job_id] = {'job_id': job_id, 'input': req2.input,
                                  'instructions': req2.instructions,
                                  'status': 'running', 'created_at': datetime.now().isoformat()}
        threading.Thread(target=_run_clip, args=(job_id, req2), daemon=True).start()
        return {'message': '裁剪任务已提交（异步）', 'job_id': job_id, 'poll': f'/api/clip/{job_id}'}

    # ── make（v12（原 v17）M2：三排正交统一入口，归一后递归复用现有分发）──
    if name == 'make':
        import shlex as _shq
        rr = _parse_repeated(req.args or '', {'say', 'ref'})
        fl, pos2 = rr['flags'], rr['pos']
        say = rr['rep'].get('say') or []
        refs = rr['rep'].get('ref') or []
        gen = fl.get('generator') or 'wan'
        concept = ' '.join(pos2) or fl.get('concept') or ''
        director = fl.get('director') or ('manual' if (say or fl.get('prompt') or fl.get('script')) else 'llm')
        if director == 'scout' and not concept:
            from utils.crawler import Crawler
            from utils.llm import LLMClient as _LLM
            topics = Crawler().fetch_hot_topics(top_per_source=15)
            cands = _LLM(load_config()).scout_topics(
                topics, account_type=fl.get('account') or '影视解说', n_candidates=3)
            if not cands:
                raise HTTPException(status_code=500, detail='scout 未选出概念')
            concept = cands[0]['concept']
        q = _shq.quote
        a2 = []
        if gen == 'svg':
            a2 = ['--concept', q(concept or (say[0] if say else ''))]
            for s_ in say:
                a2 += ['--say', q(s_)]
            for k in ('voice', '-o', 'n', 'lut', 'bgm'):
                if fl.get(k) not in (None, True):
                    a2 += ['--' + k.lstrip('-'), q(str(fl[k]))]
            return tool_dispatch('svg', ToolRequest(args=' '.join(a2)))
        if gen == 'h3':
            if fl.get('script'):
                a2 = ['--script', q(fl['script'])]
                for r_ in refs:
                    a2 += ['--ref', q(r_)]
                return tool_dispatch('custom', ToolRequest(args=' '.join(a2)))
            if not fl.get('prompt'):
                raise HTTPException(status_code=400,
                                    detail='/make 生成器 h3 需 --prompt 文件 或 --script 脚本（配 --ref）')
            a2 = [q(fl['prompt'])] + sum((['--ref', q(r_)] for r_ in refs), [])
            for k in ('-o', 'seconds'):
                if fl.get(k) not in (None, True):
                    a2 += ['--' + k.lstrip('-'), q(str(fl[k]))]
            if fl.get('fast'):
                a2.append('--fast')
            return tool_dispatch('h3shot', ToolRequest(args=' '.join(a2)))
        if gen == 'fast':
            a2 = [q(concept), '--n', str(min(int(fl.get('n') or 5), 5))]
            for k in ('voice', 'images-source', 'effects', 'lut', 'bgm'):
                kk = 'images_source' if k == 'images-source' else k
                if fl.get(k) not in (None, True):
                    a2 += ['--' + k, q(str(fl[k]))]
            return tool_dispatch('fast', ToolRequest(args=' '.join(a2)))
        # wan：有角色 → auto 全管线；无 → quick
        a2 = [q(concept)]
        tgt = 'quick'
        if fl.get('character'):
            tgt = 'auto'
            a2 += ['--character', q(fl['character'])]
            for k in ('voice', 'lut', 'bgm', 'duration'):
                if fl.get(k) not in (None, True):
                    a2 += ['--' + k, q(str(fl[k]))]
        elif fl.get('voice') not in (None, True):
            a2 += ['--voice', q(str(fl['voice']))]
        return tool_dispatch(tgt, ToolRequest(args=' '.join(a2)))

    # ── 任务型：auto / fast / hot / quick（提交任务队列，前端轮询）──
    if name in ('auto', 'fast', 'hot', 'quick'):
        if not pos:
            raise HTTPException(status_code=400, detail=f'用法: /{name} 概念')
        concept = ' '.join(pos)
        opts = {'mode': name}
        if name == 'quick':
            if flags.get('voice'):
                opts['voice'] = flags['voice']
        elif name == 'auto':
            for k in ('character', 'character_mode', 'voice', 'lut', 'bgm'):
                if flags.get(k):
                    opts[k] = flags[k]
            for k in ('duration', 'slowmo'):
                if flags.get(k):
                    opts[k] = float(flags[k])
            if flags.get('stt'):
                opts['stt'] = True
        else:  # fast / hot
            for k in ('images_source', 'effects', 'voice', 'motion', 'lut', 'bgm', 'account'):
                if flags.get(k):
                    opts[k] = flags[k]
            if flags.get('n'):
                opts['images_count'] = min(int(flags['n']), 5)  # ≤5（用户约定）
            if flags.get('stt'):
                opts['stt'] = True
        task_id = queue.submit(concept, options=opts)
        return {'message': f'任务已提交: {task_id}', 'task_id': task_id,
                'progress_url': f'/api/tasks/{task_id}'}

    raise HTTPException(status_code=400, detail=f'Tool {name} not dispatchable')


# ══ 模型提供商管理 ══

class SwitchProvider(BaseModel):
    task_type: str
    provider_id: str
    model: Optional[str] = None


class AddProvider(BaseModel):
    id: str
    name: str
    base_url: str
    api_key: str = ''
    models: list = []


class UpdateProvider(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    models: Optional[list] = None


class DiscoverModels(BaseModel):
    base_url: str
    api_key: str = ''


@app.get('/api/model-providers')
def model_providers():
    from utils.model_router import ModelRouter
    router = ModelRouter()
    return {
        'providers': router.list_providers(),
        'active': {tt: router.get_active(tt) for tt in ModelRouter.TASK_TYPES},
        'task_labels': ModelRouter.TASK_LABELS,
    }


@app.put('/api/model-providers/switch')
def switch_provider(req: SwitchProvider):
    from utils.model_router import ModelRouter
    router = ModelRouter()
    try:
        result = router.set_active(req.task_type, req.provider_id, req.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {'message': f'{req.task_type} → {req.provider_id}', **result}


@app.post('/api/model-providers')
def add_provider(req: AddProvider):
    from utils.model_router import ModelRouter
    router = ModelRouter()
    try:
        result = router.add_provider(req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {'message': f'已添加: {req.name}', 'provider': result}


@app.put('/api/model-providers/{provider_id}')
def update_provider(provider_id: str, req: UpdateProvider):
    from utils.model_router import ModelRouter
    router = ModelRouter()
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        result = router.update_provider(provider_id, updates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {'message': f'{provider_id} updated', 'provider': result}


@app.delete('/api/model-providers/{provider_id}')
def remove_provider(provider_id: str):
    from utils.model_router import ModelRouter
    router = ModelRouter()
    try:
        router.remove_provider(provider_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {'message': f'已删除: {provider_id}'}


class ImportProvidersReq(BaseModel):
    path: str = None
    text: str = None
    overwrite_llm: bool = False


@app.post('/api/model-providers/import')
def import_model_providers(req: ImportProvidersReq):
    """从本地/他机拷来的 config.json 一键导入模型配置。"""
    from utils.model_router import ModelRouter
    return ModelRouter().import_from_config(path=req.path, text=req.text,
                                            overwrite_llm=req.overwrite_llm)


@app.post('/api/model-providers/discover')
def discover_models(req: DiscoverModels):
    from utils.model_router import ModelRouter
    result = ModelRouter.discover_models(req.base_url, req.api_key)
    return result


@app.get('/api/model-providers/health')
def model_providers_health():
    """全部提供商连通性探测（ComfyUI 探实例，API 探 /models）。"""
    from utils.model_router import ModelRouter
    return {'providers': ModelRouter().health()}


class ModelChatReq(BaseModel):
    messages: list
    model: str = None
    temperature: float = 0.7
    max_tokens: int = 1024


@app.post('/api/model/chat')
def model_chat(req: ModelChatReq):
    """OpenAI 兼容 chat，按候选顺序自动轮换（一个不通自动切下一个）。"""
    from utils.model_router import ModelRouter
    return ModelRouter().chat_api(req.messages, model=req.model,
                                  temperature=req.temperature,
                                  max_tokens=req.max_tokens)


# ══ ComfyUI 节点画布反向代理 (/ui_comfyui) ══

try:
    import httpx
    import websockets
    _COMFYUI_PROXY_AVAILABLE = True
except ImportError:
    _COMFYUI_PROXY_AVAILABLE = False


def _get_comfyui_target(request):
    cfg = load_config()
    instance = request.query_params.get('instance', 'wan')
    inst_cfg = cfg.get('comfyui', {}).get(instance, {})
    host = inst_cfg.get('host', '127.0.0.1')
    port = inst_cfg.get('port', 8189)
    return f'http://{host}:{port}', f'ws://{host}:{port}'


_WS_INJECT = b'''<script>
(function(){
  var _WS = window.WebSocket;
  window.WebSocket = function(url, protocols) {
    if (typeof url === 'string' && url.indexOf('/ws') !== -1) {
      url = url.replace(/\\/ws/, '/ui_comfyui/ws');
    }
    return protocols !== undefined ? new _WS(url, protocols) : new _WS(url);
  };
  window.WebSocket.prototype = _WS.prototype;
  window.WebSocket.CONNECTING = _WS.CONNECTING;
  window.WebSocket.OPEN = _WS.OPEN;
  window.WebSocket.CLOSING = _WS.CLOSING;
  window.WebSocket.CLOSED = _WS.CLOSED;
})();
</script>'''


if _COMFYUI_PROXY_AVAILABLE:

    @app.websocket('/ui_comfyui/ws')
    async def comfyui_ws_proxy(websocket: WebSocket):
        from starlette.websockets import WebSocketDisconnect
        await websocket.accept()
        instance = websocket.query_params.get('instance', 'wan')
        cfg = load_config()
        inst_cfg = cfg.get('comfyui', {}).get(instance, {})
        host = inst_cfg.get('host', '127.0.0.1')
        port = inst_cfg.get('port', 8189)
        try:
            upstream_url = f'ws://{host}:{port}/ws'
            async with websockets.connect(upstream_url) as upstream:
                async def forward_client():
                    try:
                        while True:
                            data = await websocket.receive()
                            if data['type'] == 'websocket.disconnect':
                                return
                            msg = data.get('text') or data.get('bytes')
                            if msg is not None:
                                await upstream.send(msg)
                    except (WebSocketDisconnect, Exception):
                        pass

                async def forward_upstream():
                    try:
                        async for msg in upstream:
                            if isinstance(msg, str):
                                await websocket.send_text(msg)
                            else:
                                await websocket.send_bytes(msg)
                    except Exception:
                        await websocket.close()

                import asyncio
                done, pending = await asyncio.wait(
                    [asyncio.create_task(forward_client()),
                     asyncio.create_task(forward_upstream())],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
        except Exception as e:
            await websocket.close(code=1011)

    @app.api_route('/ui_comfyui/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'])
    async def comfyui_proxy(request: Request, path: str = ''):
        http_target, _ = _get_comfyui_target(request)
        target_url = f'{http_target}/{path}'
        if request.query_params:
            target_url += f'?{request.query_params}'

        body = await request.body()
        headers = dict(request.headers)
        for h in ('host', 'connection', 'transfer-encoding'):
            headers.pop(h, None)

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                resp = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=body,
                )
            content = resp.content
            ct = resp.headers.get('content-type', '')
            if 'text/html' in ct:
                idx = content.lower().find(b'<head>')
                if idx >= 0:
                    insert_at = idx + 6
                    content = content[:insert_at] + _WS_INJECT + content[insert_at:]

            excluded = {'transfer-encoding', 'connection', 'content-encoding', 'content-length'}
            resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in excluded}
            return Response(content=content, status_code=resp.status_code, headers=resp_headers)
        except Exception as e:
            return HTMLResponse(
                f'<html><body style="background:#0f0f1a;color:#e8e8f0;display:flex;'
                f'align-items:center;justify-content:center;height:100vh;'
                f'font-family:sans-serif;text-align:center">'
                f'<div><h2>ComfyUI 连接失败</h2>'
                f'<p style="color:#8a8a9e;margin:12px 0">无法连接到 {target_url.split("/")[2]}</p>'
                f'<p style="color:#8a8a9e;font-size:13px">{e}</p>'
                f'<p style="color:#8a8a9e;font-size:12px;margin-top:16px">'
                f'请确认 ComfyUI 已启动: <code>CUDA_VISIBLE_DEVICES=N python main.py --listen 127.0.0.1 --port 8189</code></p>'
                f'</div></body></html>',
                status_code=502,
            )


# ── v11 多智能体（原 v13）──
class AgentRunReq(BaseModel):
    params: dict = {}
    task_id: str = 'api'


class AgentChainReq(BaseModel):
    steps: list
    ctx: dict = {}
    task_id: str = 'api'


@app.get('/api/agents')
def list_agents_api():
    """列出已注册 Agent（D/G/P/V 各层薄包装）。"""
    from agents.runtime import load_all
    reg = load_all()
    return {'agents': [
        {k: v for k, v in a.items() if k != 'fn'}
        for a in sorted(reg.values(), key=lambda x: (x['layer'], x['name']))]}


class AgentStreamReq(BaseModel):
    command: str


@app.post('/api/agent/stream')
def agent_stream(req: AgentStreamReq):
    """打字机式流式执行 /agent run|chain（SSE 事件流）。"""
    import json as _json
    import queue
    import re as _re
    import threading
    import uuid as _uuid
    from agents.runtime import load_all, run_chain
    load_all()
    cmd = (req.command or '').strip()
    if cmd.startswith('/agent'):
        cmd = cmd[len('/agent'):].strip()
    m = _re.match(r'(run|chain)\s+([\s\S]*)', cmd)
    if not m:
        raise HTTPException(status_code=400, detail='用法: /agent chain [ … ] 或 /agent run <name> { … }')
    sub, rest = m.group(1), m.group(2).strip()

    def _unq(s):
        return s[1:-1].replace('\\"', '"') if len(s) > 1 and s[0] in '\"\'' and s[0] == s[-1] else s

    if sub == 'chain':
        if rest.startswith('--steps'):
            rest = rest[7:].strip()
        try:
            data = _json.loads(_unq(rest))
        except ValueError as e:
            raise HTTPException(status_code=400, detail='steps 非法 JSON: %s' % e)
        steps = data.get('steps', data.get('chain', data)) if isinstance(data, dict) else data
        ctx0 = data.get('ctx') if isinstance(data, dict) else None
    else:
        parts = rest.split(None, 1)
        if not parts:
            raise HTTPException(status_code=400, detail='用法: /agent run <name> --with { … }')
        agen, rj = parts[0], (parts[1] if len(parts) > 1 else '{}')
        if rj.startswith('--with'):
            rj = rj[6:].strip()
        k = rj.find('{')
        if k < 0:
            rj = '{}'
        elif k > 0:
            rj = rj[k:]
        try:
            params = _json.loads(_unq(rj))
        except ValueError as e:
            raise HTTPException(status_code=400, detail='--with 非法 JSON: %s' % e)
        steps, ctx0 = [{'agent': agen, 'with': params}], None
    if not isinstance(steps, list) or not steps:
        raise HTTPException(status_code=400, detail='steps 为空')

    q = queue.Queue()
    tid = 'agent_' + time.strftime('%Y%m%d_%H%M%S') + '_chain'

    def _fwd(e):
        q.put(e)
        if e.get('event') == 'start':
            _agent_log(tid, '▶ chain(stream) %d 步' % e['total'])
        elif e.get('event') == 'step':
            _agent_log(tid, '⏳ [%d] %s %s' % (e['i'] + 1, e['name'], (e.get('args') or '')[:200]))
        elif e.get('event') == 'done':
            _agent_log(tid, '%s [%d] %s %.1fs %s' % (
                '✓' if e['ok'] else '✗ %s' % e.get('error'), e['i'] + 1, e['name'],
                e['secs'], (e.get('arts') or {}).get('video') or (e.get('arts') or {}).get('audio') or ''))
            ar = ACTIVE_RUNS.get(tid)
            if ar:
                ar['done'] += 1

    def worker():
        try:
            out = run_chain(steps, ctx=ctx0, task_id=tid, board=_v13_board(),
                            on_event=_fwd)
            ctx = out['ctx']
            last_arts = (out['steps'][-1].get('artifacts') or {}) if out['steps'] else {}
            fin = next((last_arts[k] for k in ('video', 'video_path', 'glb_path', 'ply_path',
                                               'audio', 'wav_path') if last_arts.get(k)),
                       next((ctx[k] for k in ('video', 'glb_path', 'ply_path')
                             if ctx.get(k)), None))
            fin, moved = _vault_final(tid, fin)
            q.put({'event': 'final', 'ok': out['ok'], 'secs': out['t_dur'],
                   'final': fin, 'task_id': tid, 'moved': moved})
            _agent_log(tid, '■ 结束 ok=%s %.1fs' % (out['ok'], out['t_dur']))
        except Exception as e:
            q.put({'event': 'error', 'msg': str(e)[:200]})
            _agent_log(tid, '✗ 异常: %s' % str(e)[:200])
        finally:
            ar = ACTIVE_RUNS.get(tid)
            if ar:
                ar['status'] = 'ended'
                ar['t1'] = time.time()
                ACTIVE_RUNS[tid] = ar
                while len(ACTIVE_RUNS) > 20:
                    ACTIVE_RUNS.pop(next(iter(ACTIVE_RUNS)))
            q.put({'event': '__end__'})

    ACTIVE_RUNS[tid] = {'kind': 'chain', 'steps': len(steps), 'done': 0,
                        'status': 'run', 't0': time.time()}
    _n = sum(1 for _st in steps if isinstance(_st, dict)
             and isinstance(_st.get('with'), dict) and _enforce_out(_st['with'], tid))
    if _n:
        _agent_log(tid, '\u26d4 %d \u5904 out_path \u8d8a\u754c\uff0c\u5df2\u6539\u5199\u8fdb\u8fd0\u884c\u76ee\u5f55' % _n)
    threading.Thread(target=worker, daemon=True).start()

    def gen():
        yield 'data: %s\n\n' % _json.dumps({'event': 'task', 'task_id': tid})
        while True:
            try:
                e = q.get(timeout=2.5)
            except queue.Empty:
                yield ': ping\n\n'
                continue
            if e.get('event') == '__end__':
                break
            yield 'data: %s\n\n' % _json.dumps(e, ensure_ascii=False, default=str)

    return StreamingResponse(gen(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache',
                                      'X-Accel-Buffering': 'no'})

@app.post('/api/agents/{name}/run')
def run_agent_api(name: str, req: AgentRunReq):
    """同步运行单个 Agent（重活建议走 chain 或任务队列）。"""
    from agents.runtime import load_all
    from agents.base import run_agent
    from agents.blackboard import AgentBoard
    load_all()
    if name not in __import__('agents.base', fromlist=['REGISTRY']).REGISTRY:
        raise HTTPException(status_code=404, detail='unknown agent: %s' % name)
    res = run_agent(name, req.params, board=AgentBoard(), task_id=req.task_id)
    return res.to_dict()


@app.post('/api/agents/chain')
def run_chain_api(req: AgentChainReq):
    """按序运行 Agent 链，支持 ${ctx.key} 引用上一步产物。"""
    from agents.runtime import run_chain
    return run_chain(req.steps, ctx=req.ctx, task_id=req.task_id)


@app.get('/api/tasks/{task_id}/trace')
def task_trace(task_id: str):
    """v11（原 v13）：任务的 agent 链执行轨迹（黑板 agent_runs）。"""
    from agents.blackboard import AgentBoard
    runs = AgentBoard().runs(task_id=task_id, limit=200)
    task = queue.get_task(task_id)
    return {'task_id': task_id,
            'task': {k: task.get(k) for k in ('status', 'stage', 'output', 'error')}
                    if task else None,
            'runs': runs}


@app.get('/api/logs/tail')
def logs_tail(name: str = Query('wan'), n: int = Query(200, ge=1, le=800)):
    """tail 服务日志（start_services 写 /tmp）：wan/flux/tts/api/h3/h3d/hunyuan。

    容器内宿主 /tmp 不存在 → 设 VIDANCE_LOG_PREFIX（如 /hostlogs）并挂载宿主 /tmp 只读；
    前缀路径与原路径谁存在读谁（宿主机不受影响）。
    """
    _map = {'wan': '/tmp/comfyui_8189.log', 'h3': '/tmp/comfyui_8188.log',
            'flux': '/tmp/comfyui_8192.log', 'hunyuan': '/tmp/comfyui_8190.log',
            'h3d': '/tmp/comfyui_8193.log', 'tts': '/tmp/tts_9880.log',
            'api': '/tmp/api_8894.log'}
    p = _map.get(name)
    if not p:
        raise HTTPException(status_code=400,
                            detail='用法: /api/logs/tail?name=wan|flux|tts|api|h3|h3d|hunyuan&n=200')
    pref = os.environ.get('VIDANCE_LOG_PREFIX', '')
    paths = [pref + p, p] if pref and pref != '/' else [p]
    for cand in paths:
        if os.path.isfile(cand):
            p = cand
            break
    else:
        return {'log': f'（{paths[0]} 不存在——服务可能未用 start_services 启动，或容器未挂载宿主 /tmp）',
                'path': paths[0]}
    try:
        with open(p, 'rb') as f:
            f.seek(0, 2)
            sz = f.tell()
            f.seek(max(0, sz - 400_000))
            data = f.read().decode('utf-8', 'ignore')
        return {'log': '\n'.join(data.splitlines()[-n:]), 'path': p}
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/agents/records')
def agent_records(limit: int = Query(40, ge=1, le=200)):
    """扫描 output 下现存运行目录（agent.log 或 meta.json），历史记录不依赖浏览器存储。

    覆盖三类目录：agent_<ts>_<name>（agent 链）、<时间戳>（pipeline 任务）、
    f<时间戳>（fast 链）。final 在本目录或一层子目录里找。
    """
    def _find_final(d):
        for f in ('final.mp4', 'final.mov', 'final.webm'):
            p = os.path.join(d, f)
            if os.path.isfile(p):
                return p
        try:
            for sub in sorted(os.listdir(d)):
                sd = os.path.join(d, sub)
                if os.path.isdir(sd):
                    for f in ('final.mp4', 'final.mov', 'final.webm'):
                        p = os.path.join(sd, f)
                        if os.path.isfile(p):
                            return p
        except OSError:
            pass
        return None

    def _meta(d):
        mp = os.path.join(d, 'meta.json')
        if os.path.isfile(mp):
            try:
                import json as _json
                return _json.loads(open(mp, encoding='utf-8', errors='ignore').read())
            except Exception:
                return {}
        return {}

    roots = [os.path.realpath(load_config().get('output_dir', 'output')),
             os.path.realpath(os.path.join(os.path.dirname(__file__), '..', 'output')),
             '/mnt/dataset/zxy/vidance/output']
    recs, seen = [], set()
    for oroot in dict.fromkeys(roots):
        if not os.path.isdir(oroot):
            continue
        for name in sorted(os.listdir(oroot)):
            if name in seen:
                continue
            d = os.path.join(oroot, name)
            if not os.path.isdir(d):
                continue
            lp = os.path.join(d, 'agent.log')
            meta = _meta(d)
            if not os.path.isfile(lp) and not meta:
                continue
            seen.add(name)
            ts_src = lp if os.path.isfile(lp) else os.path.join(d, 'meta.json')
            ts = int(os.path.getmtime(ts_src) * 1000)
            status, title, n_lines = 'done', name, 0
            if os.path.isfile(lp):
                try:
                    lines = [l.strip() for l in open(lp, encoding='utf-8', errors='ignore')
                             if l.strip()]
                except OSError:
                    lines = []
                n_lines = len(lines)
            if lines:
                start = next((l for l in lines if '▶' in l), lines[0])
                title = start[:60]
                mc = re.search(r'"(?:concept|prompt)"\s*:\s*"([^"]+)"', '\n'.join(lines))
                if mc:
                    title = mc.group(1)[:10]
                last = lines[-1]
                status = 'run'
                if '■' in last:
                    status = 'ok' if ' ok=True' in last else 'fail'
                elif '✗' in last:
                    status = 'fail'
            if status == 'done' and not _find_final(d):
                continue
            if meta.get('concept') and title == name:
                title = str(meta['concept'])[:60]
            recs.append({'task_id': name, 'ts': ts,
                         'title': title, 'status': status, 'n': n_lines,
                         'dir': d,
                         'final': _find_final(d)})
    recs.sort(key=lambda r: -r['ts'])
    return {'records': recs[:limit]}


@app.get('/api/agents/board')
def agents_board(task_id: str = '', limit: int = Query(50, ge=1, le=500)):
    """黑板记录：agent_runs 表（谁跑了、产物、评分、耗时）。"""
    from agents.blackboard import AgentBoard
    runs = AgentBoard().runs(task_id=task_id or None, limit=limit)
    live = [{'run_id': 'act:' + k, 'task_id': k, 'agent': v.get('kind', 'chain'),
             'ok': None, 'status': v.get('status'),
             'note': '%d/%d 步 · %ds' % (v.get('done', 0), v.get('steps', 0),
                                        int((v.get('t1') or time.time()) - v.get('t0', time.time()))),
             'ts': time.strftime('%Y-%m-%d %H:%M:%S',
                                 time.localtime(v.get('t0', time.time())))}
            for k, v in sorted(ACTIVE_RUNS.items(), key=lambda x: -x[1].get('t0', 0))]
    return {'runs': live + runs, 'live': len(live)}


# ── 静态前端 /ui ──
_UI_DIR = os.path.join(os.path.dirname(__file__), '..', 'ui')

if os.path.isdir(_UI_DIR):
    from fastapi.staticfiles import StaticFiles
    app.mount('/ui', StaticFiles(directory=_UI_DIR, html=True), name='ui')



@app.middleware('http')
async def _ui_no_cache(request, call_next):
    resp = await call_next(request)
    if request.url.path in ('/ui', '/ui/', '/ui/index.html', '/api/tools', '/api/commands'):
        resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.get('/ui')
def ui_index():
    """/ui 重定向到 index.html（未挂载时兜底）"""
    index = os.path.join(_UI_DIR, 'index.html')
    if os.path.exists(index):
        return FileResponse(index, media_type='text/html')
    raise HTTPException(status_code=404, detail='ui/index.html not found')


if __name__ == '__main__':
    import uvicorn

    parser = argparse.ArgumentParser(description='Vidance API Server')
    parser.add_argument('--host', default=os.environ.get('VIDANCE_HOST', '0.0.0.0'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('VIDANCE_PORT', 8894)))
    args = parser.parse_args()

    # 2026-09-29 日志轮转：api 日志由 start_services 重定向到 /tmp/api_{port}.log（fd 直写）。
    # 进程内 RotatingFileHandler 与 fd 双写同一文件会互相覆盖 → 用 copytruncate：
    # 每 5 min 检查，>10MB 时拷贝到 .1 并原地清空（fd O_APPEND 时安全，见 start_services append）。
    def _log_rotate_loop():
        path = f'/tmp/api_{args.port}.log'
        max_bytes = 10 * 1024 * 1024
        while True:
            time.sleep(300)
            try:
                same = (os.fstat(1).st_ino == os.stat(path).st_ino)
                if not same or os.path.getsize(path) <= max_bytes:
                    continue
                import shutil
                shutil.copyfile(path, path + '.1')
                os.truncate(path, 0)
                print(f'  [api] 日志轮转: {path} → {path}.1')
            except Exception:
                continue

    threading.Thread(target=_log_rotate_loop, daemon=True).start()

    print(f'  [api] starting on {args.host}:{args.port}')
    uvicorn.run(app, host=args.host, port=args.port, log_level='info')
