# app.py - YouTube Downloader API v27.0 (MULTI-SOURCE UPLOAD + TIME TRACKING)
# Made by @KINGFFAIAK47x · ANSH AFT
# FIX: /etc/secrets read-only → copy to /tmp automatically
# NEW: 6+ upload hosts, parallel fallback, per-host timing

import os
import sys
import json
import time
import threading
import re
import shutil
import hashlib
import traceback
import uuid
import signal
import concurrent.futures
from datetime import datetime
from functools import wraps
from collections import defaultdict

from flask import Flask, jsonify, request, g

# ==============================================
# CONFIG FROM ENV
# ==============================================

API_KEYS_ENV = os.environ.get("API_KEYS", "FF,AK$&FF")
API_KEYS = set(k.strip() for k in API_KEYS_ENV.split(",") if k.strip())

YTDLP_PROXY = os.environ.get("YTDLP_PROXY", "").strip()
YT_COOKIE_ENV = os.environ.get("YT_COOKIE_FILE", "").strip()
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "5"))
DOWNLOAD_CONCURRENCY = int(os.environ.get("DOWNLOAD_CONCURRENCY", "1"))
MAX_VIDEO_SECONDS = int(os.environ.get("MAX_VIDEO_SECONDS", "7200"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
UPLOAD_TIMEOUT = int(os.environ.get("UPLOAD_TIMEOUT", "120"))
UPLOAD_PARALLEL = os.environ.get("UPLOAD_PARALLEL", "true").lower() == "true"

OUTPUT_DIR = "/tmp/youtube_data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==============================================
# LOGGING
# ==============================================

_STARTUP_LOG = []
_STARTUP_TIME = datetime.now().isoformat()
_LOG_LOCK = threading.Lock()


def log_event(msg, level="INFO"):
    entry = f"[{datetime.now().isoformat()}] [{level}] {msg}"
    with _LOG_LOCK:
        _STARTUP_LOG.append(entry)
        if len(_STARTUP_LOG) > 200:
            _STARTUP_LOG.pop(0)
    print(entry, flush=True)


# ==============================================
# COOKIE RESOLVER - FIXES READ-ONLY FS ERROR
# ==============================================

def resolve_cookie_file():
    TMP_PATH = "/tmp/yt_cookies.txt"
    candidates = []

    if YT_COOKIE_ENV:
        candidates.append(YT_COOKIE_ENV)

    candidates.append("/etc/secrets/yt_cookies.txt")
    candidates.append("/app/yt_cookies.txt")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(script_dir, "yt_cookies.txt"))
    candidates.append(TMP_PATH)

    for path in candidates:
        if not path or not os.path.exists(path):
            continue

        if path == TMP_PATH:
            log_event(f"✅ Cookies found at {path} (writable)")
            return path

        try:
            shutil.copy2(path, TMP_PATH)
            os.chmod(TMP_PATH, 0o644)
            log_event(f"✅ Cookies copied: {path} → {TMP_PATH}")
            return TMP_PATH
        except Exception as e:
            log_event(f"❌ Copy failed {path}: {e}", "ERROR")
            continue

    log_event("⚠️ No cookies file found anywhere", "WARN")
    return None


COOKIE_FILE = resolve_cookie_file()

# ==============================================
# FLASK
# ==============================================

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# ==============================================
# RATE LIMIT
# ==============================================

_RATE_STORE = defaultdict(list)
_RATE_LOCK = threading.Lock()


def check_rate_limit(client_ip):
    now = time.time()
    window = 60
    with _RATE_LOCK:
        hits = [t for t in _RATE_STORE[client_ip] if now - t < window]
        if len(hits) >= RATE_LIMIT_PER_MIN:
            retry_after = int(window - (now - hits[0])) + 1
            return False, retry_after
        hits.append(now)
        _RATE_STORE[client_ip] = hits
        if len(_RATE_STORE) > 1000:
            for ip in list(_RATE_STORE.keys()):
                _RATE_STORE[ip] = [t for t in _RATE_STORE[ip] if now - t < window]
                if not _RATE_STORE[ip]:
                    del _RATE_STORE[ip]
    return True, 0


# ==============================================
# CONCURRENCY
# ==============================================

_DL_SEMAPHORE = threading.Semaphore(DOWNLOAD_CONCURRENCY)
_SHUTTING_DOWN = threading.Event()


def _handle_sigterm(signum, frame):
    log_event(f"Signal {signum} received, shutting down", "WARN")
    _SHUTTING_DOWN.set()


try:
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)
except Exception:
    pass

# ==============================================
# LAZY LOADERS
# ==============================================

_yt_dlp_cache = None
_requests_cache = None
_import_lock = threading.Lock()
_POT_CACHE = {"checked": 0, "available": False}
_POT_LOCK = threading.Lock()


def get_yt_dlp():
    global _yt_dlp_cache
    if _yt_dlp_cache is None:
        with _import_lock:
            if _yt_dlp_cache is None:
                import yt_dlp
                _yt_dlp_cache = yt_dlp
    return _yt_dlp_cache


