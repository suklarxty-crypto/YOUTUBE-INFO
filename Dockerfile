FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    curl \
    ca-certificates \
    unzip \
    git \
    nodejs \
    npm \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# ⚡ Install yt-dlp with EJS scripts (critical for YouTube)
RUN pip3 install --break-system-packages "yt-dlp[default]" \
    && yt-dlp --version

# Deno install (JS runtime for EJS challenges)
ENV DENO_INSTALL="/root/.deno"
ENV PATH="/root/.deno/bin:$PATH"
RUN curl -fsSL https://deno.land/install.sh | sh \
    && ln -sf /root/.deno/bin/deno /usr/local/bin/deno \
    && deno --version

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# ⚡ Clone and build bgutil POT provider (server)
RUN git clone --depth 1 --branch 2.0.0 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /app/bgutil

WORKDIR /app/bgutil/server
RUN npm ci --silent && \
    npm run build 2>/dev/null || npx tsc && \
    test -f /app/bgutil/server/build/main.js && \
    echo "✅ POT server built successfully"

WORKDIR /app

# Copy app files
COPY app.py .
COPY yt_cookies.txt .

EXPOSE 10000

# Start script: POT server + gunicorn
RUN printf '#!/bin/bash\n\
set -e\n\
echo "🚀 Starting POT server on port 4416..."\n\
node /app/bgutil/server/build/main.js --port 4416 > /tmp/pot.log 2>&1 &\n\
POT_PID=$!\n\
echo "✅ POT server PID: $POT_PID"\n\
for i in {1..15}; do\n\
  if curl -s http://127.0.0.1:4416/ping > /dev/null 2>&1; then\n\
    echo "✅ POT server is ready!"\n\
    break\n\
  fi\n\
  echo "⏳ Waiting for POT server... ($i/15)"\n\
  sleep 2\n\
done\n\
echo "🎬 Starting gunicorn..."\n\
exec gunicorn app:app --bind 0.0.0.0:$PORT --timeout 600 --workers 1 --threads 8\n\
' > /app/start.sh && chmod +x /app/start.sh

CMD ["/app/start.sh"]
