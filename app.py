import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from flask import Flask, g, jsonify, request

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
log = logging.getLogger("youtube-info")

VERSION = "25.0.0-stable-render"
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "/tmp/youtube_data"))
DOWNLOAD_DIR = OUTPUT_DIR / "downloads"
POT_URL = os.getenv("POT_URL", "http://127.0.0.1:4416").rstrip("/")

# Secrets/config are runtime-only. Nothing sensitive should be hard-coded.
API_KEYS = {
    x.strip() for x in os.getenv("API_KEYS", "").split(",") if x.strip()
}
PROXY_URL = os.getenv("YTDLP_PROXY", "").strip()
COOKIE_FILE_ENV = os.getenv("YT_COOKIE_FILE", "").strip()
COOKIE_SECRET_PATH = "/etc/secrets/yt_cookies.txt"
USER_AGENT = os.getenv("YTDLP_USER_AGENT", "").strip()

USE_PROXY = bool(PROXY_URL)
USE_COOKIES = True
MAX_VIDEO_SECONDS = int(os.getenv("MAX_VIDEO_SECONDS", "7200"))
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "3"))
DOWNLOAD_CONCURRENCY = max(1, int(os.getenv("DOWNLOAD_CONCURRENCY", "1")))

DOWNLOAD_SLOTS = threading.BoundedSemaphore(DOWNLOAD_CONCURRENCY)
UPLOAD_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="upload_")
YT_DLP_CACHE = None
YT_DLP_LOCK = threading.Lock()
START_TIME = datetime.now(timezone.utc).isoformat()
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))
INFO_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
CACHE_LOCK = threading.Lock()
RATE_LOCK = threading.Lock()
RATE_BUCKETS: Dict[str, list] = {}

try:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    log.exception("Unable to create output directory")


# -----------------------------------------------------------------------------
# Generic helpers
# -----------------------------------------------------------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return default
    return str(value)


def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        try:
            return int(float(value))
        except Exception:
            return default


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


def fmt_size(size: Any) -> str:
    n = safe_int(size)
    if n <= 0:
        return "N/A"
    if n >= 1024**3:
        return f"{n / 1024**3:.2f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def fmt_num(value: Any) -> str:
    n = safe_int(value)
    if n <= 0:
        return "N/A"
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.2f}K"
    return str(n)


