# app.py - YouTube Downloader API v12.0
# Made by @KINGFFAIAK47x · ANSH AFT
# MAXIMUM DATA EXTRACTION - Full fields

from flask import Flask, jsonify, request
import os
import sys
import json
import time
import threading
import re
import shutil
import subprocess
from datetime import datetime
from functools import wraps

app = Flask(__name__)

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
        print("✅ Cookies copied")
    except Exception as e:
        print(f"❌ Cookie error: {e}")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==============================================
# WEBSHARE PROXY
# ==============================================

PROXY_HOST = "p.webshare.io"
PROXY_PORT = "80"
PROXY_USER = "zhzvbrqp-rotate"
PROXY_PASS = "0dyibxc2gqma"
PROXY_URL = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
USE_PROXY = True

# ==============================================
# LAZY LOADERS
# ==============================================

_yt_dlp_cache = None
_requests_cache = None


def get_yt_dlp():
    global _yt_dlp_cache
    if _yt_dlp_cache is None:
        import yt_dlp
        _yt_dlp_cache = yt_dlp
    return _yt_dlp_cache


def get_requests():
    global _requests_cache
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
    try:
        r = get_requests().get("http://127.0.0.1:4416/ping", timeout=3)
        return r.status_code == 200
    except:
        return False


def get_ytdlp_version():
    try:
        yt = get_yt_dlp()
        return getattr(yt.version, "__version__", "unknown")
    except:
        return "unknown"


def verify_cookies_file():
    if not os.path.exists(COOKIES_FILE):
        return False, "Not found"
    try:
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        if "Netscape HTTP Cookie File" not in content:
            return False, "Invalid format"
        valid = 0
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                if len(line.split("\t")) == 7:
                    valid += 1
        return True, f"{valid} valid"
    except:
        return False, "Error"


def safe_str(o, d=""):
    """Safe string conversion with None handling"""
    if o is None:
        return d
    if isinstance(o, (list, dict)):
        try:
            return json.dumps(o, ensure_ascii=False)
        except:
            return d
    return str(o)


def safe_int(o, d=0):
    if o is None:
        return d
    try:
        return int(o)
    except:
        try:
            return int(float(o))
        except:
            return d


def safe_float(o, d=0.0):
    if o is None:
        return d
    try:
        return float(o)
    except:
        return d


def safe_bool(o, d=False):
    if o is None:
        return d
    return bool(o)


def safe_len(o):
    if o is None:
        return 0
    try:
        return len(o)
    except:
        return 0


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
    except:
        return "N/A"


def fmt_dur(sec):
    if not sec:
        return "0:00"
    try:
        s = int(sec)
        h, m, se = s // 3600, (s % 3600) // 60, s % 60
        return f"{h}:{m:02d}:{se:02d}" if h else f"{m}:{se:02d}"
    except:
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
    except:
        return "N/A"


def fmt_date(ds):
    if not ds:
        return "N/A"
    for f in ["%Y%m%d", "%Y-%m-%d"]:
        try:
            return datetime.strptime(str(ds), f).strftime("%d %B %Y")
        except:
            continue
    return str(ds)


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
    valid = ["360p", "480p", "720p", "1080p", "best"]
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
        except:
            format_str = "bv*+ba/b"
    
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "cachedir": False,
        "no_color": True,
        "socket_timeout": 60,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 5,
        "skip_unavailable_fragments": True,
        "noprogress": True,
        "consoletitle": False,
        "format": format_str,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "mweb", "android"],
                "fetch_pot": ["auto"],
            },
        },
    }
    
    # JS runtime
    js_runtimes = {}
    if check_deno():
        js_runtimes["deno"] = {}
    if check_node():
        js_runtimes["node"] = {}
    if js_runtimes:
        opts["js_runtimes"] = js_runtimes
    
    # POT server
    if check_pot_server():
        opts["extractor_args"]["youtubepot-bgutilhttp"] = {
            "base_url": "http://127.0.0.1:4416"
        }
    
    # Proxy
    if USE_PROXY and not no_proxy:
        opts["proxy"] = PROXY_URL
    
    # Cookies
    if use_cookies and os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    
    if download:
        out_dir = os.path.join(OUTPUT_DIR, "downloads")
        os.makedirs(out_dir, exist_ok=True)
        opts["outtmpl"] = os.path.join(out_dir, "%(title).100B [%(id)s].%(ext)s")
        opts["concurrent_fragment_downloads"] = 16
        opts["merge_output_format"] = "mp4"
    else:
        opts["skip_download"] = True
    
    return opts


# ==============================================
# MAXIMUM DATA EXTRACTION
# ==============================================

