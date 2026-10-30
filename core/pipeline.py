#!/usr/bin/env python3
"""Vidance 流水线主控 — 角色一致性有声短片生成（内部模块）

推荐使用统一入口: python core/vidance.py auto ...

流程:
  concept → LLM编剧(含角色描述+camera角度) → 角色锚(FLUX生图→TripoSplat→3DGS / Hunyuan3Dv2→mesh)
  → 逐镜(FLUX背景→RenderSplat/mesh_render合成→Wan I2V + TTS + 抽帧) → 审片 → 合成
"""
import json
import os
import sys
import time
import random
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm import LLMClient
from utils.tts import TTSClient
from utils.comfy_api import ComfyClient
from utils.vendor import get_vendor
try:
    from utils.splat_renderer import render_splat_at_angle, render_splat_angles
    from utils.mesh_render import render_mesh_at_angle, render_mesh_angles
except ImportError:
    # 3D 渲染依赖（comfy/trimesh/pyrender）仅在 GPU 服务器上可用
    render_splat_at_angle = render_splat_angles = None
    render_mesh_at_angle = render_mesh_angles = None
from utils.hunyuan3d import Hunyuan3DClient
from utils.asset_registry import AssetRegistry
from utils.ffmpeg_tools import extract_frames, generate_srt, compose
from utils.rife import RIFEClient
from core.postprocess import PostProcessor

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'config.json')


def load_config():
    from utils.config_loader import load_config as _load
    return _load()


