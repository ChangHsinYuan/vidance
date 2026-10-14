#!/usr/bin/env python3
"""v13 M1（blender 线）：概念/大纲 → LLM → 3D 场景 JSON 规划 + bpy 场景构建

分工（照抄 v15 PPT 架构）：
  - LLM 只出**结构化 JSON**（标题/物体/关键帧/运镜），不产脚本 —— 可控、可容错
  - 场景由 bpy_build() 数据驱动构建（内置物体：文字/立方体/球/圆环/平面；材质：纯色/金属/发光）
  - 三个内置模板：title3d（3D 标题）/ shapes（几何动效）/ bars3d（3D 数据柱）

用法：
  python agents/generator/tools/blender_llm.py "Vidance 介绍" --n 1 -o /tmp/scene.json
"""
import os as _os
import sys as _sys
_ROOT = _os.path.abspath(__file__)
for _ in range(4):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
import argparse
import json
import re

from agents.generator.tools.ppt_llm import extract_json

SHAPES = ('text', 'cube', 'sphere', 'torus', 'plane', 'cone', 'cylinder')
MATS = ('basic', 'metal', 'emission', 'glass')
SCHEMES = {
    'ocean': {'bg': (0.04, 0.06, 0.15, 1), 'a': (0.22, 0.74, 0.97, 1), 'b': (0.98, 0.75, 0.15, 1)},
    'sunset': {'bg': (0.10, 0.04, 0.12, 1), 'a': (0.98, 0.45, 0.30, 1), 'b': (0.98, 0.75, 0.15, 1)},
    'forest': {'bg': (0.03, 0.09, 0.07, 1), 'a': (0.30, 0.85, 0.50, 1), 'b': (0.95, 0.85, 0.30, 1)},
    'mono': {'bg': (0.05, 0.05, 0.06, 1), 'a': (0.90, 0.90, 0.94, 1), 'b': (0.45, 0.65, 0.95, 1)},
}
DEFAULT_SCHEME = 'ocean'

PLAN_SYS = """你是 3D 短片策划师。根据主题规划一段 Blender 3D 动画脚本（JSON）。
场景由几个 3D 物体组成（文字标题 + 几何体阵列），带入场动画和镜头运动。约 {n} 个物体。
只输出 JSON，不要 markdown 代码块，格式：
{{"title": "3D 短片标题",
  "template": "title3d",
  "scheme": "ocean",
  "text": "主标题文字（中文，≤10 字）",
  "subtitle": "副标题（中文，≤16 字）",
  "duration": 8,
  "camera": {{"move": "dolly_in", "from": [0, -9, 2.0], "to": [0, -7, 1.4]}},
  "objects": [
    {{"shape": "cube", "at": [-2.2, -1.2, 0.5], "size": 0.9, "mat": "metal", "color": "a",
      "spin": [0, 0, 0.6], "pop": 0.3}},
    {{"shape": "sphere", "at": [0.2, -1.0, 0.8], "size": 0.7, "mat": "emission", "color": "b",
      "float": 0.25}}
  ]}}
字段说明：
- template: title3d（3D 大标题+几何环绕）/ shapes（纯几何动效阵列）/ bars3d（3D 数据柱对比）
- scheme: ocean/sunset/forest/mono 配色；text 主标题、subtitle 副标题（可空）
- camera.move: dolly_in/pan_left/pan_right/orbit（orbit 时 from/to 是角度对）
- objects[].spin: 每秒欧拉角旋转增量；pop: 入场缩放延迟秒（0=不弹入）；float: 上下浮动幅度（0=静止）
- bars3d 时 objects 是 3-5 根柱子（shape=cube，at.x 依次排开，size.y 表示数值高低）"""


