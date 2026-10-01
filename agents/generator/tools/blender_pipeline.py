#!/usr/bin/env python3
"""v13 M1/M2（blender 线）：3D 场景 JSON → bpy 构建 → 逐帧渲染 → mp4 → 有声成片

管线（渲染复用 v15 PPT 模式）：
  - bpy_build()  数据驱动建场景（文字/几何体 + 关键帧 + 运镜）
  - render_frames()  EEVEE 逐帧渲染（frame_set 天然确定性）→ yield PNG
  - BlenderLine  一键：LLM 规划 → 渲染 → ffmpeg → TTS 旁白 → 拼接成片

用法：
  python agents/generator/tools/blender_pipeline.py --scene scene.json --video -o out.mp4
"""
import os as _os
import sys as _sys
_ROOT = _os.path.abspath(__file__)
for _ in range(4):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
import argparse
import json as _json
import math
import subprocess
import time as _t

from agents.generator.tools.blender_llm import SCHEMES, plan_scene

PAGE_W, PAGE_H = 1280, 720


# ─────────────────────────── bpy 场景构建（M1） ───────────────────────────

def bpy_build(scene: dict):
    """场景 JSON → bpy 构建（bpy 5.0：BLENDER_EEVEE；返回 fps/duration）。"""
    import bpy
    import mathutils

    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = PAGE_W, PAGE_H
    sc.render.fps = 24
    scheme = SCHEMES.get(scene.get('scheme', 'ocean'), SCHEMES['ocean'])
    dur = float(scene.get('duration', 8.0))
    fps = 24
    frames = max(2, int(fps * dur))

    def _mat(name, kind, rgb):
        rgb = tuple(rgb[:3])
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = m.node_tree.nodes['Principled BSDF']
        if kind == 'emission':
            b.inputs['Base Color'].default_value = (*rgb, 1)
            b.inputs['Emission Color'].default_value = (*rgb, 1)
            b.inputs['Emission Strength'].default_value = 4.0
        elif kind == 'metal':
            b.inputs['Base Color'].default_value = (*rgb, 1)
            b.inputs['Metallic'].default_value = 0.85
            b.inputs['Roughness'].default_value = 0.22
        elif kind == 'glass':
            b.inputs['Base Color'].default_value = (*rgb, 1)
            b.inputs['Roughness'].default_value = 0.05
            try:
                b.inputs['Transmission Weight'].default_value = 0.9
            except KeyError:
                pass
        else:
            b.inputs['Base Color'].default_value = (*rgb, 1)
            b.inputs['Roughness'].default_value = 0.5
        return m

    mats = {c: {k: _mat(f'{k}_{c}', k, scheme[c]) for k in ('basic', 'metal', 'emission', 'glass')}
            for c in ('a', 'b')}

    def _add(shape, size):
        kw = {'location': (0, 0, 0)}
        if shape in ('cube', 'plane'):
            kw['size'] = size
        elif shape == 'sphere':
            kw['radius'] = size * 0.55
        elif shape == 'torus':
            kw['major_radius'] = size * 0.55
            kw['minor_radius'] = size * 0.18
        elif shape == 'cone':
            kw['radius1'] = size * 0.5
            kw['depth'] = size * 1.4
        elif shape == 'cylinder':
            kw['radius'] = size * 0.45
            kw['depth'] = size * 1.5
        ops = {'cube': bpy.ops.mesh.primitive_cube_add,
               'sphere': bpy.ops.mesh.primitive_uv_sphere_add,
               'torus': bpy.ops.mesh.primitive_torus_add,
               'plane': bpy.ops.mesh.primitive_plane_add,
               'cone': bpy.ops.mesh.primitive_cone_add,
               'cylinder': bpy.ops.mesh.primitive_cylinder_add}
        ops[shape](**kw)
        return bpy.context.object

    # 物体 + 动画（spin 关键帧 / pop 入场缩放 / float 正弦浮动由驱动器近似为关键帧）
    for i, o in enumerate(scene.get('objects', [])):
        if o['shape'] == 'text':
            continue
        obj = _add(o['shape'], float(o.get('size', 1.0)))
        obj.name = f'obj{i}'
        obj.location = o.get('at', [0, 0, 0])
        obj.data.materials.append(mats.get(o.get('color', 'a'), mats['a'])[o.get('mat', 'metal')])
        spin = o.get('spin') or [0, 0, 0]
        if any(abs(s) > 1e-4 for s in spin):
            obj.rotation_euler = (0, 0, 0)
            obj.keyframe_insert('rotation_euler', frame=1)
            end = [spin[0] * dur, spin[1] * dur, spin[2] * dur]
            obj.rotation_euler = end
            obj.keyframe_insert('rotation_euler', frame=frames)
        pop = float(o.get('pop', 0) or 0)
        if pop > 0:
            p1, p2 = max(1, int(pop * fps)), max(2, int(pop * fps) + 14)
            obj.scale = (0.01, 0.01, 0.01)
            obj.keyframe_insert('scale', frame=p1)
            obj.scale = (1, 1, 1)
            obj.keyframe_insert('scale', frame=p2)

    # 标题/副标题（中文 FONT 物体，title3d/shapes 模板都有）
    txt_body = scene.get('text', '')
    if txt_body:
        crv = bpy.data.curves.new('title', type='FONT')
        crv.body = txt_body
        crv.size = 0.62
        crv.align_x = 'CENTER'
        crv.extrude = 0.035
        tobj = bpy.data.objects.new('title', crv)
        tobj.location = (0, -0.5, 1.55)
        sc.collection.objects.link(tobj)
        tobj.data.materials.append(mats['a']['basic'])
        tobj.scale = (0.01, 0.01, 0.01)
        tobj.keyframe_insert('scale', frame=1)
        tobj.scale = (1, 1, 1)
        tobj.keyframe_insert('scale', frame=max(2, int(0.9 * fps)))
    sub = scene.get('subtitle', '')
    if sub:
        crv = bpy.data.curves.new('subtitle', type='FONT')
        crv.body = sub
        crv.size = 0.24
        crv.align_x = 'CENTER'
        sobj = bpy.data.objects.new('subtitle', crv)
        sobj.location = (0, -0.5, 1.05)
        sc.collection.objects.link(sobj)
        sobj.data.materials.append(mats['b']['basic'])
        sobj.hide_viewport = sobj.hide_render = True
        sobj.keyframe_insert('hide_render', frame=int(dur * 0.3 * fps))
        sobj.hide_viewport = sobj.hide_render = False
        sobj.keyframe_insert('hide_render', frame=int(dur * 0.3 * fps) + 1)

    # 地面（接收阴影）
    g = _add('plane', 30)
    g.name = 'ground'
    g.location = (0, 0, -0.02)
    gmat = bpy.data.materials.new('ground')
    gmat.use_nodes = True
    gb = gmat.node_tree.nodes['Principled BSDF']
    gb.inputs['Base Color'].default_value = scheme['bg']
    gb.inputs['Roughness'].default_value = 0.9
    g.data.materials.append(gmat)

    # 相机 + 运镜
    cam_data = bpy.data.cameras.new('cam')
    cam_data.lens = 50
    cam = bpy.data.objects.new('cam', cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    c = scene.get('camera') or {}
    frm = tuple(c.get('from') or [0, -9, 2.0])
    move = c.get('move', 'dolly_in')
    if move == 'orbit':
        a0 = math.radians(frm[0] or -30)
        a1 = math.radians((c.get('to') or [30, 0, 0])[0])
        r = abs(frm[1]) or 9
        h = frm[2] or 2.0
        cam.location = (r * math.cos(a0), -r * math.sin(a0), h)
        cam.keyframe_insert('location', frame=1)
        cam.location = (r * math.cos(a1), -r * math.sin(a1), h)
        cam.keyframe_insert('location', frame=frames)
        for f in (1, frames):
            sc.frame_set(f)
            d = mathutils.Vector((0, 0, 0.6)) - cam.location
            cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
            cam.keyframe_insert('rotation_euler', frame=f)
    else:
        to = tuple(c.get('to') or ([0, -7, 1.4] if move == 'dolly_in' else
                                   [frm[0] + (2.2 if move == 'pan_right' else -2.2), frm[1], frm[2]]))
        cam.location = frm
        cam.keyframe_insert('location', frame=1)
        cam.location = to
        cam.keyframe_insert('location', frame=frames)
        sc.frame_set(1)
        d = mathutils.Vector((0, 0, 0.6)) - cam.location
        cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
        cam.keyframe_insert('rotation_euler', frame=1)

    # 灯光 + 世界底色
    key = bpy.data.lights.new('key', type='AREA')
    key.energy = 1200
    key.size = 10
    key_obj = bpy.data.objects.new('key', key)
    key_obj.location = (3, -5, 6)
    sc.collection.objects.link(key_obj)
    key_obj.rotation_euler = (0.65, 0, -0.45)
    rim = bpy.data.lights.new('rim', type='AREA')
    rim.energy = 500
    rim.size = 6
    rim.color = scheme['b'][:3]
    rim_obj = bpy.data.objects.new('rim', rim)
    rim_obj.location = (-4, -2, 3.5)
    sc.collection.objects.link(rim_obj)
    rim_obj.rotation_euler = (1.1, 0, 1.2)
    world = bpy.data.worlds.new('w')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs[0].default_value = scheme['bg']
    sc.world = world

    sc.frame_start, sc.frame_end = 1, frames
    return {'fps': fps, 'frames': frames, 'duration': dur}


# ─────────────────────────── 逐帧渲染（M2） ───────────────────────────

def render_frames(scene: dict):
    """场景 → 逐帧 yield PNG（frame_set 确定性；EEVEE GPU 不可用自动 CPU）。"""
    import bpy
    info = bpy_build(scene)
    sc = bpy.context.scene
    sc.render.image_settings.file_format = 'PNG'
    sc.render.filepath = '/tmp/opencode/blender_frame_'
    for i in range(1, info['frames'] + 1):
        sc.frame_set(i)
        bpy.ops.render.render(write_still=True)
        path = f"/tmp/opencode/blender_frame_{i:04d}.png"
        if not _os.path.isfile(path):
            path = '/tmp/opencode/blender_frame_.png'
            with open(path, 'rb') as fh:
                yield fh.read()
        else:
            with open(path, 'rb') as fh:
                yield fh.read()
            _os.remove(path)


def frames_to_mp4(png_iter, out_path: str, fps: int = 24, on_frame=None, total=0):
    """PNG 流 → mp4（image2pipe，同 v13/v15）。"""
    _os.makedirs(_os.path.dirname(_os.path.abspath(out_path)) or '.', exist_ok=True)
    tmp = out_path + '.part.mp4'
    proc = subprocess.Popen(['ffmpeg', '-y', '-loglevel', 'error',
                             '-f', 'image2pipe', '-vcodec', 'png', '-framerate', str(fps),
                             '-i', '-', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                             '-preset', 'medium', '-crf', '18', '-r', str(fps), tmp],
                            stdin=subprocess.PIPE)
    n = 0
    for png in png_iter:
        try:
            proc.stdin.write(png)
        except (BrokenPipeError, OSError):
            break
        if proc.poll() is not None:
            raise RuntimeError(f'ffmpeg 渲染中途退出 (rc={proc.returncode})')
        n += 1
        if on_frame:
            try:
                on_frame(n, total)
            except Exception:
                pass
    proc.stdin.close()
    rc = proc.wait()
    if rc != 0 or not _os.path.isfile(tmp) or _os.path.getsize(tmp) == 0:
        if _os.path.isfile(tmp):
            _os.remove(tmp)
        raise RuntimeError(f'ffmpeg 渲染失败 (rc={rc})')
    _os.replace(tmp, out_path)
    return out_path


def scene_to_mp4(scene: dict, out_path: str, on_frame=None) -> dict:
    """场景 JSON → mp4（逐帧渲染 + 拼帧）。"""
    frames = max(2, int(24 * float(scene.get('duration', 8.0))))
    pngs = render_frames(scene)
    frames_to_mp4(pngs, out_path, fps=24, on_frame=on_frame, total=frames)
    return {'mp4': out_path, 'frames': frames, 'duration': scene.get('duration', 8.0)}


# ─────────────────────────── 一键流水线（M2：BlenderLine） ───────────────────────────

class BlenderLine:
    """概念 → LLM 3D 规划 → bpy 渲染 → TTS 旁白 → mp4（对标 SvgLine/PptLine）。"""

    def __init__(self, config=None):
        from utils.config_loader import load_config
        from core.narration import Narrator
        self.config = config or load_config()
        self.output_dir = self.config.get('output_dir', 'output')
        self.narr = Narrator(self.config)

    def run(self, concept, n=1, say=None, voice=None, out_path=None,
            duration=8.0, model=None, say_voice_note=True,
            stage_cb=None, on_chunk=None, on_frame=None,
            save_scene=True, png_dir=None) -> dict:
        import json as _j
        from datetime import datetime
        from agents.common.tools.config_loader import task_id_for
        start = _t.time()
        ts = task_id_for('blender3d')
        workdir = _os.path.join(self.output_dir, ts)
        _os.makedirs(workdir, exist_ok=True)
        _ = datetime  # noqa: F821

        # 1) 场景规划（LLM / 手动 say 模式：每句一个 3D 标题场景，简单版取第一句做主场景）
        if stage_cb:
            try:
                stage_cb('M1 3D 场景规划')
            except Exception:
                pass
        print('[M1] 3D 场景规划…')
        from agents.generator.tools.blender_llm import _norm_scene
        if say:
            scene = _norm_scene({'title': concept[:24], 'template': 'title3d',
                                 'scheme': 'ocean', 'text': concept[:10],
                                 'subtitle': say[0][:18] if say else '',
                                 'duration': duration}, concept)
            scene['notes'] = say[0] if say else ''
        else:
            scene = plan_scene(concept, n=n, model=model, on_chunk=on_chunk)
        if duration:
            scene['duration'] = float(duration)
        scene.setdefault('notes', scene.get('subtitle', ''))
        print(f'  {scene["template"]}/{scene["scheme"]} · {len(scene["objects"])} 物体 · {scene["duration"]}s')

        artifacts = {'task_id': ts, 'concept': concept, 'mode': 'blender3d',
                     'scene': scene}

        if save_scene:
            sp = _os.path.join(workdir, 'scene.json')
            with open(sp, 'w', encoding='utf-8') as f:
                _j.dump(scene, f, ensure_ascii=False, indent=2)
            artifacts['scene_json'] = sp

        # 2) bpy 渲染（逐帧）
        if stage_cb:
            try:
                stage_cb('M2 Blender 渲染（EEVEE）')
            except Exception:
                pass
        clip = _os.path.join(workdir, 'scene.mp4')
        frames = max(2, int(24 * scene['duration']))
        print(f'[M2] Blender 渲染 {frames} 帧（EEVEE）…')
        frames_to_mp4(render_frames(scene), clip, fps=24, on_frame=on_frame, total=frames)
        artifacts['clip'] = clip
        print(f'  ✅ {clip}')

        if png_dir:
            _os.makedirs(png_dir, exist_ok=True)
            artifacts['png_dir'] = png_dir

        # 3) TTS 旁白 + 有声成片
        voice = voice or self.config.get('tts', {}).get('default_voice', 'cosy-default')
        note = scene.get('notes', '')
        srt_ts = []
        wav = None
        if note:
            if stage_cb:
                try:
                    stage_cb('M3 TTS 旁白')
                except Exception:
                    pass
            wav = _os.path.join(workdir, 'narration.wav')
            print(f'[M3] TTS "{note[:18]}…"')
            self.narr.say(note, wav, voice=voice)
            from agents.generator.tools.ppt_pipeline import _probe_duration
            adur = _probe_duration(wav)
            srt_ts = [{'start': 0.0, 'end': min(adur + 0.3, scene['duration']),
                       'text': note}]
        if out_path is None:
            out_path = _os.path.join(workdir, 'final.mp4')
        elif not _os.path.isabs(out_path):
            out_path = _os.path.join(self.output_dir, out_path)
        if stage_cb:
            try:
                stage_cb('M3 拼接成片')
            except Exception:
                pass
        print('[M3] 拼接成片…')
        from agents.generator.tools.ppt_pipeline import _probe_duration
        if wav:
            # 画面为准：配音并轨（短则补静音、长则截到画面长），不走 compose 的"配音截画面"
            from moviepy import VideoFileClip, AudioFileClip, concatenate_audioclips
            from moviepy.audio.AudioClip import AudioClip
            import numpy as _np
            vc = VideoFileClip(clip)
            ac = AudioFileClip(wav)
            if ac.duration < vc.duration:
                sr = 44100
                pad_n = int((vc.duration - ac.duration) * sr)
                pad = AudioClip(lambda t: _np.zeros((len(t) if hasattr(t, '__len__') else 1, 2)),
                                duration=vc.duration - ac.duration, fps=sr)
                ac = concatenate_audioclips([ac, pad])
            else:
                ac = ac.subclipped(0, vc.duration)
            vc = vc.with_audio(ac).with_fps(24)
            vc.write_videofile(out_path, codec='libx264', audio_codec='aac',
                               preset='medium', bitrate='6000k', logger=None)
            vc.close()
            ac.close()
        else:
            subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', clip,
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18',
                            '-r', '24', out_path], check=True)
        if srt_ts:
            self.narr.srt(srt_ts, _os.path.join(workdir, 'subtitle.srt'))
        from agents.generator.tools.ppt_pipeline import _probe_duration
        artifacts.update({'voice': voice, 'output': out_path,
                          'duration': _probe_duration(out_path),
                          'elapsed_s': round(_t.time() - start, 1)})
        with open(_os.path.join(workdir, 'meta.json'), 'w', encoding='utf-8') as f:
            _j.dump(artifacts, f, ensure_ascii=False, indent=2)
        print(f'✅ {out_path}（{artifacts["duration"]:.1f}s，{artifacts["elapsed_s"]}s）')
        return artifacts


def _main():
    ap = argparse.ArgumentParser(description='3D 场景 JSON → mp4（v13 blender 线渲染管线）')
    ap.add_argument('--scene', required=True, help='scene.json 路径')
    ap.add_argument('-o', '--output', default=None, help='mp4 输出路径')
    args = ap.parse_args()
    with open(args.scene, 'r', encoding='utf-8') as f:
        scene = _json.load(f)
    out = args.output or args.scene.rsplit('.', 1)[0] + '.mp4'
    meta = scene_to_mp4(scene, out)
    print(f'✅ {meta["mp4"]}（{meta["frames"]} 帧，{meta["duration"]}s）')


if __name__ == '__main__':
    _main()
