#!/usr/bin/env bash
# =============================================================================
# Vidance 模型服务一键启动/停止/状态脚本
# -----------------------------------------------------------------------------
# 用法：
#   ./start_services.sh                 # 启动全部服务（默认）
#   ./start_services.sh start [名称...] # 启动指定服务（如 start tts wan）
#   ./start_services.sh stop            # 停止全部服务
#   ./start_services.sh stop tts        # 停止指定服务
#   ./start_services.sh restart         # 重启全部
#   ./start_services.sh status          # 查看端口/进程/显存
#   ./start_services.sh test            # 逐服务连通性自检 + TTS 合成测试
#   ./start_services.sh logs [名称]     # 跟踪日志（默认 api）
#
# 服务名 → 端口 / GPU 对应：
#   h3       8188  GPU0  MiniMax-H3 ref2va（custom 模式参考图条件视频，重，~46G）
#   wan      8189  GPU2  Wan T2V/I2V + RIFE（auto/quick 视频生成）
#   flux     8192  GPU3  FLUX T2I / TripoSplat（角色/场景图、fast flux 模式）
#   hunyuan  8190  GPU3  HunyuanVideo（T2V 备选，与 flux 互斥，默认不启）
#   h3d      8193  GPU1  Hunyuan3Dv2（v3 mesh 重建）
#   tts      9880  GPU2  TTS 双引擎（edge-tts 在线 + CosyVoice 本地，启动即加载占 ~4.5G）
#   api      8894  CPU   Vidance API + WebUI（Docker 不需要 GPU）
#
# 重要约定：
#   * ComfyUI 启动【绝对不能】加 --cuda-device，否则会覆盖 CUDA_VISIBLE_DEVICES
#     （ComfyUI/main.py:87 逻辑）。用环境变量 CUDA_VISIBLE_DEVICES=N 指定卡。
#   * FLUX(8192) 与 HunyuanVideo(8190) 默认共用 GPU3，二者互斥，本脚本默认只启 flux。
#   * 模型是按需加载：ComfyUI 启动时只占几百 M，首次跑 workflow 才吃满显存。
#   * TTS 启动即 load_model（CosyVoice 进 GPU2，约 28s），不是 lazy。
#   * edge-tts 是微软在线服务，需要外网。若连不上（Connection timeout to
#     speech.platform.bing.com），改用本地 CosyVoice 音色 cosy-* 即可。
#     本机 config 默认音色是 edge-moe，用 --voice 覆盖成 cosy-* 可绕过。
#
# =============================================================================

set -u

# ── 路径 / 环境常量 ──────────────────────────────────────────────────────────
VIDANCE_DIR="/mnt/disk_sdb/zxy/vidance"
COMFYUI_DIR="/mnt/disk_sdb/zxy/ComfyUI"
PY_COMFY="/home/zxy/.conda/envs/comfyui/bin/python"   # 主环境（ComfyUI/API）
PY_COSY="/home/zxy/.conda/envs/cosyvoice/bin/python"  # TTS 环境
LOG_DIR="/tmp"

# 默认要启动的服务（顺序即启动顺序；hunyuan/h3d 默认不启，需要时显式传名）
DEFAULT_SERVICES="h3 wan flux tts api"
ALL_SERVICES="h3 wan flux hunyuan h3d tts api"

# ── 工具函数 ─────────────────────────────────────────────────────────────────
c_green() { printf '\033[32m%s\033[0m\n' "$*"; }
c_red()   { printf '\033[31m%s\033[0m\n' "$*"; }
c_yel()   { printf '\033[33m%s\033[0m\n' "$*"; }

# 端口是否在监听
port_up() { curl -s -m 3 -o /dev/null "http://127.0.0.1:$1/" 2>/dev/null; }

# 按进程命令行关键字查 PID
pids_of() { pgrep -f "$1" 2>/dev/null | tr '\n' ' '; }

# 后台启动：setsid + nohup，彻底脱离当前 shell（避免阻塞/被父 shell 带走）
# 关键点：用 setsid 新建会话+进程组，且 stdin/stdout/stderr 全部重定向，
#         这样即使被 opencode/CI 这类会等待子进程管道的工具调用，也不会挂住。
# 用法：bg_run <标签> <日志文件> <工作目录> <命令...>
bg_run() {
    local tag="$1" log="$2" workdir="$3"; shift 3
    (
        cd "$workdir" || exit 1
        setsid "$@" >"$log" 2>&1 </dev/null &
        disown 2>/dev/null || true
    ) >/dev/null 2>&1 </dev/null
}

# 单个服务定义：解析 name → 端口
port_of() {
    case "$1" in
        h3)      echo 8188 ;;
        wan)     echo 8189 ;;
        hunyuan) echo 8190 ;;
        flux)    echo 8192 ;;
        h3d)     echo 8193 ;;
        tts)     echo 9880 ;;
        api)     echo 8894 ;;
        *)       echo "" ;;
    esac
}

