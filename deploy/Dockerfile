# Vidance API 层镜像（v18 部署档）
# CPU 依赖：FastAPI + svg 流水线（playwright/Chromium + CJK 字体）+ fast 爬图（ffmpeg/Pillow）
# LLM/选题走远程 API；TTS=edge-tts 在线；GPU 档位经 docker-compose.yml 叠加 ComfyUI 服务
# 档位由 VIDANCE_TIER 环境变量控制：none | flux | wan | h3 | full（缺省 none，纯 CPU 最小档）
FROM python:3.11-slim

# apt 换清华镜像（deb.debian.org 直连不稳）
RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null \
    || sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk procps \
       libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libdrm2 libxkbcommon0 \
       libatspi2.0-0t64 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2t64 \
       libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple \
    fastapi uvicorn pydantic requests edge-tts pillow numpy scipy moviepy bs4 feedparser playwright \
    && PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright playwright install chromium

# 缺省最小档（无 GPU）；挂宿主服务/换档用 compose 或 -e 覆盖
ENV VIDANCE_TIER=none \
    VIDANCE_PORT=8894

EXPOSE 8894
CMD ["python", "core/api_server.py"]
