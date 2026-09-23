#!/usr/bin/env python3
"""配置中心加载 — config.json（仓库规范值，服务器/本地通用）
+ config/config.local.json（本机覆盖，gitignore，不入库）深度合并。

所有模块的 load_config 都应委托到这里。
config.local.json 不存在时行为与直接读 config.json 完全一致（服务器零影响）。
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, 'config', 'config.json')
LOCAL_PATH = os.path.join(ROOT, 'config', 'config.local.json')


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    if os.path.isfile(LOCAL_PATH):
        with open(LOCAL_PATH, 'r', encoding='utf-8') as f:
            local = json.load(f)
        cfg = deep_merge(cfg, local)
    return cfg


def load_base_config() -> dict:
    """读原始 config.json（不含本机覆盖），供写回配置时使用，避免把本机值固化进仓库文件"""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)
