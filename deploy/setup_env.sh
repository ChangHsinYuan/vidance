#!/usr/bin/env bash
# Vidance 一键环境准备（v21 部署档，2026-10-02）
# 用法：bash deploy/setup_env.sh [--env /path/to/conda/env]
# 干净机器从零准备：pip 依赖（版本锁定）+ sam2 可编辑安装 + bpy X 库 + 权重下载 + 全量验证。
# 不装大模型（见 download_weights.sh 清单，手动下载）；不 build Docker。

set -euo pipefail

VIDANCE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$VIDANCE_DIR"

# ── 0. python 定位 ──
if [ -n "${2:-}" ]; then PY="$2"
elif [ -x /home/zxy/.conda/envs/comfyui/bin/python ]; then PY=/home/zxy/.conda/envs/comfyui/bin/python
elif [ -x "$(command -v python3)" ]; then PY="$(command -v python3)"
else echo "✗ 找不到 python，用 --env /path/to/python 指定"; exit 1; fi
echo "== [0] python: $PY ($($PY --version 2>&1)) =="

# ── 1. pip 依赖（版本锁定；清华镜像，pypi 直连不稳）──
echo "== [1] pip 安装 requirements-lock.txt =="
$PY -m pip install -r deploy/requirements-lock.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# ── 2. SAM2 可编辑安装（源码仓外 clone；pypi 构建依赖会卡死 10 分钟，--no-build-isolation 绕开）──
SAM2_SRC="${SAM2_SRC:-$(dirname "$VIDANCE_DIR")/sam2-src}"
echo "== [2] SAM2 可编辑安装（$SAM2_SRC）=="
if [ ! -d "$SAM2_SRC" ]; then
    git clone --depth 1 https://github.com/facebookresearch/sam2.git "$SAM2_SRC"
fi
$PY -c "import sam2" 2>/dev/null || \
    $PY -m pip install -e "$SAM2_SRC" --no-build-isolation \
        -i https://pypi.tuna.tsinghua.edu.cn/simple

# ── 3. bpy 渲染 X 库（deb 系；容器重建会丢，此处幂等重装）──
if command -v apt-get >/dev/null; then
    echo "== [3] apt 安装 blender X 依赖 =="
    apt-get install -y --no-install-recommends libsm6 libxext6 libxrender1 libgl1 2>/dev/null \
        || echo "  ⚠ apt 安装失败（无 sudo？），bpy 渲染可能缺 X 库"
else
    echo "== [3] 非 deb 系跳过 apt =="
fi

# ── 4. 权重下载（SAM2 + YOLO，断点续传）──
echo "== [4] 权重下载 =="
bash deploy/download_weights.sh

# ── 5. 全量验证（import + 权重 + GPU）──
echo "== [5] 验证 =="
$PY - <<'EOF'
import importlib
mods = ['torch', 'numpy', 'cv2', 'PIL', 'sam2', 'ultralytics', 'fastapi',
        'moviepy', 'faster_whisper', 'trimesh', 'scipy', 'psutil']
ok = fail = 0
for m in mods:
    try:
        importlib.import_module(m); print(f'  ✓ {m}'); ok += 1
    except Exception as e:
        print(f'  ✗ {m}: {e}'); fail += 1
import numpy, cv2, torch
print(f'  numpy {numpy.__version__}（必须 1.26.x，bpy 兼容）')
print(f'  opencv {cv2.__version__}（必须 4.11，numpy<2 铁律）')
print(f'  torch {torch.__version__}，cuda 可用: {torch.cuda.is_available()}')
print(f'== import 验证：{ok} 过 / {fail} 败 ==')
EOF

$PY - <<'EOF'
import os
p_tiny = 'models/sam2/sam2.1_hiera_tiny.pt'
p_small = 'models/sam2/sam2.1_hiera_small.pt'
p_yolo = 'models/yolo/yolov8s.pt'
for p, want in [(p_tiny, 471), (p_small, 519)]:
    if os.path.exists(p):
        try:
            import torch
            ck = torch.load(p, map_location='cpu', weights_only=False)
            n = len(ck) if isinstance(ck, dict) else -1
            print(f'  ✓ {p}（{n} keys，期望 {want}）')
        except Exception as e:
            print(f'  ✗ {p}: {e}')
    else:
        print(f'  ⚠ 缺 {p}')
print(('  ✓ ' if os.path.exists(p_yolo) else '  ⚠ 缺 ') + p_yolo)
EOF

echo ""
echo "✅ 环境准备完成。下一步："
echo "  1. bash start_services.sh status   # 服务连通"
echo "  2. python core/vidance.py edit visualize 图.jpg --yolo   # v16 编辑冒烟"
echo "  3. 需要 Docker 时再 build（deploy/README.md）"