def get_requests():
    global _requests_cache
    if _requests_cache is None:
        with _import_lock:
            if _requests_cache is None:
                import requests
                _requests_cache = requests
    return _requests_cache


def check_pot_server():
    with _POT_LOCK:
        now = time.time()
        if now - _POT_CACHE["checked"] < 30:
            return _POT_CACHE["available"]
        try:
            r = get_requests().get("http://127.0.0.1:4416/ping", timeout=2)
            _POT_CACHE["available"] = (r.status_code == 200)
        except Exception:
            _POT_CACHE["available"] = False
        _POT_CACHE["checked"] = now
        return _POT_CACHE["available"]


def check_deno():
    return shutil.which("deno") is not None


def check_node():
    return shutil.which("node") is not None


def check_ffmpeg():
    return shutil.which("ffmpeg") is not None


# ==============================================
# HELPERS
# ==============================================

def safe_str(o, d=""):
    if o is None:
        return d
    if isinstance(o, (list, dict)):
        try:
            return json.dumps(o, ensure_ascii=False)
        except Exception:
            return d
    return str(o)


def safe_int(o, d=0):
    if o is None:
        return d
    try:
        return int(o)
    except Exception:
        try:
            return int(float(o))
        except Exception:
            return d


def safe_float(o, d=0.0):
    if o is None:
        return d
    try:
        return float(o)
    except Exception:
        return d


def safe_bool(o, d=False):
    if o is None:
        return d
    return bool(o)


def fmt_size(s):
    if not s:
        return "N/A"
    try:
        s = int(s)
        if s > 1024**3:
            return f"{s/(1024**3):.2f} GB"
        elif s > 1024**2:
            return f"{s/(1024**2):.1f} MB"
        elif s > 1024:
            return f"{s/1024:.1f} KB"
        return f"{s} B"
    except Exception:
        return "N/A"


def fmt_dur(sec):
    if not sec:
        return "0:00"
    try:
        s = int(sec)
        h, m, se = s // 3600, (s % 3600) // 60, s % 60
        return f"{h}:{m:02d}:{se:02d}" if h else f"{m}:{se:02d}"
    except Exception:
        return "0:00"


def fmt_num(n):
    if not n:
        return "N/A"
    try:
        n = int(n)
        if n >= 1e9:
            return f"{n/1e9:.2f}B"
        elif n >= 1e6:
            return f"{n/1e6:.2f}M"
        elif n >= 1e3:
            return f"{n/1e3:.2f}K"
        return str(n)
    except Exception:
        return "N/A"


def fmt_date(ds):
    if not ds:
        return "N/A"
    s = str(ds).strip()
    for f in ["%Y%m%d", "%Y-%m-%d"]:
        try:
            return datetime.strptime(s, f).strftime("%d %B %Y")
        except Exception:
            continue
    return s


def cleanup_old_files(max_age=1800):
    try:
        now = time.time()
        for root, _, files in os.walk(OUTPUT_DIR):
            for fname in files:
                fp = os.path.join(root, fname)
                try:
                    if now - os.path.getmtime(fp) > max_age:
                        os.remove(fp)
                except Exception:
                    pass
    except Exception:
        pass


# ==============================================
# AUTH
# ==============================================

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        g.request_id = str(uuid.uuid4())[:8]

        if _SHUTTING_DOWN.is_set():
            return jsonify({
                "status": "error",
                "error_code": "SHUTTING_DOWN",
                "message": "Server shutting down",
                "request_id": g.request_id
            }), 503

        key = request.args.get("key", "").strip()
        if not key:
            return jsonify({
                "status": "error",
                "error_code": "MISSING_API_KEY",
                "message": "API key required",
                "request_id": g.request_id
            }), 401

        if key not in API_KEYS:
            return jsonify({
                "status": "error",
                "error_code": "INVALID_API_KEY",
                "message": "Invalid API key",
                "request_id": g.request_id
            }), 403

        client_ip = (request.headers.get("X-Forwarded-For", "")
                     or request.remote_addr or "unknown").split(",")[0].strip()
        allowed, retry = check_rate_limit(client_ip)
        if not allowed:
            return jsonify({
                "status": "error",
                "error_code": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit. Retry after {retry}s",
                "retry_after": retry,
                "request_id": g.request_id
            }), 429

        return f(*args, **kwargs)
    return decorated


# ==============================================
# URL VALIDATION
# ==============================================

