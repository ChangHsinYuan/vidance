"""G 层 Agent（薄包装）：SVG 动画、FastLine 图文、Wan T2V。"""
import os
import sys

_ROOT = os.path.abspath(__file__)
for _ in range(3):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agents.base import TaskResult, register


@register(name='generator.svg', layer='generator', needs_gpu=False,
          desc='概念 → LLM SVG 动画 → 有声短片（SvgLine 全链）',
          inputs='{concept, n?, say?, voice?, lut?, bgm?, out_path?}')
def svg(p):
    from agents.generator.tools.svg_pipeline import SvgLine
    kwargs = {k: p[k] for k in ('n', 'say', 'voice', 'out_path', 'width',
                                'height', 'fps', 'bg', 'model', 'lut', 'bgm')
              if k in p}
    meta = SvgLine().run(p['concept'], **kwargs)
    video = meta.get('video') or meta.get('out_path')
    return TaskResult(ok=bool(video), artifacts={'video': video, 'meta': meta},
                      trace=[{'step': 'svgline', 'video': video}])


@register(name='generator.fast', layer='generator', needs_gpu=False,
          desc='概念 → 网图 + 运镜 + 旁白 + BGM（FastLine 全链）',
          inputs='{concept, n?, images_dir?, motion?, out_path?}')
def fast(p):
    from agents.generator.tools.fastline import FastLine
    kwargs = {k: p[k] for k in ('images_dir', 'n', 'motion', 'output_path')
              if k in p}
    meta = FastLine().run(p['concept'], **kwargs)
    video = meta.get('video') or meta.get('output_path') if isinstance(meta, dict) else meta
    return TaskResult(ok=bool(video), artifacts={'video': video, 'meta': meta},
                      trace=[{'step': 'fastline', 'video': video}])


@register(name='generator.wan_t2v', layer='generator', needs_gpu=True,
          desc='概念 → Wan 成片（cmd_quick 语义：纯 T2V 无后处理）',
          inputs='{concept, out_path?, voice?}')
def wan_t2v(p):
    from core.pipeline import Pipeline
    pipeline = Pipeline()
    pipeline.rife_config['enabled'] = False
    pipeline.color_config['enabled'] = False
    pipeline.bgm_config['enabled'] = False
    meta = pipeline.run(p['concept'], output_path=p.get('out_path'),
                        character_desc=None, voice=p.get('voice'),
                        character_mode='auto')
    video = meta.get('output')
    return TaskResult(ok=bool(video) and os.path.isfile(video),
                      artifacts={'video': video, 'meta': meta},
                      trace=[{'step': 'quick', 'out': video}])


@register(name='generator.artist', layer='generator', needs_gpu=True,
          desc='美术师：文生图/爬图拿原材料（flux|sdxl|crawl）',
          inputs='{prompt, engine?=flux|sdxl|crawl, out_path?, top?=1}')
def artist(p):
    engine = p.get('engine', 'flux')
    prompt = p.get('prompt') or p.get('concept') or ''
    from agents.common.tools.config_loader import load_config
    out_dir = os.path.join(load_config().get('output_dir', 'output'), 'artist')
    os.makedirs(out_dir, exist_ok=True)
    if engine in ('crawl', 'bing', 'pexels'):
        from agents.common.tools.asset_crawler import AssetCrawler
        files = AssetCrawler().download_images(prompt, out_dir, top=int(p.get('top', 1)))
        paths = [f['path'] if isinstance(f, dict) else f for f in files]
        if not paths:
            return TaskResult(ok=False, error='crawl 未下载到图')
        return TaskResult(ok=True, artifacts={'image': paths[0], 'images': paths})
    inst = 'sdxl' if engine == 'sdxl' else 'flux'
    from agents.generator.tools.comfy_api import ComfyClient
    out = p.get('out_path') or os.path.join(
        out_dir, 'artist_%d.png' % abs(hash(prompt) % 10 ** 8))
    try:
        client = ComfyClient(instance=inst)
        r = client.generate_flux_t2i(prompt, width=p.get('width', 1024),
                                     height=p.get('height', 1024), output_path=out)
        path = r.get('image_path') or out
        if not os.path.isfile(path):
            return TaskResult(ok=False, error='%s 生图失败' % inst)
        return TaskResult(ok=True, artifacts={'image': path, 'engine': inst})
    except Exception as e:
        if engine == 'sdxl':  # sdxl 未起时兜底 flux
            return artist({**p, 'engine': 'flux'})
        return TaskResult(ok=False, error='artist %s: %s' % (inst, e))


