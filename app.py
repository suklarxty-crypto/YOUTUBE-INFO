# app.py - YouTube Downloader API v19.0 FINAL
# Made by @KINGFFAIAK47x · ANSH AFT
# EXACT FLAT RESPONSE + FAST + ALL DATA

os.environ["YTDLP_NO_PLUGIN_LOAD"] = "1"
os.environ["YT_DLP_NO_PLUGINS"] = "1"
os.environ["PYTHONWARNINGS"] = "ignore"

from flask import Flask, jsonify, request
import os
import sys
import json
import time
import threading
import re
import shutil
import hashlib
from datetime import datetime
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# ==============================================
# CONFIG
# ==============================================

VALID_KEYS = {
    "AK$&FF": "full_access",
    "FF": "full_access"
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = "/tmp/youtube_data"

COOKIES_SRC = os.path.join(SCRIPT_DIR, "yt_cookies.txt")
COOKIES_FILE = "/tmp/yt_cookies.txt"

if os.path.exists(COOKIES_SRC):
    try:
        shutil.copy2(COOKIES_SRC, COOKIES_FILE)
    except Exception:
        pass

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==============================================
# PROXY
# ==============================================

PROXY_HOST = "p.webshare.io"
PROXY_PORT = "80"
PROXY_USER = "zhzvbrqp-rotate"
PROXY_PASS = "0dyibxc2gqma"
PROXY_URL = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
USE_PROXY = True

# ==============================================
# THREADS / CACHE
# ==============================================

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="yt_")
_INFO_CACHE = {}
_CACHE_LOCK = threading.Lock()
CACHE_TTL = 300

_POT_CACHE = {"checked": 0, "available": False}
_POT_LOCK = threading.Lock()

MAX_TOTAL_TIME = 85

# ==============================================
# LAZY LOADERS
# ==============================================

_yt_dlp_cache = None
_requests_cache = None
_import_lock = threading.Lock()


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


# ==============================================
# HELPERS
# ==============================================

def check_deno():
    return shutil.which("deno") is not None


def check_node():
    return shutil.which("node") is not None


def check_ffmpeg():
    return shutil.which("ffmpeg") is not None


def check_pot_server():
    with _POT_LOCK:
        now = time.time()
        if now - _POT_CACHE["checked"] < 60:
            return _POT_CACHE["available"]
        try:
            r = get_requests().get("http://127.0.0.1:4416/ping", timeout=0.5)
            _POT_CACHE["available"] = (r.status_code == 200)
        except Exception:
            _POT_CACHE["available"] = False
        _POT_CACHE["checked"] = now
        return _POT_CACHE["available"]


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


# ==============================================
# AUTH
# ==============================================

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.args.get('key', '').strip()
        if not api_key:
            return jsonify({
                "status": "error",
                "error_code": "MISSING_API_KEY",
                "message": "API key required",
                "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
            }), 401
        if api_key not in VALID_KEYS:
            return jsonify({
                "status": "error",
                "error_code": "INVALID_API_KEY",
                "message": "Invalid API key",
                "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
            }), 403
        return f(*args, **kwargs)
    return decorated_function


# ==============================================
# VALIDATION
# ==============================================

def validate_youtube_url(url):
    if not url:
        return False, "URL required"
    url = str(url).strip()
    if len(url) < 10 or len(url) > 500:
        return False, "Invalid length"
    patterns = [
        r'^https?://(www\.)?youtube\.com/watch\?v=[\w\-]+',
        r'^https?://(www\.)?youtu\.be/[\w\-]+',
        r'^https?://(www\.)?youtube\.com/shorts/[\w\-]+',
        r'^https?://(www\.)?youtube\.com/embed/[\w\-]+',
    ]
    for p in patterns:
        if re.match(p, url):
            return True, url
    return False, "Invalid YouTube URL"


def validate_quality(q):
    if not q:
        return "720p"
    q = str(q).strip().lower()
    valid = ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p", "best"]
    return q if q in valid else "720p"


# ==============================================
# YT-DLP OPTS
# ==============================================