class Pipeline:
    def __init__(self, config=None):
        self.config = config or load_config()
        self.llm = LLMClient(self.config)
        self.tts = TTSClient(self.config)
        self.wan = ComfyClient(config=self.config, instance='wan')
        self.flux = ComfyClient(config=self.config, instance='flux')
        self.t2i_vendor = get_vendor(self.config, 't2i')
        self.i2v_vendor = get_vendor(self.config, 'i2v')
        self.t2v_vendor = get_vendor(self.config, 't2v')
        self.hunyuan3d = Hunyuan3DClient(config=self.config)
        self.assets = AssetRegistry(self.config)
        self.output_dir = self.config['output_dir']
        self.wan_defaults = self.config.get('wan_defaults', {})
        self.i2v_defaults = self.config.get('i2v_defaults', {})
        self.flux_defaults = self.config.get('flux_defaults', {})
        self.rife_config = self.config.get('rife', {})
        self.color_config = self.config.get('color', {})
        self.bgm_config = self.config.get('bgm', {})
        self.stt_config = self.config.get('stt', {})
        self.max_retries = 2
        self.review_mode = 'light'
        self._review_pool = ThreadPoolExecutor(max_workers=1)
        self._pending_review = None
        self._light_reviews = {}
        self.post = PostProcessor(self.config, llm=self.llm)
        self._rife_client = None
        self._board = None  # v11 黑板（M4 步进记录挂载点，懒加载）

    def _get_rife_client(self):
        """Lazy-init RIFE client for slowmo."""
        if self._rife_client is None:
            model = self.rife_config.get('model', 'rife_v4.26.safetensors')
            self._rife_client = RIFEClient(
                config=self.config, instance='wan', model_name=model)
        return self._rife_client

    # ── v17 M4 断点续跑（借鉴 MoneyPrinterTurbo task_dir 归拢 + 原子写）──
    @staticmethod
    def _save_ckpt(task_dir: str, patch: dict):
        """原子合并写 checkpoint.json（fsync + os.replace，崩溃不留半文件）"""
        import tempfile
        path = os.path.join(task_dir, 'checkpoint.json')
        data = {}
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = {}
        data.update(patch)
        data['updated_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        fd, tmp = tempfile.mkstemp(dir=task_dir, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    @staticmethod
    def _load_ckpt(task_dir: str) -> dict:
        path = os.path.join(task_dir, 'checkpoint.json')
        if not os.path.exists(path):
            return {}
        with open(path, encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def _sha256_file(path: str, chunk: int = 1 << 20) -> str:
        import hashlib
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for blk in iter(lambda: f.read(chunk), b''):
                h.update(blk)
        return h.hexdigest()

    @staticmethod
    def _fingerprint_clip(clip_info: dict) -> dict:
        """产物指纹：final_video + audio 的 sha256（文件缺失则跳过该键）"""
        fp = {}
        paths = {'final_video': clip_info.get('final_video'),
                 'audio_path': (clip_info.get('audio') or {}).get('audio_path')}
        for key, p in paths.items():
            if p and os.path.isfile(p):
                fp[key] = Pipeline._sha256_file(p)
        return fp

    def _board_log(self, task_id: str, stage: str, ok: bool = True,
                   artifacts: dict = None, error: str = None):
        """v17 M4：黑板挂载（agent_runs 步进记录），失败不阻塞流水线"""
        try:
            from agents.blackboard import AgentBoard
            if self._board is None:
                self._board = AgentBoard()
            self._board.log(task_id, 'pipeline', 'm4:%s' % stage, ok, None,
                            artifacts or {}, error, 0.0)
        except Exception:
            pass

    def run(self, concept: str, output_path: str = None,
            character_desc: str = None, voice: str = None,
            character_mode: str = 'auto', lut_override: str = None,
            bgm_override: str = None, use_stt: bool = False,
            target_duration: float = None,
            slowmo_override: int = None,
            no_asset_reuse: bool = False,
            task_id: str = None,
            resume: str = None,
            no_preflight: bool = False,
            style_hint: str = None,
            five_dim_guide: dict = None,
            style_pack: dict = None,
            rag_context: str = None) -> dict:
        """端到端生成有声短片

        character_mode:
          'auto' — 先试 3DGS，审查不过自动降级 flux（默认）
          '3dgs' — 强制 3DGS 角色锚（FLUX→TripoSplat→3DGS→RenderSplat→I2V）
          'mesh' — 强制 mesh 角色锚（FLUX→Hunyuan3Dv2→GLB→mesh_render→I2V）
          'flux' — 每镜 FLUX 直接生成角色+场景图做 I2V 参考（不重建 3D）
          不传 character_desc 时走 v0 纯 T2V
        target_duration: 目标总时长（秒），None 时默认 2-5 镜短片
        slowmo_override: 全局慢动作帧倍率，覆盖所有镜头（None 则用 LLM 标注）
        no_asset_reuse: True 时跳过资产库检索，强制重新重建 3D 资产
        task_id: 外部指定 task_id（调度器传入），None 时自动生成时间戳
        resume: v17 M4 断点续跑——传已有 task_id，从 checkpoint.json 恢复（跳过已完成阶段/镜头）
        five_dim_guide: M5a 五维提示词模板（SKILL/templates/ five_dim_guide 段），注入编剧
        style_pack: M6-S5 风格包（SKILL/templates/ style_pack 段）：锚点覆盖（style_anchor/
          color/lighting/mood 优先于 LLM 生成）+ character_sheet 四视图风格词
        rag_context: M5b RAG 检索的参考资料文本（--rag-doc 文档片段），注入编剧
        """
        resumed_from = None
        if resume:
            resumed_from = resume
            task_id = resume
            task_dir = os.path.join(self.output_dir, task_id)
            if not os.path.isdir(task_dir):
                raise FileNotFoundError(f'resume: 任务目录不存在: {task_dir}')
            ckpt = self._load_ckpt(task_dir)
            if not ckpt:
                raise ValueError(f'resume: {task_dir} 无 checkpoint.json（旧任务或从未跑过阶段 1）')
            concept = ckpt.get('concept') or concept
            character_desc = ckpt.get('character_desc') or character_desc
            print(f'[resume] {task_id} · 已完成阶段: {[k for k in ("script", "prompts", "character") if ckpt.get(k)]} · 已完成镜头: {len(ckpt.get("clips", []))}')
        else:
            if task_id is None:
                from agents.common.tools.config_loader import task_id_for
                task_id = task_id_for('auto')
        self._task_id = task_id
        task_dir = os.path.join(self.output_dir, task_id)
        clips_dir = os.path.join(task_dir, 'clips')
        char_dir = os.path.join(task_dir, 'character')
        os.makedirs(clips_dir, exist_ok=True)
        os.makedirs(char_dir, exist_ok=True)

        # preflight 预检（MPT 式 fail-fast：硬依赖挂直接拦，可降级依赖只警示）
        from core.preflight import Preflight
        Preflight(self.config).check('auto', character=character_desc, skip=no_preflight)

        meta = {
            'task_id': task_id,
            'concept': concept,
            'character_desc': character_desc,
            'character_mode': character_mode if character_desc else None,
            'voice': voice,
            'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'status': 'running',
            'clips': [],
        }
        if resumed_from:
            meta['resumed_from'] = resumed_from

        print(f'[{task_id}] concept: {concept}')
        if character_desc:
            print(f'  character: {character_desc}')
            print(f'  character_mode: {character_mode}')

        # 审片模式：none/light 不重试（light=抽1帧问1句·与下一镜生成并行）
        self._pending_review = None
        self._light_reviews = {}
        if self.review_mode in ('none', 'light'):
            self.max_retries = 0
        # ── 1. 编剧 ──
        print('\n=== [1] 编剧 ===')
        ckpt = self._load_ckpt(task_dir) if resumed_from else {}
        if resumed_from and ckpt.get('script'):
            script = ckpt['script']
            print(f'  [resume] 跳过编剧（{len(script["shots"])} 镜已缓存）')
        else:
            script = self.llm.script_write(concept, character_desc=character_desc,
                                            target_duration=target_duration,
                                            style_hint=style_hint,
                                            five_dim_guide=five_dim_guide,
                                            rag_context=rag_context)
        # ── 1.5 一致性锚点（M6.1，BigBanana consistencyAnchors）──
        # 结构守卫：编剧产物必须含 shots（LLM 回喂重问后仍缺则明确报错）
        if not script.get('shots'):
            raise RuntimeError('编剧产物缺 shots（LLM 输出不合规），请重试或换概念')
        script.setdefault('title', script.get('concept', 'untitled'))
        # M6-S5：风格包锚点优先（模板定义的"美学基因"直接覆盖 LLM 生成）
        anchors = (ckpt.get('anchors') if resumed_from else None) or {}
        if not anchors:
            anchors = self.llm.consistency_anchors(script)  # 失败返回 {}，非致命
            if anchors:
                print(f'  anchors: {str(anchors.get("style_anchor", ""))[:70]}...')
            merged = self._merge_style_pack_anchors(anchors, style_pack)
            if merged != anchors:
                print('  anchors: <style_pack override>')
                sp = (style_pack or {}).get('style_pack') or {}
                if sp.get('style_anchor'):
                    script['style'] = sp['style_anchor']  # 风格域同步，避免 script.style 与锚点打架
            anchors = merged
        self._style_pack = style_pack or {}
        self._anchors = anchors
        meta['anchors'] = anchors
        self._save_ckpt(task_dir, {'concept': concept, 'character_desc': character_desc,
                                   'target_duration': target_duration, 'script': script,
                                   'anchors': anchors})
        self._board_log(task_id, 'script', True, {'shots': len(script['shots'])})
        print(f'  title: {script["title"]}')
        print(f'  shots: {len(script["shots"])}')
        self._log('▸ [1] 编剧完成: %s · %d 镜 · review=%s' % (
            script.get('title', ''), len(script['shots']), self.review_mode))

        # 如果 LLM 生成了 character.desc 但用户没提供，用 LLM 的
        if not character_desc and 'character' in script:
            character_desc = script['character']['desc']
            meta['character_desc'] = character_desc
            print(f'  character (from LLM): {character_desc}')

        # ── 2. prompt 优化 ──
        print('\n=== [2] prompt 优化 ===')
        style = script.get('style', '')

        # 角色prompt
        character_prompt = None
        if character_desc:
            character_prompt = self.llm.optimize_character_prompt(character_desc)
            script.setdefault('character', {})['prompt'] = character_prompt
            print(f'  character_prompt: {character_prompt[:80]}...')

        # 每镜 video_prompt + background_prompt
        ckpt = self._load_ckpt(task_dir)
        if resumed_from and ckpt.get('prompts_done') and all(
                s.get('video_prompt') for s in script['shots']):
            print('  [resume] 跳过 prompt 优化（已缓存）')
        else:
            for shot in script['shots']:
                shot['style'] = style
                shot['video_prompt'] = self.llm.optimize_prompt(
                    shot['scene_desc'], style, five_dim=shot.get('five_dim'),
                    ref_frame=bool(character_desc),
                    anchors=self._anchors or None)
                bg_desc = shot.get('background_desc', shot['scene_desc'])
                shot['background_prompt'] = self.llm.optimize_background_prompt(
                    bg_desc, style, anchors=self._anchors or None)
                print(f'  shot {shot["id"]}: video={shot["video_prompt"][:50]}...')
                print(f'           bg={shot["background_prompt"][:50]}...')
            self._save_ckpt(task_dir, {'prompts_done': True, 'script': script})
            self._board_log(task_id, 'prompts', True, {'shots': len(script['shots'])})

        # ── 3. 角色锚阶段 ──
        character = None
        ckpt = self._load_ckpt(task_dir)
        if resumed_from and ckpt.get('character'):
            character = ckpt['character']
            print(f'  [resume] 跳过角色锚（mode={character.get("mode")} 已缓存）')
        elif character_prompt:
            print(f'\n=== [3] 角色锚阶段 (mode={character_mode}) ===')
            character = self._build_character_anchor(
                character_prompt, char_dir, task_id, character_mode,
                character_desc=character_desc,
                no_asset_reuse=no_asset_reuse,
            )
            character['desc'] = character_desc
            character['prompt_en'] = character_prompt
            meta['character'] = character
            self._save_ckpt(task_dir, {'character': character})
            self._board_log(task_id, 'character', True, {'mode': character.get('mode')})

            if character['mode'] in ('3dgs', 'mesh') and not character.get('review', {}).get('pass', False):
                if character_mode == 'auto':
                    print(f'  ⚠ {character["mode"].upper()} 审查未通过 (score={character["review"]["score"]})，自动降级 flux 模式')
                    character['mode'] = 'flux'
                    meta['character_mode'] = 'flux (auto-downgraded)'
                else:
                    print(f'  ⚠ {character["mode"].upper()} 审查未通过 (score={character["review"]["score"]})，继续 {character["mode"]} 模式')

        # ── 4. 逐镜生成 ──
        all_clips = []
        all_audios = []
        all_timestamps = []
        audio_offset = 0.0

        # 4a. 并行预取：FLUX 参考帧 + TTS 配音（与 Wan I2V 独立）
        i2v_w = self.i2v_defaults.get('width', 832)
        i2v_h = self.i2v_defaults.get('height', 480)
        bg_w = self.flux_defaults.get('background_width', i2v_w)
        bg_h = self.flux_defaults.get('background_height', i2v_h)

        # v17 M4：resume 时恢复已完成镜头（final_video 健在才复用，否则重做）
        ckpt = self._load_ckpt(task_dir)
        done_clips = {}
        if resumed_from:
            for ci in ckpt.get('clips', []):
                fv = ci.get('final_video')
                ap = (ci.get('audio') or {}).get('audio_path')
                if not (fv and os.path.isfile(fv) and ap and os.path.isfile(ap)):
                    print(f'  [resume] clip shot {ci.get("shot_id")} 文件缺失，将重做')
                    continue
                # 产物指纹校验（旧 checkpoint 无 sha256 字段则跳过，向后兼容）
                fp = ci.get('sha256') or {}
                mismatch = [k for k, want in fp.items()
                            if want and self._sha256_file(fv if k == 'final_video' else ap) != want]
                if mismatch:
                    print(f'  [resume] clip shot {ci.get("shot_id")} 指纹不符({",".join(mismatch)})，将重做')
                    continue
                done_clips[ci['shot_id']] = ci
            if done_clips:
                print(f'  [resume] 复用 {len(done_clips)} 个已完成镜头')
            self._board_log(task_id, 'resume', True, {
                'reused_clips': len(done_clips),
                'stages': [k for k in ('script', 'prompts', 'character') if ckpt.get(k)],
            })

        to_prefetch = [s for s in script['shots'] if s['id'] not in done_clips]
        prefetched = self._prefetch_shots(
            to_prefetch, character, clips_dir, task_id,
            voice, i2v_w, i2v_h, bg_w, bg_h,
        ) if to_prefetch else {}

        for shot in script['shots']:
            sid = shot['id']
            if sid in done_clips:
                clip_info = done_clips[sid]
                print(f'\n=== [4] shot {sid} 已完成（resume 复用）===')
            else:
                print(f'\n=== [4] shot {sid} 生成 ===')
                self._log('▸ [4] shot %s 生成' % sid)
                clip_info = self._process_shot(
                    shot, clips_dir, task_id, character, voice,
                    prefetched=prefetched.get(sid),
                    slowmo_override=slowmo_override,
                )
                clip_info['sha256'] = self._fingerprint_clip(clip_info)
                self._board_log(task_id, 'clip:%s' % sid, True,
                                {'final_video': clip_info.get('final_video')})
                # 替换同 shot 旧条目（防 resume 重做后 checkpoint 留含旧 sha 的重复项）
                clips = [c for c in self._load_ckpt(task_dir).get('clips', [])
                         if c.get('shot_id') != sid]
                self._save_ckpt(task_dir, {'clips': clips + [clip_info]})
            meta['clips'].append(clip_info)
            all_clips.append(clip_info['final_video'])
            all_audios.append(clip_info['audio']['audio_path'])
            for ts in clip_info['audio']['timestamps']:
                all_timestamps.append({
                    'text': ts['text'],
                    'start': round(ts['start'] + audio_offset, 3),
                    'end': round(ts['end'] + audio_offset, 3),
                    'duration': ts['duration'],
                })
            audio_offset += clip_info['audio']['duration']

        # 收集最后一镜的并行审片结果，回填真实分数
        self._collect_light_review()
        for ci in meta.get('clips', []):
            rev = self._light_reviews.get(ci.get('shot_id'))
            if rev:
                ci['final_score'] = rev.get('score')
                ci['review_light'] = rev
        self._review_pool.shutdown(wait=False)

        # ── 4.5 RIFE 镜头间过渡 ──
        transition_clips = []
        transition_types = []
        if self.rife_config.get('enabled', False) and len(all_clips) >= 2:
            print(f'\n=== [4.5] RIFE 镜头间过渡 ===')
            for shot in script['shots'][:-1]:
                transition_types.append(shot.get('transition_out', 'rife'))
            print(f'  transition types: {transition_types}')
            transition_clips = self.post.generate_transitions(
                all_clips, clips_dir, task_id, transition_types=transition_types)

        # ── 5. 合成 ──
        print('\n=== [5] 合成 ===')
        self._log('▸ [5] 合成 compose: %d 镜' % len(all_clips))
        if output_path is None:
            output_path = os.path.join(task_dir, 'final.mp4')

        srt_path = os.path.join(task_dir, 'subtitle.srt')
        generate_srt(all_timestamps, srt_path)

        # ── 5.5 调色 ──
        lut_path = None
        if self.color_config.get('enabled', False) or lut_override:
            print(f'\n=== [5.5] 调色 ===')
            lut_path = self.post.select_lut(concept, script, task_dir, lut_override)
            if lut_path:
                print(f'  LUT: {os.path.basename(lut_path)}')

        # ── 5.6 配乐 ──
        bgm_path = None
        if self.bgm_config.get('enabled', False) or bgm_override:
            print(f'\n=== [5.6] 配乐 ===')
            total_duration = audio_offset + 2.0
            bgm_path = self.post.select_bgm(concept, script, task_dir, total_duration, bgm_override)
            if bgm_path:
                print(f'  BGM: {os.path.basename(bgm_path)}')

        # 当 use_stt 时，compose 不烧字幕（留给 STT 步骤统一烧录，避免双重字幕）
        compose_srt = None if use_stt else srt_path

        compose(
            clips=all_clips,
            audio_paths=all_audios,
            srt_path=compose_srt,
            output_path=output_path,
            transition='cut' if transition_clips else 'crossfade',
            transition_duration=0.3,
            transition_clips=transition_clips or None,
            transition_types=transition_types or None,
            lut_path=lut_path,
            bgm_path=bgm_path,
            bgm_volume=self.bgm_config.get('volume', 0.3),
        )

        # ── 5.7 STT 字幕兜底 ──
        if self.stt_config.get('enabled', False) or use_stt:
            print(f'\n=== [5.7] STT 字幕对齐 ===')
            narration_text = '\n'.join(shot.get('narration', '') for shot in (script or []))
            stt_srt = self.post.run_stt(output_path, task_dir, script_text=narration_text or None)
            if stt_srt:
                srt_path = stt_srt
                print(f'  STT SRT: {stt_srt}')
            else:
                # STT 失败：fallback 烧录 TTS 字幕
                print(f'  ⚠ STT 失败，回退烧录 TTS 字幕: {srt_path}')
                self.post.burn_subtitles(output_path, srt_path)

        meta['output'] = output_path
        meta['srt'] = srt_path
        meta['lut'] = lut_path
        meta['bgm'] = bgm_path
        meta['status'] = 'completed'

        # v17 M4：终态落盘（幂等重入标记）+ 黑板 done 记录
        self._save_ckpt(task_dir, {'done': True, 'output': output_path})
        self._board_log(task_id, 'done', True, {'output': output_path})

        meta_path = os.path.join(task_dir, 'meta.json')
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        print(f'\n=== 完成 ===')
        print(f'  成片: {output_path}')
        self._log('■ 成片: %s' % output_path)
        print(f'  元数据: {meta_path}')
        return meta

    @staticmethod
    def _default_review(score=7, feedback='Review unavailable, auto-pass'):
        return {'score': score, 'dimensions': {}, 'feedback': feedback, 'pass': score >= 7}

    def _log(self, msg):
        """明细日志：追加 output/{tid}/agent.log（有 tasklog 上下文时）。"""
        try:
            from utils.tasklog import log as _tlog
            _tlog(msg, self.output_dir)
        except Exception:
            pass

    def _light_review(self, scene_desc, frames, char_ref=None):
        """轻度审片：抽 1 帧问 LLM 一次"与描述像不像"（1 维 1 问，快）。"""
        try:
            system = (
                '你是审片助手。根据给定的场景描述，判断这张视频帧与描述是否相符。\n'
                '只输出JSON：{"score": 8, "pass": true, "reason": "一句话"}\n'
                'score为1-10整数（画面与描述的匹配度），≥6为pass。不必评画质细节。'
            )
            content = [{'type': 'text',
                        'text': '场景描述：%s\n判断该帧与描述的匹配度。' % scene_desc}]
            if char_ref:
                content.append({'type': 'image_url',
                                'image_url': {'url': self.llm._image_to_base64(char_ref)}})
            for path in frames[:1]:
                content.append({'type': 'image_url',
                                'image_url': {'url': self.llm._image_to_base64(path)}})
            messages = [{'role': 'system', 'content': system},
                        {'role': 'user', 'content': content}]
            r = self.llm.chat_json(messages, model=self.llm.models.get('review'),
                                   temperature=0.1, timeout=60, retries=1)
            if isinstance(r, dict):
                r.setdefault('score', 7)
                r.setdefault('pass', float(r.get('score', 7)) >= 6)
                r.setdefault('feedback', r.get('reason', ''))
            return r
        except Exception as e:
            return self._default_review(score=7, feedback='light review error: %s' % e)

    def _collect_light_review(self):
        """收集上一镜的并行轻度审片结果（生成等待期它已在后台跑）。"""
        pr = self._pending_review
        if not pr:
            return None
        sid, fut = pr
        try:
            rev = fut.result(timeout=300)
        except Exception as e:
            rev = self._default_review(score=7, feedback='light review error: %s' % e)
        warn = '' if rev.get('pass') else ' ⚠ 未过(不重试): %s' % str(rev.get('feedback', ''))[:60]
        self._log('▸ shot %s 审片(light): score=%s pass=%s%s' % (
            sid, rev.get('score'), rev.get('pass'), warn))
        self._light_reviews[sid] = rev
        self._pending_review = None
        return sid, rev

    def _safe_review_character(self, ref_path, preview_paths):
        try:
            return self.llm.review_character(ref_path, preview_paths)
        except Exception as e:
            print(f'  ⚠ review_character failed: {e}')
            return self._default_review(score=5, feedback=f'Review error: {e}')

    def _safe_review_shot(self, scene_desc, frame_paths, char_ref=None):
        ens = (self.config.get('review') or {}).get('ensemble') or {}
        if ens.get('enabled'):
            try:
                from agents.base import run_agent
                res = run_agent('audit.review_ensemble', {
                    'scene_desc': scene_desc, 'frame_paths': frame_paths,
                    'models': ens.get('models'), 'char_ref': char_ref},
                    task_id=getattr(self, '_task_id', 'pipeline'))
                if res.ok:
                    votes = res.artifacts.get('votes', [])
                    fb = ' | '.join(str(v.get('feedback') or v.get('error') or '')[:120]
                                    for v in votes)
                    return {'score': round((res.score or 0) * 10, 1), 'dimensions': {},
                            'feedback': fb, 'pass': bool(res.artifacts.get('passed')),
                            'ensemble': votes}
                print('  ⚠ ensemble 全票失败，回退单票')
            except Exception as e:
                print(f'  ⚠ review_ensemble failed: {e}')
        try:
            return self.llm.review_shot(scene_desc, frame_paths, character_ref=char_ref)
        except Exception as e:
            print(f'  ⚠ review_shot failed: {e}')
            return self._default_review(score=7, feedback=f'Review error: {e}')

    def _build_character_anchor(self, character_prompt: str, char_dir: str,
                                task_id: str, mode: str = 'auto',
                                character_desc: str = None,
                                no_asset_reuse: bool = False) -> dict:
        """角色锚阶段

        mode='flux': 只生成 FLUX 角色参考图（不重建 3D）
        mode='3dgs'/'auto': FLUX生图 → TripoSplat→3DGS → 多角度预览审查
        mode='mesh': FLUX生图 → Hunyuan3Dv2→GLB → mesh_render 多角度预览审查

        资产复用：若 mode 为 mesh/3dgs 且资产库有匹配角色（quality_score≥7），跳过重建。
        no_asset_reuse=True 时跳过资产库检索。
        """
        # [3-pre] 资产库检索
        if not no_asset_reuse and mode in ('mesh', '3dgs') and character_desc:
            path_filter = 'mesh' if mode == 'mesh' else '3dgs'
            match = self.assets.find_character(character_desc, min_similarity=0.6,
                                               path_filter=path_filter)
            if match and match.get('quality_score', 0) >= 7:
                print(f'  [3-pre] 资产库命中: {match["id"]} (score={match["quality_score"]})')
                glb = match.get('glb')
                splat = match.get('splat')
                ref = match.get('ref_image')
                if mode == 'mesh' and glb and os.path.exists(glb):
                    preview_dir = os.path.join(char_dir, 'previews')
                    preview_paths = render_mesh_angles(
                        glb, angles=4, output_dir=preview_dir,
                        size=512, pitch=15.0, texture_image=ref,
                    )
                    return {
                        'ref_image': ref, 'glb_path': glb,
                        'preview_angles': preview_paths,
                        'review': {'score': match['quality_score'], 'pass': True,
                                   'feedback': f'Reused asset: {match["id"]}'},
                        'mode': 'mesh', 'asset_id': match['id'],
                    }
                elif mode == '3dgs' and splat and os.path.exists(splat):
                    preview_dir = os.path.join(char_dir, 'previews')
                    preview_paths = render_splat_angles(
                        splat, angles=4, output_dir=preview_dir,
                        size=512, pitch=15.0,
                    )
                    return {
                        'ref_image': ref, 'ply_path': splat,
                        'preview_angles': preview_paths,
                        'review': {'score': match['quality_score'], 'pass': True,
                                   'feedback': f'Reused asset: {match["id"]}'},
                        'mode': '3dgs', 'asset_id': match['id'],
                    }

        # [3a] FLUX 生成角色参考图（M6-S3：四视图设定图单图=身份锚，失败回退单视图）
        # M6-S6b 启动自愈（Toonflow fixDB 思路）：文件在即资产有效，resume 跳过再生
        ref_path = os.path.join(char_dir, 'character_ref.png')
        char_size = self.flux_defaults.get('character_size', 1024)
        if os.path.exists(ref_path) and os.path.getsize(ref_path) > 10240:
            print(f'  [3a] character_ref 已存在（resume 自愈检查通过），跳过再生')
            if mode == 'flux':
                return {
                    'ref_image': ref_path,
                    'mode': 'flux',
                    'review': {'score': 10, 'pass': True, 'feedback': 'resumed, ref exists'},
                }
        print('  [3a] FLUX 生成角色四视图设定图...')
        try:
            char_prompt = self.llm.optimize_character_turnaround_prompt(character_desc)
            sheet_terms = self._pack_terms()
            if sheet_terms:
                char_prompt = char_prompt.rstrip('. ') + '. ' + sheet_terms
        except Exception:
            char_prompt = character_prompt
        self.t2i_vendor.t2i(
            prompt=char_prompt,
            width=char_size, height=char_size,
            steps=self.flux_defaults.get('steps', 20),
            guidance=self.flux_defaults.get('guidance', 3.5),
            output_path=ref_path,
        )
        print(f'  ref_image: {ref_path}')

        if mode == 'flux':
            return {
                'ref_image': ref_path,
                'mode': 'flux',
                'review': {'score': 10, 'pass': True, 'feedback': 'flux mode, no 3DGS'},
            }

        if mode == 'mesh':
            # [3b-mesh] FLUX 生成三视图 → Hunyuan3Dv2 multiview → GLB mesh
            print('  [3b] FLUX 三视图 + Hunyuan3Dv2 multiview → GLB...')
            view_prompts = self.llm.optimize_character_multiview_prompts(character_desc)
            view_paths = {}
            for view_name in ('front', 'left', 'back'):
                vp = os.path.join(char_dir, f'character_{view_name}.png')
                self.t2i_vendor.t2i(
                    prompt=view_prompts[view_name],
                    width=char_size, height=char_size,
                    steps=self.flux_defaults.get('steps', 20),
                    guidance=self.flux_defaults.get('guidance', 3.5),
                    output_path=vp,
                )
                view_paths[view_name] = vp
                print(f'    {view_name}: {vp}')

            glb_path = os.path.join(char_dir, 'character.glb')
            self.hunyuan3d.generate_multiview(
                front_path=view_paths['front'],
                left_path=view_paths['left'],
                back_path=view_paths['back'],
                filename_prefix=f'{task_id}/character_mesh',
                output_path=glb_path,
            )
            print(f'  glb: {glb_path}')

            # [3c-mesh] mesh_render 多角度预览审查
            print('  [3c] 渲染多角度预览...')
            preview_dir = os.path.join(char_dir, 'previews')
            preview_paths = render_mesh_angles(
                glb_path, angles=4, output_dir=preview_dir,
                size=512, pitch=15.0, texture_image=ref_path,
            )
            print(f'  previews: {len(preview_paths)} angles')

            review = self._safe_review_character(ref_path, preview_paths)
            print(f'  review: score={review["score"]}, pass={review["pass"]}')
            if not review['pass']:
                print(f'    feedback: {review["feedback"][:80]}')

            # [3d-mesh] 资产入库
            if character_desc and review['score'] >= 7:
                asset_id = character_desc[:20].replace(' ', '_')
                try:
                    self.assets.register_character(
                        id=asset_id, desc=character_desc, path='mesh',
                        glb_path=glb_path, ref_image=ref_path,
                        quality_score=review['score'],
                    )
                    print(f'  [3d] 资产入库: {asset_id}')
                except Exception as e:
                    print(f'  [3d] 资产入库失败: {e}')

            return {
                'ref_image': ref_path,
                'glb_path': glb_path,
                'preview_angles': preview_paths,
                'review': review,
                'mode': 'mesh',
            }

        # [3b] TripoSplat 单图 → 3DGS (.ply)
        print('  [3b] TripoSplat → 3DGS...')
        ply_path = os.path.join(char_dir, 'character.ply')
        self.flux.generate_tripsplat(
            image_path=ref_path,
            filename_prefix=f'{task_id}/character',
            output_path=ply_path,
        )
        print(f'  ply: {ply_path}')

        # [3c] 多角度预览审查
        print('  [3c] 渲染多角度预览...')
        preview_dir = os.path.join(char_dir, 'previews')
        preview_paths = render_splat_angles(
            ply_path, angles=4, output_dir=preview_dir,
            size=512, pitch=15.0,
        )
        print(f'  previews: {len(preview_paths)} angles')

        review = self._safe_review_character(ref_path, preview_paths)
        print(f'  review: score={review["score"]}, pass={review["pass"]}')
        if not review['pass']:
            print(f'    feedback: {review["feedback"][:80]}')

        # [3d-3dgs] 资产入库
        if character_desc and review['score'] >= 7:
            asset_id = character_desc[:20].replace(' ', '_')
            try:
                self.assets.register_character(
                    id=asset_id, desc=character_desc, path='3dgs',
                    splat_path=ply_path, ref_image=ref_path,
                    quality_score=review['score'],
                )
                print(f'  [3d] 资产入库: {asset_id}')
            except Exception as e:
                print(f'  [3d] 资产入库失败: {e}')

        return {
            'ref_image': ref_path,
            'ply_path': ply_path,
            'preview_angles': preview_paths,
            'review': review,
            'mode': '3dgs',
        }

    def _generate_scene_ref(self, shot: dict, character: dict, clips_dir: str,
                            task_id: str, i2v_w: int, i2v_h: int,
                            bg_w: int, bg_h: int) -> str:
        """生成镜头参考帧（FLUX 场景图 / 3DGS 合成图 / mesh 合成图）。可并行调用。"""
        sid = shot['id']
        camera = shot.get('camera', {})
        yaw = camera.get('yaw', 0)
        pitch = camera.get('pitch', 15)
        fov = camera.get('fov', 35)

        char_mode = character.get('mode', '3dgs')
        use_flux_ref = (char_mode == 'flux')
        use_mesh_ref = (char_mode == 'mesh')

        if use_flux_ref:
            scene_prompt = self.llm.optimize_scene_prompt(
                character.get('prompt_en') or character['desc'],
                shot['scene_desc'], shot.get('style', ''),
                anchors=getattr(self, '_anchors', None) or None
            )
            composite_ref = os.path.join(clips_dir, f'composite_ref_{sid}.png')
            self.t2i_vendor.t2i(
                prompt=scene_prompt,
                seed=random.randint(0, 2**31 - 1),
                width=i2v_w, height=i2v_h,
                steps=self.flux_defaults.get('steps', 20),
                guidance=self.flux_defaults.get('guidance', 3.5),
                output_path=composite_ref,
            )
            print(f'  [prefetch] scene_ref (flux, yaw={yaw}): {sid}')
            return composite_ref
        else:
            bg_path = os.path.join(clips_dir, f'background_{sid}.png')
            self.t2i_vendor.t2i(
                prompt=shot['background_prompt'],
                seed=random.randint(0, 2**31 - 1),
                width=bg_w, height=bg_h,
                steps=self.flux_defaults.get('steps', 20),
                guidance=self.flux_defaults.get('guidance', 3.5),
                output_path=bg_path,
            )
            composite_ref = os.path.join(clips_dir, f'composite_ref_{sid}.png')
            if use_mesh_ref:
                render_mesh_at_angle(
                    glb_path=character['glb_path'],
                    yaw=yaw, pitch=pitch,
                    output_path=composite_ref,
                    bg_image=bg_path,
                    width=i2v_w, height=i2v_h,
                    fov=fov,
                    texture_image=character.get('ref_image'),
                )
                print(f'  [prefetch] composite_ref (mesh, yaw={yaw}): {sid}')
            else:
                render_splat_at_angle(
                    ply_path=character['ply_path'],
                    yaw=yaw, pitch=pitch,
                    output_path=composite_ref,
                    bg_image=bg_path,
                    width=i2v_w, height=i2v_h,
                    fov=fov,
                )
                print(f'  [prefetch] composite_ref (3dgs, yaw={yaw}): {sid}')
            return composite_ref

    @staticmethod
    def _merge_style_pack_anchors(anchors: dict, style_pack: dict) -> dict:
        """M6-S5：风格包锚点覆盖（style_pack 段四键优先于 LLM 生成锚点）。

        兼容两种入参形状：{'style_pack': {...}} 包装形 或 直接 {...} 内层形。
        """
        if not style_pack:
            return anchors
        sp = style_pack.get('style_pack') if 'style_pack' in style_pack else style_pack
        sp = sp or {}
        out = dict(anchors or {})
        for k in ('style_anchor', 'color', 'lighting', 'mood'):
            if sp.get(k):
                out[k] = sp[k]
        return out

    def _pack_terms(self) -> str:
        """S5：风格包 character_sheet 追加词（四视图 prompt 用）。"""
        sp = (getattr(self, '_style_pack', None) or {})
        sp = sp.get('style_pack') if 'style_pack' in sp else sp
        return (sp or {}).get('character_sheet') or ''

    def _shot_voice(self, shot: dict, voice: str) -> str:
        """S6a 音色资产绑定（Toonflow o_assetsRole2Audio 思路）：
        分镜 speaker 为角色名时路由到该角色绑定的音色（config tts.voice_map），
        未配置则回退全局 voice。旁白镜头用全局 voice。"""
        speaker = (shot.get('speaker') or '').strip()
        if not speaker or speaker == '旁白':
            return voice
        vmap = (self.config.get('tts') or {}).get('voice_map') or {}
        v = vmap.get(speaker)
        if v:
            print(f'  [voice] {speaker} → {v}')
        return v or voice

    def _generate_tts(self, shot: dict, clips_dir: str, voice: str) -> dict:
        """生成镜头配音。可并行调用。"""
        sid = shot['id']
        audio_path = os.path.join(clips_dir, f'shot_{sid}.wav')
        tts_result = self.tts.synthesize(
            text=shot['narration'],
            output_path=audio_path,
            voice=self._shot_voice(shot, voice),
        )
        print(f'  [prefetch] tts: shot {sid} ({tts_result["duration"]:.1f}s)')
        return {
            'audio_path': audio_path,
            'duration': tts_result['duration'],
            'timestamps': tts_result['timestamps'],
        }

    def _process_shot(self, shot: dict, clips_dir: str, task_id: str,
                      character: dict = None, voice: str = None,
                      prefetched: dict = None,
                      slowmo_override: int = None) -> dict:
        """处理单个镜头：背景生成 → 合成参考帧 → I2V + TTS + 抽帧 + 审片 + 重试

        Args:
            prefetched: 预取数据 {'composite_ref': str, 'audio': dict} 或 None
            slowmo_override: 全局慢动作帧倍率，覆盖 LLM 标注
        """
        sid = shot['id']
        duration = shot.get('duration', 5)
        fps = self.i2v_defaults.get('fps', 24)
        length = int(duration * fps)
        i2v_w = self.i2v_defaults.get('width', 832)
        i2v_h = self.i2v_defaults.get('height', 480)
        bg_w = self.flux_defaults.get('background_width', i2v_w)
        bg_h = self.flux_defaults.get('background_height', i2v_h)

        camera = shot.get('camera', {})

        attempts = []
        best = None

        for attempt in range(1, self.max_retries + 2):
            seed = random.randint(0, 2**32 - 1)
            video_prefix = f'{task_id}/shot_{sid}'
            video_path = os.path.join(clips_dir, f'shot_{sid}.mp4')
            if attempt > 1:
                video_path = os.path.join(clips_dir, f'shot_{sid}_v{attempt}.mp4')

            print(f'  attempt {attempt}, seed={seed}, length={length}')
            self._log('▸ shot %s attempt %d seed=%d len=%d帧 | %s' % (
                sid, attempt, seed, length, str(shot.get('video_prompt', ''))[:48]))

            # 参考帧生成（首次尝试用预取数据，重试时重新生成）
            composite_ref = None
            if character:
                if attempt == 1 and prefetched and prefetched.get('composite_ref'):
                    composite_ref = prefetched['composite_ref']
                    print(f'  [prefetched] composite_ref: {composite_ref}')
                else:
                    composite_ref = self._generate_scene_ref(
                        shot, character, clips_dir, task_id,
                        i2v_w, i2v_h, bg_w, bg_h,
                    )

            # [8] Wan I2V (或 T2V fallback)
            if composite_ref:
                t2v_result = self.i2v_vendor.i2v(
                    prompt=shot['video_prompt'],
                    image_path=composite_ref,
                    seed=seed,
                    width=i2v_w, height=i2v_h,
                    length=length,
                    steps=self.i2v_defaults.get('steps', 20),
                    cfg=self.i2v_defaults.get('cfg', 5.0),
                    fps=fps,
                    output_path=video_path,
                )
            else:
                t2v_result = self.t2v_vendor.t2v(
                    prompt=shot['video_prompt'],
                    seed=seed,
                    width=self.wan_defaults.get('width', 1280),
                    height=self.wan_defaults.get('height', 704),
                    length=length,
                    steps=self.wan_defaults.get('steps', 20),
                    cfg=self.wan_defaults.get('cfg', 5.0),
                    fps=fps,
                    output_path=video_path,
                )
            print(f'  video: {video_path}')
            self._log('▸ shot %s 生成完成: %s' % (sid, os.path.basename(video_path)))

            # [9] TTS（首次尝试用预取数据）
            if attempt == 1 and prefetched and prefetched.get('audio'):
                audio_info = prefetched['audio']
                audio_path = audio_info['audio_path']
                tts_result = {
                    'duration': audio_info['duration'],
                    'timestamps': audio_info['timestamps'],
                }
                print(f'  [prefetched] audio: {audio_path} ({tts_result["duration"]:.1f}s)')
            else:
                audio_path = os.path.join(clips_dir, f'shot_{sid}.wav')
                tts_result = self.tts.synthesize(
                    text=shot['narration'],
                    output_path=audio_path,
                    voice=voice,
                )
                print(f'  audio: {audio_path} ({tts_result["duration"]:.1f}s)')

            # 抽帧
            frames = extract_frames(video_path, n_frames=1,
                                    output_dir=os.path.join(clips_dir, 'frames'))
            print(f'  frames: {len(frames)}')

            # 审片（none=不审 / light=抽1帧问1句·与下一镜生成并行 / full=多维同步+重试）
            char_ref = character['ref_image'] if character else None
            if self.review_mode == 'none':
                review = self._default_review(score=10, feedback='review off (none)')
            elif self.review_mode == 'light':
                self._collect_light_review()
                fut = self._review_pool.submit(self._light_review, shot['scene_desc'],
                                               frames, char_ref)
                self._pending_review = (sid, fut)
                self._log('▸ shot %s 审片提交(light·与下一镜并行)' % sid)
                review = self._default_review(score=8, feedback='light review parallel')
            else:
                review = self._safe_review_shot(shot['scene_desc'], frames,
                                                char_ref=char_ref)
                self._log('▸ shot %s 审片(full): score=%s pass=%s' % (
                    sid, review.get('score'), review.get('pass')))
            print(f'  review: score={review["score"]}, pass={review["pass"]}')

            attempt_info = {
                'attempt': attempt,
                'seed': seed,
                'video': video_path,
                'composite_ref': composite_ref,
                'review': review,
            }
            attempts.append(attempt_info)

            if best is None or review['score'] > best['review']['score']:
                best = attempt_info

            if review['pass']:
                break

            if attempt <= self.max_retries:
                print(f'  retrying (feedback: {review["feedback"][:60]}...)')
                shot['video_prompt'] = self.llm.optimize_prompt(
                    shot['scene_desc'] + ' ' + review['feedback'],
                    shot.get('style', ''),
                    five_dim=shot.get('five_dim'),
                    ref_frame=bool(character),
                    anchors=getattr(self, '_anchors', None) or None,
                )

        # ── 慢动作后处理 ──
        final_video = best['video']
        slowmo_info = None
        slowmo_cfg = shot.get('slowmo')
        if slowmo_override:
            slowmo_cfg = {'multiplier': slowmo_override, 'mode': 'slowmo'}
        if slowmo_cfg and slowmo_cfg.get('multiplier', 1) > 1:
            mult = slowmo_cfg['multiplier']
            print(f'\n  [slowmo] RIFE {mult}x frame interpolation...')
            slowmo_out = os.path.join(clips_dir, f'shot_{sid}_slowmo.mp4')
            try:
                client = self._get_rife_client()
                result = client.slowmo(final_video, slowmo_out,
                                       multiplier=mult, fps=self.i2v_defaults.get('fps', 24))
                final_video = slowmo_out
                slowmo_info = result
                print(f'  [slowmo] done: {result["frame_count"]} frames')
                self._log('▸ shot %s slowmo %dx: %d 帧' % (sid, mult, result['frame_count']))
            except Exception as e:
                print(f'  ⚠ slowmo failed: {e}, using original video')

        return {
            'shot_id': sid,
            'camera': camera,
            'attempts': attempts,
            'final_video': final_video,
            'composite_ref': best.get('composite_ref'),
            'final_score': best['review']['score'],
            'slowmo': slowmo_info,
            'audio': {
                'narration': shot['narration'],
                'audio_path': audio_path,
                'duration': tts_result['duration'],
                'timestamps': tts_result['timestamps'],
            },
        }


    def _prefetch_shots(self, shots: list, character: dict, clips_dir: str,
                        task_id: str, voice: str,
                        i2v_w: int, i2v_h: int, bg_w: int, bg_h: int) -> dict:
        """并行预取所有镜头的 FLUX 参考帧 + TTS 配音。

        FLUX 在 GPU0:8192，TTS 在 9880，与 Wan I2V (GPU2:8189) 独立。
        使用 ThreadPoolExecutor 并行提交，结果按 shot id 索引返回。

        Returns:
            {shot_id: {'composite_ref': str, 'audio': dict}}
        """
        if not character:
            # v0 纯 T2V：只预取 TTS
            results = {}
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {}
                for shot in shots:
                    futures[pool.submit(self._generate_tts, shot, clips_dir, voice)] = shot['id']
                for fut in as_completed(futures):
                    sid = futures[fut]
                    try:
                        results[sid] = {'audio': fut.result()}
                    except Exception as e:
                        print(f'  [prefetch] tts failed for shot {sid}: {e}')
                        results[sid] = {}
            return results

        results = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {}
            for shot in shots:
                sid = shot['id']
                futures[pool.submit(self._generate_scene_ref, shot, character,
                                    clips_dir, task_id, i2v_w, i2v_h, bg_w, bg_h)] = ('ref', sid)
                futures[pool.submit(self._generate_tts, shot, clips_dir, voice)] = ('tts', sid)

            for fut in as_completed(futures):
                kind, sid = futures[fut]
                if sid not in results:
                    results[sid] = {}
                try:
                    if kind == 'ref':
                        results[sid]['composite_ref'] = fut.result()
                    else:
                        results[sid]['audio'] = fut.result()
                except Exception as e:
                    print(f'  [prefetch] {kind} failed for shot {sid}: {e}')

        print(f'  [prefetch] done: {len(results)} shots')
        return results


if __name__ == '__main__':
    import argparse
    print('提示: 推荐使用统一入口 → python core/vidance.py auto ...\n')
    parser = argparse.ArgumentParser(description='Vidance pipeline (内部入口，推荐使用 core/vidance.py)')
    parser.add_argument('concept', help='Video concept in Chinese')
    parser.add_argument('-o', '--output', default=None, help='Output video path')
    parser.add_argument('--character', default=None,
                        help='Character description in Chinese (e.g. 穿红斗篷的少年)')
    parser.add_argument('--character-mode', default='auto', choices=['auto', '3dgs', 'mesh', 'flux'],
                        help='Character anchor mode: auto(3DGS→flux降级) / 3dgs / mesh(Hunyuan3Dv2) / flux (default: auto)')
    parser.add_argument('--voice', default=None,
                        help='TTS voice (e.g. edge-moe, cosy-default)')
    parser.add_argument('--no-rife', action='store_true',
                        help='Disable RIFE frame interpolation transitions')
    parser.add_argument('--lut', default=None,
                        choices=['cinematic', 'warm', 'cool', 'vintage', 'vivid', 'soft'],
                        help='Color grading LUT style (auto-select if not specified)')
    parser.add_argument('--no-color', action='store_true',
                        help='Disable color grading')
    parser.add_argument('--bgm', default=None,
                        choices=['calm', 'uplifting', 'mysterious', 'dramatic', 'playful'],
                        help='BGM mood (auto-select if not specified)')
    parser.add_argument('--no-bgm', action='store_true',
                        help='Disable background music')
    parser.add_argument('--stt', action='store_true',
                        help='Use faster-whisper STT for subtitle alignment (overrides TTS timestamps)')
    parser.add_argument('--duration', type=float, default=None,
                        help='Target total duration in seconds (enables long-form: dynamically scales shot count)')
    parser.add_argument('--slowmo', type=int, default=None,
                        help='Global slowmo multiplier (e.g. 2 = 2x slow motion on all shots)')
    args = parser.parse_args()

    pipeline = Pipeline()
    if args.no_rife:
        pipeline.rife_config['enabled'] = False
    if args.no_color:
        pipeline.color_config['enabled'] = False
    if args.no_bgm:
        pipeline.bgm_config['enabled'] = False
    meta = pipeline.run(args.concept, output_path=args.output,
                        character_desc=args.character, voice=args.voice,
                        character_mode=args.character_mode,
                        lut_override=args.lut,
                        bgm_override=args.bgm,
                        use_stt=args.stt,
                        target_duration=args.duration,
                        slowmo_override=args.slowmo)
    print(f'\nDone: {meta["output"]}')