def fmt_dur(seconds: Any) -> str:
    s = max(0, safe_int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def fmt_date(value: Any) -> str:
    text = safe_str(value).strip()
    if not text:
        return "N/A"
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%d %B %Y")
        except ValueError:
            pass
    return text


def sha16(*parts: Any) -> str:
    raw = "|".join(safe_str(x) for x in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def remove_file(path: Optional[Path]) -> None:
    if not path:
        return
    try:
        if path.exists():
            path.unlink()
    except Exception:
        log.warning("Could not remove %s", path, exc_info=True)


# -----------------------------------------------------------------------------
# Secrets / runtime checks
# -----------------------------------------------------------------------------
def cookie_file() -> Optional[str]:
    candidates = []
    if COOKIE_FILE_ENV:
        candidates.append(COOKIE_FILE_ENV)
    candidates.append(COOKIE_SECRET_PATH)

    for item in candidates:
        p = Path(item)
        if p.is_file() and p.stat().st_size > 0:
            return str(p)
    return None


def pot_server_ok() -> bool:
    try:
        r = requests.get(f"{POT_URL}/ping", timeout=1.5)
        return r.status_code == 200
    except requests.RequestException:
        return False


def ffmpeg_ok() -> bool:
    return command_exists("ffmpeg") and command_exists("ffprobe")


def get_yt_dlp():
    global YT_DLP_CACHE
    if YT_DLP_CACHE is None:
        with YT_DLP_LOCK:
            if YT_DLP_CACHE is None:
                try:
                    import yt_dlp
                    YT_DLP_CACHE = yt_dlp
                    log.info("yt-dlp loaded: %s", getattr(yt_dlp, "version", "unknown"))
                except Exception:
                    log.exception("Failed to import yt-dlp")
                    return None
    return YT_DLP_CACHE


# -----------------------------------------------------------------------------
# Auth + rate limiting
# -----------------------------------------------------------------------------
def require_api_key(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not API_KEYS:
            return jsonify({
                "status": "error",
                "error_code": "API_NOT_CONFIGURED",
                "message": "API_KEYS is not configured on the server",
            }), 503

        key = request.args.get("key", "").strip()
        if not key:
            return jsonify({
                "status": "error",
                "error_code": "MISSING_API_KEY",
                "message": "API key required",
            }), 401
        if key not in API_KEYS:
            return jsonify({
                "status": "error",
                "error_code": "INVALID_API_KEY",
                "message": "Invalid API key",
            }), 403
        return func(*args, **kwargs)

    return wrapper


def rate_limited() -> bool:
    if RATE_LIMIT_PER_MIN <= 0:
        return False

    ip = request.headers.get("CF-Connecting-IP") or request.remote_addr or "unknown"
    cutoff = time.time() - 60
    with RATE_LOCK:
        bucket = [t for t in RATE_BUCKETS.get(ip, []) if t >= cutoff]
        if len(bucket) >= RATE_LIMIT_PER_MIN:
            RATE_BUCKETS[ip] = bucket
            return True
        bucket.append(time.time())
        RATE_BUCKETS[ip] = bucket
        # Keep this in-memory structure bounded.
        if len(RATE_BUCKETS) > 2000:
            for k in list(RATE_BUCKETS)[:500]:
                RATE_BUCKETS.pop(k, None)
    return False


# -----------------------------------------------------------------------------
# YouTube URL / format validation
# -----------------------------------------------------------------------------
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def validate_youtube_url(url: str) -> Tuple[bool, str]:
    text = (url or "").strip()
    if not text:
        return False, "YouTube URL required"
    if len(text) > 500:
        return False, "URL too long"

    patterns = (
        r"^https?://(?:www\.)?youtube\.com/watch\?v=([A-Za-z0-9_-]{11})(?:[&#?].*)?$",
        r"^https?://(?:www\.)?youtu\.be/([A-Za-z0-9_-]{11})(?:[?&#].*)?$",
        r"^https?://(?:www\.)?youtube\.com/shorts/([A-Za-z0-9_-]{11})(?:[?&#].*)?$",
        r"^https?://(?:www\.)?youtube\.com/embed/([A-Za-z0-9_-]{11})(?:[?&#].*)?$",
        r"^https?://m\.youtube\.com/watch\?v=([A-Za-z0-9_-]{11})(?:[&#?].*)?$",
        r"^https?://music\.youtube\.com/watch\?v=([A-Za-z0-9_-]{11})(?:[&#?].*)?$",
    )
    for pattern in patterns:
        m = re.match(pattern, text, flags=re.IGNORECASE)
        if m:
            vid = m.group(1)
            return True, vid

    if "youtube.com" in text.lower() or "youtu.be" in text.lower():
        return False, "Invalid YouTube URL format"
    return False, "Not a YouTube URL"


def validate_quality(value: str) -> str:
    q = (value or "720p").strip().lower()
    allowed = {"144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p", "best"}
    return q if q in allowed else "720p"


# -----------------------------------------------------------------------------
# yt-dlp
# -----------------------------------------------------------------------------
def build_opts(download: bool, quality: str, use_cookies: bool, no_proxy: bool) -> Dict[str, Any]:
    yt_quality = validate_quality(quality)
    if yt_quality == "best":
        format_str = "bv*+ba/b"
    else:
        height = int(yt_quality[:-1])
        format_str = f"bv*[height<={height}]+ba/b[height<={height}]/bv*+ba/b"

    headers = {"Accept-Language": "en-US,en;q=0.9"}
    if USER_AGENT:
        headers["User-Agent"] = USER_AGENT

    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "nocheckcertificate": True,
        "cachedir": False,
        "no_color": True,
        "socket_timeout": 15,
        "retries": 1,
        "fragment_retries": 1,
        "extractor_retries": 1,
        "skip_unavailable_fragments": True,
        "format": format_str,
        "http_headers": headers,
        "extractor_args": {
            "youtube": {
                "fetch_pot": ["auto"],
            }
        },
        # Node 22 is pinned by the Docker image. This is supported by current yt-dlp.
        "js_runtimes": {"node": {}},
        "no_call_home": True,
        "call_home": False,
        "writeinfojson": False,
        "writethumbnail": False,
        "write_all_thumbnails": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "writedescription": False,
        "writeannotations": False,
        "extract_flat": False,
        "ignoreerrors": False,
        "force_generic_extractor": False,
        "lazy_playlist": True,
        "check_formats": False,
        "overwrites": True,
        "restrictfilenames": True,
        "noplaylist": True,
    }

    # Only enable the local provider if it is actually alive.
    if pot_server_ok():
        opts["extractor_args"]["youtubepot-bgutilhttp"] = {"base_url": POT_URL}

    if USE_PROXY and not no_proxy:
        opts["proxy"] = PROXY_URL

    if use_cookies:
        cf = cookie_file()
        if cf:
            opts["cookiefile"] = cf

    if download:
        opts.update({
            "outtmpl": str(DOWNLOAD_DIR / "%(id)s.%(ext)s"),
            # Keep memory/CPU pressure low on small Render instances.
            "concurrent_fragment_downloads": 4,
            "buffersize": 1024 * 1024,
            "http_chunk_size": 2 * 1024 * 1024,
            "merge_output_format": "mp4",
            "prefer_ffmpeg": True,
            "skip_download": False,
            "retries": 2,
            "fragment_retries": 2,
        })
    else:
        opts["skip_download"] = True

    return opts


def verify_info(info: Optional[Dict[str, Any]], expected_id: str) -> Tuple[bool, str]:
    if not info:
        return False, "No info returned"
    returned_id = safe_str(info.get("id"))
    if returned_id != expected_id or not VIDEO_ID_RE.match(returned_id):
        return False, "Video ID mismatch or invalid ID"
    if not safe_str(info.get("title")).strip():
        return False, "Video has no title"
    availability = safe_str(info.get("availability"), "public")
    if availability in {"private", "premium_only", "subscriber_only"}:
        return False, f"Video is {availability}"
    if MAX_VIDEO_SECONDS > 0 and safe_int(info.get("duration")) > MAX_VIDEO_SECONDS:
        return False, f"Video duration exceeds the {MAX_VIDEO_SECONDS}s server limit"
    return True, "Verified"


def classify_ytdlp_error(exc: Exception) -> str:
    msg = str(exc)
    lower = msg.lower()
    if "private video" in lower or "sign in" in lower:
        return "VIDEO_AUTH_OR_PRIVATE"
    if "video unavailable" in lower or "removed" in lower:
        return "VIDEO_UNAVAILABLE"
    if "timed out" in lower or "timeout" in lower:
        return "UPSTREAM_TIMEOUT"
    if "http error 403" in lower or "forbidden" in lower:
        return "UPSTREAM_FORBIDDEN"
    return type(exc).__name__


def download_video(url: str, video_id: str, quality: str) -> Tuple[Optional[Dict[str, Any]], Optional[Path], list]:
    yt = get_yt_dlp()
    if yt is None:
        return None, None, ["yt-dlp import failed"]

    # Sequential attempts deliberately: the old implementation ran several full
    # yt-dlp extractors at once, which is risky on a 512 MB instance.
    attempts = [
        {"label": "cookies+proxy", "use_cookies": True, "no_proxy": False},
        {"label": "cookies", "use_cookies": True, "no_proxy": True},
        {"label": "proxy", "use_cookies": False, "no_proxy": False},
        {"label": "direct", "use_cookies": False, "no_proxy": True},
    ]

    errors = []
    for attempt in attempts:
        # Don't bother with cookie attempts when no cookie exists.
        if attempt["use_cookies"] and not cookie_file():
            continue
        if attempt["label"] == "proxy" and not USE_PROXY:
            continue

        started = time.monotonic()
        try:
            opts = build_opts(
                download=True,
                quality=quality,
                use_cookies=attempt["use_cookies"],
                no_proxy=attempt["no_proxy"],
            )
            with yt.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                ok, reason = verify_info(info, video_id)
                if not ok:
                    errors.append(f"[{attempt['label']}] {reason}")
                    continue
                filename = Path(ydl.prepare_filename(info))

            # yt-dlp may merge into a different extension.
            if not filename.exists():
                for ext in (".mp4", ".mkv", ".webm"):
                    candidate = filename.with_suffix(ext)
                    if candidate.exists():
                        filename = candidate
                        break

            if not filename.exists():
                errors.append(f"[{attempt['label']}] output file missing")
                continue

            log.info(
                "Download succeeded via %s in %.1fs (%s)",
                attempt["label"], time.monotonic() - started, filename,
            )
            return info, filename, errors
        except Exception as exc:
            errors.append(f"[{attempt['label']}] {classify_ytdlp_error(exc)}: {str(exc)[:180]}")
            log.warning("yt-dlp attempt failed: %s", errors[-1])

    return None, None, errors


# -----------------------------------------------------------------------------
# Output shaping
# -----------------------------------------------------------------------------
def build_full_info(info: Dict[str, Any]) -> Dict[str, Any]:
    vid = safe_str(info.get("id"))
    desc = safe_str(info.get("description"))
    duration = safe_int(info.get("duration"))

    thumbnails = []
    for t in info.get("thumbnails") or []:
        if not isinstance(t, dict):
            continue
        thumbnails.append({
            "url": safe_str(t.get("url")),
            "preference": safe_int(t.get("preference")),
            "id": safe_str(t.get("id")),
            "height": safe_int(t.get("height")),
            "width": safe_int(t.get("width")),
            "resolution": safe_str(t.get("resolution")),
        })

    formats = []
    for f in info.get("formats") or []:
        if not isinstance(f, dict):
            continue
        size = f.get("filesize") or f.get("filesize_approx") or 0
        formats.append({
            "format_id": safe_str(f.get("format_id")),
            "ext": safe_str(f.get("ext")),
            "resolution": safe_str(f.get("resolution")),
            "width": safe_int(f.get("width")),
            "height": safe_int(f.get("height")),
            "fps": safe_int(f.get("fps")),
            "vcodec": safe_str(f.get("vcodec")),
            "acodec": safe_str(f.get("acodec")),
            "filesize": safe_int(size),
            "filesize_formatted": fmt_size(size) if size else "N/A",
            "format_note": safe_str(f.get("format_note")),
            "quality": safe_str(f.get("quality")),
            "has_video": f.get("vcodec") not in (None, "none"),
            "has_audio": f.get("acodec") not in (None, "none"),
        })

    upload_date = safe_str(info.get("upload_date"))
    return {
        "video": {
            "id": vid,
            "title": safe_str(info.get("title")),
            "fulltitle": safe_str(info.get("fulltitle")),
            "url": safe_str(info.get("webpage_url")),
            "short_url": f"https://youtu.be/{vid}",
            "embed_url": f"https://www.youtube.com/embed/{vid}",
            "description": desc,
            "description_length": len(desc),
            "description_preview": desc[:1000],
            "thumbnail": safe_str(info.get("thumbnail")),
            "thumbnail_hd": f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg",
            "thumbnail_sd": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "thumbnails": thumbnails,
        },
        "duration": {
            "seconds": duration,
            "string": safe_str(info.get("duration_string")),
            "formatted": fmt_dur(duration),
            "minutes": duration // 60 if duration else 0,
            "hours": duration // 3600 if duration else 0,
        },
        "dates": {
            "upload_date": upload_date,
            "upload_date_formatted": fmt_date(upload_date) if upload_date else "N/A",
            "release_date": safe_str(info.get("release_date")),
            "modified_date": safe_str(info.get("modified_date")),
            "timestamp": safe_int(info.get("timestamp")),
        },
        "engagement": {
            "view_count": safe_int(info.get("view_count")),
            "view_count_formatted": fmt_num(info.get("view_count")),
            "like_count": safe_int(info.get("like_count")),
            "like_count_formatted": fmt_num(info.get("like_count")),
            "comment_count": safe_int(info.get("comment_count")),
            "comment_count_formatted": fmt_num(info.get("comment_count")),
            "average_rating": info.get("average_rating"),
        },
        "channel": {
            "name": safe_str(info.get("channel")),
            "id": safe_str(info.get("channel_id")),
            "url": safe_str(info.get("channel_url")),
            "uploader": safe_str(info.get("uploader")),
            "uploader_id": safe_str(info.get("uploader_id")),
            "uploader_url": safe_str(info.get("uploader_url")),
            "follower_count": safe_int(info.get("channel_follower_count")),
            "follower_count_formatted": fmt_num(info.get("channel_follower_count")),
        },
        "metadata": {
            "categories": info.get("categories") or [],
            "tags": info.get("tags") or [],
            "tags_count": len(info.get("tags") or []),
            "language": safe_str(info.get("language")),
            "age_limit": safe_int(info.get("age_limit")),
            "is_family_friendly": info.get("is_family_friendly"),
            "availability": safe_str(info.get("availability")),
        },
        "subtitles": {
            "manual": list((info.get("subtitles") or {}).keys()),
            "automatic": list((info.get("automatic_captions") or {}).keys()),
            "total_manual": len(info.get("subtitles") or {}),
            "total_auto": len(info.get("automatic_captions") or {}),
        },
        "live": {
            "is_live": safe_bool(info.get("is_live")),
            "was_live": safe_bool(info.get("was_live")),
            "live_status": safe_str(info.get("live_status")),
        },
        "technical": {
            "ext": safe_str(info.get("ext")),
            "format": safe_str(info.get("format")),
            "format_id": safe_str(info.get("format_id")),
            "format_note": safe_str(info.get("format_note")),
            "width": safe_int(info.get("width")),
            "height": safe_int(info.get("height")),
            "fps": safe_int(info.get("fps")),
            "vcodec": safe_str(info.get("vcodec")),
            "acodec": safe_str(info.get("acodec")),
            "filesize": safe_int(info.get("filesize")),
            "filesize_formatted": fmt_size(info.get("filesize")),
            "audio_channels": safe_int(info.get("audio_channels")),
            "audio_bitrate": safe_float(info.get("audio_bitrate")),
            "video_bitrate": safe_float(info.get("video_bitrate")),
        },
        "extractor": {
            "name": safe_str(info.get("extractor")),
            "key": safe_str(info.get("extractor_key")),
            "domain": safe_str(info.get("webpage_url_domain")),
        },
        "chapters": [
            {
                "start_time": safe_float(c.get("start_time")),
                "end_time": safe_float(c.get("end_time")),
                "title": safe_str(c.get("title")),
            }
            for c in (info.get("chapters") or [])
            if isinstance(c, dict)
        ],
        "heatmap": info.get("heatmap"),
        "formats": formats,
        "format_count": len(formats),
    }


# -----------------------------------------------------------------------------
# Upload helpers
# -----------------------------------------------------------------------------
def upload_tmpfiles(path: Path):
    try:
        with path.open("rb") as fp:
            r = requests.post(
                "https://tmpfiles.org/api/v1/upload",
                files={"file": fp},
                timeout=(10, 30),
            )
        if r.status_code == 200:
            data = r.json()
            url = data.get("data", {}).get("url", "")
            if url:
                return "tmpfiles.org", url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
    except Exception as exc:
        log.warning("tmpfiles upload failed: %s", str(exc)[:120])
    return None


def upload_catbox(path: Path):
    try:
        with path.open("rb") as fp:
            r = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": fp},
                timeout=(10, 30),
            )
        text = r.text.strip()
        if r.status_code == 200 and text.startswith("http"):
            return "catbox.moe", text
    except Exception as exc:
        log.warning("catbox upload failed: %s", str(exc)[:120])
    return None


def upload_litterbox(path: Path):
    try:
        with path.open("rb") as fp:
            r = requests.post(
                "https://litterbox.catbox.moe/resources/internals/api.php",
                data={"reqtype": "fileupload", "time": "1h"},
                files={"fileToUpload": fp},
                timeout=(10, 30),
            )
        text = r.text.strip()
        if r.status_code == 200 and text.startswith("http"):
            return "litterbox", text
    except Exception as exc:
        log.warning("litterbox upload failed: %s", str(exc)[:120])
    return None


def upload_parallel(path: Path) -> Dict[str, str]:
    funcs = [upload_tmpfiles, upload_catbox, upload_litterbox]
    futures = {UPLOAD_EXECUTOR.submit(fn, path): fn.__name__ for fn in funcs}
    try:
        for future in as_completed(futures, timeout=35):
            try:
                result = future.result()
                if result:
                    # Stop waiting for slower mirrors. The upload functions stream from
                    # disk and do not load the full video into memory.
                    return {"host": result[0], "url": result[1]}
            except Exception:
                log.exception("Upload worker failed")
    except TimeoutError:
        pass
    return {"host": "N/A", "url": "UPLOAD_FAILED"}


# -----------------------------------------------------------------------------
# Cache (only metadata objects, never files)
# -----------------------------------------------------------------------------
def cache_get(url: str) -> Optional[Dict[str, Any]]:
    with CACHE_LOCK:
        item = INFO_CACHE.get(url)
        if not item:
            return None
        ts, value = item
        if time.time() - ts >= CACHE_TTL:
            INFO_CACHE.pop(url, None)
            return None
        return value


def cache_set(url: str, value: Dict[str, Any]) -> None:
    with CACHE_LOCK:
        INFO_CACHE[url] = (time.time(), value)
        if len(INFO_CACHE) > 50:
            cutoff = time.time() - CACHE_TTL
            for key, (ts, _) in list(INFO_CACHE.items()):
                if ts < cutoff:
                    INFO_CACHE.pop(key, None)


# -----------------------------------------------------------------------------
# Flask diagnostics
# -----------------------------------------------------------------------------
@app.before_request
def before_request():
    g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    g.started = time.monotonic()


@app.after_request
def after_request(response):
    duration = time.monotonic() - getattr(g, "started", time.monotonic())
    response.headers["X-Request-ID"] = getattr(g, "request_id", "unknown")
    response.headers["X-Response-Time"] = f"{duration:.3f}s"
    log.info("%s %s -> %s (%.3fs) id=%s", request.method, request.path, response.status_code, duration, g.request_id)
    return response


@app.get("/")
def home():
    return jsonify({
        "service": "YouTube Downloader API",
        "version": VERSION,
        "status": "ok",
        "endpoints": {
            "/yt": "GET - download video + full info",
            "/ping": "GET - liveness",
            "/health": "GET - health",
            "/ready": "GET - app + POT readiness",
            "/debug": "GET - safe diagnostics",
        },
        "started_at": START_TIME,
    }), 200


@app.get("/ping")
def ping():
    return "pong", 200


@app.get("/health")
def health():
    # Keep this endpoint extremely cheap. Render checks it every few seconds.
    return jsonify({
        "status": "healthy",
        "version": VERSION,
        "timestamp": now_iso(),
        "uptime_seconds": round(time.monotonic(), 2),
    }), 200


@app.get("/ready")
def ready():
    pot_ok = pot_server_ok()
    healthy = bool(get_yt_dlp()) and ffmpeg_ok() and pot_ok
    return jsonify({
        "status": "ready" if healthy else "degraded",
        "yt_dlp": bool(get_yt_dlp()),
        "ffmpeg": ffmpeg_ok(),
        "pot_server": pot_ok,
        "cookies": bool(cookie_file()),
        "proxy_enabled": USE_PROXY,
        "timestamp": now_iso(),
    }), (200 if healthy else 503)


@app.get("/debug")
def debug():
    # Never expose API keys, cookie contents, or proxy credentials.
    return jsonify({
        "status": "ok",
        "version": VERSION,
        "python": os.sys.version.split()[0],
        "port": os.getenv("PORT", "10000"),
        "render": os.getenv("RENDER", "false"),
        "cpu_count": os.getenv("RENDER_CPU_COUNT", "unknown"),
        "yt_dlp_loaded": YT_DLP_CACHE is not None,
        "yt_dlp_version": getattr(YT_DLP_CACHE, "version", None) if YT_DLP_CACHE else None,
        "node": command_exists("node"),
        "ffmpeg": command_exists("ffmpeg"),
        "ffprobe": command_exists("ffprobe"),
        "pot_server": pot_server_ok(),
        "cookies_present": bool(cookie_file()),
        "proxy_enabled": USE_PROXY,
        "output_dir": str(OUTPUT_DIR),
        "free_plan_note": "Keep concurrency at 1 on the 512 MB Free plan",
        "cache_entries": len(INFO_CACHE),
    }), 200


@app.get("/yt")
@require_api_key
def download_yt():
    if rate_limited():
        return jsonify({
            "status": "error",
            "error_code": "RATE_LIMITED",
            "message": "Too many requests. Try again later.",
            "request_id": g.request_id,
        }), 429

    url_raw = request.args.get("url", "").strip()
    quality = validate_quality(request.args.get("quality", "720p"))
    if not url_raw:
        return jsonify({
            "status": "error",
            "error_code": "MISSING_URL",
            "message": "YouTube URL required",
            "request_id": g.request_id,
        }), 400

    valid, result = validate_youtube_url(url_raw)
    if not valid:
        return jsonify({
            "status": "error",
            "error_code": "INVALID_URL",
            "message": result,
            "url_received": url_raw,
            "request_id": g.request_id,
        }), 400

    video_id = result
    canonical_url = f"https://www.youtube.com/watch?v={video_id}"

    acquired = DOWNLOAD_SLOTS.acquire(blocking=False)
    if not acquired:
        return jsonify({
            "status": "error",
            "error_code": "BUSY",
            "message": "Another download is currently running. Retry shortly.",
            "request_id": g.request_id,
        }), 429

    started = time.monotonic()
    video_file: Optional[Path] = None
    try:
        info, video_file, errors = download_video(canonical_url, video_id, quality)
        if not info or not video_file:
            return jsonify({
                "status": "error",
                "error_code": "EXTRACTION_FAILED",
                "message": "All YouTube extraction attempts failed",
                "all_errors": errors[-8:],
                "debug_info": {
                    "yt_dlp": bool(get_yt_dlp()),
                    "ffmpeg": ffmpeg_ok(),
                    "pot_server": pot_server_ok(),
                    "cookies_present": bool(cookie_file()),
                    "proxy_enabled": USE_PROXY,
                },
                "total_time": f"{time.monotonic() - started:.2f}s",
                "request_id": g.request_id,
            }), 502

        full = build_full_info(info)
        fingerprint = sha16(info.get("id"), info.get("title"), info.get("duration"))
        cache_set(canonical_url, info)

        upload_started = time.monotonic()
        upload = upload_parallel(video_file)
        upload_time = time.monotonic() - upload_started
        size = video_file.stat().st_size

        return jsonify({
            "status": "success",
            "version": VERSION,
            "request_id": g.request_id,
            "total_time": f"{time.monotonic() - started:.2f}s",
            "download": {
                "status": "success",
                "filename": video_file.name,
                "file_size": size,
                "file_size_formatted": fmt_size(size),
                "quality": quality,
                "share_url": upload["url"],
                "upload_host": upload["host"],
                "upload_time": f"{upload_time:.2f}s",
                "downloaded_at": now_iso(),
            },
            "fingerprint": fingerprint,
            **full,
        }), 200

    except Exception as exc:
        log.exception("Unhandled /yt failure id=%s", g.request_id)
        return jsonify({
            "status": "error",
            "error_code": "PROCESS_ERROR",
            "message": str(exc)[:300],
            "request_id": g.request_id,
        }), 500
    finally:
        remove_file(video_file)
        DOWNLOAD_SLOTS.release()


@app.errorhandler(404)
def not_found(_error):
    return jsonify({
        "status": "error",
        "error_code": "NOT_FOUND",
        "message": "Endpoint not found",
        "request_id": getattr(g, "request_id", None),
    }), 404


@app.errorhandler(Exception)
def unhandled(exc):
    log.exception("Unhandled Flask exception")
    return jsonify({
        "status": "error",
        "error_code": "UNHANDLED_EXCEPTION",
        "message": str(exc)[:300],
        "request_id": getattr(g, "request_id", None),
    }), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
