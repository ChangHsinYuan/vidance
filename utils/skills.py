#!/usr/bin/env python3
"""SKILL 风格技能加载器 — vidance/SKILL/*.yaml

一个 skill = 出片参数包(defaults) + LLM 编剧文风(narration_style) + 测试案例(test_cases)。
fast/hot 命令 --skill <name> 时套用：CLI 显式传参永远优先，skill 只填未传的。

用法:
    from utils.skills import SkillManager
    sm = SkillManager()
    sm.list()                    # ['marketing', 'narrative']
    sk = sm.get('narrative')     # dict 或 None（含 _dir 路径）
    sk['defaults']['voice']      # 'cosy-jilupian1'
"""

import os

_SKILL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'SKILL')


class SkillManager:
    def __init__(self, skill_dir: str = None):
        self.skill_dir = skill_dir or _SKILL_DIR

    def list(self) -> list:
        """可用 skill 名列表（按文件名排序）。"""
        if not os.path.isdir(self.skill_dir):
            return []
        out = []
        for f in sorted(os.listdir(self.skill_dir)):
            if f.endswith(('.yaml', '.yml')):
                sk = self._load(os.path.join(self.skill_dir, f))
                if sk and sk.get('name'):
                    out.append(sk['name'])
        return out

    def get(self, name: str) -> dict:
        """按 name 读 skill（匹配文件内 name 字段或文件名），找不到返回 None。"""
        if not name or not os.path.isdir(self.skill_dir):
            return None
        name = name.strip().lower()
        for f in sorted(os.listdir(self.skill_dir)):
            if not f.endswith(('.yaml', '.yml')):
                continue
            sk = self._load(os.path.join(self.skill_dir, f))
            if sk and (sk.get('name', '').lower() == name
                       or os.path.splitext(f)[0].lower() == name):
                sk['_dir'] = os.path.join(self.skill_dir, f)
                return sk
        return None

    @staticmethod
    def _load(path: str) -> dict:
        try:
            import yaml
            with open(path, 'r', encoding='utf-8') as f:
                d = yaml.safe_load(f)
            return d if isinstance(d, dict) else {}
        except Exception as e:
            print(f'  ⚠ skill 加载失败 {os.path.basename(path)}: {e}')
            return {}

    @staticmethod
    def merge(args_dict: dict, skill: dict) -> dict:
        """把 skill defaults 填进参数 dict：只覆盖 None/未提供的键（CLI 显式值优先）。

        args_dict: {'voice': None, 'bgm': 'calm', ...}（argparse 取出的，未传=None）
        skill: get() 返回的 dict（可 None）
        返回合并后的新 dict（不改原 dict）。
        """
        merged = dict(args_dict or {})
        if not skill:
            return merged
        for k, v in (skill.get('defaults') or {}).items():
            if merged.get(k) is None:
                merged[k] = v
        return merged


if __name__ == '__main__':
    sm = SkillManager()
    names = sm.list()
    print(f'可用 skill ({len(names)}): {", ".join(names)}')
    for n in names:
        sk = sm.get(n)
        d = sk.get('defaults', {})
        print(f"\n[{n}] {sk.get('display_name', '')}")
        print(f"  {sk.get('description', '')}")
        for k in ('n', 'voice', 'bgm', 'lut', 'transition', 'clip_speed', 'effects'):
            if k in d:
                print(f'  {k}: {d[k]}')
        tc = sk.get('test_cases') or []
        if tc:
            print(f'  测试案例: {tc}')
