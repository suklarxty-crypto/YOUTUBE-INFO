# app.py - YouTube Downloader API v3.0
# Made by @KINGFFAIAK47x · ANSH AFT
# Render deployment ready

from flask import Flask, jsonify, request
import os
import sys
import json
import time
import subprocess
import threading
import re
import shutil
from datetime import datetime
from functools import wraps

# ==============================================
# INSTALL DEPENDENCIES IF MISSING
# ==============================================

def install_package(p):
    try:
        __import__(p.replace("-", "_"))
        return True
    except ImportError:
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", p],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True
        except:
            return False

install_package("yt-dlp")
install_package("requests")

import yt_dlp
import requests

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
COOKIES_FILE = os.path.join(SCRIPT_DIR, "yt_cookies.txt")
DATA_FILE = os.path.join(OUTPUT_DIR, "youtube_data.json")

os.makedirs(OUTPUT_DIR, exist_ok=True)


# ==============================================
# AUTHENTICATION
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
                "usage": "/yt?url=YOUTUBE_URL&key=your_api_key",
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
# COOKIES VERIFICATION
# ==============================================

def verify_cookies_file():
    """Cookie file verify karo - 7 columns check"""
    if not os.path.exists(COOKIES_FILE):
        return False, "Cookie file not found"
    
    try:
        with open(COOKIES_FILE, "r", encoding="utf-8") as f:
            content = f.read()
        
        if "Netscape HTTP Cookie File" not in content:
            return False, "Invalid cookie format (header missing)"
        
        valid_count = 0
        invalid_count = 0
        
        for line in content.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            
            parts = line.split("\t")
            if len(parts) == 7:
                valid_count += 1
            else:
                invalid_count += 1
        
        if valid_count < 5:
            return False, f"Too few valid cookies: {valid_count} (need 5+)"
        
        return True, f"{valid_count} valid cookies, {invalid_count} invalid"
    except Exception as e:
        return False, str(e)


# ==============================================
# HELPERS
# ==============================================

def safe_str(o, d=""):
    return d if o is None else str(o)


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
# VALIDATION
# ==============================================

def validate_youtube_url(url):
    if not url:
        return False, "URL required"
    
    url = str(url).strip()
    
    if len(url) < 10 or len(url) > 500:
        return False, "URL length invalid (10-500 chars)"
    
    patterns = [
        r'^https?://(www\.)?youtube\.com/watch\?v=[\w\-]+',
        r'^https?://(www\.)?youtu\.be/[\w\-]+',
        r'^https?://(www\.)?youtube\.com/shorts/[\w\-]+',
        r'^https?://(www\.)?youtube\.com/embed/[\w\-]+',
        r'^https?://m\.youtube\.com/watch\?v=[\w\-]+',
        r'^https?://music\.youtube\.com/watch\?v=[\w\-]+',
    ]
    
    for p in patterns:
        if re.match(p, url):
            return True, url
    
    return False, "Invalid YouTube URL"


def validate_quality(quality):
    if not quality:
        return "720p"
    quality = str(quality).strip().lower()
    valid = ["360p", "480p", "720p", "1080p", "best"]
    return quality if quality in valid else "720p"


# ==============================================
# JSON DB
# ==============================================

def load_db():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(DATA_FILE):
        return {
            "file_info": {
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "total_videos": 0
            },
            "videos": []
        }
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {
            "file_info": {
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "total_videos": 0
            },
            "videos": []
        }


def save_db(db):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    db["file_info"]["last_updated"] = datetime.now().isoformat()
    db["file_info"]["total_videos"] = len(db["videos"])
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        return DATA_FILE
    except:
        return None


def append_db(vdata):
    db = load_db()
    vid = vdata.get("video", {}).get("id", "")
    replaced = False
    for i, ex in enumerate(db["videos"]):
        if ex.get("video", {}).get("id", "") == vid:
            db["videos"][i] = vdata
            replaced = True
            break
    if not replaced:
        db["videos"].append(vdata)
    return save_db(db)


