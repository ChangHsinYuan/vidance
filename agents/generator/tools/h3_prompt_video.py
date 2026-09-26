#!/usr/bin/env python3
"""整段式 prompt + 参考图 → H3 ref2va 单镜视频（原生音频直出）

用于《奶蛙徽商》这类"一整段自包含 prompt"（新格式，非多镜【XX｜标题｜约X秒】）：
直接把 prompt 原文喂给 MiniMax-H3 ref2va，参考图按 <Picture i> 顺序用文字标签绑定。

与 core/custom_gen.py 的区别：
  - custom_gen 走 parse_script 解析多镜脚本；本脚本把整个 prompt 文件当**单一镜头**
  - 不做 LLM 编剧、不做后处理（LUT/BGM/STT），H3 原生音频直出
  - 参考图自动拷成 ASCII 临时名（规避中文文件名上传 ComfyUI 的坑）

用法：
  python utils/h3_prompt_video.py \
      --prompt input/prompt1.txt \
      --ref input/徽派布衣奶蛙.png --name 奶蛙 \
      --ref input/豆包.jpg --name 豆包 \
      -o output/prompt01/01.mp4
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
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from utils.comfy_api import ComfyClient
from utils.config_loader import load_config


def parse_seconds(text: str, default: float = 8.0) -> float:
    """从 prompt 文本里解析 '约N秒' → 秒数"""
    m = re.search(r'约([\d.]+)\s*秒', text)
    return float(m.group(1)) if m else default


def load_prompt_text(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read().strip()


def prepare_refs(ref_paths: list, names: list, work_dir: str) -> list:
    """把参考图拷成 ASCII 临时名，返回 [(tmp_path, display_name, cn_name)]。

    临时名形如 ref_1_naiwa.png，规避中文文件名上传 ComfyUI 的兼容问题。
    """
    import unicodedata
    os.makedirs(work_dir, exist_ok=True)
    out = []
    for i, rp in enumerate(ref_paths):
        if not os.path.isfile(rp):
            raise FileNotFoundError(f'参考图不存在: {rp}')
        ext = os.path.splitext(rp)[1].lower() or '.png'
        display = names[i] if i < len(names) and names[i] else \
            os.path.splitext(os.path.basename(rp))[0]
        ascii_stem = re.sub(r'[^0-9a-zA-Z]+', '_',
                            unicodedata.normalize('NFKD', display).encode('ascii', 'ignore').decode() or f'char{i+1}').strip('_') or f'char{i+1}'
        tmp_name = f'ref_{i+1}_{ascii_stem}{ext}'
        tmp_path = os.path.join(work_dir, tmp_name)
        shutil.copy2(rp, tmp_path)
        out.append((tmp_path, display, display))
    return out


def build_h3_prompt(prompt_text: str, refs: list, descs: list) -> str:
    """拼 H3 prompt：<Picture i> 标签块 + 约束 + 原始 prompt 原文"""
    tags = []
    for i, (_tmp, name, _cn) in enumerate(refs):
        desc = descs[i] if i < len(descs) and descs[i] else name
        tags.append(f'<Picture {i+1}> 是{name}：{desc}')
    picture_text = '\n'.join(tags)
    constraints = (
        f'画面中只能出现以上 {len(refs)} 个参考角色，外观（脸型、发型、身体比例、材质、服装）'
        '必须与参考图完全一致，不要创造或添加任何其他角色，也不要把参考图画成画中画。'
    )
    return f'{picture_text}\n\n{constraints}\n\n{prompt_text}'


def main():
    ap = argparse.ArgumentParser(description='整段式 prompt + 参考图 → H3 ref2va 单镜视频')
    ap.add_argument('--prompt', required=True, help='整段式 prompt 文件路径（如 input/prompt1.txt）')
    ap.add_argument('--ref', action='append', default=[], help='参考图路径（可重复，顺序对应 <Picture i>）')
    ap.add_argument('--name', action='append', default=[], help='参考图角色名（可重复，与 --ref 对齐；缺省用文件名）')
    ap.add_argument('-o', '--output', default=None, help='输出 mp4 路径（相对→output_dir）')
    ap.add_argument('--width', type=int, default=None)
    ap.add_argument('--height', type=int, default=None)
    ap.add_argument('--seconds', type=float, default=None, help='时长（秒）；缺省从 prompt 的"约N秒"解析')
    ap.add_argument('--steps', type=int, default=None)
    ap.add_argument('--fps', type=int, default=24)
    ap.add_argument('--seed', type=int, default=None)
    ap.add_argument('--ref-image-size', choices=['match', 'max'], default='match')
    ap.add_argument('--no-describe', action='store_true', help='跳过 LLM 看图描述，直接用角色名做标签')
    ap.add_argument('--fast', action='store_true',
                    help='快速档：steps=14 + 1024x576（约省一半时间，质量略降）；显式 --steps/--width/--height 可覆盖')
    args = ap.parse_args()

    # ── 速度档位（--fast 为默认基线，显式参数优先）──
    DEFAULT_W, DEFAULT_H, DEFAULT_STEPS = 1344, 768, 20
    if args.fast:
        defaults = {'width': 1024, 'height': 576, 'steps': 14}
    else:
        defaults = {'width': DEFAULT_W, 'height': DEFAULT_H, 'steps': DEFAULT_STEPS}
    width = args.width if args.width is not None else defaults['width']
    height = args.height if args.height is not None else defaults['height']
    steps = args.steps if args.steps is not None else defaults['steps']
    args.width, args.height, args.steps = width, height, steps

    if not args.ref:
        print('错误: 至少需要一个 --ref 参考图', file=sys.stderr)
        sys.exit(1)

    config = load_config()
    output_dir = config['output_dir']

    task_id = time.strftime('%Y%m%d_%H%M%S')
    if args.output is None:
        task_dir = os.path.join(output_dir, f'h3_{task_id}')
        output_path = os.path.join(task_dir, 'clip.mp4')
    else:
        output_path = args.output if os.path.isabs(args.output) else os.path.join(output_dir, args.output)
        task_dir = os.path.dirname(os.path.abspath(output_path))
    clips_dir = os.path.join(task_dir, 'clips')
    os.makedirs(clips_dir, exist_ok=True)

    prompt_text = load_prompt_text(args.prompt)
    seconds = args.seconds if args.seconds is not None else parse_seconds(prompt_text)
    length = int(round(seconds * args.fps))

    print(f'[{task_id}] H3 ref2va 单镜生成{"（fast 档）" if args.fast else ""}')
    print(f'  prompt: {args.prompt} ({seconds:.1f}s → {length} 帧)')
    print(f'  refs: {args.ref}')
    print(f'  output: {output_path}')
    print(f'  size: {args.width}x{args.height}  steps: {args.steps}')

    refs = prepare_refs(args.ref, args.name, clips_dir)

    # LLM 看图 → 角色描述（可选）
    descs = []
    if not args.no_describe:
        print('\n=== 角色描述（多模态 LLM）===')
        try:
            from utils.llm import LLMClient
            llm = LLMClient(config)
            for tmp_path, name, _cn in refs:
                print(f'  describing {name} ...')
                try:
                    descs.append(llm.describe_character(tmp_path, name=name))
                except Exception as e:
                    print(f'  ⚠ 描述失败({e})，回退用角色名')
                    descs.append('')
        except Exception as e:
            print(f'  ⚠ LLM 初始化失败({e})，跳过描述')
            descs = [''] * len(refs)
    else:
        descs = [''] * len(refs)

    h3_prompt = build_h3_prompt(prompt_text, refs, descs)
    print(f'\n=== H3 prompt（前 300 字）===\n{h3_prompt[:300]}...\n')

    h3 = ComfyClient(config=config, instance='h3')
    seed = args.seed
    print(f'=== 提交生成 === seed={seed or "random"} length={length} steps={args.steps} '
          f'ref_image_size={args.ref_image_size}')
    result = h3.generate_h3_ref2v(
        prompt=h3_prompt,
        ref_image_paths=[r[0] for r in refs],
        seed=seed,
        width=args.width,
        height=args.height,
        length=length,
        steps=args.steps,
        ref_image_size=args.ref_image_size,
        filename_prefix=f'vidance/h3_{task_id}',
        output_path=output_path,
    )

    meta = {
        'task_id': task_id,
        'prompt_file': args.prompt,
        'ref_images': args.ref,
        'ref_names': [r[1] for r in refs],
        'char_descs': descs,
        'h3_prompt': h3_prompt,
        'seconds': seconds,
        'length': length,
        'width': args.width,
        'height': args.height,
        'steps': args.steps,
        'fast': args.fast,
        'seed': result.get('seed'),
        'output': output_path,
        'status': 'completed',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    meta_path = os.path.join(task_dir, 'meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f'\n=== 完成 ===\n  成片: {output_path}\n  元数据: {meta_path}')


if __name__ == '__main__':
    main()
