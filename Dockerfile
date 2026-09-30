FROM python:3.11-slim

# System dependencies (ffmpeg, node, deno ke liye unzip zaroori)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    python3 \
    python3-pip \
    curl \
    ca-certificates \
    unzip \
    git \
    nodejs \
    npm \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# ⚡ IMPORTANT: yt-dlp[default] — EJS scripts included
RUN pip3 install --break-system-packages "yt-dlp[default]" \
    && yt-dlp --version

# Deno 2.x install (JS runtime for n-challenge)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh \
    && deno --version

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# ⚡ Clone and build bgutil POT provider
RUN git clone --single-branch --branch 2.0.0 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /app/bgutil

WORKDIR /app/bgutil/server
RUN npm ci && npx tsc

WORKDIR /app

# Copy app files
COPY app.py .
COPY yt_cookies.txt .

EXPOSE 10000

# ⚡ Start POT server + gunicorn
RUN echo '#!/bin/bash\n\
set -e\n\
echo "🚀 Starting POT server on port 4416..."\n\
node /app/bgutil/server/build/main.js --port 4416 &\n\
POT_PID=$!\n\
echo "✅ POT server PID: $POT_PID"\n\
sleep 10\n\
echo "🎬 Starting gunicorn..."\n\
exec gunicorn app:app --bind 0.0.0.0:$PORT --timeout 600 --workers 1 --threads 8 --preload\n\
' > /app/start.sh && chmod +x /app/start.sh

CMD ["/app/start.sh"]
