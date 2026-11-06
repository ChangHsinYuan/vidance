#!/usr/bin/env python3
"""配置中心加载 — config.json（仓库规范值，服务器/本地通用）
+ config/config.local.json（本机覆盖，gitignore，不入库）
+ config/tiers/{tier}.json（v18 部署档覆盖，VIDANCE_TIER=none|flux|wan|h3|full）深度合并。

所有模块的 load_config 都应委托到这里。
config.local.json 不存在时行为与直接读 config.json 完全一致（服务器零影响）。
VIDANCE_TIER 未设时为 full（全量），宿主机行为零变化。
"""

import os as _os
import sys as _sys
_ROOT = _os.path.abspath(__file__)
for _ in range(4):
    _ROOT = _os.path.dirname(_ROOT)
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CONFIG_PATH = os.path.join(ROOT, 'config', 'config.json')
LOCAL_PATH = os.path.join(ROOT, 'config', 'config.local.json')
TIERS_DIR = os.path.join(ROOT, 'config', 'tiers')

# v18 部署档：VIDANCE_TIER=none|flux|wan|h3|full（缺省 full=全量，宿主机行为零变化）
FULL_CAPS = {
    'generators': ['svg', 'fast', 'flux', 'wan', 'h3'],
    'comfyui': ['flux', 'wan', 'h3', 'hunyuan', 'h3d'],
    'tts': ['edge', 'cosy'],
    'stt': True, 'voice_clone': True, 'auto': True, 'custom': True, 'h3shot': True,
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def get_tier() -> str:
    return _os.environ.get('VIDANCE_TIER', '').strip().lower() or 'full'


def load_config() -> dict:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    if os.path.isfile(LOCAL_PATH):
        with open(LOCAL_PATH, 'r', encoding='utf-8') as f:
            local = json.load(f)
        cfg = deep_merge(cfg, local)
    tier = get_tier()
    tier_path = os.path.join(TIERS_DIR, tier + '.json')
    if os.path.isfile(tier_path):
        with open(tier_path, 'r', encoding='utf-8') as f:
            cfg = deep_merge(cfg, json.load(f))
    else:
        raise SystemExit(f'⛔ 未知部署档 {tier!r}（可选 none/flux/wan/h3/full，定义在 config/tiers/）')
    cfg.setdefault('tier', tier)
    return cfg


def capabilities(cfg: dict = None) -> dict:
    """当前档位能力（generators/comfyui/tts/stt/auto/custom/h3shot）"""
    if cfg is None:
        cfg = load_config()
    return cfg.get('tier_capabilities', FULL_CAPS)


def require(cap: str, cfg: dict = None):
    """CLI 档位守卫：能力不足直接退出并提示（cap ∈ auto/custom/h3shot 或 generators 元素）"""
    caps = capabilities(cfg)
    ok = caps.get(cap) if isinstance(caps.get(cap), bool) else cap in caps.get('generators', [])
    if not ok:
        tier = (cfg or {}).get('tier') or get_tier()
        raise SystemExit(
            f"⛔ 当前部署档 {tier} 不支持 {cap}（能力：{caps.get('generators')}）。"
            f"换档：VIDANCE_TIER=<none|flux|wan|h3|full>；或用该档可用子命令（svg/fast 等）")


def task_id_for(mode: str, task_id: str = None) -> str:
    """统一产出命名：{config task_prefixes[mode]}_{时间戳}（可被外部 task_id 覆盖）。

    config.json task_prefixes 定义各方法前缀（auto/quick/fast/hot/custom/make/chain），
    输出目录=output_dir/{task_id}/，不重不覆盖。未知 mode 用 mode 原名。
    """
    import time as _t
    if task_id:
        return task_id
    cfg = load_config()
    pref = (cfg.get('task_prefixes') or {}).get(mode, mode)
    return f'{pref}_{_t.strftime("%Y%m%d_%H%M%S")}'


def load_base_config() -> dict:
    """读原始 config.json（不含本机覆盖），供写回配置时使用，避免把本机值固化进仓库文件"""
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def user_config_path() -> str:
    """用户配置写回目标：已有 config.local.json 写本机覆盖（不入库），否则写 config.json 本体"""
    return LOCAL_PATH if os.path.isfile(LOCAL_PATH) else CONFIG_PATH


def save_config(update: dict) -> dict:
    """把 {段: {...}} 增量合并进用户配置文件（v21 M3：init 向导/设置端点共用），返回合并后全量"""
    path = user_config_path()
    with open(path, 'r', encoding='utf-8') as f:
        cur = json.load(f)
    cur = deep_merge(cur, update)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(cur, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return cur