# ==============================================
# YT-DLP OPTS - FIXED
# ==============================================

def build_opts(download=False, quality="720p"):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "cachedir": False,
        "no_color": True,
        "socket_timeout": 15,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 2,
        "skip_unavailable_fragments": True,
        "noprogress": True,
        "consoletitle": False,
        
        # ⚡ WORKING CLIENTS (android/ios blocked)
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "mweb", "tv"]
            }
        },
        
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }
    
    # Deno available? toh use karo
    if shutil.which("deno"):
        opts["js_runtimes"] = ["deno"]
    
    # Cookies add karo
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    
    if download:
        out_dir = os.path.join(OUTPUT_DIR, "downloads")
        os.makedirs(out_dir, exist_ok=True)
        opts["outtmpl"] = os.path.join(out_dir, "%(title)s [%(id)s].%(ext)s")
        opts["concurrent_fragment_downloads"] = 32
        opts["buffersize"] = 2 * 1024 * 1024
        
        if quality == "best":
            opts["format"] = "best[ext=mp4]/best"
        else:
            try:
                h = int(str(quality).rstrip("p"))
                opts["format"] = (f"best[height<={h}][ext=mp4]/"
                                  f"best[height<={h}]/best[ext=mp4]/best")
            except:
                opts["format"] = "best[ext=mp4]/best"
    else:
        opts["skip_download"] = True
    
    return opts


# ==============================================
# EXTRACT INFO
# ==============================================

def extract_info(url):
    try:
        with yt_dlp.YoutubeDL(build_opts(download=False)) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        return {"_error": str(e)}


def build_full_info(info):
    if not info or info.get("_error"):
        return {"error": info.get("_error", "No info") if info else "No info"}
    
    vid = safe_str(info.get("id"))
    dur = safe_int(info.get("duration"))
    desc = safe_str(info.get("description"))
    vc = safe_int(info.get("view_count"))
    lc = safe_int(info.get("like_count"))
    cc = safe_int(info.get("comment_count"))
    
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
            "thumbnail_sd": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        },
        "duration": {
            "seconds": dur,
            "string": safe_str(info.get("duration_string")),
            "formatted": fmt_dur(dur),
            "minutes": dur // 60 if dur else 0,
            "hours": dur // 3600 if dur else 0
        },
        "dates": {
            "upload_date": safe_str(info.get("upload_date")),
            "upload_date_formatted": fmt_date(info.get("upload_date")),
            "release_date": safe_str(info.get("release_date")),
            "timestamp": safe_int(info.get("timestamp"))
        },
        "engagement": {
            "view_count": vc,
            "view_count_formatted": fmt_num(vc),
            "like_count": lc,
            "like_count_formatted": fmt_num(lc),
            "comment_count": cc,
            "comment_count_formatted": fmt_num(cc),
            "average_rating": info.get("average_rating")
        },
        "channel": {
            "name": safe_str(info.get("channel")),
            "id": safe_str(info.get("channel_id")),
            "url": safe_str(info.get("channel_url")),
            "uploader": safe_str(info.get("uploader")),
            "uploader_id": safe_str(info.get("uploader_id")),
            "follower_count": safe_int(info.get("channel_follower_count")),
            "follower_count_formatted": fmt_num(info.get("channel_follower_count"))
        },
        "metadata": {
            "categories": info.get("categories") or [],
            "tags": info.get("tags") or [],
            "tags_count": len(info.get("tags") or []),
            "language": safe_str(info.get("language")),
            "age_limit": safe_int(info.get("age_limit")),
            "availability": safe_str(info.get("availability"))
        },
        "technical": {
            "ext": safe_str(info.get("ext")),
            "format": safe_str(info.get("format")),
            "format_id": safe_str(info.get("format_id")),
            "width": safe_int(info.get("width")),
            "height": safe_int(info.get("height")),
            "fps": safe_int(info.get("fps")),
            "vcodec": safe_str(info.get("vcodec")),
            "acodec": safe_str(info.get("acodec")),
            "filesize": safe_int(info.get("filesize")),
            "filesize_formatted": fmt_size(info.get("filesize"))
        },
        "extractor": {
            "name": safe_str(info.get("extractor")),
            "key": safe_str(info.get("extractor_key"))
        },
        "format_count": len(info.get("formats") or [])
    }


