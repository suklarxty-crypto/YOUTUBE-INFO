#!/bin/bash
set -e

echo "=========================================="
echo "🎬 YouTube Downloader API v29.3"
echo "=========================================="

mkdir -p /tmp/youtube_data/downloads

# ---- Start bgutil POT server ----
echo "Starting bgutil POT server on 127.0.0.1:4416..."
node /app/bgutil/server/build/main.js --port 4416 &
POT_PID=$!
echo "POT PID=$POT_PID"

# ---- Wait for POT ----
READY=0
for i in $(seq 1 30); do
    echo "Waiting for POT server... ($i/30)"
    if curl -sf --max-time 2 http://127.0.0.1:4416/ping > /dev/null 2>&1; then
        echo "✅ POT server ready after ${i}s"
        READY=1
        break
    fi
    if ! kill -0 $POT_PID 2>/dev/null; then
        echo "❌ POT server process died"
        exit 1
    fi
    sleep 1
done

if [ "$READY" != "1" ]; then
    echo "⚠️ POT not responding after 30s — continuing anyway"
fi

# ---- Cleanup handler ----
cleanup() {
    echo "🛑 Shutting down..."
    kill $POT_PID 2>/dev/null || true
    wait $POT_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# ---- Start Gunicorn ----
PORT="${PORT:-10000}"
echo "🚀 Starting Gunicorn on 0.0.0.0:${PORT}..."

exec gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers 1 \
    --threads 8 \
    --worker-class gthread \
    --timeout 300 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    app:app
