#!/usr/bin/env python3
"""Vidance 统一入口 — AI 有声短片生成

子命令:
  auto    概念 → LLM 编剧 → Wan/FLUX 生成 → 后处理（RIFE/LUT/BGM/STT）
  custom  参考图 + 预写脚本 → H3 ref2va 生成 → 后处理
  quick   纯 T2V，无角色锚无后处理
  concat  多视频拼接（硬切 / RIFE 过渡 / 交叉淡化）
  compose v10 时间线拼接（JSON 时间线：特效/转场/画中画/文字/混音）
  svg     v13（原 v15）SVG 流水线（概念→LLM 生成 SVG→逐帧渲染→mp4，纯 CPU）
  make    v12（原 v17）统一入口：--director llm|manual|scout × --generator wan|fast|svg|h3 排列组合

用法:
  python core/vidance.py auto "雪山日出：小狐狸的冒险" --character "红色小狐狸" --character-mode flux --stt
  python core/vidance.py auto "深海探险" --character "蓝色水母" --duration 60 --slowmo 2
  python core/vidance.py custom --ref input/doubao.jpg --ref input/naiwa.jpg --script input/prompt1.txt --lut cinematic --bgm dramatic
  python core/vidance.py quick "一只猫在月球上跳舞"
  python core/vidance.py concat clip1.mp4 clip2.mp4 clip3.mp4 -o merged.mp4 --transition rife
  python core/vidance.py svg --concept "鹈鹕骑自行车"
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pipeline import Pipeline
from core.custom_gen import run_custom, concat_videos
from core.postprocess import PostProcessor
from utils.fastline import FastLine


def cmd_auto(args):
    """auto 子命令：概念 → LLM 编剧 → 生成 → 后处理"""
    pipeline = Pipeline()
    if args.no_rife:
        pipeline.rife_config['enabled'] = False
    if args.no_color:
        pipeline.color_config['enabled'] = False
    if args.no_bgm:
        pipeline.bgm_config['enabled'] = False

    meta = pipeline.run(
        args.concept,
        output_path=args.output,
        character_desc=args.character,
        voice=args.voice,
        character_mode=args.character_mode,
        lut_override=args.lut,
        bgm_override=args.bgm,
        use_stt=args.stt,
        target_duration=args.duration,
        slowmo_override=args.slowmo,
        no_asset_reuse=args.no_asset_reuse,
        task_id=getattr(args, 'task_id', None),
    )
    print(f'\nDone: {meta["output"]}')


def cmd_custom(args):
    """custom 子命令：参考图 + 脚本 → H3 ref2va → 后处理"""
    post_kwargs = dict(
        no_rife=args.no_rife,
        lut_override=args.lut,
        no_color=args.no_color,
        bgm_override=args.bgm,
        no_bgm=args.no_bgm,
        use_stt=args.stt,
    )
    meta = run_custom(
        ref_images=args.ref,
        script_path=args.script,
        output_path=args.output,
        ref_image_size=args.ref_image_size,
        post_kwargs=post_kwargs,
    )
    print(f'\nDone: {meta["output"]}')


def cmd_quick(args):
    """quick 子命令：纯 T2V，无角色无后处理"""
    pipeline = Pipeline()
    pipeline.rife_config['enabled'] = False
    pipeline.color_config['enabled'] = False
    pipeline.bgm_config['enabled'] = False

    meta = pipeline.run(
        args.concept,
        output_path=args.output,
        character_desc=None,
        voice=args.voice,
        character_mode='auto',
        lut_override=None,
        bgm_override=None,
        use_stt=False,
    )
    print(f'\nDone: {meta["output"]}')


def _concat_cut(clips, output_path):
    """硬切拼接（ffmpeg concat demuxer, stream copy）"""
    list_path = output_path.replace('.mp4', '_concat.txt')
    with open(list_path, 'w') as f:
        for vp in clips:
            f.write(f"file '{os.path.abspath(vp)}'\n")
    cmd = [
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', list_path,
        '-c', 'copy', output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    os.remove(list_path)
    return output_path


def _concat_crossfade(clips, output_path, duration=0.5):
    """交叉淡化拼接（moviepy）"""
    from moviepy import VideoFileClip, concatenate_videoclips
    from moviepy.video.fx import CrossFadeIn

    video_clips = []
    for i, vp in enumerate(clips):
        vc = VideoFileClip(vp)
        if i > 0:
            vc = vc.with_effects([CrossFadeIn(duration)])
        video_clips.append(vc)

    final = concatenate_videoclips(video_clips, method='compose')
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    final.write_videofile(output_path, codec='libx264', audio_codec='aac',
                          fps=24, logger=None)
    final.close()
    for vc in video_clips:
        vc.close()
    return output_path


def cmd_concat(args):
    """concat 子命令：多视频拼接"""
    clips = args.videos
    for vp in clips:
        if not os.path.isfile(vp):
            print(f'错误: 文件不存在: {vp}')
            sys.exit(1)

    output_path = args.output
    if output_path is None:
        output_path = os.path.join(os.path.dirname(clips[0]), 'merged.mp4')
    if not os.path.isabs(output_path):
        from core.pipeline import CONFIG_PATH
        config_path = CONFIG_PATH
        with open(config_path) as f:
            config = json.load(f)
        output_path = os.path.join(config['output_dir'], output_path)

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    transition = args.transition
    print(f'拼接 {len(clips)} 个视频 → {output_path} (transition={transition})')

    if transition == 'cut':
        _concat_cut(clips, output_path)
    elif transition == 'rife':
        from utils.config_loader import load_config as _load
        config = _load()
        post = PostProcessor(config)
        tmpdir = tempfile.mkdtemp(prefix='vidance_concat_')
        try:
            transition_types = ['rife'] * (len(clips) - 1)
            transitions = post.generate_transitions(clips, tmpdir, 'concat',
                                                     transition_types=transition_types)
            concat_videos(clips, output_path, transitions)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
    elif transition == 'crossfade':
        _concat_crossfade(clips, output_path, duration=args.crossfade_duration)

    dur = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'csv=p=0', output_path],
        capture_output=True, text=True).stdout.strip()
    print(f'\nDone: {output_path} ({float(dur):.1f}s)')


def cmd_hot(args):
    """hot 子命令：爬热点 → LLM scout 选题 → fast 出片（一步到位，固定流程）"""
    from utils.crawler import Crawler
    from datetime import datetime

    fl = FastLine()
    llm = fl.llm

    # 1) 爬实时热点
    print('=== [hot] 爬实时热点 ===')
    topics = Crawler().fetch_hot_topics(top_per_source=args.top_each)

    # 2) LLM 自动选题
    print(f'=== [hot] LLM scout 选题 ===')
    cands = llm.scout_topics(topics, account_type=args.account, n_candidates=args.n_cand)
    for c in cands:
        print(f'  [{c.get("predicted_score")}] {c.get("concept")}')
    top = cands[0]
    source = top.get('source_topic', '')
    date = datetime.now().strftime('%Y-%m-%d')
    print(f'选中: {top["predicted_score"]}分 | 源自: {date}: {source}')

    # 3) fast 出片
    meta = fl.run(
        top['concept'],
        images_source=args.images_source,
        n=args.images_count,
        voice=args.voice,
        bgm_override=args.bgm,
        lut_override=args.lut,
        use_stt=args.stt,
        slowmo=args.slowmo,
        source_topic=source,
        trend_date=date,
        show_source=not args.no_source,
        task_id=args.task_id,
        effects=getattr(args, 'effects', 'off'),
    )
    print(f'\nDone: {meta["output"]}')


def cmd_fast(args):
    """fast 子命令：图片 + 运镜动效组成视频，跳过视频模型（v4 M6 快速链路）"""
    fl = FastLine()
    meta = fl.run(
        args.concept, output_path=args.output, images_dir=args.images,
        n=args.images_count, voice=args.voice, speed=args.speed,
        motion=args.motion, seconds=args.seconds, task_id=args.task_id,
        no_rife=args.no_rife, lut_override=args.lut, no_color=args.no_color,
        bgm_override=args.bgm, no_bgm=args.no_bgm, use_stt=args.stt,
        slowmo=args.slowmo, images_source=args.images_source,
        source_topic=args.source_topic, trend_date=args.trend_date,
        show_source=not args.no_source, effects=getattr(args, 'effects', 'off'),
    )
    print(f'\nDone: {meta["output"]}')


def cmd_ask(args):
    """ask 子命令：prompt 多轮核实（v6）——交互式补齐缺失维度 → 输出增强概念。

    若概念已完整则直接回传；否则按轮追问：每轮把当前问题逐条问完，
    合并成一条 reply 重新评估（≤3 轮）。--out 可存增强概念。
    """
    from utils.dialog import DialogManager, MAX_ROUNDS
    dm = DialogManager()
    s = dm.start(args.concept)
    print(f'\n[ask] 完整度评估: {s["status"]}')
    print(f'  缺失: {s["missing"]}')
    cur = s
    rounds = 0
    while (cur['status'] not in ('COMPLETE', 'LOCKED')
           and cur.get('questions') and rounds < MAX_ROUNDS):
        # 本轮：把当前轮的问题逐条问完
        answers = []
        quit_ask = False
        for q in cur['questions']:
            print(f'\n问: {q}')
            try:
                ans = input('答: ').strip()
            except EOFError:
                print('\n(输入结束)')
                quit_ask = True
                break
            if ans.lower() in ('q', 'quit', 'exit'):
                quit_ask = True
                break
            # "随便/都可以"类回答跳过（不进概念，也不阻塞本轮）
            if ans and ans not in ('随便', '都可以', '随便吧'):
                answers.append(ans)
        if quit_ask or not answers:
            break
        # 合并本轮回答 → 一次重评
        cur = dm.reply(cur['dialog_id'], '；'.join(answers))
        rounds += 1
    concept = dm.locked_concept(cur['dialog_id'])
    print(f'\n[ask] 状态: {cur["status"]}')
    print(f'增强概念: {concept}')
    out = args.out
    if out:
        with open(out, 'w', encoding='utf-8') as f:
            f.write(concept)
        print(f'已存: {out}')
    return concept



def _compose_default_out():
    """compose 默认输出：<config.output_dir>/<timestamp>/final.mp4"""
    import time, os
    root = '/mnt/dataset/zxy/vidance/output'
    try:
        from core.pipeline import load_config
        root = load_config().get('output_dir') or root
    except Exception:
        pass
    d = os.path.join(root, time.strftime('%Y%m%d_%H%M%S'))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, 'final.mp4')


def cmd_compose(args):
    # v10 timeline compose
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if args.init:
        import json as _j
        from utils.compose import FFMPEG
        tmpl = {
            'output': 'out.mp4', 'width': 1280, 'height': 704,
            'main': [{'id': 'c1', 'type': 'video', 'source': 'clip1.mp4',
                      'transition_in': {'kind': 'fade', 'duration': 0.4}}],
            'overlay': [{'id': 't1', 'type': 'text', 'text': 'title',
                          'start': 0.5, 'duration': 3, 'fontsize': 48,
                          'fontcolor': 'white'}],
            'audio': [{'id': 'a1', 'source': 'bgm.wav', 'start': 0,
                        'volume': 0.3, 'ducking': True}],
        }
        _j.dump(tmpl, open(args.init, 'w'), ensure_ascii=False, indent=2)
        print('template ->', args.init)
        return
    from utils.compose import run_timeline, _media_kind, json as _j
    if args.clips:
        els = []
        for i, c in enumerate(args.clips):
            els.append({'id': 'c%d' % i, 'type': _media_kind(c), 'source': c,
                        'transition_in': None if i == 0 else
                        {'kind': args.transition, 'duration': args.transition_duration}})
        tl = {'output': _compose_default_out(), 'main': els}
        out = run_timeline(tl, args.output)
    elif args.timeline:
        out = run_timeline(args.timeline, args.output)
    else:
        print('usage: compose timeline.json [-o out] | compose a.mp4 b.mp4 --transition fade | compose --init tmpl.json')
        return
    print(out)


def cmd_svg(args):
    """v13（原 v15）SVG 流水线：概念 → LLM 生成 SVG → 无头浏览器逐帧渲染 → mp4（纯 CPU）"""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils import svg_pipeline as sp

    out = args.output
    if out is None:
        root = _compose_default_out()
        out = os.path.join(os.path.dirname(root), 'svg.mp4')
    if not os.path.isabs(out):
        from core.pipeline import load_config
        out = os.path.join(load_config()['output_dir'], out)

    voiced = bool(getattr(args, 'voice', None)) or bool(getattr(args, 'say', None))
    if voiced:
        res = sp.narrate_to_mp4(concept=args.concept, n=args.n, say=args.say,
                                out_path=out, width=args.width, height=args.height,
                                fps=args.fps, model=args.model,
                                lut=getattr(args, 'lut', None),
                                bgm=getattr(args, 'bgm', None))
        print(res['output'])
    elif args.concept:
        res = sp.concept_to_mp4(args.concept, out_path=out, duration=args.duration,
                                width=args.width, height=args.height, fps=args.fps,
                                model=args.model)
        print(res['mp4'])
    elif args.svg:
        if args.still:
            print(sp.render_still(svg_path=args.svg, out_path=os.path.splitext(out)[0] + '.png',
                                  width=args.width, height=args.height, at=args.at))
        elif args.frames:
            print(sp.dump_frames(svg_path=args.svg,
                                 out_dir=args.frames_dir or os.path.splitext(out)[0] + '_frames',
                                 width=args.width, height=args.height, fps=args.fps,
                                 duration=args.duration))
        else:
            print(sp.svg_to_mp4(svg_path=args.svg, out_path=out, width=args.width,
                                height=args.height, fps=args.fps, duration=args.duration))
    else:
        print('usage: svg --concept "鹈鹕骑自行车" | svg --svg scene.svg [--still|--frames]')


def cmd_make(args):
    """v12（原 v17）M2 统一入口：--director × --generator 排列组合路由到现有实现（子命令变别名）"""
    gen = args.generator or 'wan'
    director = args.director or ('manual' if (args.say or args.prompt or args.script) else 'llm')
    concept = args.concept or ''

    # D3 导演：爬热点 → scout 选题 → 得 concept 继续（等效 hot 的选概念半段）
    if director == 'scout':
        from utils.crawler import Crawler
        from core.pipeline import load_config
        from utils.llm import LLMClient
        topics = Crawler().fetch_hot_topics(top_per_source=15)
        cands = LLMClient(load_config()).scout_topics(
            topics, account_type=args.account or '影视解说', n_candidates=3)
        if cands:
            concept = cands[0]['concept']
            print(f'[D3 scout] 选题：{concept}（{cands[0].get("predicted_score")}分）')
    if director == 'manual' and not concept:
        if args.prompt:
            concept = open(args.prompt, encoding='utf-8').read().strip()[:40]
        elif args.say:
            concept = args.say[0][:40]
    if not concept and gen != 'h3':
        print('usage: make 概念 [--director llm|manual|scout] [--generator wan|fast|svg|h3]')
        return

    # G4 svg：D1(--say)/D2 → 有声(S5)/无声
    if gen == 'svg':
        from utils import svg_pipeline as sp
        voiced = bool(args.voice) or bool(args.say)
        out = _resolve_out(args.output, 'svg')
        if voiced:
            res = sp.narrate_to_mp4(concept, n=args.n or 3, say=args.say, out_path=out,
                                    voice=args.voice, lut=args.lut, bgm=args.bgm)
            print(res['output'])
        else:
            print(sp.concept_to_mp4(concept, out_path=out,
                                    duration=args.duration or 3.0)['mp4'])
        return

    # G3 fast：营销号爬图/生图 + Ken Burns（scout 已在上面选好概念 = hot）
    if gen == 'fast':
        cmd_fast(_ns(args, concept=concept))
        return

    # G1 h3：手动导演（整段式 prompt + 参考图，异步慢通道；多镜 --script 走 custom 子命令）
    if gen == 'h3':
        import subprocess as _sp2
        if args.script and not args.prompt:
            ns = _ns(args, ref=args.ref or [])
            ns.script, ns.ref_image_size = args.script, 'match'
            cmd_custom(ns)
            return
        if not args.prompt:
            print('make --generator h3 需要 --prompt <整段式.txt> 或 --script <多镜脚本>')
            return
        cmd = [sys.executable,
               os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'utils', 'h3_prompt_video.py'),
               '--prompt', args.prompt]
        for r in (args.ref or []):
            cmd += ['--ref', r]
        if args.output:
            cmd += ['-o', args.output]
        if args.fast:
            cmd.append('--fast')
        _sp2.run(cmd)
        return

    # G2 wan：D2 自动（有角色→auto 全管线；无→quick 裸 T2V）
    if args.character:
        cmd_auto(_ns(args, concept=concept))
    else:
        cmd_quick(_ns(args, concept=concept))


def _resolve_out(out, tag):
    from core.pipeline import load_config
    from datetime import datetime as _dt
    if not out:
        out = f'make_{tag}_{_dt.now().strftime("%H%M%S")}.mp4'
    if not os.path.isabs(out):
        out = os.path.join(load_config()['output_dir'], out)
    return out


def _ns(args, **over):
    """把 make 命名空间补齐为 fast/auto/quick/custom 所需字段（缺失给默认）。"""
    import argparse
    d = dict(vars(args))
    d.update(over)
    d.update(n=d.get('n') or 1, images=d.get('images'),
             images_count=d.get('n') or 3, effects='off', motion=None, seconds=None,
             speed=1.0, slowmo=None, task_id=None,
             character=d.get('character'), character_mode='auto',
             no_asset_reuse=False, ref_image_size='match',
             images_source=d.get('images_source') or 'crawl',
             source_topic=None, trend_date=None, no_source=True,
             duration=d.get('duration'))
    d.setdefault('stt', False)
    d.setdefault('task_id', None)
    for k in ('script', 'ref'):
        d.setdefault(k, None)
    return argparse.Namespace(**d)


def cmd_agent(args):
    """agent 子命令（v11，原 v13）：list / run / chain。"""
    import json as _json
    from agents.runtime import load_all, run_chain
    reg = load_all()
    if args.action == 'list':
        for a in sorted(reg.values(), key=lambda x: (x['layer'], x['name'])):
            print('%-28s [%s]%s %s' % (a['name'], a['layer'],
                                       ' [GPU]' if a['needs_gpu'] else '', a['desc']))
        return
    if args.action == 'run':
        from agents.base import run_agent
        from agents.blackboard import AgentBoard
        res = run_agent(args.name, _json.loads(args.with_json),
                        board=AgentBoard(), task_id=args.task_id)
        print(_json.dumps(res.to_dict(), ensure_ascii=False, indent=2, default=str))
        if not res.ok:
            sys.exit(1)
        return
    if args.action == 'chain':
        steps = args.steps
        if os.path.isfile(steps):
            steps = open(steps, encoding='utf-8').read()
        data = _json.loads(steps)
        steps = data.get('steps', data.get('chain', data))
        out = run_chain(steps, ctx=data.get('ctx'), task_id=args.task_id)
        print(_json.dumps(out, ensure_ascii=False, indent=2, default=str))
        if not out['ok']:
            sys.exit(1)


def build_parser():
    parser = argparse.ArgumentParser(
        prog='vidance',
        description='Vidance — AI 有声短片生成',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest='command', required=True, metavar='<command>')

    # ── 共享参数组 ──
    output_parent = argparse.ArgumentParser(add_help=False)
    output_parent.add_argument('-o', '--output', default=None,
                               help='输出视频路径（相对路径自动 resolve 到 output_dir）')

    post_parent = argparse.ArgumentParser(add_help=False)
    post_parent.add_argument('--no-rife', action='store_true',
                             help='禁用 RIFE 镜头间过渡')
    post_parent.add_argument('--lut', default=None,
                             choices=['cinematic', 'warm', 'cool', 'vintage', 'vivid', 'soft'],
                             help='调色 LUT 风格（不指定则 LLM 自动选择）')
    post_parent.add_argument('--no-color', action='store_true',
                             help='禁用 LUT 调色')
    post_parent.add_argument('--bgm', default=None,
                             choices=['calm', 'uplifting', 'mysterious', 'dramatic', 'playful', 'epic'],
                             help='BGM mood（不指定则 LLM 自动选择）')
    post_parent.add_argument('--no-bgm', action='store_true',
                             help='禁用背景音乐')
    post_parent.add_argument('--stt', action='store_true',
                             help='使用 faster-whisper STT 字幕对齐（覆盖 TTS 时间戳）')

    # ── auto 子命令 ──
    p_auto = sub.add_parser('auto', parents=[output_parent, post_parent],
                            help='概念 → LLM 编剧 → Wan/FLUX 生成 → 后处理')
    p_auto.add_argument('concept', help='视频概念（中文）')
    p_auto.add_argument('--character', default=None,
                        help='角色描述（中文，如：穿红斗篷的少年）')
    p_auto.add_argument('--character-mode', default='auto',
                        choices=['auto', '3dgs', 'mesh', 'flux'],
                        help='角色锚模式: auto(3DGS→flux降级) / 3dgs / mesh(Hunyuan3Dv2) / flux (默认: auto)')
    p_auto.add_argument('--no-asset-reuse', action='store_true',
                        help='禁用资产库复用，强制重新重建 3D 资产')
    p_auto.add_argument('--voice', default=None,
                        help='TTS 音色 (如 edge-moe, cosy-default)')
    p_auto.add_argument('--duration', type=float, default=None,
                        help='目标总时长（秒），动态调整镜头数（解锁长片，不指定则默认 2-5 镜）')
    p_auto.add_argument('--slowmo', type=int, default=None,
                        help='全局慢动作帧倍率（如 2 = 2x 慢放，覆盖所有镜头）')
    p_auto.add_argument('--task-id', default=None,
                        help='外部指定 task_id（调度器传入），不指定则自动生成时间戳')
    p_auto.set_defaults(func=cmd_auto)

    # ── custom 子命令 ──
    p_custom = sub.add_parser('custom', parents=[output_parent, post_parent],
                              help='参考图 + 预写脚本 → H3 ref2va 生成 → 后处理')
    p_custom.add_argument('--ref', action='append', required=True,
                          help='角色参考图路径（可重复指定多个角色）')
    p_custom.add_argument('--script', required=True,
                          help='分镜脚本文件路径（prompt.txt 格式）')
    p_custom.add_argument('--ref-image-size', choices=['match', 'max'], default='match',
                          help='H3 参考图尺寸: match (更快) / max (2048px, 最佳身份保真)')
    p_custom.set_defaults(func=cmd_custom)

    # ── quick 子命令 ──
    p_quick = sub.add_parser('quick', parents=[output_parent],
                             help='纯 T2V，无角色锚无后处理')
    p_quick.add_argument('concept', help='视频概念（中文）')
    p_quick.add_argument('--voice', default=None,
                         help='TTS 音色 (如 edge-moe)')
    p_quick.set_defaults(func=cmd_quick)

    # ── concat 子命令 ──
    p_concat = sub.add_parser('concat', parents=[output_parent],
                              help='多视频拼接（硬切 / RIFE 过渡 / 交叉淡化）')
    p_concat.add_argument('videos', nargs='+',
                          help='待拼接的视频文件路径列表')
    p_concat.add_argument('--transition', default='cut',
                          choices=['cut', 'rife', 'crossfade'],
                          help='过渡方式: cut(硬切) / rife(光流插帧) / crossfade(交叉淡化) (默认: cut)')
    p_concat.add_argument('--crossfade-duration', type=float, default=0.5,
                          help='交叉淡化时长（秒，仅 --transition crossfade 时生效）')
    p_concat.set_defaults(func=cmd_concat)

    # ── hot 子命令（爬热点→选题→出片，一步到位） ──
    p_hot = sub.add_parser('hot', parents=[output_parent],
                           help='爬实时热点 → LLM scout 选题 → fast 出片（固定流程，一步到位）')
    p_hot.add_argument('-n', '--images-count', type=int, default=5,
                       help='图片/段落数（默认 5）')
    p_hot.add_argument('--top-each', type=int, default=10,
                       help='每个来源抓取热点条数（默认 10）')
    p_hot.add_argument('--n-cand', type=int, default=6,
                       help='scout 候选数（默认 6）')
    p_hot.add_argument('--account', default='热门资讯',
                       help='账号定位（默认 热门资讯，可改 影视解说/萌宠/情感 等）')
    p_hot.add_argument('--images-source', default='crawl',
                       choices=['crawl', 'flux'],
                       help='图片来源: crawl(爬图+相关性校验，默认) / flux(FLUX 文生图)')
    p_hot.add_argument('--voice', default=None, help='TTS 音色')
    p_hot.add_argument('--bgm', default=None, help='BGM mood')
    p_hot.add_argument('--lut', default=None, help='LUT 风格')
    p_hot.add_argument('--stt', action='store_true', help='STT 字幕对齐')
    p_hot.add_argument('--slowmo', type=int, default=None,
                       help='RIFE 慢放帧倍率（另出 final_slow.mp4，原片保留）')
    p_hot.add_argument('--no-source', action='store_true',
                       help='不烧录热搜来源角标')
    p_hot.add_argument('--effects', default='off',
                       choices=['auto', 'off'],
                       help='v5 剪辑特效: auto(LLM 选) / off(关闭，默认)')
    p_hot.add_argument('--task-id', default=None)
    p_hot.set_defaults(func=cmd_hot)

    # ── fast 子命令（v4 M6 快速营销号链路） ──
    p_fast = sub.add_parser('fast', parents=[output_parent],
                            help='图片+运镜动效组成视频，跳过视频模型（快速营销号链路）')
    p_fast.add_argument('concept', help='热点概念/旁白主题（中文）')
    p_fast.add_argument('--images', default=None,
                        help='图片目录（有图则用，否则按 --images-source 出图）')
    p_fast.add_argument('--images-source', default='crawl',
                        choices=['crawl', 'flux'],
                        help='图片来源: crawl(必应爬图，默认) / flux(FLUX 文生图)')
    p_fast.add_argument('--source-topic', default=None,
                        help='对应热搜标题（写进 meta + 片头水印，便于验证真实性）')
    p_fast.add_argument('--trend-date', default=None,
                        help='热搜日期（如 2026-09-14，默认今天；写进 meta + 片头）')
    p_fast.add_argument('--no-source', action='store_true',
                        help='不烧录热搜来源水印')
    p_fast.add_argument('--effects', default='off',
                        choices=['auto', 'off'],
                        help='v5 剪辑特效: auto(LLM 逐段选特效) / off(关闭，默认)')
    p_fast.add_argument('-n', '--images-count', type=int, default=5,
                        help='图片/段落数（默认 5）')
    p_fast.add_argument('--voice', default=None, help='TTS 音色')
    p_fast.add_argument('--speed', type=float, default=1.0, help='旁白语速')
    p_fast.add_argument('--motion', default=None,
                        choices=['pan', 'zoom-in', 'zoom-out'],
                        help='统一运镜（默认 LLM 每段自选 pan/zoom）')
    p_fast.add_argument('--seconds', type=float, default=None,
                        help='每段时长（秒，默认按旁白对齐）')
    p_fast.add_argument('--slowmo', type=int, default=None,
                        help='RIFE slowmo 帧倍率（需 GPU2:8189，默认关闭）')
    p_fast.add_argument('--no-rife', action='store_true', help='禁用 RIFE 过渡')
    p_fast.add_argument('--lut', default=None,
                        choices=['cinematic', 'warm', 'cool', 'vintage', 'vivid', 'soft'],
                        help='LUT 调色风格')
    p_fast.add_argument('--no-color', action='store_true', help='禁用调色')
    p_fast.add_argument('--bgm', default=None,
                        choices=['calm', 'uplifting', 'mysterious', 'dramatic', 'playful', 'epic'],
                        help='BGM mood（默认 LLM 选）')
    p_fast.add_argument('--no-bgm', action='store_true', help='禁用 BGM')
    p_fast.add_argument('--stt', action='store_true', help='STT 字幕对齐')
    p_fast.add_argument('--task-id', default=None,
                        help='外部指定 task_id（调度器传入）')
    p_fast.set_defaults(func=cmd_fast)

    # ── ask 子命令（v6 prompt 多轮核实） ──
    p_ask = sub.add_parser('ask', help='prompt 多轮核实：交互补齐缺失维度 → 增强概念')
    p_ask.add_argument('concept', help='原始概念（中文）')
    p_ask.add_argument('--out', default=None,
                       help='输出增强概念到文件（否则打印 stdout）')
    p_ask.set_defaults(func=cmd_ask)

    # compose zilingmian (v10 timeline)
    p_compose = sub.add_parser('compose',
        help='v10 timeline compose: JSON timeline -> video (trim/rate/fx/xfade/pip/text/audio)')
    p_compose.add_argument('timeline', nargs='?', default=None,
                          help='timeline JSON path')
    p_compose.add_argument('-o', '--output', default=None, help='output path (override)')
    p_compose.add_argument('--init', default=None, help='write template then exit')
    p_compose.add_argument('clips', nargs='*', help='quick: list clips to concat')
    p_compose.add_argument('--transition', default='fade')
    p_compose.add_argument('--transition-duration', type=float, default=0.4)
    p_compose.set_defaults(func=cmd_compose)

    # ── svg 子命令（v13（原 v15）SVG 流水线，纯 CPU） ──
    p_svg = sub.add_parser('svg',
        help='v13（原 v15）SVG 流水线：概念→LLM 生成 SVG→逐帧渲染→mp4（纯 CPU，秒级）')
    p_svg.add_argument('--concept', default=None, help='概念（一键：LLM 生成 SVG→mp4）')
    p_svg.add_argument('--svg', default=None, help='SVG 文件路径（渲染模式）')
    p_svg.add_argument('-o', '--output', default=None, help='输出 mp4 路径')
    p_svg.add_argument('--duration', type=float, default=3.0, help='动画时长（秒）')
    p_svg.add_argument('--width', type=int, default=800)
    p_svg.add_argument('--height', type=int, default=450)
    p_svg.add_argument('--fps', type=int, default=24)
    p_svg.add_argument('--model', default=None, help='LLM 模型（一键模式）')
    p_svg.add_argument('--still', action='store_true', help='只渲染单帧 PNG（调试）')
    p_svg.add_argument('--at', type=float, default=0.0, help='--still 时刻（秒）')
    p_svg.add_argument('--frames', action='store_true', help='抽帧成 PNG 序列')
    p_svg.add_argument('--frames-dir', default=None, help='抽帧输出目录')
    p_svg.add_argument('--voice', default=None, help='S5 有声模式：配音音色')
    p_svg.add_argument('--say', action='append', default=None, help='S5 有声模式：手动旁白段（可重复）')
    p_svg.add_argument('-n', type=int, default=3, help='S5：LLM 旁白段数（默认 3）')
    p_svg.add_argument('--lut', default=None, help='S5：调色风格')
    p_svg.add_argument('--bgm', default=None, help='S5：BGM mood')
    p_svg.set_defaults(func=cmd_svg)

    # ── make 子命令（v12（原 v17）M2 三排正交统一入口） ──
    p_make = sub.add_parser('make', parents=[output_parent, post_parent],
                            help='统一入口：--director llm|manual|scout × --generator wan|fast|svg|h3')
    p_make.add_argument('concept', nargs='?', default=None, help='概念（manual/scout 可省）')
    p_make.add_argument('--director', default=None, choices=['llm', 'manual', 'scout'],
                        help='导演层（默认：有 --say/--prompt 即 manual，否则 llm）')
    p_make.add_argument('--generator', default=None, choices=['wan', 'fast', 'svg', 'h3'],
                        help='生成层（默认 wan：带 --character 走 auto，不然 quick）')
    p_make.add_argument('--voice', default=None, help='配音音色')
    p_make.add_argument('--say', action='append', default=None, help='手动旁白段（可重复，D1）')
    p_make.add_argument('-n', dest='n', type=int, default=None, help='段数')
    p_make.add_argument('--duration', type=float, default=None, help='时长（svg 无声段渲染秒数）')
    p_make.add_argument('--prompt', default=None, help='D1 整段式 prompt 文件（h3）')
    p_make.add_argument('--script', default=None, help='D1 多镜脚本（h3→custom）')
    p_make.add_argument('--ref', action='append', default=None, help='参考图（可重复）')
    p_make.add_argument('--fast', action='store_true', help='h3 快速档')
    p_make.add_argument('--character', default=None, help='角色描述（wan→auto）')
    p_make.add_argument('--images-source', dest='images_source', default=None,
                        choices=['crawl', 'flux'], help='fast 图源')
    p_make.add_argument('--account', default=None, help='scout 账号定位')
    p_make.set_defaults(func=cmd_make)

    # ── agent（v11，原 v13）──
    p_agent = sub.add_parser('agent', help='v11（原 v13）多智能体：list / run / chain')
    agent_sub = p_agent.add_subparsers(dest='action', required=True)
    agent_sub.add_parser('list', help='列出已注册 Agent')
    p_arun = agent_sub.add_parser('run', help='运行单个 Agent')
    p_arun.add_argument('name')
    p_arun.add_argument('--with', dest='with_json', default='{}',
                        help='参数 JSON，如 \'{"concept":"猫"}\'')
    p_arun.add_argument('--task-id', default='cli')
    p_achain = agent_sub.add_parser('chain', help='运行 Agent 链')
    p_achain.add_argument('steps', help='steps JSON（字符串或 .json 文件路径）')
    p_achain.add_argument('--task-id', default='cli')
    p_agent.set_defaults(func=cmd_agent)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
