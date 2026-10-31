#!/usr/bin/env python3
"""v18 M3 一镜到底（oneshot）：末帧回灌链式 I2V + 每段锚重注入 + LLM 连续运镜链.

零新模型：LLM 运镜脚本 + FLUX 首帧 + wan I2V（1280x704@24fps，97 帧≈4s/段）
+ ffmpeg 末帧提取/拼接。链式逻辑：段 N 末帧提取 → 段 N+1 I2V 首帧条件；
每段 prompt 重注角色锚+风格锚（防漂移累积），运镜链由 LLM 保证方向/速度连续。

用法：
  python utils/oneshot.py "穿越隧道的光" --duration 30
  python core/vidance.py auto "概念" --oneshot --duration 30
"""
import argparse
import json
import os
import subprocess
import time

W, H, FPS, LENGTH = 1280, 704, 24, 97
SEG_DUR = LENGTH / FPS  # ≈4.04s，段长硬约束（wan 上限内）
NEG = ('blurry, low quality, distorted, extra limbs, text, watermark, '
       'scene change, jump cut, static image')
MOTION_TAIL = 'continuous single take, smooth camera movement, no cuts'


def probe_dur(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                        '-of', 'csv=p=0', path], capture_output=True, text=True)
    return float(r.stdout.strip())


def last_frame(video, png):
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-sseof', '-0.1',
                    '-i', video, '-update', '1', '-frames:v', '1', png], check=True)
    return png


def plan(concept, duration, character=None):
    from agents.common.tools.llm import LLMClient
    nseg = max(2, round(duration / SEG_DUR))
    sys_p = (
        '你是长镜头调度导演。把概念设计成一镜到底的连续运镜片。\n'
        f'要求：\n1. 共 {nseg} 段，同一场景一镜到底，主体/环境全程一致（不得换景）\n'
        '2. 每段 desc：中文画面描述（20-40字），必须独立完整地重述主体外观'
        + (f'（主体：{character}，每段逐字复用同一句外观描述）' if character else '')
        + '与所在环境\n'
        '3. 每段 motion：英文运镜指令（五维运动域：push/pull/pan/tilt/dolly + 速度），'
        '段间方向与速度必须连续（如 push-in 后继续 push-in 或顺势 tilt），不得跳切\n'
        '4. style_en：全片统一画面风格（英文短语）；flux_prompt：第一段画面英文 prompt'
        '（含 style_en 与主体完整外观）\n'
        '只输出 JSON：{"title":.., "style_en":.., "flux_prompt":.., '
        '"segments":[{"desc":.., "motion":..}]}')
    plan = LLMClient().chat_json(
        [{'role': 'system', 'content': sys_p},
         {'role': 'user', 'content': f'概念：{concept}（目标总时长约 {duration} 秒）'}],
        temperature=0.6)
    segs = plan.get('segments') or []
    assert len(segs) >= 2, f'运镜脚本段数不足: {len(segs)}'
    return plan