# ==============================================
# UPLOAD FUNCTIONS
# ==============================================

UPLOAD_TIMEOUT = 30


def up_0x0(fp):
    try:
        with open(fp, "rb") as f:
            r = requests.post("https://0x0.st", files={"file": f},
                              headers={"User-Agent": "Mozilla/5.0"},
                              timeout=UPLOAD_TIMEOUT)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            return ("0x0.st", r.text.strip())
    except:
        pass
    return None


def up_catbox(fp):
    try:
        with open(fp, "rb") as f:
            r = requests.post("https://catbox.moe/user/api.php",
                              data={"reqtype": "fileupload"},
                              files={"fileToUpload": f}, timeout=UPLOAD_TIMEOUT)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            return ("catbox.moe", r.text.strip())
    except:
        pass
    return None


def up_tmpfiles(fp):
    try:
        with open(fp, "rb") as f:
            r = requests.post("https://tmpfiles.org/api/v1/upload",
                              files={"file": f}, timeout=UPLOAD_TIMEOUT)
        if r.status_code == 200:
            u = r.json().get("data", {}).get("url", "")
            if u:
                return ("tmpfiles.org", u.replace("tmpfiles.org/", "tmpfiles.org/dl/"))
    except:
        pass
    return None


def up_litterbox(fp):
    try:
        with open(fp, "rb") as f:
            r = requests.post("https://litterbox.catbox.moe/resources/internals/api.php",
                              data={"reqtype": "fileupload", "time": "1h"},
                              files={"fileToUpload": f}, timeout=UPLOAD_TIMEOUT)
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
               for f in [up_0x0, up_catbox, up_tmpfiles, up_litterbox]]
    for t in threads:
        t.start()
    
    start = time.time()
    while time.time() - start < UPLOAD_TIMEOUT:
        if res["url"]:
            break
        if all(not t.is_alive() for t in threads):
            break
        time.sleep(0.05)
    
    return res


# ==============================================
# PROCESS VIDEO
# ==============================================

def process_video(url, quality="720p"):
    t_start = time.time()
    
    # Step 1: Extract info
    t0 = time.time()
    info = extract_info(url)
    if not info or info.get("_error"):
        return {
            "status": "error",
            "error_code": "EXTRACT_FAILED",
            "message": info.get("_error", "Failed") if info else "No info"
        }
    
    info_time = round(time.time() - t0, 2)
    full = build_full_info(info)
    
    # Step 2: Download
    t0 = time.time()
    dl_data = {"status": "failed"}
    share_url = None
    fname = None
    
    try:
        opts = build_opts(download=True, quality=quality)
        with yt_dlp.YoutubeDL(opts) as ydl:
            dl_info = ydl.extract_info(url, download=True)
            fname = ydl.prepare_filename(dl_info)
            if not os.path.exists(fname):
                base = os.path.splitext(fname)[0]
                for ext in [".mp4", ".mkv", ".webm"]:
                    if os.path.exists(base + ext):
                        fname = base + ext
                        break
        
        dl_time = round(time.time() - t0, 2)
        
        if fname and os.path.exists(fname):
            size = os.path.getsize(fname)
            
            # Step 3: Upload
            up_res = upload_parallel(fname)
            share_url = up_res.get("url")
            
            dl_data = {
                "status": "success",
                "filename": os.path.basename(fname),
                "file_size": size,
                "file_size_formatted": fmt_size(size),
                "quality": quality,
                "download_time": f"{dl_time}s",
                "share_url": share_url or "UPLOAD_FAILED",
                "upload_host": up_res.get("host") or "N/A"
            }
        else:
            dl_data = {"status": "failed", "error": "File not found after download"}
    except Exception as ex:
        dl_data = {"status": "failed", "error": str(ex)[:200]}
    
    total_time = round(time.time() - t_start, 2)
    
    return {
        "status": "success",
        "total_time": f"{total_time}s",
        "info_time": f"{info_time}s",
        "download": dl_data,
        "video": full.get("video", {}),
        "duration": full.get("duration", {}),
        "dates": full.get("dates", {}),
        "engagement": full.get("engagement", {}),
        "channel": full.get("channel", {}),
        "metadata": full.get("metadata", {}),
        "technical": full.get("technical", {}),
        "extractor": full.get("extractor", {}),
        "formats_count": full.get("format_count", 0),
        "credit": {
            "username": "@KINGFFAIAK47x",
            "made_by": "ANSH AFT"
        }
    }


