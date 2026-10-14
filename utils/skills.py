#!/usr/bin/env python3
"""SKILL 风格技能加载器 — SKILL/{commands,agents}/...

双维度组织（按消费方式分）：
    SKILL/commands/{模块}/{技能}.yaml   命令式：CLI --skill 直接消费（模块=CLI 子命令）
        fast/ auto/ quick/ svg/ ppt/ blender3d/ ...
    SKILL/agents/{分类}/{技能}.yaml     agent 式：职业配方/工作流（跨命令组合，yaml 间引用）
        personas/artist.yaml、personas/researcher.yaml 等，下面按需再分文件夹

一个 skill = 出片参数包(defaults) + LLM 文风指令(narration_style) + 测试案例(test_cases)。
agent 式配方用 commands: {fast: {...}, ppt: {...}} 段按命令给参数（schema 同 defaults），
post: 段放独立后处理配方（grain/warmth 等，post 链/agent 消费）。

CLI 显式传参永远优先，skill 只填未传的（argparse 默认值视为未传）。

用法:
    from utils.skills import SkillManager
    sm = SkillManager()
    sm.list()                          # ['agents/artist', 'commands/fast/narrative', …]
    sm.list(kind='commands')           # 只要命令式
    sk = sm.get('narrative')           # 任意深度，name 全局唯一即可命中
    d = sm.params_for(sk, 'fast')      # 命令式→defaults；agent 式→commands['fast']
"""

import os

_SKILL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'SKILL')


class SkillManager:
    def __init__(self, skill_dir: str = None):
        self.skill_dir = skill_dir or _SKILL_DIR

    # ── 内部 ──
    def _walk(self):
        """递归列出所有 skill yaml → [(kind, module, path)]。

        kind = SKILL 下一级目录（commands/agents）；module = 其余子目录路径。
        """
        if not os.path.isdir(self.skill_dir):
            return []
        out = []
        for root, _dirs, files in os.walk(self.skill_dir):
            for f in sorted(files):
                if not f.endswith(('.yaml', '.yml')):
                    continue
                path = os.path.join(root, f)
                rel = os.path.relpath(path, self.skill_dir)
                parts = rel.replace(os.sep, '/').split('/')
                kind = parts[0] if len(parts) > 1 else 'misc'
                module = '/'.join(parts[1:-1])
                out.append((kind, module, path))
        return sorted(out)

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

    # ── 对外 ──
    def list(self, kind: str = None) -> list:
        """全部 skill 键 'kind/module/name'（kind 可过滤：commands/agents）。"""
        keys = []
        for k, mod, path in self._walk():
            if kind and k != kind:
                continue
            sk = self._load(path)
            name = sk.get('name') or os.path.splitext(os.path.basename(path))[0]
            keys.append('/'.join([k] + ([mod] if mod else []) + [name]))
        return keys

    def get(self, key: str) -> dict:
        """按 name（全局唯一）或路径键 'kind/module/name' 读 skill，找不到返回 None。

        返回 dict 附带 _meta：{kind, module, path, file}。
        """
        if not key or not os.path.isdir(self.skill_dir):
            return None
        key = str(key).strip().lower()
        fallback = None
        for kind, mod, path in self._walk():
            sk = self._load(path)
            stem = os.path.splitext(os.path.basename(path))[0].lower()
            name = (sk.get('name') or stem).lower()
            ns = '/'.join([kind] + ([mod] if mod else []) + [name])
            if ns == key:
                sk['_meta'] = {'kind': kind, 'module': mod, 'path': path,
                               'file': os.path.basename(path)}
                return sk
            if name == key or stem == key:
                if sk.get('name'):          # 显式 name 全局唯一 → 直接命中
                    sk['_meta'] = {'kind': kind, 'module': mod, 'path': path,
                                   'file': os.path.basename(path)}
                    return sk
                fallback = (sk, kind, mod, path)
        if fallback:
            sk, kind, mod, path = fallback
            sk['_meta'] = {'kind': kind, 'module': mod, 'path': path,
                           'file': os.path.basename(path)}
            return sk
        return None

    @staticmethod
    def params_for(skill: dict, module: str) -> dict:
        """取 skill 对某命令的参数包。

        commands/ 命令式 → defaults；
        agents/ agent 式 → commands[module]（该命令没写则 {}）。
        """
        if not skill:
            return {}
        if skill.get('_meta', {}).get('kind') == 'agents':
            return (skill.get('commands') or {}).get(module) or {}
        return skill.get('defaults') or {}

    @staticmethod
    def style_for(skill: dict, module: str = None) -> str:
        """取 skill 的文风指令（narration_style，命令式/agent 式同字段）。"""
        if not skill:
            return None
        s = skill.get('narration_style')
        return str(s).strip() if s else None

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
    import sys
    sm = SkillManager()
    kind = sys.argv[1] if len(sys.argv) > 1 else None
    keys = sm.list(kind)
    print(f'可用 skill ({len(keys)}):')
    for k in keys:
        sk = sm.get(k)
        kind_, mod = sk['_meta']['kind'], sk['_meta']['module']
        print(f"\n[{k}]  {sk.get('display_name', '')}")
        print(f"  {sk.get('description', '')}")
        if kind_ == 'agents':
            for m, d in (sk.get('commands') or {}).items():
                print(f'  ·{m}: {d}')
            if sk.get('post'):
                print(f"  post: {sk['post']}")
        else:
            for k2, v in (sk.get('defaults') or {}).items():
                print(f'    {k2}: {v}')
        tc = sk.get('test_cases') or []
        if tc:
            print(f'  测试案例: {tc}')
        st = SkillManager.style_for(sk)
        if st:
            print(f'  文风: {st[:40]}…')
