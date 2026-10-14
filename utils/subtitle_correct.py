#!/usr/bin/env python3
"""STT 字幕智能纠正 — 借鉴 MoneyPrinterTurbo app/services/subtitle.py::correct()

问题：faster-whisper 转写文本常有错字（专有名词/同音字），直接烧录上屏。
方案：STT 转写只贡献时间轴，文本用剧本原文替换——按标点把剧本切段，
与字幕逐段 Levenshtein 相似度对齐（>0.8 判定同句则替换文本，相似度
提升时合并多段字幕），对不齐的段落同样以剧本文本+STT 时间轴兜底，
多余的幻觉字幕段（BGM 误识别等）直接丢弃。

用法:
    from utils.subtitle_correct import correct_srt
    correct_srt('subtitle_stt.srt', '全片旁白原文')
"""

import os
import re

# 中英文自然断句点（参考 MPT app/models/const.py PUNCTUATIONS）
_PUNCTUATIONS = [
    "?", ",", ".", "、", ";", ":", "!", "…",
    "？", "，", "。", "；", "：", "！", "...",
]

_SRT_TIME_RE = re.compile(r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})")


def _parse_srt(path: str) -> list:
    """解析 SRT 为 [(index, 'start --> end', text), ...]（借鉴 MPT file_to_subtitles）"""
    if not path or not os.path.isfile(path):
        return []
    items = []
    current_times = None
    current_text = ""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            times = _SRT_TIME_RE.findall(line)
            if len(times) >= 2:
                if current_times and current_text.strip():
                    items.append((len(items) + 1, current_times.strip(), current_text.strip()))
                current_times = f"{times[0]} --> {times[1]}"
                current_text = ""
            elif current_times is not None:
                if line.strip() == "":
                    if current_text.strip():
                        items.append((len(items) + 1, current_times.strip(), current_text.strip()))
                        current_times, current_text = None, ""
                    # 连续空行容忍
                else:
                    current_text += line
    if current_times and current_text.strip():
        items.append((len(items) + 1, current_times.strip(), current_text.strip()))
    return items


def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    return 1 - (_levenshtein(a.lower(), b.lower()) / max_len)


def _normalize_script(text: str) -> str:
    """清理剧本中不会被朗读的标记（Markdown 分隔线/下划线/【】镜头标记头）"""
    text = text or ""
    cleaned_lines = []
    for line in text.splitlines():
        line = line.strip()
        if re.fullmatch(r"[-*_]{3,}", line):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def split_script_lines(text: str) -> list:
    """剧本按换行+标点切句（借鉴 MPT split_string_by_punctuations）"""
    result = []
    txt = ""
    for i, char in enumerate(text):
        if char == "\n":
            result.append(txt.strip())
            txt = ""
            continue
        if char == "." and i > 0 and i < len(text) - 1 \
                and text[i - 1].isdigit() and text[i + 1].isdigit():
            txt += char  # 小数点不断句
            continue
        if char == "," and i > 0 and i < len(text) - 1 \
                and text[i - 1].isdigit() and text[i + 1].isdigit():
            txt += char  # 千分位逗号不断句
            continue
        if char not in _PUNCTUATIONS:
            txt += char
        else:
            result.append(txt.strip())
            txt = ""
    result.append(txt.strip())
    return list(filter(None, result))


def _t2s(t: str) -> float:
    """SRT 时间 "HH:MM:SS,mmm" → 秒。"""
    t = t.strip().replace(',', '.')
    parts = t.split(':')
    while len(parts) < 3:
        parts.insert(0, '0')
    h, m, s = parts
    return int(h) * 3600 + int(m) * 60 + float(s)


def _s2t(sec: float) -> str:
    """秒 → SRT 时间 "HH:MM:SS,mmm"（总毫秒取整，防 999→1000 溢出）。"""
    ms = max(0, int(round(max(0.0, sec) * 1000)))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _expand_coarse_segments(subtitle_items: list, script_lines: list) -> list:
    """STT 粗段展开：whisper 把多句旁白并成少量长段（长文案+BGM 常见）时，
    按剧本句字符占比把 STT 时间轴切成句级伪字幕（文本=剧本句原文）。

    触发：STT 段数 < 剧本句数，且 STT 总字数 ≥ 剧本总字数 60%（内容基本都在，
    只是没分段；真漏识别多则维持原行为——宁缺勿错）。
    """
    n_stt, n_scr = len(subtitle_items), len(script_lines)
    if n_stt <= 0 or n_stt >= n_scr:
        return subtitle_items
    stt_chars = sum(len(it[2]) for it in subtitle_items)
    scr_chars = sum(len(l) for l in script_lines)
    if scr_chars <= 0 or stt_chars < scr_chars * 0.6:
        return subtitle_items

    print(f'  [字幕纠正] STT 段数({n_stt}) 远少于剧本句数({n_scr})，'
          f'按剧本句字符占比展开时间轴')
    # 时间轴范围 = 首段起点 → 末段终点（段间隙忽略，whisper 连续转写间隙极小）
    start_all = _t2s(subtitle_items[0][1].split(' --> ')[0])
    end_all = _t2s(subtitle_items[-1][1].split(' --> ')[-1])
    total = end_all - start_all
    chars = [max(1, len(l)) for l in script_lines]
    char_sum = sum(chars)

    expanded = []
    t = start_all
    for l, c in zip(script_lines, chars):
        dur = total * (c / char_sum)
        expanded.append((len(expanded) + 1, f'{_s2t(t)} --> {_s2t(t + dur)}', l))
        t += dur
    # 末句终点对齐段终点（防累计误差）
    expanded[-1] = (len(expanded),
                    f'{_s2t(end_all - (total * chars[-1] / char_sum))} --> {_s2t(end_all)}',
                    script_lines[-1])
    return expanded