def validate_youtube_url(url):
    if not url:
        return False, "URL required"
    url = str(url).strip()
    if len(url) < 10 or len(url) > 500:
        return False, "URL length invalid"
    patterns = [
        r'^https?://(www\.)?youtube\.com/watch\?v=([\w\-]{11})',
        r'^https?://(www\.)?youtu\.be/([\w\-]{11})',
        r'^https?://(www\.)?youtube\.com/shorts/([\w\-]{11})',
        r'^https?://(www\.)?youtube\.com/embed/([\w\-]{11})',
        r'^https?://m\.youtube\.com/watch\?v=([\w\-]{11})',
        r'^https?://music\.youtube\.com/watch\?v=([\w\-]{11})',
    ]
    for p in patterns:
        m = re.match(p, url)
        if m:
            return True, m.groups()[-1]
    if 'youtube.com' in url or 'youtu.be' in url:
        return False, "Invalid YouTube URL format"
    return False, "Not a YouTube URL"


def validate_quality(q):
    if not q:
        return "720p"
    q = str(q).strip().lower()
    valid = ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p", "best"]
    return q if q in valid else "720p"


# ==============================================
# YT-DLP OPTS
# ==============================================

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def build_opts(download=False, quality="720p", use_cookies=True, use_proxy=True):
    if quality == "best":
        fmt = "bv*+ba/b"
    else:
        try:
            h = int(str(quality).rstrip("p"))
            fmt = f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
        except Exception:
            fmt = "bv*+ba/b"

    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "cachedir": False,
        "no_color": True,
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
        "extractor_retries": 2,
        "skip_unavailable_fragments": True,
        "noprogress": True,
        "consoletitle": False,
        "format": fmt,
        "http_headers": {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "tv_embedded", "web"],
                "fetch_pot": ["auto"] if check_pot_server() else ["never"],
            },
        },
        "no_call_home": True,
        "call_home": False,
        "writeinfojson": False,
        "writethumbnail": False,
        "write_all_thumbnails": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "writedescription": False,
        "writeannotations": False,
        "skip_download": not download,
        "extract_flat": False,
        "ignoreerrors": False,
        "force_generic_extractor": False,
        "lazy_playlist": True,
        "check_formats": False,
        "concurrent_fragment_downloads": 4,
    }

    if check_deno():
        opts["js_runtimes"] = {"deno": {}}
    elif check_node():
        opts["js_runtimes"] = {"node": {}}

    if check_pot_server():
        opts["extractor_args"]["youtubepot-bgutilhttp"] = {
            "base_url": "http://127.0.0.1:4416"
        }

    if use_proxy and YTDLP_PROXY:
        opts["proxy"] = YTDLP_PROXY

    if use_cookies and COOKIE_FILE and os.path.exists(COOKIE_FILE):
        opts["cookiefile"] = COOKIE_FILE

    if download:
        out_dir = os.path.join(OUTPUT_DIR, "downloads")
        os.makedirs(out_dir, exist_ok=True)
        opts["outtmpl"] = os.path.join(out_dir, "%(title).100B [%(id)s].%(ext)s")
        opts["merge_output_format"] = "mp4"
        opts["buffersize"] = 1024 * 1024 * 2
        opts["http_chunk_size"] = 1024 * 1024 * 2
        opts["skip_download"] = False

    return opts


# ==============================================
# EXTRACT INFO
# ==============================================

def extract_info(url):
    yt = get_yt_dlp()
    if not yt:
        return {"_error": "yt-dlp not available", "_verified": False}

    attempts = [
        {"label": "cookies+proxy", "cookies": True, "proxy": True},
        {"label": "cookies_only", "cookies": True, "proxy": False},
        {"label": "proxy_only", "cookies": False, "proxy": True},
        {"label": "direct", "cookies": False, "proxy": False},
    ]

    errors = []

    for a in attempts:
        if _SHUTTING_DOWN.is_set():
            errors.append("shutting_down")
            break
        try:
            opts = build_opts(
                download=False,
                use_cookies=a["cookies"],
                use_proxy=a["proxy"],
            )
            with yt.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and not info.get("_error"):
                    if info.get("id") and info.get("title"):
                        info["_verified"] = True
                        return info
                errors.append(f"[{a['label']}] Invalid response")
        except Exception as e:
            err_msg = str(e)[:180]
            if "Sign in to confirm" in err_msg or "bot" in err_msg.lower():
                errors.append(f"[{a['label']}] BOT_CHECK: {err_msg}")
            elif "Private video" in err_msg:
                errors.append(f"[{a['label']}] PRIVATE: {err_msg}")
            elif "unavailable" in err_msg.lower():
                errors.append(f"[{a['label']}] UNAVAILABLE: {err_msg}")
            elif "Read-only file system" in err_msg:
                errors.append(f"[{a['label']}] FS_READONLY: {err_msg}")
            else:
                errors.append(f"[{a['label']}] {err_msg}")
            continue

    return {
        "_error": "All extraction attempts failed",
        "_all_errors": errors,
        "_verified": False,
    }


# ==============================================
# BUILD FULL INFO
# ==============================================