def extract_info(url):
    yt = get_yt_dlp()
    if not yt:
        return {"_error": "yt-dlp not available"}
    
    attempts = [
        {"use_cookies": True, "no_proxy": False, "label": "cookies+proxy"},
        {"use_cookies": False, "no_proxy": False, "label": "proxy_only"},
        {"use_cookies": True, "no_proxy": True, "label": "cookies_only"},
    ]
    
    last_error = None
    all_errors = []
    
    for attempt in attempts:
        try:
            opts = build_opts(
                download=False,
                use_cookies=attempt["use_cookies"],
                no_proxy=attempt["no_proxy"]
            )
            with yt.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and not info.get("_error"):
                    return info
        except Exception as e:
            msg = str(e)
            last_error = msg
            all_errors.append(f"[{attempt['label']}] {msg[:200]}")
            continue
    
    return {"_error": last_error or "Failed", "_all_errors": all_errors}


def build_full_info(info):
    """
    MAXIMUM DATA EXTRACTION
    Returns ALL available fields — same as local machine JSON
    """
    if not info or info.get("_error"):
        return {"error": info.get("_error", "No info") if info else "No info"}
    
    vid = safe_str(info.get("id"))
    dur = safe_int(info.get("duration"))
    desc = safe_str(info.get("description"))
    vc = safe_int(info.get("view_count"))
    lc = safe_int(info.get("like_count"))
    cc = safe_int(info.get("comment_count"))
    
    # ============================================
    # FORMATS EXTRACTION - ALL FIELDS
    # ============================================
    formats = []
    for f in (info.get("formats") or []):
        if not f:
            continue
        fs = f.get("filesize") or f.get("filesize_approx")
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
            "filesize_formatted": fmt_size(fs),
            "format_note": safe_str(f.get("format_note")),
            "quality": safe_str(f.get("quality")),
            "has_video": f.get("vcodec") != "none" if f.get("vcodec") else False,
            "has_audio": f.get("acodec") != "none" if f.get("acodec") else False,
            "audio_channels": safe_int(f.get("audio_channels")),
            "audio_bitrate": safe_float(f.get("abr")),
            "video_bitrate": safe_float(f.get("vbr")),
            "tbr": safe_float(f.get("tbr")),
            "protocol": safe_str(f.get("protocol")),
            "container": safe_str(f.get("container")),
            "language": safe_str(f.get("language")),
            "dynamic_range": safe_str(f.get("dynamic_range")),
        })
    
    # ============================================
    # THUMBNAILS EXTRACTION - ALL
    # ============================================
    thumbnails = []
    for t in (info.get("thumbnails") or []):
        if not t:
            continue
        thumbnails.append({
            "url": safe_str(t.get("url")),
            "id": safe_str(t.get("id")),
            "preference": safe_int(t.get("preference")),
            "width": safe_int(t.get("width")),
            "height": safe_int(t.get("height")),
            "resolution": safe_str(t.get("resolution")),
        })
    
    # ============================================
    # SUBTITLES EXTRACTION
    # ============================================
    subtitles_manual = list((info.get("subtitles") or {}).keys())
    subtitles_auto = list((info.get("automatic_captions") or {}).keys())
    
    # ============================================
    # CHAPTERS EXTRACTION
    # ============================================
    chapters = []
    for c in (info.get("chapters") or []):
        if not c:
            continue
        chapters.append({
            "start_time": safe_float(c.get("start_time")),
            "end_time": safe_float(c.get("end_time")),
            "title": safe_str(c.get("title")),
        })
    
    # ============================================
    # FULL RESPONSE - MAXIMUM DATA
    # ============================================
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
            "thumbnails_count": len(thumbnails),
        },
        "duration": {
            "seconds": dur,
            "string": safe_str(info.get("duration_string")),
            "formatted": fmt_dur(dur),
            "minutes": dur // 60 if dur else 0,
            "hours": dur // 3600 if dur else 0,
        },
        "dates": {
            "upload_date": safe_str(info.get("upload_date")),
            "upload_date_formatted": fmt_date(info.get("upload_date")),
            "release_date": safe_str(info.get("release_date")),
            "modified_date": safe_str(info.get("modified_date")),
            "timestamp": safe_int(info.get("timestamp")),
        },
        "engagement": {
            "view_count": vc,
            "view_count_formatted": fmt_num(vc),
            "like_count": lc,
            "like_count_formatted": fmt_num(lc),
            "comment_count": cc,
            "comment_count_formatted": fmt_num(cc),
            "average_rating": info.get("average_rating"),
            "repost_count": safe_int(info.get("repost_count")),
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
            "manual": subtitles_manual,
            "automatic": subtitles_auto,
            "total_manual": len(subtitles_manual),
            "total_auto": len(subtitles_auto),
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
        "chapters": chapters,
        "chapters_count": len(chapters),
        "heatmap": info.get("heatmap"),
        "formats": formats,
        "format_count": len(formats),
    }


# ==============================================
# UPLOAD
# ==============================================

