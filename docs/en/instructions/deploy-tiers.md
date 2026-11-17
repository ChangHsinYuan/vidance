> English | [简体中文](../../instructions/deploy-tiers.md)

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
cd /mnt/disk_sdb/zxy/vidance

# Full tier: vidance API in a container (host network reaches host ComfyUI/TTS directly), on 9401
VIDANCE_TIER=full VIDANCE_PORT=9401 docker compose -f deploy/docker-compose.yml up -d vidance
curl http://127.0.0.1:9401/api/health      # → "tier": "full"

# Minimal tier: GPU-less machine (another server/PC), on 9400
VIDANCE_TIER=none docker compose -f deploy/docker-compose.yml up -d vidance
curl http://127.0.0.1:9400/api/health      # → "tier": "none", capabilities.generators=[svg,fast]
```

- **API image** `deploy/Dockerfile` (python:3.11-slim + ffmpeg + Noto CJK + playwright/Chromium, ~2GB): API + svg + fast image-crawl works out of the box
- **Output**: container `/app/output` volume-mounts the host `output/` (the unified output dir is unchanged)
- **Config**: container `/app/config` volume-mounts the host `config/` (LLM key/tier definitions ride the volume into the container; changing tiers requires no rebuild)

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