# ==============================================
# ENDPOINTS
# ==============================================

@app.route('/', methods=['GET'])
def home():
    """API info"""
    cookie_status, cookie_msg = verify_cookies_file()
    deno_ok = shutil.which("deno") is not None
    
    return jsonify({
        "service": "🎬 YouTube Downloader API",
        "version": "3.0.0",
        "status": "active",
        "system": {
            "cookies_loaded": cookie_status,
            "cookies_message": cookie_msg,
            "deno_available": deno_ok,
            "python_version": sys.version.split()[0],
            "yt_dlp_version": getattr(yt_dlp.version, "__version__", "unknown")
        },
        "endpoint": {
            "/yt": {
                "method": "GET",
                "description": "Download YouTube video",
                "example": "/yt?url=YOUTUBE_URL&quality=720p&key=FF",
                "params": {
                    "url": "YouTube video URL",
                    "quality": "360p|480p|720p|1080p|best",
                    "key": "API key"
                }
            }
        },
        "credit": {
            "username": "@KINGFFAIAK47x",
            "made_by": "ANSH AFT"
        }
    })


@app.route('/yt', methods=['GET'])
@require_api_key
def download_yt():
    """Download YouTube video"""
    url = request.args.get('url', '').strip()
    quality = request.args.get('quality', '720p').strip()
    
    if not url:
        return jsonify({
            "status": "error",
            "error_code": "MISSING_URL",
            "message": "YouTube URL required",
            "usage": "/yt?url=YOUTUBE_URL&quality=720p&key=FF",
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
    
    start_time = time.time()
    
    try:
        result = process_video(url, quality)
        elapsed = round((time.time() - start_time) * 1000, 2)
        
        result["response_time"] = f"{elapsed}ms"
        result["credit"] = {
            "username": "@KINGFFAIAK47x",
            "made_by": "ANSH AFT"
        }
        
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


@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    cookie_status, cookie_msg = verify_cookies_file()
    deno_ok = shutil.which("deno") is not None
    
    return jsonify({
        "status": "healthy",
        "cookies_loaded": cookie_status,
        "cookies_info": cookie_msg,
        "deno_available": deno_ok,
        "timestamp": datetime.now().isoformat()
    })


@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "status": "error",
        "message": "Endpoint not found. Use /yt",
        "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
    }), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        "status": "error",
        "message": "Internal server error",
        "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
    }), 500


# ==============================================
# MAIN
# ==============================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    cookie_status, cookie_msg = verify_cookies_file()
    deno_ok = shutil.which("deno") is not None
    
    print("=" * 60)
    print("🎬 YOUTUBE DOWNLOADER API v3.0")
    print("=" * 60)
    print(f"🚀 Port: {port}")
    print(f"🍪 Cookies: {cookie_msg}")
    print(f"⚙️  Deno: {'✅ Available' if deno_ok else '❌ NOT available'}")
    print(f"🐍 Python: {sys.version.split()[0]}")
    print(f"📦 yt-dlp: {getattr(yt_dlp.version, '__version__', 'unknown')}")
    print("🔑 Keys: FF / AK$&FF")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=False)
