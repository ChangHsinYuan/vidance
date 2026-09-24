#!/usr/bin/env bash
# 《奶蛙徽商》01-13 逐集批量生成（H3 ref2va 整段式 prompt → 原生音频直出）
#
# 参考图按剧情服装分档：
#   01-05：徽派布衣奶蛙.png（灰褐粗布短衣） + 豆包.jpg
#   06-13：成功徽商奶蛙.png（深青长袍）   + 豆包.jpg
# 输出：output/output/promptNN/NN.mp4（= /mnt/dataset/zxy/vidance/output/promptNN/）
#
# 用法：
#   bash utils/run_naiwa_episodes.sh            # 全部 01-13（跳过已存在的）
#   bash utils/run_naiwa_episodes.sh 2 5        # 只跑 02-05
#   FORCE=1 bash utils/run_naiwa_episodes.sh 6  # 重跑 06（覆盖）
#   FAST=1  bash utils/run_naiwa_episodes.sh    # 快速档（steps=14 + 1024x576，约省一半时间）
set -u
cd "$(dirname "$0")/.." || exit 1

PY=/home/zxy/.conda/envs/comfyui/bin/python
REF_BASE="input/徽派布衣奶蛙.png"      # 01-05 布衣奶蛙
REF_RICH="input/成功徽商奶蛙.png"      # 06-13 成功徽商奶蛙
REF_DB="input/豆包.jpg"

START="${1:-1}"
END="${2:-13}"
FORCE="${FORCE:-0}"
FAST_ARG=""
[ "${FAST:-0}" = "1" ] && FAST_ARG="--fast"

for i in $(seq "$START" "$END"); do
  p=$(printf '%02d' "$i")
  out="output/prompt${p}/${p}.mp4"
  if [ "$FORCE" != "1" ] && [ -f "/mnt/dataset/zxy/vidance/output/prompt${p}/${p}.mp4" ]; then
    echo "== 跳过 ${p}（已存在 $out）=="
    continue
  fi
  if [ "$i" -le 5 ]; then REF="$REF_BASE"; else REF="$REF_RICH"; fi
  echo "==== 生成 $p : $REF + $REF_DB ====  $(date '+%H:%M:%S') ===="
  "$PY" utils/h3_prompt_video.py \
    --prompt "input/prompt${i}.txt" \
    --ref "$REF" --name 奶蛙 \
    --ref "$REF_DB" --name 豆包 \
    $FAST_ARG \
    -o "$out" || echo "!! ${p} 失败，继续下一集"
  echo "==== 完成 $p ====  $(date '+%H:%M:%S') ===="
done
echo "全部结束 $(date '+%H:%M:%S')"