def _norm_scene(raw: dict, concept: str) -> dict:
    """LLM 输出规范化：模板/配色/物体白名单、数值钳制、页数兜底。"""
    scheme = str(raw.get('scheme', DEFAULT_SCHEME)).strip().lower()
    if scheme not in SCHEMES:
        scheme = DEFAULT_SCHEME
    template = str(raw.get('template', 'title3d')).strip().lower()
    if template not in ('title3d', 'shapes', 'bars3d'):
        template = 'title3d'
    dur = raw.get('duration')
    try:
        dur = min(20.0, max(4.0, float(dur)))
    except (TypeError, ValueError):
        dur = 8.0

    def _vec(v, n=3, d=0.0):
        try:
            vals = [float(x) for x in (v if isinstance(v, (list, tuple)) else [d] * n)][:n]
            vals += [d] * (n - len(vals))
            return [min(30.0, max(-30.0, x)) for x in vals]
        except (TypeError, ValueError):
            return [d] * n

    cam = raw.get('camera') if isinstance(raw.get('camera'), dict) else {}
    move = str(cam.get('move', 'dolly_in')).strip().lower()
    if move not in ('dolly_in', 'pan_left', 'pan_right', 'orbit'):
        move = 'dolly_in'
    scene = {
        'title': str(raw.get('title', '')).strip()[:32] or concept[:24],
        'template': template, 'scheme': scheme,
        'text': str(raw.get('text', '')).strip()[:12] or concept[:10],
        'subtitle': str(raw.get('subtitle', '')).strip()[:18],
        'duration': dur,
        'camera': {'move': move,
                   'from': _vec(cam.get('from'), d=-9.0), 'to': _vec(cam.get('to'))},
        'objects': [],
    }
    for o in (raw.get('objects') or [])[:8]:
        if not isinstance(o, dict):
            continue
        shape = str(o.get('shape', 'cube')).strip().lower()
        if shape not in SHAPES:
            shape = 'cube'
        mat = str(o.get('mat', 'metal')).strip().lower()
        if mat not in MATS:
            mat = 'metal'
        color = str(o.get('color', 'a')).strip().lower()
        scene['objects'].append({
            'shape': shape,
            'at': _vec(o.get('at')),
            'size': min(4.0, max(0.1, float(o.get('size', 1.0) if isinstance(o.get('size'), (int, float)) else 1.0))),
            'mat': mat, 'color': 'b' if color == 'b' else 'a',
            'spin': _vec(o.get('spin')),
            'pop': min(3.0, max(0.0, float(o.get('pop', 0) if isinstance(o.get('pop'), (int, float)) else 0))),
            'float': min(1.0, max(0.0, float(o.get('float', 0) if isinstance(o.get('float'), (int, float)) else 0))),
        })
    if not scene['objects']:
        scene['objects'] = [{'shape': 'cube', 'at': [-2.0, -1.2, 0.5], 'size': 0.9,
                             'mat': 'metal', 'color': 'a', 'spin': [0, 0, 0.5],
                             'pop': 0.2, 'float': 0.0},
                            {'shape': 'sphere', 'at': [1.6, -1.0, 0.7], 'size': 0.6,
                             'mat': 'emission', 'color': 'b', 'spin': [0, 0, 0],
                             'pop': 0.5, 'float': 0.2}]
    return scene


def plan_scene(concept: str, n: int = 1, model: str = None, on_chunk=None,
               style_hint: str = None) -> dict:
    """概念 → LLM → 3D 场景 JSON。解析失败时用内置默认（title3d + ocean）。

    style_hint: SKILL 文风指令（追加到 system，控制场景布局/配色/运镜）。
    """
    from utils.config_loader import load_config
    llm = None
    try:
        from utils.llm import LLMClient
        llm = LLMClient(load_config())
    except Exception:
        pass
    sys_p = PLAN_SYS.format(n=max(3, n * 4))
    if style_hint:
        sys_p += f'\n场景风格要求：{str(style_hint).strip()}'
    messages = [{'role': 'system', 'content': sys_p},
                {'role': 'user', 'content': f'主题：{concept}'}]
    if llm is not None:
        try:
            from agents.generator.tools.svg_llm import _chat_stream
            text = _chat_stream(llm, messages, model=model, temperature=0.5,
                                read_timeout=20, on_chunk=on_chunk)
            return _norm_scene(extract_json(text), concept)
        except Exception as e:
            print(f'  ⚠ 3D 规划失败（{e}），用默认场景兜底')
    return _norm_scene({'title': concept[:24], 'template': 'title3d', 'scheme': 'ocean',
                        'text': concept[:10], 'subtitle': 'Blender 3D 渲染',
                        'duration': 8.0}, concept)


def main():
    ap = argparse.ArgumentParser(description='概念 → LLM → 3D 场景 JSON（v13 blender 线）')
    ap.add_argument('concept', help='主题（中文）')
    ap.add_argument('-o', '--output', default=None, help='JSON 输出路径')
    ap.add_argument('--n', type=int, default=1, help='物体数提示（约 n*4 个）')
    ap.add_argument('--model', default=None, help='LLM 模型')
    args = ap.parse_args()
    out = args.output or 'output/blender3d/scene.json'
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    scene = plan_scene(args.concept, n=args.n, model=args.model)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(scene, f, ensure_ascii=False, indent=2)
    print(f'✅ {out}（{scene["template"]}/{scene["scheme"]}，{len(scene["objects"])} 物体，{scene["duration"]}s）')


if __name__ == '__main__':
    main()
