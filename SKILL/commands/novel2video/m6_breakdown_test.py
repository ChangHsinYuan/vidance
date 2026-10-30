"""M6 剧本结构化拆解原型（档1：纯 LLM）。

用法: python m6_breakdown_test.py [章节名]   # 默认 藥
流程: nahan.txt 切章 → 取章全文 + RAG 人物卡 → LLM chat_json 结构化拆解
幂等: output/m6/breakdown_<章节>.json 已存在则跳过 LLM 直接复用（--force 重拆）
输出: output/m6/breakdown_<章节>.json + 控制台摘要
"""
import json
import os
import sys

sys.path.insert(0, '.')
from utils.rag import RagIndex, split_novel_chapters, read_document
from agents.common.tools.llm import LLMClient

KEY = '454eb1f2826b56685bf7ab155c6eb06e'
SRC = os.path.join(os.path.dirname(__file__), 'nahan.txt')
OUT_DIR = 'output/m6'
FORCE = '--force' in sys.argv

CH_NAME = next((a for a in sys.argv[1:] if not a.startswith('--')), '藥')

os.makedirs(OUT_DIR, exist_ok=True)
out_path = os.path.join(OUT_DIR, f'breakdown_{CH_NAME}.json')
if os.path.isfile(out_path) and not FORCE:
    r = json.load(open(out_path))
    print(f'已存在 {out_path}，跳过 LLM（--force 重拆）')
else:
    title, chapters = split_novel_chapters(read_document(SRC))
    ch = next((c for c in chapters if c['title'].strip() == CH_NAME), None)
    if ch is None:
        cands = [c['title'] for c in chapters]
        print(f'未找到章节「{CH_NAME}」，可选: {cands}')
        sys.exit(1)
    if len(ch['text']) > 8000 and not FORCE:
        print(f'⚠「{CH_NAME}」{len(ch["text"])} 字 >8000（可能含并入的无篇名章），'
              '拆解易超时/降质。确认要拆加 --force，或换短章。')
        sys.exit(1)
    r = _breakdown(title, ch, out_path)

sb = r.get('storyboard') or []

title, chapters = split_novel_chapters(read_document(SRC))
ch = next((c for c in chapters if c['title'].strip() == CH_NAME), None)
if ch is None:
    cands = [c['title'] for c in chapters]
    print(f'未找到章节「{CH_NAME}」，可选: {cands}')
    sys.exit(1)


def _breakdown(title, ch, out_path):
    """RAG 人物卡注入 → LLM 流式拆解 → 存 JSON。"""
    idx = RagIndex()
    cards = idx._load_cards(KEY)
    # 只注入名字出现在本章正文的人物卡（其余卡对本章拆解是噪声，放大输入拉爆推理时间）
    relevant = [c for c in cards if c.get('name') and c['name'] in ch['text']]
    if not relevant:
        relevant = cards[:3]

    schema = '''{
  "characters": [{"name": "角色名", "appearance": "外貌/服饰（用于定妆照）", "personality": "性格关键词"}],
  "scenes": [{"id": 1, "location": "地点", "time": "时间", "description": "场景描述"}],
  "props": [{"name": "道具名", "owner": "归属", "significance": "象征意义"}],
  "storyboard": [{"shot": 1, "scene": 1, "size": "远景|中景|近景|特写",
                  "visual": "画面内容（具体可拍摄）", "narration": "旁白（原文语感，可空串）",
                  "duration": "建议时长秒数（数字）"}]
}'''

    msgs = [
        {'role': 'system', 'content':
         '你是影视编剧。把小说章节拆解为结构化剧本 JSON，严格符合给定 schema。'
         '要求：\n'
         '1. characters 只列本章出场角色，appearance 依据原文描写（无则按时代合理推断并标注"推断"）\n'
         '2. scenes 按叙事顺序编号，storyboard.shot 全片连续编号，scene 引用场景 id\n'
         '3. visual 只写可见的画面信息（人物动作/环境/光线），不写心理活动\n'
         '4. narration 用白话转写旁白/台词，保留鲁迅的冷峻语感\n'
         '5. 分镜要覆盖整章叙事，重要情节给特写；总时长控制在 3-5 分钟\n'
         f'schema:\n{schema}\n只输出 JSON，不要 markdown 代码块。'},
        {'role': 'user', 'content':
         f'【小说】{title}·{ch["title"]}（{len(ch["text"])} 字）\n\n{ch["text"]}\n\n'
         f'【人物卡参考】\n{json.dumps(relevant, ensure_ascii=False, indent=1)}'},
    ]

    lc = LLMClient()
    print(f'拆解 {title}·{ch["title"]}（{len(ch["text"])} 字，人物卡 {len(relevant)}/{len(cards)} 张），LLM 调用中（流式）…', flush=True)
    # 非流式在长 reasoning 期间零字节→read timeout 必死；流式期间 delta 持续到达不会超时
    text = lc.chat_stream(msgs, model=lc.models['script'], temperature=0.3,
                          max_tokens=16384, timeout=1800,
                          on_chunk=lambda d: print('.', end='', flush=True))
    print(flush=True)
    r = lc._extract_json(text)
    print('JSON 解析 OK')
    json.dump(r, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return r


# schema 校验摘要
errs = []
if not isinstance(r.get('characters'), list) or not r['characters']:
    errs.append('characters 空')
if not isinstance(r.get('scenes'), list) or not r['scenes']:
    errs.append('scenes 空')
sb = r.get('storyboard') or []
if not sb:
    errs.append('storyboard 空')
shots = [s.get('shot') for s in sb]
if shots != sorted(shots) or len(set(shots)) != len(shots):
    errs.append(f'shot 编号不连续/重复: {shots[:20]}')
scene_ids = {s.get('id') for s in (r.get('scenes') or [])}
for s in sb:
    if s.get('scene') not in scene_ids:
        errs.append(f'shot {s.get("shot")} 引用了不存在的场景 {s.get("scene")}')
        break
total_dur = sum(float(s.get('duration') or 0) for s in sb)

print(f'\n✓ 已保存 {out_path}')
print(f'  角色 {len(r.get("characters", []))} | 场景 {len(r.get("scenes", []))} | '
      f'道具 {len(r.get("props", []))} | 分镜 {len(sb)} 镜，总时长 {total_dur:.0f}s')
print(f'  schema 校验: {"✅ 全部通过" if not errs else "⚠ " + "; ".join(errs)}')
print('\n分镜预览:')
for s in sb[:8]:
    print(f'  #{s.get("shot")} [{s.get("size")}] {str(s.get("visual"))[:50]}')
if len(sb) > 8:
    print(f'  … 共 {len(sb)} 镜')
