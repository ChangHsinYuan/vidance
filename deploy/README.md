# Vidance 部署档（v21，原 v18）

> 按部署机器的硬件能力分档打包：能走接口的走接口（LLM/选题/TTS=edge-tts 在线），能部署的模型才进档。同一份代码 + `VIDANCE_TIER` 环境变量 + `config/tiers/{档}.json` 覆盖，Docker 挂一个端口即服务。

## 档位阶梯（逐级累加）

| 档 | GPU | 能力 | LLM | TTS | 图源 | 视频 |
|----|-----|------|-----|-----|------|------|
| `none` | 无 | svg + fast（爬图部分） | USTC 远程 API | edge-tts（在线） | Pexels/必应爬图 | 仅 SVG 动画 |
| `flux` | 1×图像卡 | + SDXL/FLUX 生图 | 同上 | 同上 | 爬图 + FLUX 补足 | 仅 SVG 动画 |
| `wan` | 1×视频卡 | + Wan T2V/I2V + RIFE + auto/quick | 同上 | + CosyVoice（本地） | 同上 | + Wan 视频 |
| `h3` | 1× | + MiniMax-H3 ref2va + custom/h3shot | 同上 | 同上 | 同上 | 同上 |
| `full` | 多卡 | 全功能（含 Hunyuan3D/STT/克隆） | 同上 | 同上 | 同上 | 全部 |

- 档位定义：`config/tiers/{none,flux,wan,h3,full}.json`（`tier_capabilities`：generators/comfyui/tts/stt/auto/custom/h3shot）
- 守卫点：`GET /api/health` 报档位+能力 · `GET /api/tools` 按档过滤 · `POST /api/tool/{name}` 档位不足 400 · CLI `auto/quick/hot`（需 wan）、`custom/h3shot`（需 h3）直接退出并提示换档
- 缺省 `VIDANCE_TIER` 未设 = `full`（宿主机行为零变化）

## Docker 用法（本机 = full 档演示）

```bash
# ── 一键安装（v21 M2）：探测 → 选档 → 起容器 → 冒烟 ──
bash deploy/install.sh                          # doctor 推荐档，默认 :9400，docker
bash deploy/install.sh --tier full --port 9401  # 指定档/端口
bash deploy/install.sh --gpu                    # 干净机器额外起 GPU 服务（compose gpu-* profile）
bash deploy/install.sh --mode conda             # 无 docker：setup_env.sh + 后台 api_server

cd /mnt/disk_sdb/zxy/vidance

# 全量档：容器内 vidance API（host 网络直连宿主 ComfyUI/TTS），挂 9401
VIDANCE_TIER=full VIDANCE_PORT=9401 docker compose -f deploy/docker-compose.yml up -d vidance
curl http://127.0.0.1:9401/api/health      # → "tier": "full"

# 最小档：无 GPU 机器（别的服务器/PC），挂 9400
VIDANCE_TIER=none docker compose -f deploy/docker-compose.yml up -d vidance
curl http://127.0.0.1:9400/api/health      # → "tier": "none"，capabilities.generators=[svg,fast]
```

- **API 镜像** `deploy/Dockerfile`（python:3.11-slim + ffmpeg + Noto CJK + playwright/Chromium，~2GB）：API + svg + fast 爬图开箱即用
- **产出**：容器 `/app/output` 卷挂宿主 `output/`（统一产出目录不变）
- **配置**：容器 `/app/config` 卷挂宿主 `config/`（LLM key/tier 定义随卷进容器；改档不用重 build）

## 干净机器上的 ComfyUI 容器（可选，构建重 ~10GB）

```bash
docker compose -f deploy/docker-compose.yml --profile gpu-wan up -d comfyui-wan   # Wan:8189 GPU2
# profiles: gpu-flux/gpu-wan/gpu-h3/gpu-full；模型经 volume 挂 /mnt/dataset（不进镜像）
```

> 本机已有宿主 ComfyUI 服务，**勿**启动同端口容器（8188/8189/8192 冲突）。
> ⚠️ ComfyUI 容器同样不能加 `--cuda-device`（覆盖 CUDA_VISIBLE_DEVICES）。

## 端口约定

| 档 | 服务 | 端口 |
|----|------|------|
| 任意档 | vidance API（容器） | `VIDANCE_PORT`，缺省 9400 |
| full（本机演示） | vidance API | 9401 |
| 宿主已有 | h3/wan/flux/tts/api | 8188/8189/8192/9880/8894（不变） |

## 环境固化与一键准备（2026-10-02，v16 编辑增强配套）

| 文件 | 用途 |
|------|------|
| `requirements-lock.txt` | 主环境（comfyui env）版本冻结。**三条铁律**：numpy 1.26.x（bpy 兼容）/ opencv 4.11 headless（5.x 连带 numpy 2.x）/ sam2 可编辑安装 |
| `setup_env.sh` | 干净机器一键准备：pip 锁定安装 + SAM2 可编辑安装（`--no-build-isolation` 绕 pypi 构建卡死）+ bpy X 库 + 权重下载 + 全量验证（import/权重/GPU） |
| `download_weights.sh` | 权重下载（SAM2 tiny/small + YOLOv8s，curl 断点续传；大模型清单+手动下载说明） |

```bash
# 干净机器（或重建后）：
bash deploy/setup_env.sh                       # 默认找 comfyui env
bash deploy/setup_env.sh -- /path/to/python    # 指定解释器

# 冒烟验证：
python core/vidance.py edit visualize 图.jpg --yolo --classes "cat,dog"   # Grounded-SAM 流程
```

> 权重目录：`models/sam2/`（tiny+small）+ `models/yolo/`（yolov8s）；`*.pt` 已 gitignore，重建后跑 download_weights.sh 即可恢复。
> 大模型（FLUX Fill/Canny/Kontext、Wan2.2 VACE 等编辑系候选）不进自动化下载——见 download_weights.sh 清单，手动下载到 ComfyUI/models/ 对应子目录。