def build_full_info(info):
    if not info or info.get("_error"):
        return None

    vid = safe_str(info.get("id"))
    dur = safe_int(info.get("duration"))
    desc = safe_str(info.get("description"))

    thumbnails = []
    for t in (info.get("thumbnails") or []):
        if not t:
            continue
        entry = {
            "url": safe_str(t.get("url")),
            "preference": safe_int(t.get("preference")),
            "id": safe_str(t.get("id")),
        }
        if t.get("height") is not None:
            entry["height"] = safe_int(t.get("height"))
        if t.get("width") is not None:
            entry["width"] = safe_int(t.get("width"))
        if t.get("resolution"):
            entry["resolution"] = safe_str(t.get("resolution"))
        thumbnails.append(entry)

    video = {
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
    }

    duration = {
        "seconds": dur,
        "string": safe_str(info.get("duration_string")),
        "formatted": fmt_dur(dur),
        "minutes": dur // 60 if dur else 0,
        "hours": dur // 3600 if dur else 0,
    }

    ud = safe_str(info.get("upload_date"))
    dates = {
        "upload_date": ud,
        "upload_date_formatted": fmt_date(ud) if ud else "N/A",
        "release_date": safe_str(info.get("release_date")),
        "modified_date": safe_str(info.get("modified_date")),
        "timestamp": safe_int(info.get("timestamp")),
    }

    vc = safe_int(info.get("view_count"))
    lc = safe_int(info.get("like_count"))
    cc = safe_int(info.get("comment_count"))
    engagement = {
        "view_count": vc,
        "view_count_formatted": fmt_num(vc) if vc else "N/A",
        "like_count": lc,
        "like_count_formatted": fmt_num(lc) if lc else "N/A",
        "comment_count": cc,
        "comment_count_formatted": fmt_num(cc) if cc else "N/A",
        "average_rating": info.get("average_rating"),
    }

    channel = {
        "name": safe_str(info.get("channel")),
        "id": safe_str(info.get("channel_id")),
        "url": safe_str(info.get("channel_url")),
        "uploader": safe_str(info.get("uploader")),
        "uploader_id": safe_str(info.get("uploader_id")),
        "uploader_url": safe_str(info.get("uploader_url")),
        "follower_count": safe_int(info.get("channel_follower_count")),
        "follower_count_formatted": fmt_num(info.get("channel_follower_count")) if info.get("channel_follower_count") else "N/A",
    }

    metadata = {
        "categories": info.get("categories") or [],
        "tags": info.get("tags") or [],
        "tags_count": len(info.get("tags") or []),
        "language": safe_str(info.get("language")),
        "age_limit": safe_int(info.get("age_limit")),
        "is_family_friendly": info.get("is_family_friendly"),
        "availability": safe_str(info.get("availability")),
    }

    sub_manual = list((info.get("subtitles") or {}).keys())
    sub_auto = list((info.get("automatic_captions") or {}).keys())
    subtitles = {
        "manual": sub_manual,
        "automatic": sub_auto,
        "total_manual": len(sub_manual),
        "total_auto": len(sub_auto),
    }

    live = {
        "is_live": safe_bool(info.get("is_live")),
        "was_live": safe_bool(info.get("was_live")),
        "live_status": safe_str(info.get("live_status")),
    }

    technical = {
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
        "filesize_formatted": fmt_size(info.get("filesize")) if info.get("filesize") else "N/A",
        "audio_channels": safe_int(info.get("audio_channels")),
        "audio_bitrate": safe_float(info.get("audio_bitrate")),
        "video_bitrate": safe_float(info.get("video_bitrate")),
    }

    extractor = {
        "name": safe_str(info.get("extractor")),
        "key": safe_str(info.get("extractor_key")),
        "domain": safe_str(info.get("webpage_url_domain")),
    }

    chapters = []
    for c in (info.get("chapters") or []):
        if not c:
            continue
        chapters.append({
            "start_time": safe_float(c.get("start_time")),
            "end_time": safe_float(c.get("end_time")),
            "title": safe_str(c.get("title")),
        })

    formats = []
    for f in (info.get("formats") or []):
        if not f:
            continue
        fs = f.get("filesize") or f.get("filesize_approx") or 0
        formats.append({
            "format_id": safe_str(f.get("format_id")),
            "ext": safe_str(f.get("ext")),
            "resolution": safe_str(f.get("resolution")),
            "width": safe_int(f.get("width")),
            "height": safe_int(f.get("height")),
            "fps": safe_int(f.get("fps")),
            "vcodec": safe_str(f.get("vcodec")),
            "acodec": safe_str(f.get("acodec")),
            "filesize": safe_int(fs),
            "filesize_formatted": fmt_size(fs) if fs else "N/A",
            "format_note": safe_str(f.get("format_note")),
            "quality": safe_str(f.get("quality")),
            "has_video": f.get("vcodec") != "none" if f.get("vcodec") else False,
            "has_audio": f.get("acodec") != "none" if f.get("acodec") else False,
        })

    return {
        "video": video,
        "duration": duration,
        "dates": dates,
        "engagement": engagement,
        "channel": channel,
        "metadata": metadata,
        "subtitles": subtitles,
        "live": live,
        "technical": technical,
        "extractor": extractor,
        "chapters": chapters,
        "chapters_count": len(chapters),
        "heatmap": info.get("heatmap"),
        "formats": formats,
        "format_count": len(formats),
    }


