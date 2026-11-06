"""v21（原 v18）M0 doctor 单元测试：纯逻辑，不依赖真实 GPU/网络。直接跑。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.doctor import (TIER_ORDER, TIER_REQUIREMENTS, check_disk,
                         recommend_tier, run_doctor)

PASS = []


def ok(name, cond):
    PASS.append((name, bool(cond)))
    print(('✓' if cond else '✗'), name)


# ── 1. 档位阶梯定义 ──
ok('五档齐全', set(TIER_ORDER) == {'none', 'flux', 'wan', 'h3', 'full'})
ok('阶梯递增显存', all(TIER_REQUIREMENTS[a]['vram_mb'] <= TIER_REQUIREMENTS[b]['vram_mb']
                   for a, b in zip(TIER_ORDER, TIER_ORDER[1:])))

# ── 2. recommend_tier 纯逻辑 ──
ok('无卡 → none', recommend_tier([]) == 'none')
ok('单卡 47G → 至少 h3', recommend_tier(
    [{'index': 0, 'name': 'x', 'vram_total_mb': 47621, 'vram_free_mb': 1000}]) == 'h3')
ok('单卡 16G → flux', recommend_tier(
    [{'index': 0, 'name': 'x', 'vram_total_mb': 16384, 'vram_free_mb': 1000}]) == 'flux')
ok('单卡 24G → wan', recommend_tier(
    [{'index': 0, 'name': 'x', 'vram_total_mb': 24576, 'vram_free_mb': 1000}]) == 'wan')
ok('四卡 47G → full', recommend_tier(
    [{'index': i, 'name': 'x', 'vram_total_mb': 47621, 'vram_free_mb': 1000}
     for i in range(4)]) == 'full')
ok('单卡 8G → none', recommend_tier(
    [{'index': 0, 'name': 'x', 'vram_total_mb': 8192, 'vram_free_mb': 1000}]) == 'none')

# ── 3. check_disk 真实执行（无网络依赖） ──
d = check_disk()
ok('磁盘检查有 free_gb', 'free_gb' in d and d['free_gb'] > 0)

# ── 4. run_doctor 端到端（真实本机，nvidia-smi 有则 GPU 列表非空） ──
p = run_doctor()
ok('profile 含五要素', all(k in p for k in (
    'gpus', 'services_online', 'conda_envs', 'disk', 'net')))
ok('推荐档在五档内', p['recommended_tier'] in TIER_ORDER)
ok('服务端口 7 项', set(p['services_online']) == {
    'h3', 'h3d', 'wan', 'hunyuan', 'flux', 'tts', 'api'})
ok('net 三项', set(p['net']) == {'ustc_llm', 'edge_tts', 'pypi_mirror'})

print(f'\n{sum(1 for _, c in PASS if c)}/{len(PASS)} passed')
sys.exit(0 if all(c for _, c in PASS) else 1)
