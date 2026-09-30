FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    git \
    ffmpeg \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Deno
RUN curl -fsSL https://deno.land/install.sh | sh
ENV DENO_INSTALL="/root/.deno"
ENV PATH="$DENO_INSTALL/bin:$PATH"

# Verify installations
RUN deno --version && node --version && ffmpeg -version

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Clone and build bgutil POT provider
RUN git clone --single-branch --branch 2.0.0 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /app/bgutil

WORKDIR /app/bgutil/server
RUN npm ci && npx tsc

WORKDIR /app

# Copy app files
COPY app.py .
COPY yt_cookies.txt .

EXPOSE 10000

# Start script: POT server + gunicorn
RUN echo '#!/bin/bash\n\
    set -e\n\
    echo "Starting POT server..."\n\
    node /app/bgutil/server/build/main.js --port 4416 &\n\
    POT_PID=$!\n\
    echo "POT server PID: $POT_PID"\n\
    sleep 8\n\
    echo "Starting gunicorn..."\n\
    exec gunicorn app:app --bind 0.0.0.0:$PORT --timeout 600 --workers 1 --threads 8\n\
' > /app/start.sh && chmod +x /app/start.sh

CMD ["/app/start.sh"]
