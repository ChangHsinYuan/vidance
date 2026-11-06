#!/usr/bin/env bash
# Vidance 一键安装（v21 M2，2026-11-05）
# 用法：bash deploy/install.sh [--tier none|flux|wan|h3|full] [--port N] [--mode docker|conda] [--gpu] [--no-smoke]
# 流程：doctor 资源探测 → 选档（推荐档可 --tier 覆盖）→ docker compose 起服务（无 docker 走 conda setup_env.sh）
#       → 冒烟自检（/api/health + 能力清单）；--gpu 额外起 GPU 服务 compose profile（干净机器用，与宿主已有服务同端口会冲突）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TIER="" PORT="" MODE="" WITH_GPU=0 SMOKE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --tier) TIER="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --mode) MODE="$2"; shift 2;;
    --gpu) WITH_GPU=1; shift;;
    --no-smoke) SMOKE=0; shift;;
    *) echo "✗ 未知参数: $1"; echo "用法: bash deploy/install.sh [--tier T] [--port N] [--mode docker|conda] [--gpu] [--no-smoke]"; exit 1;;
  esac
done

# ── 0. python 定位（doctor 探测用） ──
PY=""
for c in /home/zxy/.conda/envs/comfyui/bin/python "$(command -v python3 || true)"; do
  if [ -n "$c" ] && [ -x "$c" ]; then PY="$c"; break; fi
done
[ -z "$PY" ] && { echo "✗ 找不到 python（先装 conda/python3）"; exit 1; }

# ── 1. doctor 资源探测 ──
echo "== [1] 资源探测 (doctor) =="
PROFILE="$($PY core/doctor.py --json 2>/dev/null)" || { echo "✗ doctor 探测失败"; exit 1; }
read -r GPU_N REC DISK_GB <<EOF
$(echo "$PROFILE" | $PY -c "import json,sys;d=json.load(sys.stdin);print(d['gpu_count'],d['recommended_tier'],round(d['disk']['free_gb']))")
EOF
echo "  GPU: ${GPU_N} 块 | 磁盘剩余: ${DISK_GB}GB | doctor 推荐档: $REC"

TIER="${TIER:-$REC}"
PORT="${PORT:-9400}"
if [ -z "$MODE" ]; then
  if command -v docker >/dev/null 2>&1; then MODE=docker; else MODE=conda; fi
fi
echo "  选定: tier=$TIER port=$PORT mode=$MODE"

# ── 2. 端口占用预检 ──
if ss -tln 2>/dev/null | grep -q ":$PORT "; then
  echo "✗ 端口 $PORT 已被占用（换 --port N 或停掉占用进程）"; exit 1
fi

# ── 3a. docker 路径 ──
if [ "$MODE" = "docker" ]; then
  echo "== [2] docker 镜像准备 =="
  if ! docker image inspect vidance-api:latest >/dev/null 2>&1; then
    echo "  本地无 vidance-api:latest，构建中（首次约 5-10 分钟，依赖层有缓存）..."
    docker build -f deploy/Dockerfile -t vidance-api:latest .
  else
    echo "  vidance-api:latest 已存在，跳过构建（要更新代码重 build：docker build -f deploy/Dockerfile -t vidance-api:latest .）"
  fi
  echo "== [3] 启动容器（tier=$TIER port=$PORT）=="
  (cd deploy && VIDANCE_TIER="$TIER" VIDANCE_PORT="$PORT" docker compose up -d vidance)
  if [ "$WITH_GPU" = "1" ] && [ "$TIER" != "none" ]; then
    echo "  追加启动 GPU 服务（profile gpu-$TIER）..."
    (cd deploy && VIDANCE_TIER="$TIER" VIDANCE_PORT="$PORT" docker compose --profile "gpu-$TIER" up -d)
  fi
# ── 3b. conda 路径（无 docker 的裸机） ──
else
  echo "== [2] conda 环境准备（setup_env.sh，首次较久）=="
  bash deploy/setup_env.sh
  echo "== [3] 启动 API（tier=$TIER port=$PORT）=="
  VIDANCE_TIER="$TIER" nohup "$PY" core/api_server.py --port "$PORT" \
    >> "$ROOT/output/install_api.log" 2>&1 < /dev/null &
  echo "  api_server 已后台启动（日志 output/install_api.log）；GPU 服务用 ./start_services.sh start <h3|wan|flux|h3d|tts>"
fi

[ "$SMOKE" = "0" ] && { echo "== 跳过冒烟（--no-smoke）== 安装完成"; exit 0; }

# ── 4. 冒烟自检 ──
echo "== [4] 冒烟自检 =="
HEALTH=""
for i in $(seq 1 30); do
  HEALTH="$(curl -s -m 3 "http://127.0.0.1:$PORT/api/health" 2>/dev/null || true)"
  echo "$HEALTH" | grep -q '"tier"' && break
  sleep 2
done
if ! echo "$HEALTH" | grep -q '"tier"'; then
  echo "✗ 健康检查超时（60s），看日志：docker logs vidance / output/install_api.log"; exit 1
fi
echo "$HEALTH" | $PY -c "
import json,sys
d=json.load(sys.stdin)
cap=d.get('capabilities',{})
print('  服务健康 ✓  tier=%s' % d.get('tier'))
print('  生成器: %s' % ','.join(cap.get('generators',[])))
print('  comfyui=%s tts=%s stt=%s auto=%s custom=%s' % (cap.get('comfyui'),cap.get('tts'),cap.get('stt'),cap.get('auto'),cap.get('custom')))
"
echo ""
echo "✅ 安装完成"
echo "  WebUI : http://127.0.0.1:$PORT/ui"
echo "  API   : http://127.0.0.1:$PORT/api/health | /api/tools | /api/doctor"
echo "  诊断  : curl 127.0.0.1:$PORT/api/doctor（端口/显存/外网点名）"
echo "  GPU 服务（docker 机器）: cd deploy && docker compose --profile gpu-<档> up -d"
echo "  GPU 服务（本机裸机）  : ./start_services.sh start <h3|wan|flux|h3d|tts>"