# 匹配该服务的进程命令行特征（用于 stop / 查进程）
match_of() {
    case "$1" in
        h3)      echo "main.py --listen 0.0.0.0 --port 8188" ;;
        wan)     echo "main.py --listen 0.0.0.0 --port 8189" ;;
        hunyuan) echo "main.py --listen 0.0.0.0 --port 8190" ;;
        flux)    echo "main.py --listen 0.0.0.0 --port 8192" ;;
        h3d)     echo "main.py --listen 0.0.0.0 --port 8193" ;;
        tts)     echo "[t]ts_server.py" ;;
        api)     echo "[a]pi_server.py --port 8894" ;;
        *)       echo "" ;;
    esac
}

# ── 启动单个服务 ─────────────────────────────────────────────────────────────
start_one() {
    local name="$1" port; port="$(port_of "$name")"
    if [ -z "$port" ]; then c_red "未知服务: $name"; return 1; fi

    if port_up "$port"; then
        c_yel "[$name] 已在运行（端口 $port），跳过"; return 0
    fi

    case "$name" in
        h3)   # H3 ref2va → GPU0
            bg_run h3 "$LOG_DIR/comfyui_8188.log" "$COMFYUI_DIR" \
                env CUDA_VISIBLE_DEVICES=0 "$PY_COMFY" main.py --listen 0.0.0.0 --port 8188 ;;
        wan)  # Wan T2V/I2V + RIFE → GPU2
            bg_run wan "$LOG_DIR/comfyui_8189.log" "$COMFYUI_DIR" \
                env CUDA_VISIBLE_DEVICES=2 "$PY_COMFY" main.py --listen 0.0.0.0 --port 8189 ;;
        hunyuan) # HunyuanVideo → GPU3（与 flux 互斥）
            bg_run hunyuan "$LOG_DIR/comfyui_8190.log" "$COMFYUI_DIR" \
                env CUDA_VISIBLE_DEVICES=3 "$PY_COMFY" main.py --listen 0.0.0.0 --port 8190 ;;
        flux) # FLUX / TripoSplat → GPU3
            bg_run flux "$LOG_DIR/comfyui_8192.log" "$COMFYUI_DIR" \
                env CUDA_VISIBLE_DEVICES=3 "$PY_COMFY" main.py --listen 0.0.0.0 --port 8192 ;;
        h3d)  # Hunyuan3Dv2 → GPU1
            bg_run h3d "$LOG_DIR/comfyui_8193.log" "$COMFYUI_DIR" \
                env CUDA_VISIBLE_DEVICES=1 "$PY_COMFY" main.py --listen 0.0.0.0 --port 8193 ;;
        tts)  # TTS 双引擎 → GPU2（启动即加载 CosyVoice，约 28s）
            bg_run tts "$LOG_DIR/tts_9880.log" "$VIDANCE_DIR" \
                env CUDA_VISIBLE_DEVICES=2 TTS_FP16=1 "$PY_COSY" utils/tts_server.py ;;
        api)  # Vidance API + WebUI → CPU
            bg_run api "$LOG_DIR/api_8894.log" "$VIDANCE_DIR" \
                "$PY_COMFY" core/api_server.py --port 8894 ;;
    esac

    # 等待端口就绪（TTS 加载慢，给 60s；ComfyUI 给 40s）
    local wait_s=40; [ "$name" = "tts" ] && wait_s=75
    local i=0
    while [ $i -lt "$wait_s" ]; do
        if port_up "$port"; then c_green "[$name] 已启动 :$port ($(match_of "$name" | head -c 20)...)"; return 0; fi
        sleep 1; i=$((i+1))
    done
    c_red "[$name] 启动超时（端口 $port 未就绪），查看日志: $LOG_DIR/$name*.log"
    return 1
}

# ── 停止单个服务 ─────────────────────────────────────────────────────────────
stop_one() {
    local name="$1" port; port="$(port_of "$name")"
    local pat; pat="$(match_of "$name")"
    local pids; pids="$(pids_of "$pat")"
    if [ -z "$pids" ]; then c_yel "[$name] 未在运行"; return 0; fi
    # 注意：不要用 pkill -f，会连自身 shell 一起杀；拿 PID 逐个 kill
    for pid in $pids; do kill "$pid" 2>/dev/null; done
    sleep 2
    # 二次确认，残留则强杀
    pids="$(pids_of "$pat")"
    for pid in $pids; do kill -9 "$pid" 2>/dev/null; done
    c_green "[$name] 已停止（端口 $port）"
}

