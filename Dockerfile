# ---- Stage 1: build the bgutil POT provider with a supported Node runtime ----
FROM node:22-bookworm-slim AS pot-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --depth 1 --branch 2.0.0 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /build/bgutil

WORKDIR /build/bgutil/server
RUN npm ci --silent --no-audit --no-fund \
    && npx tsc \
    && test -f /build/bgutil/server/build/main.js

# ---- Stage 2: Python API image ----
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy Node 22 runtime + the compiled bgutil server from the builder.
COPY --from=pot-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=pot-builder /build/bgutil/server/build /app/bgutil/server/build
COPY --from=pot-builder /build/bgutil/server/node_modules /app/bgutil/server/node_modules

RUN python3 -m venv /opt/venv

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt \
    && python -m pip show yt-dlp \
    && python -m pip show bgutil-ytdlp-pot-provider

COPY app.py ./
COPY start.sh ./
RUN chmod +x /app/start.sh \
    && mkdir -p /tmp/youtube_data/downloads

EXPOSE 10000

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/start.sh"]
