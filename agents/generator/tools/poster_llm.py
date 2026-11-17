#!/usr/bin/env python3
"""v22 M1（poster 线）：概念 → LLM → 海报 JSON 规划（标题/标语/底板提示词/生灵分区）

分工（照抄 v13 blender 架构）：
  - LLM 只出**结构化 JSON**（title/subtitle/tagline/bg_prompt/creatures），不产像素 —— 可控、可容错
  - 像素由 poster_pipeline.PosterLine 数据驱动合成（FLUX 底板 + SAM 抠图 + PIL 排版）
  - 生灵（creatures）分区白名单：back-center（后景全息）/ mid-right（中景渐隐）/ front-left / front-right

用法：
  python agents/generator/tools/poster_llm.py "紫色雨夜霓虹月亮下的红蓝猫" -o /tmp/plan.json
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

from agents.generator.tools.ppt_llm import extract_json

ZONES = ('back-center', 'mid-right', 'mid-left', 'front-left', 'front-right')
DEFAULT_ZONE = 'front-right'

PLAN_SYS = """你是电影海报策划师。根据主题规划一张竖版宣传海报的内容规划（JSON）。
海报由底板（文生图背景）+ 1-3 个生灵立绘 + 大标题 + 副标题 + 中文标语 + 底部信息栏组成。
只输出 JSON，不要 markdown 代码块，格式：
{{"title": "VIDANCE",
  "subtitle": "AI VIDEO CREATION AGENT",
  "tagline": "从一句话，到一整部片",
  "bg_prompt": "英文 FLUX 背景提示词（scene only, no text, no letters, no watermark；描述天气/光线/主色调/地标氛围）",
  "creatures": [
    {{"name": "红蓝双色猫", "prompt": "英文立绘提示词（full body, centered, simple dark background, no text）",
      "zone": "front-left", "height": 0.36}},
    {{"name": "柴犬", "prompt": "...", "zone": "mid-right", "height": 0.24}}
  ]}}
字段说明：
- title: 主标题（品牌词/英文/拼音，≤12 字符，会被拉大加色散与辉光）；subtitle: 英文副标题（≤32 字符，可空字符串）
- tagline: 中文标语（≤14 字，副标题下方，会加紫色辉光）
- bg_prompt: 必须是英文，禁止出现任何文字/字母/水印字样；体现主题的氛围与主色
- creatures: 0-3 个；zone 白名单 {zones}（back=后景在全息渐隐，mid=中景，front=前景最大最清晰）
- creatures[].height: 相对画布高的比例（0.15-0.45，back 建议小、front 建议大）
- 没有合适生灵就给空数组（纯风景+排版海报也可以）""".format(zones='/'.join(ZONES))


def _norm_plan(raw: dict, concept: str) -> dict:
    """LLM 输出规范化：分区白名单、数值钳制、生灵数量兜底（对标 blender _norm_scene）。"""
    plan = {
        'title': str(raw.get('title', '')).strip()[:12] or 'VIDANCE',
        'subtitle': str(raw.get('subtitle', '')).strip()[:32],
        'tagline': str(raw.get('tagline', '')).strip()[:14] or concept[:12],
        'bg_prompt': str(raw.get('bg_prompt', '')).strip()[:480] or concept[:80],
        'creatures': [],
    }
    for c in (raw.get('creatures') or [])[:3]:
        if not isinstance(c, dict):
            continue
        name = str(c.get('name', '')).strip()[:24]
        prompt = str(c.get('prompt', '')).strip()[:400]
        if not prompt:
            continue
        zone = str(c.get('zone', DEFAULT_ZONE)).strip().lower()
        if zone not in ZONES:
            zone = DEFAULT_ZONE
        try:
            height = min(0.45, max(0.15, float(c.get('height', 0.3))))
        except (TypeError, ValueError):
            height = 0.3
        if zone == 'back-center':
            height = min(height, 0.30)
        plan['creatures'].append({'name': name, 'prompt': prompt,
                                  'zone': zone, 'height': height})
    if len(plan['creatures']) >= 2:
        zs = [c['zone'] for c in plan['creatures']]
        if len(set(zs)) < len(zs):  # 分区冲突：后面的挤到空位
            used = set()
            for c in plan['creatures']:
                if c['zone'] in used:
                    c['zone'] = next(z for z in ZONES if z not in used)
                used.add(c['zone'])
    return plan


def default_plan(concept: str) -> dict:
    """LLM 不可用时的内置兜底（纯风景+排版，无生灵）。"""
    return _norm_plan({'title': 'VIDANCE', 'subtitle': 'AI VIDEO CREATION AGENT',
                       'tagline': concept[:12], 'bg_prompt': concept[:80],
                       'creatures': []}, concept)


def plan_poster(concept: str, model: str = None, on_chunk=None,
                style_hint: str = None) -> dict:
    """概念 → LLM → 海报 JSON。解析失败时用内置默认（纯风景+排版）。"""
    from utils.config_loader import load_config
    llm = None
    try:
        from utils.llm import LLMClient
        llm = LLMClient(load_config())
    except Exception:
        pass
    sys_p = PLAN_SYS
    if style_hint:
        sys_p += f'\n海报风格要求：{str(style_hint).strip()}'
    messages = [{'role': 'system', 'content': sys_p},
                {'role': 'user', 'content': f'海报主题：{concept}'}]
    if llm is not None:
        try:
            from agents.generator.tools.svg_llm import _chat_stream
            text = _chat_stream(llm, messages, model=model, temperature=0.5,
                                read_timeout=20, on_chunk=on_chunk)
            return _norm_plan(extract_json(text), concept)
        except Exception as e:
            print(f'  ⚠ 海报规划失败（{e}），用默认规划兜底')
    return default_plan(concept)


def main():
    ap = argparse.ArgumentParser(description='概念 → LLM → 海报 JSON（v22 poster 线）')
    ap.add_argument('concept', help='主题（中文）')
    ap.add_argument('-o', '--output', default=None, help='JSON 输出路径')
    ap.add_argument('--model', default=None, help='LLM 模型')
    args = ap.parse_args()
    out = args.output or 'output/poster/plan.json'
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    plan = plan_poster(args.concept, model=args.model)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f'✅ {out}（{len(plan["creatures"])} 生灵 · {plan["tagline"]}）')


if __name__ == '__main__':
    main()
