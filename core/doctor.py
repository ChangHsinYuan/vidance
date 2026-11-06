#!/usr/bin/env python
"""v21（原 v18）M0 资源探测 doctor：GPU/端口/conda/磁盘/外网 → profile JSON + 档位推荐。

CLI:  python core/doctor.py [--json] [--recommend-only]
API:  GET /api/doctor（api_server 内 import 本模块）
产出：每项检查 {name, ok, detail}；末尾 recommended_tier = 不降级能力能吃下的最高档。
档位阶梯（逐级累加）：none < flux < wan < h3 < full——需求见 config/tiers/*.json。
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 档位 → 最低资源需求（GPU 显存 MB；-1 = 无卡可行）
TIER_REQUIREMENTS = {
    'none': {'vram_mb': 0, 'gpus': 0, 'desc': 'SVG 动画 + fast 爬图（LLM/edge-tts 全远程）'},
    'flux': {'vram_mb': 16000, 'gpus': 1, 'desc': '+ SDXL/FLUX 生图'},
    'wan': {'vram_mb': 24000, 'gpus': 1, 'desc': '+ Wan T2V/I2V + RIFE + auto/quick'},
    'h3': {'vram_mb': 40000, 'gpus': 1, 'desc': '+ MiniMax-H3 ref2va + custom/h3shot'},
    'full': {'vram_mb': 40000, 'gpus': 4, 'desc': '全功能（Hunyuan3D/STT/克隆，多卡）'},
}
TIER_ORDER = ['none', 'flux', 'wan', 'h3', 'full']

# 本机服务端口（start_services.sh 约定）
SERVICE_PORTS = {
    'h3': 8188, 'h3d': 8193, 'wan': 8189, 'hunyuan': 8190,
    'flux': 8192, 'tts': 9880, 'api': 8894,
}


def _port_open(port, host='127.0.0.1', timeout=1.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_gpus():
    """nvidia-smi → [{index, name, vram_total_mb, vram_free_mb}]；无卡返回 []"""
    try:
        out = subprocess.run(
            ['nvidia-smi', '--query-gpu=index,name,memory.total,memory.free',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=10)
        if out.returncode != 0:
            return []
        gpus = []
        for line in out.stdout.strip().splitlines():
            idx, name, total, free = [x.strip() for x in line.split(',')]
            gpus.append({'index': int(idx), 'name': name,
                         'vram_total_mb': int(float(total)),
                         'vram_free_mb': int(float(free))})
        return gpus
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def check_disk(path=None):
    path = path or os.path.join(os.path.dirname(__file__), '..', 'output')
    try:
        usage = shutil.disk_usage(path)
        return {'path': os.path.abspath(path),
                'free_gb': round(usage.free / 1e9, 1),
                'total_gb': round(usage.total / 1e9, 1)}
    except OSError as e:
        return {'error': str(e)}


def check_net():
    """外网可达性：USTC LLM / edge-tts(bing) / pypi 清华镜像"""
    import urllib.request
    targets = {
        'ustc_llm': 'https://api.llm.ustc.edu.cn/v1/models',
        'edge_tts': 'https://speech.platform.bing.com',
        'pypi_mirror': 'https://pypi.tuna.tsinghua.edu.cn/simple/',
    }
    res = {}
    for k, url in targets.items():
        try:
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=5) as r:
                res[k] = (r.status < 500)
        except urllib.error.HTTPError as e:
            res[k] = e.code < 500  # 401/404 = 主机可达（key 未带/路径不存在而已）
        except Exception:
            res[k] = False
    return res


def check_conda_envs():
    """conda env 列表（检测 comfyui/cosyvoice 环境是否就位）"""
    base = os.path.expanduser('~/.conda/envs')
    if not os.path.isdir(base):
        return []
    return sorted(d for d in os.listdir(base)
                  if os.path.isdir(os.path.join(base, d)))


def recommend_tier(gpus):
    """按显存/卡数推荐最高可跑档（探测值 ≥ 需求才升档）"""
    if not gpus:
        return 'none'
    n_gpus = len(gpus)
    best = 'none'
    for tier in TIER_ORDER:
        req = TIER_REQUIREMENTS[tier]
        if n_gpus >= req['gpus'] and \
           max(g['vram_total_mb'] for g in gpus) >= req['vram_mb']:
            best = tier
    return best


def run_doctor():
    gpus = check_gpus()
    services = {k: _port_open(p) for k, p in SERVICE_PORTS.items()}
    envs = check_conda_envs()
    profile = {
        'tier_env': os.environ.get('VIDANCE_TIER', '(未设，缺省 full)'),
        'gpus': gpus,
        'gpu_count': len(gpus),
        'services_online': services,
        'conda_envs': envs,
        'envs_ok': {'comfyui': 'comfyui' in envs, 'cosyvoice': 'cosyvoice' in envs},
        'disk': check_disk(),
        'net': check_net(),
        'recommended_tier': recommend_tier(gpus),
    }
    return profile


def print_report(p):
    print('═' * 60)
    print(' Vidance doctor — 资源探测（v21 M0）')
    print('═' * 60)
    tier = p['recommended_tier']
    print(f"\n▶ 推荐档位: {tier}  —  {TIER_REQUIREMENTS[tier]['desc']}")
    print(f"  当前 VIDANCE_TIER: {p['tier_env']}")
    if p['gpus']:
        print(f"\n▶ GPU × {p['gpu_count']}")
        for g in p['gpus']:
            print(f"  [{g['index']}] {g['name']}  {g['vram_total_mb']//1024}G"
                  f"（空闲 {g['vram_free_mb']//1024}G）")
    else:
        print('\n▶ GPU: 无（nvidia-smi 不可用）→ none 档（纯 CPU 链路）')
    print('\n▶ 本机服务端口')
    for k, v in p['services_online'].items():
        mark = '✓' if v else '✗'
        print(f"  {mark} {k:8s} :{SERVICE_PORTS[k]}")
    print('\n▶ conda 环境:', ', '.join(p['conda_envs']) or '(无)')
    if p['conda_envs']:
        for k, v in p['envs_ok'].items():
            print(f"  {'✓' if v else '✗'} {k}")
    d = p['disk']
    if 'error' not in d:
        print(f"\n▶ 磁盘 {d['path']}: 空闲 {d['free_gb']}G / {d['total_gb']}G")
    print('\n▶ 外网:', '  '.join(f"{k}={'✓' if v else '✗'}" for k, v in p['net'].items()))
    print()


if __name__ == '__main__':
    args = sys.argv[1:]
    p = run_doctor()
    if '--json' in args or '--recommend-only' in args:
        if '--recommend-only' in args:
            print(p['recommended_tier'])
        else:
            print(json.dumps(p, ensure_ascii=False, indent=1))
    else:
        print_report(p)
