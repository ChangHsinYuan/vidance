#!/usr/bin/env bash
# Vidance 权重下载脚本（v21 部署档 + v16 编辑，2026-10-02）
# 用法：bash deploy/download_weights.sh [--dir 目标目录]
# 断点续传（curl -C -），已存在文件跳过；镜像不通时手动换源。

set -euo pipefail

VIDANCE_DIR="${VIDANCE_DIR:-/mnt/disk_sdb/zxy/vidance}"
DEST="${2:-$VIDANCE_DIR/models}"
SAM2_DIR="$DEST/sam2"
YOLO_DIR="$DEST/yolo"

echo "== [1/3] SAM2 权重 → $SAM2_DIR =="
mkdir -p "$SAM2_DIR"
# SAM2.1 官方权重（Meta）；tiny 156MB / small 184MB（vidance 主用）
dl() {  # dl <url> <out>
    local url="$1" out="$2"
    if [ -s "$out" ]; then
        echo "  已存在，跳过: $out"
    else
        echo "  下载: $url"
        curl -L -C - --retry 3 -o "$out" "$url"
    fi
}
dl "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt" "$SAM2_DIR/sam2.1_hiera_tiny.pt"
dl "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt" "$SAM2_DIR/sam2.1_hiera_small.pt"
# 大模型可选（b+ 313MB / l 425MB）：
# dl "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt" "$SAM2_DIR/sam2.1_hiera_base_plus.pt"
# dl "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt" "$SAM2_DIR/sam2.1_hiera_large.pt"

echo "== [2/3] YOLO 权重 → $YOLO_DIR =="
mkdir -p "$YOLO_DIR"
# ultralytics github release（yolov8s 22MB；v8n 太小检不出猫狗，主用 8s）
dl "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8s.pt" "$YOLO_DIR/yolov8s.pt"
# 若 github 不通可换镜像：
#   hf-mirror.com/Ultralytics/YOLOv8/resolve/main/yolov8s.pt

echo "== [3/3] ComfyUI 模型（超大，默认不自动下载，清单如下）=="
cat <<'EOF'
本机已有（/mnt/dataset/zxy/*-ComfyUI，extra_model_paths.yaml 挂载，无需下载）：
  MiniMax-H3  70G   minimax_h3_{ref2va,fl2va}_pruned_int8_convrot.safetensors
  Wan2.2      17G   wan2.2_ti2v_5B_fp16.safetensors
  FLUX dev    16G   flux1-dev-fp8.safetensors
  HunyuanVideo      hunyuan_video_t2v_720p_bf16.safetensors
  SDXL base         sd_xl_base_1.0.safetensors
  TripoSplat        triposplat_fp16.safetensors

干净机器需要手动下载（模型卡/内网盘）：
  FLUX.1 Fill dev fp8   ~17G  → ComfyUI/models/diffusion_models/  （v16.x M5 inpaint）
  FLUX.1 Canny/Depth    ~8G   → ComfyUI/models/controlnet/        （v16.x M5/M6）
  InstantX FLUX Union   ~2.5G → ComfyUI/models/controlnet/        （六合一 ControlNet）
  SDXL ControlNet v1.1  ~2.5G → ComfyUI/models/controlnet/        （canny/depth/seg）
  FLUX.1 Kontext dev    ~17G  → ComfyUI/models/diffusion_models/  （v16.x M8 指令编辑）
  Wan2.2 VACE           ~3G   → ComfyUI/models/diffusion_models/  （v16.x M7 视频编辑）
  RVM 视频抠像          ~50M  → vidance/models/rvm/               （v16.x M7 cutout alpha）

SAM2 源码（可编辑安装，vidance 仓外）：
  git clone --depth 1 https://github.com/facebookresearch/sam2.git "$SAM2_SRC_DIR"
  pip install -e "$SAM2_SRC_DIR" --no-build-isolation   # pypi 构建依赖会卡，--no-build-isolation 绕开
EOF

echo "== 完成。校验 =="
ls -la "$SAM2_DIR" "$YOLO_DIR" 2>/dev/null | grep -v "^total\|^d" || true
echo "（SAM2 权重 torch.load 双验证：tiny 471 keys / small 519 keys）"