def correct_srt(srt_path: str, script_text: str, threshold: float = 0.8) -> bool:
    """用剧本原文纠正 STT 字幕文本（原地重写 SRT，返回是否有改动）。

    算法（MPT correct() + vidance 扩展）：
    0. STT 段数远少于剧本句数（长段合并）→ 先按剧本句字符占比展开时间轴
    1. 剧本切句、字幕逐段扫描，双指针推进
    2. 当前剧本句与当前字幕相似度不够时，尝试向后合并字幕段
       （合并后相似度提升才继续合并）
    3. 相似度 > threshold：同句，替换为剧本文本（修错字）
       否则：对不齐，仍以剧本文本+该段时间轴兜底（STT 只提供时间轴）
    4. 剩余剧本句：无对应字幕则跳过（STT 漏识别，宁缺勿错）
       剩余字幕段：视为 BGM 幻觉，丢弃
    """
    subtitle_items = _parse_srt(srt_path)
    if not subtitle_items:
        return False
    script_lines = split_script_lines(_normalize_script(script_text))
    if not script_lines:
        return False

    expanded_items = _expand_coarse_segments(subtitle_items, script_lines)
    if expanded_items is not subtitle_items:
        subtitle_items = expanded_items
        # 时间轴已被展开重排：伪段文本=剧本句，exact-match 直通，但需强制写回
        with open(srt_path, 'w', encoding='utf-8') as f:
            for i, (_, timespan, text) in enumerate(subtitle_items):
                f.write(f'{i + 1}\n{timespan}\n{text}\n\n')
        return True

    new_items = []
    script_index = 0
    subtitle_index = 0
    corrected = False

    while script_index < len(script_lines) and subtitle_index < len(subtitle_items):
        script_line = script_lines[script_index]
        subtitle_line = subtitle_items[subtitle_index][2]

        if script_line == subtitle_line:
            new_items.append(subtitle_items[subtitle_index])
            script_index += 1
            subtitle_index += 1
            continue

        times = subtitle_items[subtitle_index][1].split(" --> ")
        start_time, end_time = times[0], times[-1]
        combined = subtitle_line
        next_index = subtitle_index + 1

        while next_index < len(subtitle_items):
            next_text = subtitle_items[next_index][2]
            if similarity(script_line, combined + next_text) > similarity(script_line, combined):
                combined += next_text
                end_time = subtitle_items[next_index][1].split(" --> ")[-1]
                next_index += 1
            else:
                break

        sim = similarity(script_line, combined)
        if sim > threshold:
            print(f'  [字幕纠正] 同句替换 (相似度 {sim:.2f}): "{combined[:20]}" → "{script_line[:20]}"')
        else:
            print(f'  [字幕纠正] 对不齐兜底 (相似度 {sim:.2f}): STT "{combined[:20]}" → 剧本 "{script_line[:20]}"')
        new_items.append((len(new_items) + 1, f"{start_time} --> {end_time}", script_line))
        corrected = True
        script_index += 1
        subtitle_index = next_index

    # STT 漏句：跳过（宁缺勿错，不留零时长字幕）
    if script_index < len(script_lines):
        print(f'  [字幕纠正] STT 漏识别 {len(script_lines) - script_index} 句，跳过')
        corrected = True

    # 剩余字幕段：BGM/噪声幻觉，丢弃
    if subtitle_index < len(subtitle_items):
        dropped = [it[2] for it in subtitle_items[subtitle_index:]]
        print(f'  [字幕纠正] 丢弃 {len(dropped)} 段多余字幕（疑似幻觉）: '
              + ' | '.join(t[:12] for t in dropped[:3]))
        corrected = True

    if corrected:
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, (_, timespan, text) in enumerate(new_items):
                f.write(f"{i + 1}\n{timespan}\n{text}\n\n")
    return corrected


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='STT 字幕纠正（剧本原文替换转写文本）')
    parser.add_argument('srt', help='SRT 文件路径（原地重写）')
    parser.add_argument('script', help='剧本原文文件路径')
    args = parser.parse_args()
    with open(args.script, 'r', encoding='utf-8') as f:
        text = f.read()
    changed = correct_srt(args.srt, text)
    print(f'{"已纠正" if changed else "无需纠正"}: {args.srt}')