def build_opts(download=False, quality="720p", use_cookies=True, no_proxy=False):
    if quality == "best":
        format_str = "bv*+ba/b"
    else:
        try:
            h = int(str(quality).rstrip("p"))
            format_str = f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
        except Exception:
            format_str = "bv*+ba/b"
    
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "cachedir": False,
        "no_color": True,
        "socket_timeout": 12,
        "retries": 1,
        "fragment_retries": 1,
        "extractor_retries": 1,
        "skip_unavailable_fragments": True,
        "noprogress": True,
        "consoletitle": False,
        "format": format_str,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["tv", "web", "mweb", "android"],
                "fetch_pot": ["auto"],
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
    }
    
    if check_deno():
        opts["js_runtimes"] = {"deno": {}}
    elif check_node():
        opts["js_runtimes"] = {"node": {}}
    
    if check_pot_server():
        opts["extractor_args"]["youtubepot-bgutilhttp"] = {
            "base_url": "http://127.0.0.1:4416"
        }
    
    if USE_PROXY and not no_proxy:
        opts["proxy"] = PROXY_URL
    
    if use_cookies and os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    
    if download:
        out_dir = os.path.join(OUTPUT_DIR, "downloads")
        os.makedirs(out_dir, exist_ok=True)
        opts["outtmpl"] = os.path.join(out_dir, "%(title).100B [%(id)s].%(ext)s")
        opts["concurrent_fragment_downloads"] = 32
        opts["merge_output_format"] = "mp4"
        opts["buffersize"] = 1024 * 1024 * 8
        opts["http_chunk_size"] = 1024 * 1024 * 8
        opts["skip_download"] = False
        opts["retries"] = 2
        opts["fragment_retries"] = 2
    
    return opts


# ==============================================
# VERIFY
# ==============================================

def verify_video_exists(info):
    if not info:
        return False, "No info"
    vid = info.get("id")
    if not vid or not re.match(r'^[\w\-]{11}$', str(vid)):
        return False, "Invalid video ID"
    title = info.get("title")
    if not title or str(title).strip() == "":
        return False, "Empty title"
    if info.get("_error") or info.get("error"):
        return False, f"Error: {info.get('_error') or info.get('error')}"
    webpage = info.get("webpage_url")
    if not webpage or ("youtube.com" not in str(webpage) and "youtu.be" not in str(webpage)):
        return False, "Invalid webpage URL"
    formats = info.get("formats")
    if not formats or not isinstance(formats, list) or len(formats) == 0:
        return False, "No formats"
    return True, "Verified"