# ==============================================
# 🚀 MULTI-SOURCE UPLOAD SYSTEM
# ==============================================

def up_tmpfiles(fp):
    """tmpfiles.org - 1GB limit, 1 hour retention"""
    r_ = get_requests()
    t0 = time.time()
    try:
        with open(fp, "rb") as f:
            r = r_.post("https://tmpfiles.org/api/v1/upload",
                        files={"file": f}, timeout=UPLOAD_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success":
                url = data.get("data", {}).get("url", "")
                if url:
                    return {
                        "host": "tmpfiles.org",
                        "url": url.replace("tmpfiles.org/", "tmpfiles.org/dl/"),
                        "time": round(time.time() - t0, 2),
                        "status": "success"
                    }
    except Exception as e:
        return {"host": "tmpfiles.org", "status": "failed", "error": str(e)[:150], "time": round(time.time() - t0, 2)}
    return {"host": "tmpfiles.org", "status": "failed", "error": "Invalid response", "time": round(time.time() - t0, 2)}


def up_catbox(fp):
    """catbox.moe - 200MB limit, permanent"""
    r_ = get_requests()
    t0 = time.time()
    try:
        with open(fp, "rb") as f:
            r = r_.post("https://catbox.moe/user/api.php",
                        data={"reqtype": "fileupload"},
                        files={"fileToUpload": f}, timeout=UPLOAD_TIMEOUT)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            return {
                "host": "catbox.moe",
                "url": r.text.strip(),
                "time": round(time.time() - t0, 2),
                "status": "success"
            }
    except Exception as e:
        return {"host": "catbox.moe", "status": "failed", "error": str(e)[:150], "time": round(time.time() - t0, 2)}
    return {"host": "catbox.moe", "status": "failed", "error": "Invalid response", "time": round(time.time() - t0, 2)}


def up_0x0(fp):
    """0x0.st - 512MB limit, 30 days retention"""
    r_ = get_requests()
    t0 = time.time()
    try:
        with open(fp, "rb") as f:
            r = r_.post("https://0x0.st",
                        files={"file": f},
                        headers={"User-Agent": USER_AGENT},
                        timeout=UPLOAD_TIMEOUT)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            return {
                "host": "0x0.st",
                "url": r.text.strip(),
                "time": round(time.time() - t0, 2),
                "status": "success"
            }
    except Exception as e:
        return {"host": "0x0.st", "status": "failed", "error": str(e)[:150], "time": round(time.time() - t0, 2)}
    return {"host": "0x0.st", "status": "failed", "error": "Invalid response", "time": round(time.time() - t0, 2)}


def up_litterbox(fp):
    """litterbox.catbox.moe - temporary (1h/12h/24h/72h)"""
    r_ = get_requests()
    t0 = time.time()
    try:
        with open(fp, "rb") as f:
            r = r_.post("https://litterbox.catbox.moe/resources/internals/api.php",
                        data={"reqtype": "fileupload", "time": "24h"},
                        files={"fileToUpload": f}, timeout=UPLOAD_TIMEOUT)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            return {
                "host": "litterbox.catbox.moe",
                "url": r.text.strip(),
                "time": round(time.time() - t0, 2),
                "status": "success"
            }
    except Exception as e:
        return {"host": "litterbox.catbox.moe", "status": "failed", "error": str(e)[:150], "time": round(time.time() - t0, 2)}
    return {"host": "litterbox.catbox.moe", "status": "failed", "error": "Invalid response", "time": round(time.time() - t0, 2)}


def up_uguu(fp):
    """uguu.se - 128MB limit, 3 hours retention"""
    r_ = get_requests()
    t0 = time.time()
    try:
        with open(fp, "rb") as f:
            r = r_.post("https://uguu.se/upload.php",
                        files={"files[]": f}, timeout=UPLOAD_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if data.get("success") and data.get("files"):
                url = data["files"][0].get("url", "")
                if url:
                    return {
                        "host": "uguu.se",
                        "url": url,
                        "time": round(time.time() - t0, 2),
                        "status": "success"
                    }
    except Exception as e:
        return {"host": "uguu.se", "status": "failed", "error": str(e)[:150], "time": round(time.time() - t0, 2)}
    return {"host": "uguu.se", "status": "failed", "error": "Invalid response", "time": round(time.time() - t0, 2)}


def up_fileio(fp):
    """file.io - 2GB limit, one-time download"""
    r_ = get_requests()
    t0 = time.time()
    try:
        with open(fp, "rb") as f:
            r = r_.post("https://file.io",
                        files={"file": f}, timeout=UPLOAD_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if data.get("success") and data.get("link"):
                return {
                    "host": "file.io",
                    "url": data["link"],
                    "time": round(time.time() - t0, 2),
                    "status": "success"
                }
    except Exception as e:
        return {"host": "file.io", "status": "failed", "error": str(e)[:150], "time": round(time.time() - t0, 2)}
    return {"host": "file.io", "status": "failed", "error": "Invalid response", "time": round(time.time() - t0, 2)}


# List of all upload functions
UPLOAD_HOSTS = [
    up_tmpfiles,
    up_catbox,
    up_0x0,
    up_litterbox,
    up_uguu,
    up_fileio,
]


def upload_sequential(fp, existing_results=None):
    """
    Try upload hosts sequentially.
    Returns: (best_result, all_attempts)
    """
    all_attempts = existing_results or []
    best = None

    for fn in UPLOAD_HOSTS:
        if _SHUTTING_DOWN.is_set():
            break
        try:
            res = fn(fp)
            all_attempts.append(res)
            log_event(f"📤 Upload {res.get('host')}: {res.get('status')} ({res.get('time', 0)}s)")
            if res.get("status") == "success" and not best:
                best = res
                # Don't break — we want to try all for better host
        except Exception as e:
            all_attempts.append({
                "host": fn.__name__,
                "status": "failed",
                "error": str(e)[:150],
                "time": 0
            })
            continue

    return best, all_attempts


def upload_parallel(fp, max_workers=4):
    """
    Try multiple upload hosts in parallel.
    Returns: (best_result, all_attempts)
    """
    all_attempts = []
    best = None

    def _try_upload(fn):
        try:
            res = fn(fp)
            return res
        except Exception as e:
            return {
                "host": fn.__name__,
                "status": "failed",
                "error": str(e)[:150],
                "time": 0
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_try_upload, fn): fn for fn in UPLOAD_HOSTS}
        for future in concurrent.futures.as_completed(futures):
            try:
                res = future.result(timeout=UPLOAD_TIMEOUT + 10)
                all_attempts.append(res)
                log_event(f"📤 [PARALLEL] {res.get('host')}: {res.get('status')} ({res.get('time', 0)}s)")
                if res.get("status") == "success" and not best:
                    best = res
            except Exception as e:
                all_attempts.append({
                    "host": futures[future].__name__,
                    "status": "failed",
                    "error": str(e)[:150],
                    "time": 0
                })

    return best, all_attempts


def upload_multi(fp):
    """
    Main upload function — tries parallel first, then sequential fallback.
    Returns: dict with url, host, time, all_attempts
    """
    t_start = time.time()
    all_attempts = []

    # Check file size
    try:
        size = os.path.getsize(fp)
        log_event(f"📁 File size: {fmt_size(size)}")
    except Exception:
        size = 0

    # Try parallel first if enabled
    if UPLOAD_PARALLEL:
        best, attempts = upload_parallel(fp)
        all_attempts.extend(attempts)
    else:
        best = None

    # If parallel failed, try sequential
    if not best:
        log_event("🔄 Parallel upload failed, trying sequential...")
        best, seq_attempts = upload_sequential(fp, all_attempts)
        all_attempts = seq_attempts

    total_time = round(time.time() - t_start, 2)

    if best:
        return {
            "url": best.get("url"),
            "host": best.get("host"),
            "upload_time": best.get("time", total_time),
            "total_upload_time": total_time,
            "all_attempts": all_attempts,
            "status": "success"
        }
    else:
        return {
            "url": None,
            "host": None,
            "upload_time": total_time,
            "total_upload_time": total_time,
            "all_attempts": all_attempts,
            "status": "failed"
        }


# ==============================================
# PROCESS VIDEO
# ==============================================

def process_video(url, quality="720p", video_id=None):
    t_start = time.time()

    yt = get_yt_dlp()
    if not yt:
        return {
            "status": "error",
            "error_code": "YTDLP_NOT_AVAILABLE",
            "message": "yt-dlp not loaded",
        }

    acquired = _DL_SEMAPHORE.acquire(timeout=30)
    if not acquired:
        return {
            "status": "error",
            "error_code": "SERVER_BUSY",
            "message": "Another download in progress",
            "total_time": f"{round(time.time() - t_start, 2)}s",
        }

    try:
        # EXTRACT
        info = extract_info(url)

        if not info or info.get("_error") or not info.get("_verified"):
            total_time = round(time.time() - t_start, 2)

            raw_errors = info.get("_all_errors", []) if info else []
            user_message = "Video extraction failed"
            error_code = "EXTRACTION_FAILED"

            joined = " | ".join(raw_errors)
            if "BOT_CHECK" in joined or "Sign in to confirm" in joined:
                error_code = "VIDEO_AUTH_OR_PRIVATE"
                user_message = ("YouTube bot detection: cookies expired/invalid. "
                                "Export fresh cookies from browser and update secret file.")
            elif "PRIVATE" in joined:
                error_code = "PRIVATE_VIDEO"
                user_message = "Video is private"
            elif "UNAVAILABLE" in joined:
                error_code = "VIDEO_UNAVAILABLE"
                user_message = "Video unavailable"
            elif "FS_READONLY" in joined:
                error_code = "FS_READONLY"
                user_message = "Cookie file path is read-only"

            return {
                "status": "error",
                "error_code": error_code,
                "message": user_message,
                "all_errors": raw_errors,
                "video_id": video_id,
                "source_url": url,
                "total_time": f"{total_time}s",
                "debug_info": {
                    "yt_dlp": True,
                    "ffmpeg": check_ffmpeg(),
                    "pot_server": check_pot_server(),
                    "deno": check_deno(),
                    "node": check_node(),
                    "cookies_present": bool(COOKIE_FILE and os.path.exists(COOKIE_FILE)),
                    "cookies_path": COOKIE_FILE,
                    "proxy_enabled": bool(YTDLP_PROXY),
                },
                "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
            }

        # DOWNLOAD
        dl_result = {"status": "pending"}
        fname = None

        try:
            t_dl = time.time()
            opts = build_opts(download=True, quality=quality, use_cookies=True)
            with yt.YoutubeDL(opts) as ydl:
                dl_info = ydl.extract_info(url, download=True)
                fname = ydl.prepare_filename(dl_info)
                if not os.path.exists(fname):
                    base = os.path.splitext(fname)[0]
                    for ext in [".mp4", ".mkv", ".webm"]:
                        if os.path.exists(base + ext):
                            fname = base + ext
                            break
            t_dl_end = time.time()

            if fname and os.path.exists(fname):
                size = os.path.getsize(fname)
                t_up = time.time()
                up_res = upload_multi(fname)  # 🚀 Multi-source upload
                t_up_end = time.time()

                dl_result = {
                    "status": up_res.get("status", "failed"),
                    "filename": os.path.basename(fname),
                    "file_size": size,
                    "file_size_formatted": fmt_size(size),
                    "quality": quality,
                    "download_time": f"{round(t_dl_end - t_dl, 2)}s",
                    "upload_time": f"{round(t_up_end - t_up, 2)}s",
                    "upload_time_best_host": f"{up_res.get('upload_time', 0)}s",
                    "downloaded_at": datetime.now().isoformat(),
                    "share_url": up_res.get("url") or "UPLOAD_FAILED",
                    "upload_host": up_res.get("host") or "N/A",
                    "upload_attempts": up_res.get("all_attempts", []),
                    "total_upload_time": f"{up_res.get('total_upload_time', 0)}s",
                }
            else:
                dl_result = {
                    "status": "failed",
                    "error": "File not found after download",
                    "error_code": "FILE_NOT_FOUND",
                    "quality": quality,
                }
        except Exception as ex:
            dl_result = {
                "status": "failed",
                "error": str(ex)[:200],
                "error_code": type(ex).__name__,
                "quality": quality,
            }
        finally:
            try:
                if fname and os.path.exists(fname):
                    os.remove(fname)
            except Exception:
                pass
            cleanup_old_files()

        full = build_full_info(info)
        total_time = round(time.time() - t_start, 2)

        if not full:
            return {
                "status": "error",
                "error_code": "BUILD_FAILED",
                "message": "Failed to build info",
                "download": dl_result,
                "total_time": f"{total_time}s",
            }

        return {
            "status": "success" if dl_result.get("status") == "success" else "partial",
            "total_time": f"{total_time}s",
            "download": dl_result,
            "video": full.get("video", {}),
            "duration": full.get("duration", {}),
            "dates": full.get("dates", {}),
            "engagement": full.get("engagement", {}),
            "channel": full.get("channel", {}),
            "metadata": full.get("metadata", {}),
            "subtitles": full.get("subtitles", {}),
            "live": full.get("live", {}),
            "technical": full.get("technical", {}),
            "extractor": full.get("extractor", {}),
            "chapters": full.get("chapters", []),
            "chapters_count": full.get("chapters_count", 0),
            "heatmap": full.get("heatmap"),
            "formats": full.get("formats", []),
            "format_count": full.get("format_count", 0),
            "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
        }
    finally:
        _DL_SEMAPHORE.release()

# ==============================================
# 🚀 ROUTES
# ==============================================

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "service": "🎬 YouTube Downloader API",
        "version": "27.0.0",
        "upload_hosts": [fn.__name__ for fn in UPLOAD_HOSTS],
        "qualities": ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p", "best"],
        "endpoints": {
            "/yt": {
                "method": "GET",
                "description": "Download YouTube video + full info + multi-source upload",
                "example": "/yt?url=https://youtu.be/VIDEO_ID&quality=720p&key=FF"
            },
            "/health": "Health check"
        },
        "credit": {
            "username": "@KINGFFAIAK47x",
            "made_by": "ANSH AFT"
        }
    })


