#!/bin/sh
set -eu

POT_LOG=/tmp/pot.log
POT_PID=""
GUNICORN_PID=""

cleanup() {
  status=$?
  if [ -n "${GUNICORN_PID}" ]; then
    kill -TERM "${GUNICORN_PID}" 2>/dev/null || true
  fi
  if [ -n "${POT_PID}" ]; then
    kill -TERM "${POT_PID}" 2>/dev/null || true
  fi
  exit "$status"
}
trap cleanup INT TERM HUP

echo "Starting bgutil POT server on 127.0.0.1:4416..."
node /app/bgutil/server/build/main.js --host 127.0.0.1 --port 4416 >"${POT_LOG}" 2>&1 &
POT_PID=$!

echo "POT PID=${POT_PID}"
ready=0
for i in $(seq 1 20); do
  if ! kill -0 "${POT_PID}" 2>/dev/null; then
    echo "POT server exited during startup"
    cat "${POT_LOG}" || true
    exit 1
  fi
  if curl -fsS --max-time 2 http://127.0.0.1:4416/ping >/dev/null 2>&1; then
    ready=1
    echo "POT server ready"
    break
  fi
  echo "Waiting for POT server... (${i}/20)"
  sleep 1
done

if [ "$ready" -ne 1 ]; then
  echo "POT server failed health check"
  cat "${POT_LOG}" || true
  exit 1
fi

echo "Starting Gunicorn on 0.0.0.0:${PORT:-10000}..."
gunicorn app:app \
  --bind "0.0.0.0:${PORT:-10000}" \
  --workers 1 \
  --threads 2 \
  --worker-class gthread \
  --timeout 120 \
  --graceful-timeout 30 \
  --keep-alive 5 \
  --max-requests 100 \
  --max-requests-jitter 20 \
  --access-logfile - \
  --error-logfile - \
  --log-level info &
GUNICORN_PID=$!

wait "${GUNICORN_PID}"
status=$?
cleanup
exit "$status"