# ── 状态 ─────────────────────────────────────────────────────────────────────
show_status() {
    echo "======== 服务状态 ========"
    printf "%-8s %-6s %-8s %s\n" "服务" "端口" "状态" "PID"
    for name in $ALL_SERVICES; do
        local port; port="$(port_of "$name")"
        local pat; pat="$(match_of "$name")"
        local pids; pids="$(pids_of "$pat")"
        if port_up "$port" >/dev/null 2>&1; then
            printf "%-8s %-6s \033[32m%-8s\033[0m %s\n" "$name" "$port" "UP" "$pids"
        else
            printf "%-8s %-6s \033[31m%-8s\033[0m %s\n" "$name" "$port" "DOWN" "$pids"
        fi
    done
    echo
    echo "======== GPU 显存 ========"
    nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader 2>/dev/null \
        || c_red "nvidia-smi 不可用"
}

# ── 自检（逐服务 + TTS 合成）─────────────────────────────────────────────────
run_test() {
    echo "======== 连通性自检 ========"
    for name in $ALL_SERVICES; do
        local port; port="$(port_of "$name")"
        if port_up "$port" >/dev/null 2>&1; then
            c_green "[$name] :$port 可达"
        else
            c_red "[$name] :$port 不可达"
        fi
    done

    echo
    echo "======== LLM 远程连通 ========"
    "$PY_COMFY" - <<'PYEOF' 2>&1 | tail -2
import sys
sys.path.insert(0, '/mnt/disk_sdb/zxy/vidance')
from utils.llm import LLMClient
from core.scheduler import load_config
try:
    r = LLMClient(load_config()).chat([{'role': 'user', 'content': '回复OK'}])
    print('LLM OK:', str(r)[:60])
except Exception as e:
    print('LLM FAIL:', repr(e)[:150])
PYEOF

    echo
    echo "======== TTS 合成测试 ========"
    echo "-- edge-tts（微软在线，需外网）--"
    curl -s -m 30 -X POST http://127.0.0.1:9880/tts -H 'Content-Type: application/json' \
        -d '{"text":"测试一下","voice":"edge-moe"}' | head -c 160; echo
    echo "-- cosy-default（本地 GPU）--"
    curl -s -m 120 -X POST http://127.0.0.1:9880/tts -H 'Content-Type: application/json' \
        -d '{"text":"测试一下声音是否正常","voice":"cosy-default"}' | head -c 160; echo
    echo "-- cosy-jieshuo1（克隆音色）--"
    curl -s -m 120 -X POST http://127.0.0.1:9880/tts -H 'Content-Type: application/json' \
        -d '{"text":"深夜的灯塔，守夜人独自值班","voice":"cosy-jieshuo1"}' | head -c 160; echo

    echo
    echo "提示：TTS 返回 JSON {\"audio\":\"...base64 wav...\"} 即成功；"
    echo "      edge-* 报 Connection timeout 是外网问题，改用 cosy-* 音色即可。"
}

# ── 日志 ─────────────────────────────────────────────────────────────────────
show_logs() {
    local name="${1:-api}"
    local f
    case "$name" in
        h3)    f="$LOG_DIR/comfyui_8188.log" ;;
        wan)   f="$LOG_DIR/comfyui_8189.log" ;;
        flux)  f="$LOG_DIR/comfyui_8192.log" ;;
        h3d)   f="$LOG_DIR/comfyui_8193.log" ;;
        tts)   f="$LOG_DIR/tts_9880.log" ;;
        api)   f="$LOG_DIR/api_8894.log" ;;
        *) c_red "未知服务: $name"; return 1 ;;
    esac
    echo "跟踪 $f （Ctrl+C 退出）"
    tail -f "$f"
}

# ── 主入口 ───────────────────────────────────────────────────────────────────
CMD="${1:-start}"; shift || true

case "$CMD" in
    start)
        SERVICES="${*:-$DEFAULT_SERVICES}"
        for s in $SERVICES; do start_one "$s"; done
        echo; show_status
        ;;
    stop)
        SERVICES="${*:-$ALL_SERVICES}"
        for s in $SERVICES; do stop_one "$s"; done
        ;;
    restart)
        # 支持 restart [服务名...]：给了名字只重启这些，否则全部
        RESTART_LIST="${*:-}"
        if [ -n "$RESTART_LIST" ]; then
            echo "先停止: $RESTART_LIST"; for s in $RESTART_LIST; do stop_one "$s"; done
            sleep 2
            echo "再启动: $RESTART_LIST"; for s in $RESTART_LIST; do start_one "$s"; done
        else
            echo "先停止全部..."; for s in $ALL_SERVICES; do stop_one "$s"; done
            sleep 2
            echo "再启动默认集..."; for s in $DEFAULT_SERVICES; do start_one "$s"; done
        fi
        echo; show_status
        ;;
    status) show_status ;;
    test)   run_test ;;
    logs)   show_logs "${1:-api}" ;;
    *)
        echo "用法: $0 {start|stop|restart|status|test|logs} [服务名...]"
        echo "服务名: $ALL_SERVICES"
        exit 1
        ;;
esac
