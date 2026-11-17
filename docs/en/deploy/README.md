> English | [简体中文](../../../deploy/README.md)

# Vidance Deployment Tiers (v21, formerly v18)

> Package by the deployment machine's hardware: anything that can go through an API goes through an API (LLM/topic selection/TTS = edge-tts online); only models that can actually be deployed enter a tier. Same codebase + `VIDANCE_TIER` env var + `config/tiers/{tier}.json` overrides; Docker mounts one port and it serves.

## Tier ladder (cumulative)

| Tier | GPU | Capabilities | LLM | TTS | Image source | Video |
|------|-----|--------------|-----|-----|--------------|-------|
| `none` | None | svg + fast (crawled-image part) | USTC remote API | edge-tts (online) | Pexels/Bing crawl | SVG animation only |
| `flux` | 1× image GPU | + SDXL/FLUX image generation | Same | Same | Crawl + FLUX backfill | SVG animation only |
| `wan` | 1× video GPU | + Wan T2V/I2V + RIFE + auto/quick | Same | + CosyVoice (local) | Same | + Wan video |
| `h3` | 1× | + MiniMax-H3 ref2va + custom/h3shot | Same | Same | Same | Same |
| `full` | Multi-GPU | Full feature set (incl. Hunyuan3D/STT/cloning) | Same | Same | Same | All |

- Tier definitions: `config/tiers/{none,flux,wan,h3,full}.json` (`tier_capabilities`: generators/comfyui/tts/stt/auto/custom/h3shot)
- Guard points: `GET /api/health` reports tier + capabilities · `GET /api/tools` filters by tier · `POST /api/tool/{name}` returns 400 when the tier is insufficient · CLI `auto/quick/hot` (needs wan), `custom/h3shot` (needs h3) exit directly with a hint to switch tiers
- `VIDANCE_TIER` unset defaults to `full` (zero behavior change on the host machine)

## Docker usage (this machine = full-tier demo)

```bash
# ── One-line install (v21 M2): probe → pick tier → start container → smoke ──
bash deploy/install.sh                          # doctor recommends the tier, default :9400, docker
bash deploy/install.sh --tier full --port 9401  # explicit tier/port
bash deploy/install.sh --gpu                    # on a clean machine, also start GPU services (compose gpu-* profile)
bash deploy/install.sh --mode conda             # no docker: setup_env.sh + background api_server

cd /mnt/disk_sdb/zxy/vidance

# Full tier: vidance API in a container (host network reaches host ComfyUI/TTS directly), on 9401
VIDANCE_TIER=full VIDANCE_PORT=9401 docker compose -f deploy/docker-compose.yml up -d vidance
curl http://127.0.0.1:9401/api/health      # → "tier": "full"

# Minimal tier: GPU-less machine (another server/PC), on 9400
VIDANCE_TIER=none docker compose -f deploy/docker-compose.yml up -d vidance
curl http://127.0.0.1:9400/api/health      # → "tier": "none", capabilities.generators=[svg,fast]
```

- **API image** `deploy/Dockerfile` (python:3.11-slim + ffmpeg + Noto CJK + playwright/Chromium): API + svg + fast image-crawl works out of the box
- **Cloud pull**: after pushing a tag (e.g. `v1.1.0`) the Release workflow builds and pushes `ghcr.io/changhsinyuan/vidance-api:{tag,latest}`; to skip a local build, `export VIDANCE_API_IMAGE=ghcr.io/changhsinyuan/vidance-api:latest` before compose up (compose supports this override variable)
- **Output**: container `/app/output` volume-mounts the host `output/` (the unified output dir is unchanged)
- **Config**: container `/app/config` volume-mounts the host `config/` (LLM key/tier definitions ride the volume into the container; changing tiers requires no rebuild)

## Images & offline delivery (2026-11-06)

> **Five tiers ≠ five images**: all tiers share one `vidance-api:latest`; the tier is decided by the `VIDANCE_TIER` env var + `config/tiers/*.json` (see above). The image tags carry only three derived meanings:

| Tag | Description |
|-----|-------------|
| `vidance-api:latest` | Main image (always required); `full` is an alias of it |
| `vidance-api:rag` | + CPU torch/transformers/faiss (only needed for RAG novel-retrieval enhancement; optional) |
| `vidance-api:update` | Thin dev hot-update image (code layer only); can be omitted from delivery |
| `vidance-comfyui:latest` | GPU services image (~10GB); built on demand for the `--gpu` profile on clean machines |

**Offline delivery bundle** (`dist/images/`, checksummed docker save artifacts; `*.tar.gz` are gitignored):

```bash
# Export on this machine (after rebuilding the image):
docker save vidance-api:latest | gzip > dist/images/vidance-api-latest.tar.gz

# Import + one-line install on the target machine:
docker load < vidance-api-latest.tar.gz
docker tag vidance-api:latest vidance-api:full
bash deploy/install.sh        # image already local; jumps straight to container start + smoke test
```

## ComfyUI containers on clean machines (optional, ~10GB build)

```bash
docker compose -f deploy/docker-compose.yml --profile gpu-wan up -d comfyui-wan   # Wan:8189 GPU2
# profiles: gpu-flux/gpu-wan/gpu-h3/gpu-full; models volume-mounted from /mnt/dataset (not baked into the image)
```

> This machine already runs host ComfyUI services — do **not** start same-port containers (8188/8189/8192 conflicts).
> ⚠️ ComfyUI containers likewise must NOT get `--cuda-device` (it overrides CUDA_VISIBLE_DEVICES).

## Port conventions

| Tier | Service | Port |
|------|---------|------|
| Any tier | vidance API (container) | `VIDANCE_PORT`, default 9400 |
| full (demo on this machine) | vidance API | 9401 |
| Already on host | h3/wan/flux/tts/api | 8188/8189/8192/9880/8894 (unchanged) |

## Environment pinning & one-shot prep (2026-10-02, companion to v16 editing enhancements)

| File | Purpose |
|------|---------|
| `requirements-lock.txt` | Version freeze for the main env (comfyui env). **Three iron rules**: numpy 1.26.x (bpy compatibility) / opencv 4.11 headless (5.x drags in numpy 2.x) / sam2 as editable install |
| `setup_env.sh` | One-shot prep on clean machines: locked pip install + SAM2 editable install (`--no-build-isolation` to dodge the PyPI build hang) + bpy X libs + weight downloads + full verification (imports/weights/GPU) |
| `download_weights.sh` | Weight downloads (SAM2 tiny/small + YOLOv8s, curl with resume; large-model manifest + manual download instructions) |

```bash
# Clean machine (or after a rebuild):
bash deploy/setup_env.sh                       # finds the comfyui env by default
bash deploy/setup_env.sh -- /path/to/python    # explicit interpreter

# Smoke test:
python core/vidance.py edit visualize 图.jpg --yolo --classes "cat,dog"   # Grounded-SAM flow
```

> Weight dirs: `models/sam2/` (tiny+small) + `models/yolo/` (yolov8s); `*.pt` are gitignored — rerun download_weights.sh after a rebuild to restore.
> Large models (FLUX Fill/Canny/Kontext, Wan2.2 VACE and other editing candidates) are not in the automated download — see the manifest in download_weights.sh and fetch them manually into the matching ComfyUI/models/ subdirectories.