def up_catbox(fp):
    r_ = get_requests()
    try:
        with open(fp, "rb") as f:
            r = r_.post("https://catbox.moe/user/api.php",
                        data={"reqtype": "fileupload"},
                        files={"fileToUpload": f}, timeout=60)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            return ("catbox.moe", r.text.strip())
    except:
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
    except:
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
        except:
            pass
    
    threads = [threading.Thread(target=worker, args=(f,), daemon=True)
               for f in [up_catbox, up_litterbox]]
    for t in threads:
        t.start()
    
    start = time.time()
    while time.time() - start < 60:
        if res["url"]:
            break
        if all(not t.is_alive() for t in threads):
            break
        time.sleep(0.1)
    
    return res


# ==============================================
# PROCESS VIDEO
# ==============================================

def process_video(url, quality="720p"):
    yt = get_yt_dlp()
    if not yt:
        return {
            "status": "error",
            "error_code": "YTDLP_NOT_AVAILABLE",
            "message": "yt-dlp not loaded"
        }
    
    t_start = time.time()
    
    # ========== STEP 1: Extract Info ==========
    info = extract_info(url)
    if not info or info.get("_error"):
        return {
            "status": "error",
            "error_code": "EXTRACT_FAILED",
            "message": info.get("_error", "Failed") if info else "No info",
            "all_errors": info.get("_all_errors", []) if info else [],
            "environment": {
                "deno": check_deno(),
                "node": check_node(),
                "ffmpeg": check_ffmpeg(),
                "pot_server": check_pot_server(),
                "proxy_enabled": USE_PROXY,
                "yt_dlp_version": get_ytdlp_version()
            }
        }
    
    full = build_full_info(info)
    
    # ========== STEP 2: Download ==========
    dl_data = {"status": "failed"}
    fname = None
    
    try:
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
        
        if fname and os.path.exists(fname):
            size = os.path.getsize(fname)
            up_res = upload_parallel(fname)
            
            dl_data = {
                "status": "success",
                "filename": os.path.basename(fname),
                "file_size": size,
                "file_size_formatted": fmt_size(size),
                "quality": quality,
                "share_url": up_res.get("url") or "UPLOAD_FAILED",
                "upload_host": up_res.get("host") or "N/A"
            }
    except Exception as ex:
        dl_data = {"status": "failed", "error": str(ex)[:200]}
    
    total_time = round(time.time() - t_start, 2)
    
    # ========== FINAL RESPONSE - MAXIMUM DATA ==========
    return {
        "status": "success",
        "total_time": f"{total_time}s",
        "download": dl_data,
        # ⚡ FULL DATA - ALL FIELDS
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
        "environment": {
            "deno": check_deno(),
            "node": check_node(),
            "ffmpeg": check_ffmpeg(),
            "pot_server": check_pot_server(),
            "proxy_enabled": USE_PROXY,
            "yt_dlp_version": get_ytdlp_version()
        },
        "credit": {
            "username": "@KINGFFAIAK47x",
            "made_by": "ANSH AFT"
        }
    }


# ==============================================
# ENDPOINTS
# ==============================================

@app.route('/', methods=['GET', 'HEAD'])
def home():
    cookie_status, cookie_msg = verify_cookies_file()
    return jsonify({
        "service": "🎬 YouTube Downloader API",
        "version": "12.0.0",
        "status": "active",
        "system": {
            "cookies_loaded": cookie_status,
            "cookies_message": cookie_msg,
            "cookies_file": COOKIES_FILE,
            "deno_available": check_deno(),
            "node_available": check_node(),
            "ffmpeg_available": check_ffmpeg(),
            "pot_server": check_pot_server(),
            "proxy_enabled": USE_PROXY,
            "proxy_host": PROXY_HOST,
            "yt_dlp_version": get_ytdlp_version()
        },
        "endpoint": {
            "/yt": {
                "method": "GET",
                "example": "/yt?url=YOUTUBE_URL&quality=720p&key=FF"
            }
        },
        "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
    }), 200


@app.route('/health', methods=['GET', 'HEAD'])
def health():
    return jsonify({
        "status": "healthy",
        "deno": check_deno(),
        "node": check_node(),
        "ffmpeg": check_ffmpeg(),
        "pot_server": check_pot_server(),
        "proxy": USE_PROXY,
        "cookies_file": COOKIES_FILE,
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
    print("=" * 60)
    print("🎬 YOUTUBE DOWNLOADER API v12.0 - MAXIMUM DATA")
    print("=" * 60)
    print(f"🚀 Port: {port}")
    print(f"🍪 Cookies: {verify_cookies_file()[1]}")
    print(f"⚙️  Deno: {check_deno()}")
    print(f"📦 Node: {check_node()}")
    print(f"🎥 ffmpeg: {check_ffmpeg()}")
    print(f"🔥 POT Server: {check_pot_server()}")
    print(f"🌐 Proxy: {USE_PROXY} → {PROXY_HOST}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False)