@register(name='generator.h3shot', layer='generator', needs_gpu=True,
          desc='参考图+整段分镜 prompt → H3 有声单镜（ref2va 原生音）',
          inputs='{prompt, refs, out_path?, seconds?, ref_image_size?}')
def h3shot(p):
    from agents.generator.tools.comfy_api import ComfyClient
    refs = p.get('refs') or ([p['ref']] if p.get('ref') else [])
    if not refs or not p.get('prompt'):
        return TaskResult(ok=False, error='需 prompt + refs')
    seconds = float(p.get('seconds', 5))
    length = int(min(max(seconds, 2), 15) * 24) + 1
    out = p.get('out_path') or os.path.join(
        os.getcwd(), 'h3shot_%d.mp4' % abs(hash(p['prompt']) % 10 ** 8))
    try:
        client = ComfyClient(instance='h3')
        r = client.generate_h3_ref2v(p['prompt'], refs, length=length,
                                     ref_image_size=p.get('ref_image_size', 'match'),
                                     output_path=out)
        path = (r or {}).get('video_path') or out
        return TaskResult(ok=os.path.isfile(path), artifacts={'video': path})
    except Exception as e:
        return TaskResult(ok=False, error='h3shot: %s' % str(e)[:200])


@register(name='generator.splat', layer='generator', needs_gpu=True,
          desc='单图 → 3DGS PLY（TripoSplat）',
          inputs='{image, out_path?}')
def splat(p):
    from agents.generator.tools.comfy_api import ComfyClient
    out = p.get('out_path') or os.path.join(
        os.getcwd(), 'splat_%d.ply' % abs(hash(p['image']) % 10 ** 8))
    try:
        client = ComfyClient(instance='flux')
        r = client.generate_tripsplat(p['image'], output_path=out)
        path = (r or {}).get('ply_path') or (r or {}).get('path') or out
        return TaskResult(ok=os.path.isfile(path), artifacts={'ply': path})
    except Exception as e:
        return TaskResult(ok=False, error='splat: %s' % str(e)[:200])


@register(name='generator.mesh', layer='generator', needs_gpu=True,
          desc='单图/三视图 → GLB mesh（Hunyuan3Dv2，可 mesh_render 出预览）',
          inputs='{image | images={front,left,back}, out_path?, preview?}')
def mesh(p):
    from agents.generator.tools.hunyuan3d import Hunyuan3DClient
    out = p.get('out_path') or os.path.join(
        os.getcwd(), 'mesh_%d.glb' % abs(hash(str(p.get('image') or p.get('images'))) % 10 ** 8))
    client = Hunyuan3DClient()
    try:
        imgs = p.get('images')
        if imgs and all(imgs.get(k) for k in ('front', 'left', 'back')):
            r = client.generate_multiview(imgs['front'], imgs['left'], imgs['back'],
                                          output_path=out)
        else:
            r = client.generate_single(p['image'], output_path=out)
        glb = (r.get('glb_path') if isinstance(r, dict) else r) or out
        arts = {'glb': glb}
        if p.get('preview') and os.path.isfile(glb):
            from agents.generator.tools.mesh_render import render_mesh_angles
            pv_dir = os.path.join(os.path.dirname(glb), 'previews')
            arts['previews'] = render_mesh_angles(glb, angles=4, output_dir=pv_dir)
        return TaskResult(ok=os.path.isfile(glb), artifacts=arts)
    except Exception as e:
        return TaskResult(ok=False, error='mesh: %s' % str(e)[:200])
