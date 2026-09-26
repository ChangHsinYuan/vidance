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
