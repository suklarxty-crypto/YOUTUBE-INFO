# YouTube INFO – Render-stable build

This version is designed to reduce intermittent Render 502s on small instances.

## Important before deploying

1. Remove `yt_cookies.txt` and any proxy/API secrets from the Git repository and Git history.
2. Rotate any credentials that were previously committed.
3. In Render, add `API_KEYS` as an environment variable.
4. Upload the YouTube cookies as a **Render Secret File** named `yt_cookies.txt`. The app reads `/etc/secrets/yt_cookies.txt`.
5. Put your proxy URL in `YTDLP_PROXY` instead of source code.
6. Make sure the Render service branch is `main` and manually deploy the latest commit after pushing these files.

## Render

The Dockerfile starts:

- bgutil POT server on `127.0.0.1:4416`
- Gunicorn on `0.0.0.0:$PORT`
- `/health` is the Render health-check endpoint

The API intentionally limits the heavy download path to one active job on a 512 MB instance.

## Endpoints

- `GET /` – service information
- `GET /ping` – `pong`
- `GET /health` – cheap health probe
- `GET /ready` – checks yt-dlp, ffmpeg, and POT
- `GET /debug` – safe diagnostics, no secrets
- `GET /yt?url=...&quality=720p&key=...` – download + metadata

## Local test

```bash
python -m unittest discover -s tests -v
python -m compileall -q app.py
```