def run_oneshot(concept, duration=30, character=None, out_dir=None):
    out_dir = out_dir or os.path.join('output', 'oneshot', time.strftime('os-%Y%m%d-%H%M%S'))
    os.makedirs(out_dir, exist_ok=True)
    plan_file = os.path.join(out_dir, 'plan.json')
    if os.path.isfile(plan_file):
        pl = json.load(open(plan_file))
        print(f'[oneshot] 复用 plan.json（{len(pl["segments"])} 段）')
    else:
        print(f'[oneshot] LLM 运镜脚本…（目标 {duration}s ≈ {max(2, round(duration / SEG_DUR))} 段）')
        pl = plan(concept, duration, character)
        json.dump(pl, open(plan_file, 'w'), ensure_ascii=False, indent=1)
        print(f'[oneshot] ✓ {pl["title"]} · {len(pl["segments"])} 段 · {pl["style_en"][:60]}')

    segs = pl['segments']
    anchor = f'{character}，' if character else ''
    style = pl.get('style_en', '')
    flux = os.path.join(out_dir, 'first.png')
    if not os.path.isfile(flux):
        from agents.generator.tools.comfy_api import ComfyClient
        fcli = ComfyClient(instance='flux')
        print('[oneshot] FLUX 首帧…')
        fcli.generate_flux_t2i(pl['flux_prompt'], width=W, height=H, output_path=flux)
        print('[oneshot] ✓ first.png')

    from agents.generator.tools.comfy_api import ComfyClient
    wan = ComfyClient(instance='wan')
    prev = None
    for i, seg in enumerate(segs, 1):
        segf = os.path.join(out_dir, f'seg_{i:02d}.mp4')
        if os.path.isfile(segf):
            print(f'[oneshot] 段{i} 已存在，跳过')
        else:
            prompt = f'{anchor}{seg["desc"]}，{style}。{seg["motion"]}, {MOTION_TAIL}'
            if prev is None:
                kf = flux
            else:
                kf = os.path.join(out_dir, f'kf_{i:02d}.png')
                last_frame(prev, kf)
            print(f'[oneshot] 段{i} I2V（{"首帧" if prev is None else "末帧回灌"}）…')
            wan.generate_i2v(prompt, kf, width=W, height=H, length=LENGTH, steps=20,
                             fps=FPS, negative_prompt=NEG, output_path=segf)
            print(f'[oneshot] 段{i} ✓ {probe_dur(segf):.1f}s')
        prev = segf

    final = os.path.join(out_dir, 'oneshot.mp4')
    lst = os.path.join(out_dir, 'concat.txt')
    with open(lst, 'w') as f:
        for i in range(1, len(segs) + 1):
            f.write(f"file 'seg_{i:02d}.mp4'\n")
    if not os.path.isfile(final):
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0',
                        '-i', lst, '-vf', f'scale={W}:{H},setsar=1,fps={FPS}',
                        '-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
                        '-pix_fmt', 'yuv420p', '-an', final], check=True)

    # 验收断言：段间拼缝 = 成片段 k+1 首帧 vs 回灌条件图 kf_{k+1}（验 I2V 首帧服从度）+ 成片规格
    import numpy as np
    from PIL import Image
    joints = []
    for i in range(1, len(segs)):
        subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', '0.05',
                        '-i', os.path.join(out_dir, f'seg_{i + 1:02d}.mp4'),
                        '-update', '1', '-frames:v', '1', '/tmp/_os_b.png'], check=True)
        a = np.asarray(Image.open('/tmp/_os_b.png').convert('L').resize((160, 88)), float) / 255
        b = np.asarray(Image.open(os.path.join(
            out_dir, f'kf_{i + 1:02d}.png')).convert('L').resize((160, 88)), float) / 255
        joints.append(round(float(np.abs(a - b).mean()), 3))
    dur = probe_dur(final)
    ok = all(j < 0.10 for j in joints)
    md = ['# 一镜到底（oneshot）prompt 清单', '',
          f'- 概念: {concept} · 目标 {duration}s · 实际 {dur:.1f}s（{len(segs)} 段 × {SEG_DUR:.2f}s）',
          f'- 角色锚: {character or "（无）"}（每段重注）', f'- 风格: {style}',
          f'- 拼缝 MAE（段k末帧 vs 段k+1首帧）: {joints} {"全部<0.10 ✓" if ok else "⚠ 存在跳变"}',
          '']
    for i, seg in enumerate(segs, 1):
        md.append(f'**段{i}** desc: {seg["desc"]}  \nmotion: {seg["motion"]}')
    open(os.path.join(out_dir, 'prompts.md'), 'w').write('\n'.join(md))
    json.dump({'duration': dur, 'joints_mae': joints, 'ok': ok, 'segments': len(segs)},
              open(os.path.join(out_dir, 'report.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'✓ 一镜到底 {final}（{dur:.1f}s，{len(segs)} 段，h264+yuv420p；拼缝 MAE {joints}）')
    return final


def main():
    ap = argparse.ArgumentParser(description='一镜到底：末帧回灌链式 I2V（v18 M3）')
    ap.add_argument('concept', help='视频概念（中文）')
    ap.add_argument('--duration', type=float, default=30, help='目标总时长秒（默认 30）')
    ap.add_argument('--character', default=None, help='主体外观描述（每段锚重注入）')
    ap.add_argument('--out', default=None, help='输出目录（默认 output/oneshot/时间戳）')
    a = ap.parse_args()
    run_oneshot(a.concept, duration=a.duration, character=a.character, out_dir=a.out)


if __name__ == '__main__':
    main()