def compute_video_fingerprint(info):
    if not info:
        return None
    parts = [
        safe_str(info.get("id")),
        safe_str(info.get("title")),
        safe_str(info.get("duration")),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ==============================================
# CACHE
# ==============================================

def cache_get(url):
    with _CACHE_LOCK:
        entry = _INFO_CACHE.get(url)
        if entry:
            ts, info = entry
            if time.time() - ts < CACHE_TTL:
                return info
            else:
                del _INFO_CACHE[url]
    return None


def cache_set(url, info):
    with _CACHE_LOCK:
        _INFO_CACHE[url] = (time.time(), info)
        if len(_INFO_CACHE) > 50:
            now = time.time()
            keys = [k for k, (ts, _) in _INFO_CACHE.items() if now - ts > CACHE_TTL]
            for k in keys:
                del _INFO_CACHE[k]


# ==============================================
# PARALLEL EXTRACTION
# ==============================================

def _extract_attempt(url, attempt):
    yt = get_yt_dlp()
    try:
        opts = build_opts(
            download=False,
            use_cookies=attempt["use_cookies"],
            no_proxy=attempt["no_proxy"]
        )
        opts["socket_timeout"] = attempt["timeout"]
        with yt.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None, f"[{attempt['label']}] No info"
            if info.get("_error"):
                return None, f"[{attempt['label']}] {info['_error']}"
            is_valid, reason = verify_video_exists(info)
            if is_valid:
                return info, None
            return None, f"[{attempt['label']}] Verify: {reason}"
    except Exception as e:
        return None, f"[{attempt['label']}] {str(e)[:150]}"


def extract_info(url):
    cached = cache_get(url)
    if cached:
        return cached
    
    yt = get_yt_dlp()
    if not yt:
        return {"_error": "yt-dlp not available", "_verified": False}
    
    attempts = [
        {"use_cookies": True, "no_proxy": False, "label": "ck+px", "timeout": 12},
        {"use_cookies": False, "no_proxy": False, "label": "px", "timeout": 12},
        {"use_cookies": True, "no_proxy": True, "label": "ck", "timeout": 10},
    ]
    
    all_errors = []
    winner = None
    
    futures = {_EXECUTOR.submit(_extract_attempt, url, a): a for a in attempts}
    
    try:
        for fut in as_completed(futures, timeout=20):
            try:
                info, err = fut.result(timeout=1)
                if info and not winner:
                    winner = info
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    break
                elif err:
                    all_errors.append(err)
            except Exception as e:
                all_errors.append(str(e)[:100])
    except Exception as e:
        all_errors.append(f"Parallel timeout: {e}")
    
    if winner:
        winner["_verified"] = True
        winner["_fingerprint"] = compute_video_fingerprint(winner)
        cache_set(url, winner)
        return winner
    
    return {
        "_error": "All extraction attempts failed",
        "_all_errors": all_errors,
        "_verified": False
    }


# ==============================================
# BUILD FULL INFO - EXACT FLAT STRUCTURE
# ==============================================

def build_full_info(info):
    if not info or info.get("_error"):
        return {"error": info.get("_error", "No info") if info else "No info"}
    
    vid = safe_str(info.get("id"))
    dur = safe_int(info.get("duration"))
    desc = safe_str(info.get("description"))
    
    # ===== VIDEO =====
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
    
    # ===== DURATION =====
    duration = {
        "seconds": dur,
        "string": safe_str(info.get("duration_string")),
        "formatted": fmt_dur(dur),
        "minutes": dur // 60 if dur else 0,
        "hours": dur // 3600 if dur else 0,
    }
    
    # ===== DATES =====
    upload_date = safe_str(info.get("upload_date"))
    dates = {
        "upload_date": upload_date,
        "upload_date_formatted": fmt_date(upload_date) if upload_date else "N/A",
        "release_date": safe_str(info.get("release_date")),
        "modified_date": safe_str(info.get("modified_date")),
        "timestamp": safe_int(info.get("timestamp")),
    }
    
    # ===== ENGAGEMENT =====
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
    
    # ===== CHANNEL =====
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
    
    # ===== METADATA =====
    metadata = {
        "categories": info.get("categories") or [],
        "tags": info.get("tags") or [],
        "tags_count": len(info.get("tags") or []),
        "language": safe_str(info.get("language")),
        "age_limit": safe_int(info.get("age_limit")),
        "is_family_friendly": info.get("is_family_friendly"),
        "availability": safe_str(info.get("availability")),
    }
    
    # ===== SUBTITLES =====
    subtitles_manual = list((info.get("subtitles") or {}).keys())
    subtitles_auto = list((info.get("automatic_captions") or {}).keys())
    subtitles = {
        "manual": subtitles_manual,
        "automatic": subtitles_auto,
        "total_manual": len(subtitles_manual),
        "total_auto": len(subtitles_auto),
    }
    
    # ===== LIVE =====
    live = {
        "is_live": safe_bool(info.get("is_live")),
        "was_live": safe_bool(info.get("was_live")),
        "live_status": safe_str(info.get("live_status")),
    }
    
    # ===== TECHNICAL =====
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
    
    # ===== EXTRACTOR =====
    extractor = {
        "name": safe_str(info.get("extractor")),
        "key": safe_str(info.get("extractor_key")),
        "domain": safe_str(info.get("webpage_url_domain")),
    }
    
    # ===== CHAPTERS =====
    chapters = []
    for c in (info.get("chapters") or []):
        if not c:
            continue
        chapters.append({
            "start_time": safe_float(c.get("start_time")),
            "end_time": safe_float(c.get("end_time")),
            "title": safe_str(c.get("title")),
        })
    
    # ===== FORMATS =====
    formats = []
    for f in (info.get("formats") or []):
        if not f:
            continue
        fs = f.get("filesize") or f.get("filesize_approx") or 0
        fmt_entry = {
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
        }
        formats.append(fmt_entry)
    
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
# UPLOAD
# ==============================================

def up_tmpfiles(fp):
    r_ = get_requests()
    try:
        with open(fp, "rb") as f:
            r = r_.post("https://tmpfiles.org/api/v1/upload",
                        files={"file": f}, timeout=60)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success":
                url = data.get("data", {}).get("url", "")
                if url:
                    direct = url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    return ("tmpfiles.org", direct)
    except Exception:
        pass
    return None


def up_catbox(fp):
    r_ = get_requests()
    try:
        with open(fp, "rb") as f:
            r = r_.post("https://catbox.moe/user/api.php",
                        data={"reqtype": "fileupload"},
                        files={"fileToUpload": f}, timeout=60)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            return ("catbox.moe", r.text.strip())
    except Exception:
        pass
    return None


def up_litterbox(fp):
    r_ = get_requests()
    try:
        with open(fp, "rb") as f:
            r = r_.post("https://litterbox.catbox.moe/resources/internals/api.php",
                        data={"reqtype": "fileupload", "time": "1h"},
                        files={"fileToUpload": f}, timeout=60)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            return ("litterbox", r.text.strip())
    except Exception:
        pass
    return None


def up_0x0(fp):
    r_ = get_requests()
    try:
        with open(fp, "rb") as f:
            r = r_.post("https://0x0.st", files={"file": f}, timeout=60)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            return ("0x0.st", r.text.strip())
    except Exception:
        pass
    return None


def upload_parallel(fp):
    res = {"url": None, "host": None}
    lock = threading.Lock()
    stop = threading.Event()
    
    def worker(fn):
        if stop.is_set():
            return
        try:
            r = fn(fp)
            if r and not stop.is_set():
                with lock:
                    if not res["url"]:
                        res["url"] = r[1]
                        res["host"] = r[0]
                        stop.set()
        except Exception:
            pass
    
    hosts = [up_tmpfiles, up_catbox, up_litterbox, up_0x0]
    threads = [threading.Thread(target=worker, args=(f,), daemon=True) for f in hosts]
    for t in threads:
        t.start()
    
    start = time.time()
    while time.time() - start < 60:
        if res["url"]:
            break
        if all(not t.is_alive() for t in threads):
            break
        time.sleep(0.05)
    
    return res


# ==============================================
# PROCESS VIDEO - EXACT FLAT STRUCTURE
# ==============================================

def process_video(url, quality="720p"):
    yt = get_yt_dlp()
    if not yt:
        return {
            "status": "error",
            "error_code": "YTDLP_NOT_AVAILABLE",
            "message": "yt-dlp not loaded",
            "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
        }
    
    t_start = time.time()
    
    dl_result = {"status": "pending"}
    info_result = {"info": None}
    dl_lock = threading.Lock()
    info_lock = threading.Lock()
    
    def do_download():
        nonlocal dl_result
        try:
            t_dl_start = time.time()
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
                t_up_start = time.time()
                up_res = upload_parallel(fname)
                t_up_end = time.time()
                
                with dl_lock:
                    dl_result = {
                        "status": "success",
                        "filename": os.path.basename(fname),
                        "file_size": size,
                        "file_size_formatted": fmt_size(size),
                        "quality": quality,
                        "download_time": f"{round(t_dl_end - t_dl_start, 2)}s",
                        "downloaded_at": datetime.now().isoformat(),
                        "share_url": up_res.get("url") or "UPLOAD_FAILED",
                        "upload_host": up_res.get("host") or "N/A",
                    }
            else:
                with dl_lock:
                    dl_result = {
                        "status": "failed",
                        "error": "File not found after download",
                        "quality": quality,
                    }
        except Exception as ex:
            with dl_lock:
                dl_result = {
                    "status": "failed",
                    "error": str(ex)[:200],
                    "quality": quality,
                }
    
    def do_info():
        nonlocal info_result
        try:
            info = extract_info(url)
            with info_lock:
                info_result["info"] = info
        except Exception as e:
            with info_lock:
                info_result["info"] = {"_error": str(e)[:200], "_verified": False}
    
    t_dl = threading.Thread(target=do_download, daemon=True)
    t_info = threading.Thread(target=do_info, daemon=True)
    
    t_dl.start()
    t_info.start()
    
    t_dl.join(timeout=MAX_TOTAL_TIME - 20)
    t_info.join(timeout=20)
    
    info = info_result.get("info")
    
    if not info or info.get("_error"):
        return {
            "status": "error",
            "error_code": "EXTRACT_FAILED",
            "message": (info.get("_error", "Failed") if info else "No info"),
            "all_errors": (info.get("_all_errors", []) if info else []),
            "download": dl_result,
            "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
        }
    
    full = build_full_info(info)
    total_time = round(time.time() - t_start, 2)
    
    # ⚡⚡⚡ EXACT FLAT STRUCTURE ⚡⚡⚡
    return {
        "status": "success",
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


# ==============================================
# ENDPOINTS
# ==============================================

@app.route('/', methods=['GET', 'HEAD'])
def home():
    return jsonify({
        "service": "🎬 YouTube Downloader API",
        "version": "19.0.0",
        "description": "Download YouTube videos and get complete info in one request",
        "endpoints": {
            "/yt": {
                "method": "GET",
                "description": "Download YouTube video + get full info",
                "example": "/yt?url=https://youtu.be/VIDEO_ID&quality=720p&key=FF",
                "qualities": ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p", "best"]
            },
            "/health": {
                "method": "GET",
                "description": "Health check"
            }
        },
        "credit": {
            "username": "@KINGFFAIAK47x",
            "made_by": "ANSH AFT"
        }
    }), 200


@app.route('/health', methods=['GET', 'HEAD'])
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }), 200


@app.route('/yt', methods=['GET'])
@require_api_key
def download_yt():
    url = request.args.get('url', '').strip()
    quality = request.args.get('quality', '720p').strip()
    
    if not url:
        return jsonify({
            "status": "error",
            "error_code": "MISSING_URL",
            "message": "YouTube URL required",
            "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
        }), 400
    
    is_valid, result = validate_youtube_url(url)
    if not is_valid:
        return jsonify({
            "status": "error",
            "error_code": "INVALID_URL",
            "message": result,
            "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
        }), 400
    
    url = result
    quality = validate_quality(quality)
    
    try:
        result = process_video(url, quality)
        result["credit"] = {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
        if result.get("status") == "success":
            return jsonify(result), 200
        else:
            return jsonify(result), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "error_code": "PROCESS_ERROR",
            "message": str(e)[:200],
            "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
        }), 500


@app.errorhandler(404)
def not_found(error):
    return jsonify({"status": "error", "message": "Use /yt"}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"status": "error", "message": "Internal error"}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
