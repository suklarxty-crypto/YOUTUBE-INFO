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

# Install Deno (JavaScript runtime for yt-dlp EJS)
RUN curl -fsSL https://deno.land/install.sh | sh
ENV DENO_INSTALL="/root/.deno"
ENV PATH="$DENO_INSTALL/bin:$PATH"

# Verify Deno
RUN deno --version

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install bgutil PO Token provider plugin
RUN pip install --no-cache-dir bgutil-ytdlp-pot-provider

# Copy app files
COPY app.py .
COPY yt_cookies.txt .

# Expose port
EXPOSE 10000

# Start command
CMD gunicorn app:app --bind 0.0.0.0:$PORT --timeout 300 --workers 1 --threads 4