@app.route('/ping', methods=['GET', 'HEAD'])
def ping():
    return "pong", 200


@app.route('/health', methods=['GET', 'HEAD'])
def health():
    return jsonify({
        "status": "healthy" if not _SHUTTING_DOWN.is_set() else "shutting_down",
        "timestamp": datetime.now().isoformat(),
        "started_at": _STARTUP_TIME,
    }), 200


@app.route('/ready', methods=['GET', 'HEAD'])
def ready():
    yt_ok = False
    try:
        yt_ok = get_yt_dlp() is not None
    except Exception:
        pass

    ffmpeg_ok = check_ffmpeg()
    pot_ok = check_pot_server()
    cookies_ok = bool(COOKIE_FILE and os.path.exists(COOKIE_FILE))

    return jsonify({
        "status": "ready" if (yt_ok and ffmpeg_ok) else "not_ready",
        "yt_dlp": yt_ok,
        "ffmpeg": ffmpeg_ok,
        "pot_server": pot_ok,
        "cookies": cookies_ok,
        "cookies_path": COOKIE_FILE,
        "deno": check_deno(),
        "node": check_node(),
        "proxy": bool(YTDLP_PROXY),
        "upload_hosts": [fn.__name__ for fn in UPLOAD_HOSTS],
        "timestamp": datetime.now().isoformat(),
    }), 200 if (yt_ok and ffmpeg_ok) else 503


