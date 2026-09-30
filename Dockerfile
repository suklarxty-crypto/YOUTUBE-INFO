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

# Verify
RUN deno --version && node --version && ffmpeg -version

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Clone and build bgutil POT provider
RUN git clone --single-branch --branch 2.0.0 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /app/bgutil
RUN cd /app/bgutil/server && \
    npm ci && \
    npx tsc

# Copy app
COPY app.py .
COPY yt_cookies.txt .

EXPOSE 10000

# Start POT server + gunicorn
CMD node /app/bgutil/server/build/main.js --port 4416 & \
    sleep 5 && \
    gunicorn app:app --bind 0.0.0.0:$PORT --timeout 600 --workers 1 --threads 8