@app.route('/yt', methods=['GET'])
@require_api_key
def download_yt():
    try:
        url_raw = request.args.get("url", "").strip()
        quality = request.args.get("quality", "720p").strip()

        if not url_raw:
            return jsonify({
                "status": "error",
                "error_code": "MISSING_URL",
                "message": "URL required",
                "request_id": getattr(g, "request_id", None),
            }), 400

        ok, result = validate_youtube_url(url_raw)
        if not ok:
            return jsonify({
                "status": "error",
                "error_code": "INVALID_URL",
                "message": result,
                "request_id": getattr(g, "request_id", None),
            }), 400

        video_id = result
        url = f"https://www.youtube.com/watch?v={video_id}"
        quality = validate_quality(quality)

        log_event(f"[{getattr(g, 'request_id', '?')}] {video_id} @ {quality}")

        data = process_video(url, quality, video_id=video_id)
        data["request_id"] = getattr(g, "request_id", None)

        if data.get("status") in ("success", "partial"):
            return jsonify(data), 200
        return jsonify(data), 400

    except Exception as e:
        return jsonify({
            "status": "error",
            "error_code": "PROCESS_ERROR",
            "message": str(e)[:300],
            "request_id": getattr(g, "request_id", None),
        }), 500


@app.route('/debug', methods=['GET', 'HEAD'])
@require_api_key
def debug():
    return jsonify({
        "status": "ok",
        "version": "27.0.0",
        "started_at": _STARTUP_TIME,
        "now": datetime.now().isoformat(),
        "pid": os.getpid(),
        "system": {
            "yt_dlp": True,
            "deno": check_deno(),
            "node": check_node(),
            "ffmpeg": check_ffmpeg(),
            "pot_server": check_pot_server(),
            "cookies_exists": bool(COOKIE_FILE and os.path.exists(COOKIE_FILE)),
            "cookies_path": COOKIE_FILE,
            "cookies_writable": bool(COOKIE_FILE and os.access(COOKIE_FILE, os.W_OK)) if COOKIE_FILE else False,
            "proxy_enabled": bool(YTDLP_PROXY),
            "proxy_host": YTDLP_PROXY.split("@")[-1] if YTDLP_PROXY else "N/A",
        },
        "config": {
            "rate_limit_per_min": RATE_LIMIT_PER_MIN,
            "download_concurrency": DOWNLOAD_CONCURRENCY,
            "upload_parallel": UPLOAD_PARALLEL,
            "upload_timeout": UPLOAD_TIMEOUT,
            "upload_hosts": [fn.__name__ for fn in UPLOAD_HOSTS],
        },
        "threads": {
            "active": threading.active_count(),
        },
        "logs": _STARTUP_LOG[-30:],
    }), 200


@app.errorhandler(404)
def nf(e):
    return jsonify({"status": "error", "message": "Not found"}), 404


@app.errorhandler(500)
def ie(e):
    return jsonify({"status": "error", "message": "Internal error"}), 500


@app.errorhandler(Exception)
def he(e):
    return jsonify({
        "status": "error",
        "error_code": "UNHANDLED_EXCEPTION",
        "message": str(e)[:300],
    }), 500


# ==============================================
# STARTUP
# ==============================================

log_event("=" * 60)
log_event("YouTube Downloader API v27.0 STARTED")
log_event(f"Deno: {check_deno()}, Node: {check_node()}, FFmpeg: {check_ffmpeg()}")
log_event(f"Cookies: {COOKIE_FILE}")
log_event(f"Proxy: {'SET' if YTDLP_PROXY else 'NOT SET'}")
log_event(f"POT: {check_pot_server()}")
log_event(f"Upload Hosts: {len(UPLOAD_HOSTS)} available")
log_event(f"Upload Parallel: {UPLOAD_PARALLEL}")
log_event("=" * 60)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
