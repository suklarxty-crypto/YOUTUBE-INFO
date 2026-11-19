# app.py - YouTube Downloader API v29.2
# Made by @KINGFFAIAK47x · ANSH AFT
# NEW v29.2:
#   - Cookies EMBEDDED in code (Chrome JSON format → auto-converted to Netscape)
#   - /cookie/update endpoint — hot swap cookies without redeploy
#   - Zero env setup needed — works out of the box
# KEEP FROM v29.1:
#   - 10x multi-proxy rotation
#   - /cookie/check real-time cookie health
#   - 2K quality verify + 3 host upload + cache

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
import subprocess
import concurrent.futures
from datetime import datetime
from functools import wraps
from collections import defaultdict

from flask import Flask, jsonify, request, g

# ==============================================
# 🔁 MULTI-PROXY ROTATION
# ==============================================

_DEFAULT_PROXY_LIST = """p.webshare.io:6361:obxhxmoa:2mxbvi0048se
p.webshare.io:6014:obxhxmoa:2mxbvi0048se
p.webshare.io:7693:obxhxmoa:2mxbvi0048se
p.webshare.io:6185:obxhxmoa:2mxbvi0048se
p.webshare.io:6095:obxhxmoa:2mxbvi0048se
p.webshare.io:5628:obxhxmoa:2mxbvi0048se
p.webshare.io:6370:obxhxmoa:2mxbvi0048se
p.webshare.io:5803:obxhxmoa:2mxbvi0048se
p.webshare.io:5092:obxhxmoa:2mxbvi0048se
p.webshare.io:6641:obxhxmoa:2mxbvi0048se"""


def _parse_proxy(line):
    line = (line or "").strip()
    if not line or line.startswith("#"):
        return None
    if "://" in line:
        return line
    parts = [p.strip() for p in line.split(":")]
    if len(parts) == 4:
        h, p, u, pw = parts
        return f"http://{u}:{pw}@{h}:{p}"
    if len(parts) == 2:
        h, p = parts
        return f"http://{h}:{p}"
    return None


def _load_proxies():
    raw = os.environ.get("YTDLP_PROXIES", "").strip()
    if not raw:
        raw = _DEFAULT_PROXY_LIST
    return [p for p in (_parse_proxy(l) for l in raw.splitlines()) if p]


PROXY_POOL        = _load_proxies()
PROXY_STATE       = {"index": 0}
PROXY_FAILS       = defaultdict(int)
PROXY_COOLDOWN    = {}
PROXY_LOCK        = threading.Lock()
PROXY_MAX_FAILS   = 3
PROXY_COOLDOWN_S  = 120


def _mask_proxy(p):
    try:
        rest = p.split("://", 1)[1]
        return rest.split("@", 1)[1] if "@" in rest else rest
    except Exception:
        return "?"


def pick_proxy():
    if not PROXY_POOL:
        return None
    now = time.time()
    with PROXY_LOCK:
        n = len(PROXY_POOL)
        for _ in range(n):
            i = PROXY_STATE["index"] % n
            PROXY_STATE["index"] = (i + 1) % n
            p = PROXY_POOL[i]
            if PROXY_COOLDOWN.get(p, 0) <= now:
                return p
        i = PROXY_STATE["index"] % n
        PROXY_STATE["index"] = (i + 1) % n
        return PROXY_POOL[i]


def report_proxy_result(proxy, ok):
    if not proxy:
        return
    with PROXY_LOCK:
        if ok:
            PROXY_FAILS[proxy] = 0
            PROXY_COOLDOWN.pop(proxy, None)
        else:
            PROXY_FAILS[proxy] += 1
            if PROXY_FAILS[proxy] >= PROXY_MAX_FAILS:
                PROXY_COOLDOWN[proxy] = time.time() + PROXY_COOLDOWN_S


def get_proxy_stats():
    now = time.time()
    with PROXY_LOCK:
        return {
            "total": len(PROXY_POOL),
            "active": sum(1 for p in PROXY_POOL if PROXY_COOLDOWN.get(p, 0) <= now),
            "cooling": sum(1 for p in PROXY_POOL if PROXY_COOLDOWN.get(p, 0) > now),
            "proxies": [
                {
                    "proxy": _mask_proxy(p),
                    "fails": PROXY_FAILS.get(p, 0),
                    "cooling": PROXY_COOLDOWN.get(p, 0) > now,
                    "cooldown_left_s": max(0, int(PROXY_COOLDOWN.get(p, 0) - now)),
                } for p in PROXY_POOL
            ],
        }


# ==============================================
# CONFIG
# ==============================================

API_KEYS_ENV        = os.environ.get("API_KEYS", "FF,AK$&FF")
API_KEYS            = set(k.strip() for k in API_KEYS_ENV.split(",") if k.strip())

YTDLP_PROXY         = os.environ.get("YTDLP_PROXY", "").strip()
YT_COOKIE_ENV       = os.environ.get("YT_COOKIE_FILE", "").strip()
RATE_LIMIT_PER_MIN  = int(os.environ.get("RATE_LIMIT_PER_MIN", "5"))
DOWNLOAD_CONCURRENCY= int(os.environ.get("DOWNLOAD_CONCURRENCY", "1"))
LOG_LEVEL           = os.environ.get("LOG_LEVEL", "INFO")
UPLOAD_TIMEOUT      = int(os.environ.get("UPLOAD_TIMEOUT", "120"))
UPLOAD_PARALLEL     = os.environ.get("UPLOAD_PARALLEL", "true").lower() == "true"

# ==============================================
# 🚫 HARD LIMITS
# ==============================================

MAX_QUALITY = "1440p"
MAX_HEIGHT = 1440
MIN_HEIGHT = 144

QUALITY_ORDER = ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p"]
QUALITY_HEIGHT = {
    "144p": 144, "240p": 240, "360p": 360, "480p": 480,
    "720p": 720, "1080p": 1080, "1440p": 1440, "2160p": 2160,
    "best": 1440
}

SIZE_2K_MIN_BYTES = 1 * 1024 * 1024
SIZE_2K_MAX_BYTES = 6 * 1024 * 1024 * 1024

OUTPUT_DIR = "/tmp/youtube_data"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==============================================
# 💾 CACHE CONFIG
# ==============================================

CACHE_ENABLED = os.environ.get("CACHE_ENABLED", "true").lower() == "true"
CACHE_TTL = int(os.environ.get("CACHE_TTL", "3600"))
CACHE_MAX_ENTRIES = int(os.environ.get("CACHE_MAX_ENTRIES", "500"))
CACHE_DIR = os.path.join(OUTPUT_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

_CACHE_STORE = {}
_CACHE_LOCK = threading.Lock()
_CACHE_STATS = {"hits": 0, "misses": 0, "evictions": 0, "expired": 0, "total_cached": 0}

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
# 💾 CACHE FUNCTIONS
# ==============================================

def make_cache_key(video_id, quality):
    raw = f"{video_id}:{quality}:{MAX_HEIGHT}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def cache_get(cache_key):
    if not CACHE_ENABLED:
        return None
    with _CACHE_LOCK:
        entry = _CACHE_STORE.get(cache_key)
        if not entry:
            _CACHE_STATS["misses"] += 1
            return None
        age = time.time() - entry["timestamp"]
        if age > CACHE_TTL:
            del _CACHE_STORE[cache_key]
            _CACHE_STATS["expired"] += 1
            _CACHE_STATS["misses"] += 1
            return None
        entry["hits"] += 1
        _CACHE_STATS["hits"] += 1
        return entry["data"]


def cache_set(cache_key, data):
    if not CACHE_ENABLED:
        return
    with _CACHE_LOCK:
        if len(_CACHE_STORE) >= CACHE_MAX_ENTRIES:
            _evict_cache()
        _CACHE_STORE[cache_key] = {
            "data": data,
            "timestamp": time.time(),
            "hits": 0,
            "video_id": data.get("video_id", "?"),
            "quality": data.get("download", {}).get("quality", "?"),
        }
        _CACHE_STATS["total_cached"] = len(_CACHE_STORE)


def _evict_cache():
    if not _CACHE_STORE:
        return
    sorted_keys = sorted(_CACHE_STORE.keys(), key=lambda k: _CACHE_STORE[k]["timestamp"])
    to_remove = max(1, len(sorted_keys) // 10)
    for k in sorted_keys[:to_remove]:
        del _CACHE_STORE[k]
        _CACHE_STATS["evictions"] += 1


def cache_invalidate(cache_key=None):
    with _CACHE_LOCK:
        if cache_key:
            if cache_key in _CACHE_STORE:
                del _CACHE_STORE[cache_key]
                return True
            return False
        count = len(_CACHE_STORE)
        _CACHE_STORE.clear()
        _CACHE_STATS["total_cached"] = 0
        return count


def cache_cleanup_expired():
    if not CACHE_ENABLED:
        return 0
    now = time.time()
    removed = 0
    with _CACHE_LOCK:
        keys_to_remove = [k for k, v in _CACHE_STORE.items() if now - v["timestamp"] > CACHE_TTL]
        for k in keys_to_remove:
            del _CACHE_STORE[k]
            removed += 1
            _CACHE_STATS["expired"] += 1
        _CACHE_STATS["total_cached"] = len(_CACHE_STORE)
    return removed


def get_cache_stats():
    with _CACHE_LOCK:
        total = _CACHE_STATS["hits"] + _CACHE_STATS["misses"]
        hit_rate = (_CACHE_STATS["hits"] / total * 100) if total > 0 else 0
        return {
            "enabled": CACHE_ENABLED,
            "ttl_seconds": CACHE_TTL,
            "max_entries": CACHE_MAX_ENTRIES,
            "current_entries": len(_CACHE_STORE),
            "hits": _CACHE_STATS["hits"],
            "misses": _CACHE_STATS["misses"],
            "hit_rate": f"{hit_rate:.1f}%",
            "evictions": _CACHE_STATS["evictions"],
            "expired": _CACHE_STATS["expired"],
        }


def _cache_cleanup_loop():
    while not _SHUTTING_DOWN.is_set():
        try:
            time.sleep(300)
            if _SHUTTING_DOWN.is_set():
                break
            cache_cleanup_expired()
        except Exception as e:
            log_event(f"Cache cleanup error: {e}", "ERROR")


# ==============================================
# 🍪 EMBEDDED COOKIES (v29.2) — Chrome JSON format
# ==============================================
# Real cookies embedded directly. Startup pe auto Netscape format me convert hongi.
# Agar ye expire ho jayen → /cookie/update endpoint se hot-swap kar sakte ho.

_EMBEDDED_COOKIES_JSON = '''[
{"domain":".youtube.com","expirationDate":1829664806.972525,"hostOnly":false,"httpOnly":false,"name":"PREF","path":"/","sameSite":"unspecified","secure":true,"session":false,"storeId":"0","value":"tz=Asia.Calcutta&f6=40000000&f7=100&f5=20000"},
{"domain":".youtube.com","hostOnly":false,"httpOnly":false,"name":"wide","path":"/","sameSite":"unspecified","secure":false,"session":true,"storeId":"0","value":"0"},
{"domain":".youtube.com","expirationDate":1829660240.574859,"hostOnly":false,"httpOnly":false,"name":"SID","path":"/","sameSite":"unspecified","secure":false,"session":false,"storeId":"0","value":"g.a000Ewl_IGq4NqIDT0l4UGBodP8Z9hizVrqooF0_Bb5c5ue0K20KkFFjwJxVthbIIB5z5vRZTgACgYKAZ4SARMSFQHGX2Mi_kUD4JJHnPVMohpd8GgtnxoVAUF8yKqRn4UVFGy3LEQq1j4sIa2Y0076"},
{"domain":".youtube.com","expirationDate":1829660240.574936,"hostOnly":false,"httpOnly":true,"name":"__Secure-1PSID","path":"/","sameSite":"unspecified","secure":true,"session":false,"storeId":"0","value":"g.a000Ewl_IGq4NqIDT0l4UGBodP8Z9hizVrqooF0_Bb5c5ue0K20KeejTJGN9zctQYZnp_cxnfwACgYKATASARMSFQHGX2Mi7-n5hmsZclqiUTQLBA25dRoVAUF8yKo9x5wwvi9tq2kiR2o8mEyk0076"},
{"domain":".youtube.com","expirationDate":1829660240.57501,"hostOnly":false,"httpOnly":true,"name":"__Secure-3PSID","path":"/","sameSite":"no_restriction","secure":true,"session":false,"storeId":"0","value":"g.a000Ewl_IGq4NqIDT0l4UGBodP8Z9hizVrqooF0_Bb5c5ue0K20KP3MYj462XAhP-fKLvUH5AQACgYKAVcSARMSFQHGX2MimVIfMJeXypOgiVLVGofYrhoVAUF8yKpyuL-Ah9AEs4oDn563P07X0076"},
{"domain":".youtube.com","expirationDate":1829660240.57508,"hostOnly":false,"httpOnly":true,"name":"HSID","path":"/","sameSite":"unspecified","secure":false,"session":false,"storeId":"0","value":"AWyrpEllEsShtoE63"},
{"domain":".youtube.com","expirationDate":1829660240.575152,"hostOnly":false,"httpOnly":true,"name":"SSID","path":"/","sameSite":"unspecified","secure":true,"session":false,"storeId":"0","value":"AF-eIhpxVdnCSL0CV"},
{"domain":".youtube.com","expirationDate":1829660240.575264,"hostOnly":false,"httpOnly":false,"name":"APISID","path":"/","sameSite":"unspecified","secure":false,"session":false,"storeId":"0","value":"hid7LvudC-3O5TJi/AlxNJmeAVUcgb0lvR"},
{"domain":".youtube.com","expirationDate":1829660240.575337,"hostOnly":false,"httpOnly":false,"name":"SAPISID","path":"/","sameSite":"unspecified","secure":true,"session":false,"storeId":"0","value":"VWAKvehkS06nFE_X/A3O1ojutVe6xXB4i1"},
{"domain":".youtube.com","expirationDate":1829660240.575411,"hostOnly":false,"httpOnly":false,"name":"__Secure-1PAPISID","path":"/","sameSite":"unspecified","secure":true,"session":false,"storeId":"0","value":"VWAKvehkS06nFE_X/A3O1ojutVe6xXB4i1"},
{"domain":".youtube.com","expirationDate":1829660240.575508,"hostOnly":false,"httpOnly":false,"name":"__Secure-3PAPISID","path":"/","sameSite":"no_restriction","secure":true,"session":false,"storeId":"0","value":"VWAKvehkS06nFE_X/A3O1ojutVe6xXB4i1"},
{"domain":".youtube.com","expirationDate":1826640641.605413,"hostOnly":false,"httpOnly":true,"name":"__Secure-1PSIDTS","path":"/","sameSite":"unspecified","secure":true,"session":false,"storeId":"0","value":"sidts-CjQBnJZzamuGOSWbnfPOJoASNxh6rzK_OWJZFrIkci7DW-hOL1XThUZOhxJF0YXzG_34PvRNEAA"},
{"domain":".youtube.com","expirationDate":1826640641.605532,"hostOnly":false,"httpOnly":true,"name":"__Secure-3PSIDTS","path":"/","sameSite":"no_restriction","secure":true,"session":false,"storeId":"0","value":"sidts-CjQBnJZzamuGOSWbnfPOJoASNxh6rzK_OWJZFrIkci7DW-hOL1XThUZOhxJF0YXzG_34PvRNEAA"},
{"domain":".youtube.com","expirationDate":1829664802.728433,"hostOnly":false,"httpOnly":true,"name":"LOGIN_INFO","path":"/","sameSite":"no_restriction","secure":true,"session":false,"storeId":"0","value":"AFmmF2swRQIgMlGpVmuNwbbGiXxeUOVTG5yjKMbCzwI8cvzr6c5oBIcCIQDNaSZCxB5RUzr-LMS-u8cM9hpoxte7IwCPlhEHvRJMtA:QUQ3MjNmeFdBYnNtYkhZRjFZRE16Q2lscElmZF96ZTA0cnBieW9vMGMzRHdDRjNoVkJYdVZnV3RaT095azF4Mm1zYkNjQjg3WXlwMHY0YzdFVzluaE56RVJVN3NXWFJEOWF5ZkJiYVRacEJoejU0c3NrRE5icl9UR01PR2hMZHNQN3Fra0FlT2F4akYwTDNMUjlLUlU4cFVaTEFIRFJadXN3"},
{"domain":".youtube.com","expirationDate":1826640814.014395,"hostOnly":false,"httpOnly":false,"name":"SIDCC","path":"/","sameSite":"unspecified","secure":false,"session":false,"storeId":"0","value":"APD_SKGkE0jzeG_1HRtrtvPXZheICs89qmt2ITUsHh1l9WIKVl4AgYTeqs4F6-hBWAhmnLCjAzk"},
{"domain":".youtube.com","expirationDate":1826640814.014553,"hostOnly":false,"httpOnly":true,"name":"__Secure-1PSIDCC","path":"/","sameSite":"unspecified","secure":true,"session":false,"storeId":"0","value":"APD_SKH8fmXYtaEuH_1XaC8mnfs6uDz4VQqTS4-T6FT4bDGdbF3OYd0lJy1TxMZKLRkEM8VGHG0"},
{"domain":".youtube.com","expirationDate":1826640814.014621,"hostOnly":false,"httpOnly":true,"name":"__Secure-3PSIDCC","path":"/","sameSite":"no_restriction","secure":true,"session":false,"storeId":"0","value":"APD_SKEtj6VvfrfKDZNbHHwKJwOqHu23FX_-PJzrDQV7t9LIGLMUxKkiqQvop4JTg8OGQDcB2jw"},
{"domain":".youtube.com","hostOnly":false,"httpOnly":true,"name":"YSC","partitionKey":{"hasCrossSiteAncestor":false,"topLevelSite":"https://youtube.com"},"path":"/","sameSite":"no_restriction","secure":true,"session":true,"storeId":"0","value":"5tJCA-RsZJw"},
{"domain":".youtube.com","expirationDate":1810656809.737504,"hostOnly":false,"httpOnly":true,"name":"VISITOR_INFO1_LIVE","partitionKey":{"hasCrossSiteAncestor":false,"topLevelSite":"https://youtube.com"},"path":"/","sameSite":"no_restriction","secure":true,"session":false,"storeId":"0","value":"eHSL9jDul4c"},
{"domain":".youtube.com","expirationDate":1810656809.737613,"hostOnly":false,"httpOnly":true,"name":"VISITOR_PRIVACY_METADATA","partitionKey":{"hasCrossSiteAncestor":false,"topLevelSite":"https://youtube.com"},"path":"/","sameSite":"no_restriction","secure":true,"session":false,"storeId":"0","value":"CgJJThIEGgAgDA%3D%3D"},
{"domain":".youtube.com","expirationDate":1810655553.244503,"hostOnly":false,"httpOnly":true,"name":"__Secure-YNID","partitionKey":{"hasCrossSiteAncestor":false,"topLevelSite":"https://youtube.com"},"path":"/","sameSite":"no_restriction","secure":true,"session":false,"storeId":"0","value":"CuwBCAUSngEBDB6PDOhzj4qF4kPopMeiExCIV0KJhYWNaqbRAfZAPCDf4zcOLS6Fl1JdGXydmjx9Ji4l578RMNFLWPd0yMdiaQh7Ch1zopmb_qFr9fkY11up-QTnFSaYx0t1nsWq5LxlqxztXKb5G1AFezEHqOwz7yNBsAsd57w37fWY4X0yWgL5mortSVZ8tcWEEuP-O4B6BTGvRqwocr_Rmfk2eCgFMkUBHFj1alTftR6eOjAnFlZWqoQcQvD4pCCnxa0nK0IWIoiS4f7CUbuXK-gSOaMXkS_wCusxYFHK8bR7FlXm9jKew-8ogAE"},
{"domain":".youtube.com","expirationDate":1810655553.244625,"hostOnly":false,"httpOnly":true,"name":"__Secure-ROLLOUT_TOKEN","partitionKey":{"hasCrossSiteAncestor":false,"topLevelSite":"https://youtube.com"},"path":"/","sameSite":"no_restriction","secure":true,"session":false,"storeId":"0","value":"CKij47Kh74aeHhCa0uuouMqXAxicw6_tsZSYAw%3D%3D"}
]'''


def _cookies_json_to_netscape(json_str):
    """Convert Chrome-extension JSON cookie format → Netscape cookies.txt format."""
    try:
        data = json.loads(json_str)
    except Exception as e:
        log_event(f"❌ Embedded cookie JSON parse error: {e}", "ERROR")
        return None

    if isinstance(data, dict):
        data = data.get("cookies", [])
    if not isinstance(data, list):
        log_event("❌ Cookie JSON must be an array", "ERROR")
        return None

    lines = [
        "# Netscape HTTP Cookie File",
        "# Auto-generated by app.py from embedded Chrome JSON cookies",
        f"# Generated: {datetime.now().isoformat()}",
        "",
    ]

    count = 0
    for c in data:
        try:
            domain = str(c.get("domain", "") or "").strip()
            name = str(c.get("name", "") or "").strip()
            value = str(c.get("value", "") or "")
            if not domain or not name:
                continue
            flag = "TRUE" if domain.startswith(".") else "FALSE"
            path = str(c.get("path", "/") or "/")
            secure = "TRUE" if c.get("secure") else "FALSE"
            session = bool(c.get("session", False))
            if session or "expirationDate" not in c:
                exp = 0
            else:
                try:
                    exp = int(float(c.get("expirationDate", 0)))
                except Exception:
                    exp = 0
            lines.append(f"{domain}\t{flag}\t{path}\t{secure}\t{exp}\t{name}\t{value}")
            count += 1
        except Exception:
            continue

    if count == 0:
        log_event("❌ No valid cookies to write", "ERROR")
        return None

    log_event(f"🍪 Converted {count} cookies to Netscape format")
    return "\n".join(lines) + "\n"


def _write_embedded_cookies(tmp_path):
    """Write embedded cookies as Netscape format file."""
    netscape = _cookies_json_to_netscape(_EMBEDDED_COOKIES_JSON)
    if not netscape:
        return None
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(netscape)
        os.chmod(tmp_path, 0o644)
        return tmp_path
    except Exception as e:
        log_event(f"❌ Failed to write embedded cookies: {e}", "ERROR")
        return None


# ==============================================
# COOKIE RESOLVER (v29.2 — embedded first)
# ==============================================

COOKIE_TMP_PATH = "/tmp/yt_cookies.txt"


def resolve_cookie_file():
    # Priority 1: Embedded cookies (always works — zero config)
    if _EMBEDDED_COOKIES_JSON and _EMBEDDED_COOKIES_JSON.strip():
        result = _write_embedded_cookies(COOKIE_TMP_PATH)
        if result:
            log_event(f"✅ Embedded cookies written → {result}")
            return result

    # Priority 2: Env or file paths
    candidates = []
    if YT_COOKIE_ENV:
        candidates.append(YT_COOKIE_ENV)
    candidates.append("/etc/secrets/yt_cookies.txt")
    candidates.append("/app/yt_cookies.txt")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(script_dir, "yt_cookies.txt"))

    for path in candidates:
        if not path or not os.path.exists(path):
            continue
        try:
            shutil.copy2(path, COOKIE_TMP_PATH)
            os.chmod(COOKIE_TMP_PATH, 0o644)
            log_event(f"✅ Cookies copied: {path} → {COOKIE_TMP_PATH}")
            return COOKIE_TMP_PATH
        except Exception as e:
            log_event(f"❌ Copy failed {path}: {e}", "ERROR")
            continue

    log_event("⚠️ No cookies available", "WARN")
    return None


COOKIE_FILE = resolve_cookie_file()


# ==============================================
# 🍪 COOKIE HEALTH CHECKER
# ==============================================

_COOKIE_CRITICAL = {
    "SID", "HSID", "SSID", "APISID", "SAPISID",
    "__Secure-1PSID", "__Secure-3PSID",
    "__Secure-1PAPISID", "__Secure-3PAPISID",
    "SIDCC", "__Secure-1PSIDCC", "__Secure-3PSIDCC",
    "LOGIN_INFO",
}


def _parse_cookie_file(path):
    cookies = []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                exp_raw = parts[4].strip()
                try:
                    exp = int(exp_raw) if exp_raw.isdigit() else 0
                except Exception:
                    exp = 0
                cookies.append({
                    "domain": parts[0],
                    "path": parts[2],
                    "secure": parts[3].upper() == "TRUE",
                    "expires": exp,
                    "name": parts[5],
                    "has_value": bool(parts[6].strip()),
                })
    except Exception as e:
        return [], str(e)
    return cookies, None


def _cookie_expiry_info(expires):
    now = time.time()
    if expires <= 0:
        return {"human": "session", "expired": False, "expiring_soon": False,
                "days_left": None, "unix": 0}
    try:
        dt = datetime.fromtimestamp(expires)
        human = dt.isoformat()
    except Exception:
        human = "invalid"
    days_left = (expires - now) / 86400
    return {
        "human": human,
        "expired": expires < now,
        "expiring_soon": 0 <= days_left < 7,
        "days_left": round(days_left, 1),
        "unix": expires,
    }


def _deep_cookie_test():
    if not COOKIE_FILE or not os.path.exists(COOKIE_FILE):
        return {"passed": False, "error": "cookies_missing"}

    yt = get_yt_dlp()
    if not yt:
        return {"passed": False, "error": "ytdlp_not_loaded"}

    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    t0 = time.time()
    try:
        opts = build_opts(download=False, use_cookies=True,
                          use_proxy=False, proxy=None)
        opts["skip_download"] = True
        opts["socket_timeout"] = 15
        opts["extract_flat"] = False
        with yt.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(test_url, download=False)
        elapsed = round(time.time() - t0, 2)
        if info and info.get("id"):
            return {
                "passed": True,
                "elapsed_s": elapsed,
                "test_url": test_url,
                "video_id": info.get("id"),
                "title": (info.get("title") or "")[:80],
                "verdict": "cookies_working",
            }
        return {"passed": False, "elapsed_s": elapsed, "error": "invalid_response"}
    except Exception as e:
        err = str(e)[:400]
        elapsed = round(time.time() - t0, 2)
        verdict = "unknown_error"
        if "Sign in to confirm" in err or "bot" in err.lower():
            verdict = "bot_check_triggered"
        elif "Private video" in err:
            verdict = "private_or_region"
        elif "unavailable" in err.lower():
            verdict = "unavailable"
        elif "timed out" in err.lower() or "timeout" in err.lower():
            verdict = "network_timeout"
        return {"passed": False, "elapsed_s": elapsed,
                "error": err, "verdict": verdict}


def check_cookie_health(deep=False):
    result = {
        "status": "unknown",
        "cookies_present": False,
        "cookies_path": None,
        "cookies_writable": False,
        "cookies_size_bytes": 0,
        "total_cookies": 0,
        "critical_cookies": {},
        "critical_count": 0,
        "missing_critical": [],
        "expired_cookies": [],
        "expiring_soon": [],
        "earliest_expiry": None,
        "deep_test": None,
        "checked_at": datetime.now().isoformat(),
        "verdict": "unknown",
        "recommendation": "",
    }

    if not COOKIE_FILE or not os.path.exists(COOKIE_FILE):
        result["status"] = "missing"
        result["verdict"] = "no_cookies"
        result["recommendation"] = "Cookies file missing — embedded cookies failed to write"
        return result

    result["cookies_present"] = True
    result["cookies_path"] = COOKIE_FILE
    result["cookies_writable"] = os.access(COOKIE_FILE, os.W_OK)
    try:
        result["cookies_size_bytes"] = os.path.getsize(COOKIE_FILE)
    except Exception:
        pass

    cookies, err = _parse_cookie_file(COOKIE_FILE)
    if err:
        result["status"] = "parse_error"
        result["verdict"] = "parse_error"
        result["error"] = err
        result["recommendation"] = "Cookie file corrupt"
        return result

    result["total_cookies"] = len(cookies)
    if len(cookies) == 0:
        result["status"] = "empty"
        result["verdict"] = "empty_file"
        result["recommendation"] = "Cookie file empty"
        return result

    found_critical = set()
    earliest_exp = None

    for c in cookies:
        name = c["name"]
        exp_info = _cookie_expiry_info(c["expires"])
        is_critical = name in _COOKIE_CRITICAL

        if is_critical:
            found_critical.add(name)
            result["critical_cookies"][name] = {
                "present": True,
                "has_value": c["has_value"],
                "domain": c["domain"],
                **exp_info,
            }
            if exp_info["unix"] > 0:
                if earliest_exp is None or exp_info["unix"] < earliest_exp:
                    earliest_exp = exp_info["unix"]

        if exp_info["expired"]:
            result["expired_cookies"].append({
                "name": name,
                "expired_at": exp_info["human"],
            })
        elif exp_info["expiring_soon"]:
            result["expiring_soon"].append({
                "name": name,
                "days_left": exp_info["days_left"],
                "expires_at": exp_info["human"],
            })

    result["critical_count"] = len(found_critical)
    result["missing_critical"] = sorted(_COOKIE_CRITICAL - found_critical)
    if earliest_exp:
        result["earliest_expiry"] = _cookie_expiry_info(earliest_exp)

    if deep:
        result["deep_test"] = _deep_cookie_test()

    if result["critical_count"] == 0:
        result["status"] = "no_auth_cookies"
        result["verdict"] = "unauthenticated"
        result["recommendation"] = "No auth cookies — not logged in when exporting"
        return result

    if result["expired_cookies"]:
        result["status"] = "expired"
        result["verdict"] = "expired"
        result["recommendation"] = f"{len(result['expired_cookies'])} cookies expired — re-export"
        return result

    if deep:
        dt = result["deep_test"]
        if dt.get("passed"):
            result["status"] = "valid"
            result["verdict"] = "working"
            result["recommendation"] = "Cookies valid and working ✓"
        else:
            verdict = dt.get("verdict", "unknown")
            result["status"] = "deep_test_failed"
            result["verdict"] = verdict
            if verdict == "bot_check_triggered":
                result["recommendation"] = "Bot check — cookies stale, re-export needed"
            elif verdict == "network_timeout":
                result["recommendation"] = "Network timeout — retry"
            else:
                result["recommendation"] = f"Deep test failed: {verdict}"
    else:
        if result["expiring_soon"]:
            result["status"] = "expiring_soon"
            result["verdict"] = "expiring_soon"
            result["recommendation"] = f"{len(result['expiring_soon'])} cookies expiring soon"
        else:
            result["status"] = "likely_valid"
            result["verdict"] = "likely_valid"
            result["recommendation"] = "Cookies present. Run ?deep=true for live test"

    return result


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


def check_ffprobe():
    return shutil.which("ffprobe") is not None


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
# QUALITY CLAMPING
# ==============================================

def clamp_quality(q):
    if not q:
        return MAX_QUALITY
    q = str(q).strip().lower()
    if q == "best":
        return MAX_QUALITY
    if q not in QUALITY_ORDER:
        return "720p"
    requested_h = QUALITY_HEIGHT.get(q, 720)
    if requested_h > MAX_HEIGHT:
        return MAX_QUALITY
    return q


# ==============================================
# FILE VERIFICATION
# ==============================================

def verify_file_with_ffprobe(filepath):
    if not check_ffprobe():
        return {"ok": False, "error": "ffprobe not available"}
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=height,width,codec_name,duration",
            "-of", "json",
            filepath
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {"ok": False, "error": f"ffprobe failed: {result.stderr[:200]}"}
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if not streams:
            return {"ok": False, "error": "No video stream found"}
        s = streams[0]
        return {
            "ok": True,
            "height": int(s.get("height") or 0),
            "width": int(s.get("width") or 0),
            "vcodec": s.get("codec_name", ""),
            "duration": float(s.get("duration") or 0),
            "error": None,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def verify_download(filepath, requested_quality):
    details = {
        "path": filepath,
        "requested_quality": requested_quality,
        "max_allowed_height": MAX_HEIGHT,
    }
    if not filepath or not os.path.exists(filepath):
        return {"passed": False, "reason": "FILE_NOT_FOUND", "details": details}
    size = os.path.getsize(filepath)
    details["size_bytes"] = size
    details["size_formatted"] = fmt_size(size)
    if size <= 0:
        return {"passed": False, "reason": "EMPTY_FILE", "details": details}
    if size < SIZE_2K_MIN_BYTES:
        return {"passed": False, "reason": "FILE_TOO_SMALL_FOR_2K", "details": details}
    if size > SIZE_2K_MAX_BYTES:
        return {
            "passed": False, "reason": "FILE_TOO_LARGE_FOR_2K",
            "details": details,
            "message": f"File exceeds 2K max size.",
        }
    probe = verify_file_with_ffprobe(filepath)
    details["ffprobe"] = probe
    if not probe.get("ok"):
        details["verification_mode"] = "size_only"
        return {"passed": True, "reason": "SIZE_OK_PROBE_UNAVAILABLE", "details": details}
    height = probe.get("height", 0)
    width = probe.get("width", 0)
    details["actual_height"] = height
    details["actual_width"] = width
    details["actual_resolution"] = f"{width}x{height}"
    if height > MAX_HEIGHT:
        return {
            "passed": False, "reason": "QUALITY_EXCEEDS_2K", "details": details,
            "message": f"File is {height}p — exceeds 2K limit.",
        }
    if height < MIN_HEIGHT:
        return {
            "passed": False, "reason": "QUALITY_TOO_LOW", "details": details,
            "message": f"File is only {height}p.",
        }
    requested_h = QUALITY_HEIGHT.get(requested_quality, MAX_HEIGHT)
    if requested_h > MAX_HEIGHT:
        requested_h = MAX_HEIGHT
    details["requested_height"] = requested_h
    details["verification_mode"] = "ffprobe"
    return {"passed": True, "reason": "QUALITY_VERIFIED", "details": details}


# ==============================================
# AUTH
# ==============================================

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        g.request_id = str(uuid.uuid4())[:8]
        if _SHUTTING_DOWN.is_set():
            return jsonify({
                "status": "error", "error_code": "SHUTTING_DOWN",
                "message": "Server shutting down", "request_id": g.request_id,
            }), 503
        key = request.args.get("key", "").strip()
        if not key:
            return jsonify({
                "status": "error", "error_code": "MISSING_API_KEY",
                "message": "API key required", "request_id": g.request_id,
            }), 401
        if key not in API_KEYS:
            return jsonify({
                "status": "error", "error_code": "INVALID_API_KEY",
                "message": "Invalid API key", "request_id": g.request_id,
            }), 403
        client_ip = (request.headers.get("X-Forwarded-For", "")
                     or request.remote_addr or "unknown").split(",")[0].strip()
        allowed, retry = check_rate_limit(client_ip)
        if not allowed:
            return jsonify({
                "status": "error", "error_code": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit. Retry after {retry}s",
                "retry_after": retry, "request_id": g.request_id,
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
    return clamp_quality(q)


# ==============================================
# YT-DLP OPTS
# ==============================================

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def build_opts(download=False, quality="720p", use_cookies=True,
               use_proxy=True, proxy=None):
    quality = clamp_quality(quality)
    if quality == "best":
        fmt = f"bv*[height<={MAX_HEIGHT}]+ba/b[height<={MAX_HEIGHT}]/bv*+ba/b"
    else:
        try:
            h = min(int(str(quality).rstrip("p")), MAX_HEIGHT)
            fmt = f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
        except Exception:
            fmt = f"bv*[height<={MAX_HEIGHT}]+ba/b[height<={MAX_HEIGHT}]/bv*+ba/b"

    opts = {
        "quiet": True, "no_warnings": True, "nocheckcertificate": True,
        "geo_bypass": True, "cachedir": False, "no_color": True,
        "socket_timeout": 20, "retries": 2, "fragment_retries": 2,
        "extractor_retries": 2, "skip_unavailable_fragments": True,
        "noprogress": True, "consoletitle": False,
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
        "no_call_home": True, "call_home": False,
        "writeinfojson": False, "writethumbnail": False,
        "write_all_thumbnails": False, "writesubtitles": False,
        "writeautomaticsub": False, "writedescription": False,
        "writeannotations": False,
        "skip_download": not download,
        "extract_flat": False, "ignoreerrors": False,
        "force_generic_extractor": False, "lazy_playlist": True,
        "check_formats": False,
        "concurrent_fragment_downloads": 4,
        "format_sort": [f"res:{MAX_HEIGHT}"],
    }

    if check_deno():
        opts["js_runtimes"] = {"deno": {}}
    elif check_node():
        opts["js_runtimes"] = {"node": {}}

    if check_pot_server():
        opts["extractor_args"]["youtubepot-bgutilhttp"] = {
            "base_url": "http://127.0.0.1:4416"
        }

    if use_proxy:
        chosen = proxy or pick_proxy() or (YTDLP_PROXY or None)
        if chosen:
            opts["proxy"] = chosen

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

    attempts = []
    for _ in range(3):
        p = pick_proxy()
        if p:
            attempts.append({"label": "proxy+cookies", "cookies": True,
                             "proxy": True, "proxy_url": p})
    attempts.append({"label": "cookies_only", "cookies": True,
                     "proxy": False, "proxy_url": None})
    attempts.append({"label": "direct", "cookies": False,
                     "proxy": False, "proxy_url": None})

    errors = []
    for a in attempts:
        if _SHUTTING_DOWN.is_set():
            errors.append("shutting_down")
            break
        try:
            opts = build_opts(download=False,
                              use_cookies=a["cookies"],
                              use_proxy=a["proxy"],
                              proxy=a["proxy_url"])
            with yt.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and not info.get("_error") and info.get("id") and info.get("title"):
                    if a["proxy_url"]:
                        report_proxy_result(a["proxy_url"], True)
                    info["_verified"] = True
                    return info
                if a["proxy_url"]:
                    report_proxy_result(a["proxy_url"], False)
                errors.append(f"[{a['label']}] Invalid response")
        except Exception as e:
            if a.get("proxy_url"):
                report_proxy_result(a["proxy_url"], False)
            err_msg = str(e)[:180]
            if "Sign in to confirm" in err_msg or "bot" in err_msg.lower():
                errors.append(f"[{a['label']}] BOT_CHECK: {err_msg}")
            elif "Private video" in err_msg:
                errors.append(f"[{a['label']}] PRIVATE: {err_msg}")
            elif "unavailable" in err_msg.lower():
                errors.append(f"[{a['label']}] UNAVAILABLE: {err_msg}")
            else:
                errors.append(f"[{a['label']}] {err_msg}")
            continue

    return {"_error": "All extraction attempts failed",
            "_all_errors": errors, "_verified": False}


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
        "video": video, "duration": duration, "dates": dates,
        "engagement": engagement, "channel": channel, "metadata": metadata,
        "subtitles": subtitles, "live": live, "technical": technical,
        "extractor": extractor, "chapters": chapters,
        "chapters_count": len(chapters), "heatmap": info.get("heatmap"),
        "formats": formats, "format_count": len(formats),
    }


# ==============================================
# UPLOAD — 3 ALLOWED HOSTS
# ==============================================

def up_tmpfiles(fp):
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
    r_ = get_requests()
    t0 = time.time()
    try:
        with open(fp, "rb") as f:
            r = r_.post("https://catbox.moe/user/api.php",
                        data={"reqtype": "fileupload"},
                        files={"fileToUpload": f}, timeout=UPLOAD_TIMEOUT)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            return {"host": "catbox.moe", "url": r.text.strip(),
                    "time": round(time.time() - t0, 2), "status": "success"}
    except Exception as e:
        return {"host": "catbox.moe", "status": "failed", "error": str(e)[:150], "time": round(time.time() - t0, 2)}
    return {"host": "catbox.moe", "status": "failed", "error": "Invalid response", "time": round(time.time() - t0, 2)}


def up_litterbox(fp):
    r_ = get_requests()
    t0 = time.time()
    try:
        with open(fp, "rb") as f:
            r = r_.post("https://litterbox.catbox.moe/resources/internals/api.php",
                        data={"reqtype": "fileupload", "time": "24h"},
                        files={"fileToUpload": f}, timeout=UPLOAD_TIMEOUT)
        if r.status_code == 200 and r.text.strip().startswith("http"):
            return {"host": "litterbox.catbox.moe", "url": r.text.strip(),
                    "time": round(time.time() - t0, 2), "status": "success"}
    except Exception as e:
        return {"host": "litterbox.catbox.moe", "status": "failed", "error": str(e)[:150], "time": round(time.time() - t0, 2)}
    return {"host": "litterbox.catbox.moe", "status": "failed", "error": "Invalid response", "time": round(time.time() - t0, 2)}


UPLOAD_HOSTS = [up_tmpfiles, up_catbox, up_litterbox]


def upload_sequential(fp):
    all_attempts = []
    best = None
    for fn in UPLOAD_HOSTS:
        if _SHUTTING_DOWN.is_set():
            break
        try:
            res = fn(fp)
            all_attempts.append(res)
            if res.get("status") == "success" and not best:
                best = res
        except Exception as e:
            all_attempts.append({
                "host": fn.__name__, "status": "failed",
                "error": str(e)[:150], "time": 0
            })
            continue
    return best, all_attempts


def upload_parallel(fp, max_workers=3):
    all_attempts = []
    best = None

    def _try_upload(fn):
        try:
            return fn(fp)
        except Exception as e:
            return {"host": fn.__name__, "status": "failed",
                    "error": str(e)[:150], "time": 0}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_try_upload, fn): fn for fn in UPLOAD_HOSTS}
        for future in concurrent.futures.as_completed(futures):
            try:
                res = future.result(timeout=UPLOAD_TIMEOUT + 10)
                all_attempts.append(res)
                if res.get("status") == "success" and not best:
                    best = res
            except Exception as e:
                all_attempts.append({
                    "host": futures[future].__name__, "status": "failed",
                    "error": str(e)[:150], "time": 0
                })
    return best, all_attempts


def upload_multi(fp):
    t_start = time.time()
    all_attempts = []
    if UPLOAD_PARALLEL:
        best, attempts = upload_parallel(fp)
        all_attempts.extend(attempts)
    else:
        best = None
    if not best:
        best, seq_attempts = upload_sequential(fp)
        all_attempts.extend(seq_attempts)
    total_time = round(time.time() - t_start, 2)
    if best:
        return {
            "url": best.get("url"), "host": best.get("host"),
            "upload_time": best.get("time", total_time),
            "total_upload_time": total_time,
            "all_attempts": all_attempts, "status": "success"
        }
    return {
        "url": None, "host": None, "upload_time": total_time,
        "total_upload_time": total_time, "all_attempts": all_attempts,
        "status": "failed"
    }


# ==============================================
# PROCESS VIDEO
# ==============================================

def process_video(url, quality="720p", video_id=None):
    t_start = time.time()
    quality = clamp_quality(quality)

    cache_key = make_cache_key(video_id, quality) if video_id else None
    if cache_key:
        cached = cache_get(cache_key)
        if cached:
            cached_copy = dict(cached)
            cached_copy["cached"] = True
            cached_copy["cache_key"] = cache_key
            cached_copy["total_time"] = f"{round(time.time() - t_start, 2)}s (CACHED)"
            cached_copy["request_id"] = getattr(g, "request_id", None)
            return cached_copy

    yt = get_yt_dlp()
    if not yt:
        return {"status": "error", "error_code": "YTDLP_NOT_AVAILABLE",
                "message": "yt-dlp not loaded"}

    acquired = _DL_SEMAPHORE.acquire(timeout=30)
    if not acquired:
        return {"status": "error", "error_code": "SERVER_BUSY",
                "message": "Another download in progress",
                "total_time": f"{round(time.time() - t_start, 2)}s"}

    try:
        info = extract_info(url)

        if not info or info.get("_error") or not info.get("_verified"):
            total_time = round(time.time() - t_start, 2)
            raw_errors = info.get("_all_errors", []) if info else []
            user_message = "Video extraction failed"
            error_code = "EXTRACTION_FAILED"
            joined = " | ".join(raw_errors)
            if "BOT_CHECK" in joined or "Sign in to confirm" in joined:
                error_code = "VIDEO_AUTH_OR_PRIVATE"
                user_message = "YouTube bot detection: cookies invalid. Check /cookie/check?deep=true"
            elif "PRIVATE" in joined:
                error_code = "PRIVATE_VIDEO"
                user_message = "Video is private"
            elif "UNAVAILABLE" in joined:
                error_code = "VIDEO_UNAVAILABLE"
                user_message = "Video unavailable"

            return {
                "status": "error", "error_code": error_code,
                "message": user_message, "all_errors": raw_errors,
                "video_id": video_id, "source_url": url,
                "total_time": f"{total_time}s",
                "cookie_health": check_cookie_health(deep=False),
                "proxies": get_proxy_stats(),
                "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"},
            }

        dl_result = {"status": "pending"}
        fname = None
        t_dl = time.time()
        dl_error = None

        for attempt in range(3):
            if _SHUTTING_DOWN.is_set():
                break
            proxy = pick_proxy()
            try:
                opts = build_opts(download=True, quality=quality,
                                  use_cookies=True, proxy=proxy)
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
                    report_proxy_result(proxy, True)
                    break
                report_proxy_result(proxy, False)
                dl_error = "File not created"
                fname = None
            except Exception as ex:
                report_proxy_result(proxy, False)
                dl_error = str(ex)[:200]
                log_event(f"⚠️ DL attempt {attempt+1}/3 failed: {dl_error}", "WARN")
                fname = None
                continue

        t_dl_end = time.time()

        try:
            if fname and os.path.exists(fname):
                size = os.path.getsize(fname)
                log_event(f"🔍 Verifying file quality for 2K compliance...")
                verify = verify_download(fname, quality)

                if not verify.get("passed"):
                    dl_result = {
                        "status": "failed",
                        "error": f"Quality verification failed: {verify.get('reason')}",
                        "error_code": verify.get("reason"),
                        "message": verify.get("message", "File did not pass 2K quality check"),
                        "quality": quality, "verification": verify,
                        "filename": os.path.basename(fname),
                        "file_size": size, "file_size_formatted": fmt_size(size),
                        "download_time": f"{round(t_dl_end - t_dl, 2)}s",
                        "uploaded": False, "share_url": None, "upload_host": None,
                    }
                else:
                    log_event(f"✅ Quality verified: {verify.get('details', {}).get('actual_resolution', 'N/A')}")
                    t_up = time.time()
                    up_res = upload_multi(fname)
                    t_up_end = time.time()
                    dl_result = {
                        "status": up_res.get("status", "failed"),
                        "filename": os.path.basename(fname),
                        "file_size": size, "file_size_formatted": fmt_size(size),
                        "quality": quality,
                        "download_time": f"{round(t_dl_end - t_dl, 2)}s",
                        "upload_time": f"{round(t_up_end - t_up, 2)}s",
                        "upload_time_best_host": f"{up_res.get('upload_time', 0)}s",
                        "downloaded_at": datetime.now().isoformat(),
                        "share_url": up_res.get("url") or "UPLOAD_FAILED",
                        "upload_host": up_res.get("host") or "N/A",
                        "upload_attempts": up_res.get("all_attempts", []),
                        "total_upload_time": f"{up_res.get('total_upload_time', 0)}s",
                        "verification": verify,
                        "uploaded": up_res.get("status") == "success",
                    }
            else:
                dl_result = {
                    "status": "failed",
                    "error": dl_error or "File not found after download",
                    "error_code": "DOWNLOAD_FAILED",
                    "quality": quality, "uploaded": False,
                    "proxies_tried": 3,
                }
        except Exception as ex:
            dl_result = {
                "status": "failed", "error": str(ex)[:200],
                "error_code": type(ex).__name__, "quality": quality,
                "uploaded": False,
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
            return {"status": "error", "error_code": "BUILD_FAILED",
                    "message": "Failed to build info",
                    "download": dl_result, "total_time": f"{total_time}s"}

        result = {
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
            "video_id": video_id, "cached": False,
            "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"},
        }

        if cache_key and dl_result.get("status") == "success":
            cache_set(cache_key, result)

        return result
    finally:
        _DL_SEMAPHORE.release()


# ==============================================
# ROUTES
# ==============================================

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        "service": "🎬 YouTube Downloader API",
        "version": "29.2.0",
        "rules": {"max_quality": MAX_QUALITY, "max_height": MAX_HEIGHT},
        "features": {
            "embedded_cookies": bool(_EMBEDDED_COOKIES_JSON.strip()),
            "cache_system": CACHE_ENABLED,
            "cache_ttl_seconds": CACHE_TTL,
            "quality_verification": True,
            "multi_proxy_rotation": len(PROXY_POOL),
            "cookie_health_checker": True,
            "upload_hosts": ["tmpfiles.org", "catbox.moe", "litterbox.catbox.moe"],
        },
        "qualities": ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p"],
        "endpoints": {
            "/yt": "Download YouTube video (max 2K)",
            "/cookie/check": "Real-time cookie health (?deep=true for yt-dlp test)",
            "/cookie/update": "Hot-swap cookies (POST JSON or Netscape)",
            "/proxy/stats": "Proxy rotation status",
            "/health": "Health check",
            "/cache/stats": "Cache statistics",
            "/cache/clear": "Clear cache (admin)",
        },
        "credit": {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
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
        "cache": get_cache_stats(),
        "proxies": get_proxy_stats(),
        "cookies_embedded": bool(_EMBEDDED_COOKIES_JSON.strip()),
        "cookies_file": COOKIE_FILE,
    }), 200


@app.route('/ready', methods=['GET', 'HEAD'])
def ready():
    yt_ok = False
    try:
        yt_ok = get_yt_dlp() is not None
    except Exception:
        pass
    ffmpeg_ok = check_ffmpeg()
    return jsonify({
        "status": "ready" if (yt_ok and ffmpeg_ok) else "not_ready",
        "yt_dlp": yt_ok, "ffmpeg": ffmpeg_ok,
        "ffprobe": check_ffprobe(), "pot_server": check_pot_server(),
        "cookies": bool(COOKIE_FILE and os.path.exists(COOKIE_FILE)),
        "cookies_path": COOKIE_FILE,
        "deno": check_deno(), "node": check_node(),
        "proxies": get_proxy_stats(),
        "max_quality": MAX_QUALITY, "max_height": MAX_HEIGHT,
        "cache": get_cache_stats(),
        "timestamp": datetime.now().isoformat(),
    }), 200 if (yt_ok and ffmpeg_ok) else 503


# ==============================================
# 🍪 COOKIE CHECK ROUTE
# ==============================================

@app.route('/cookie/check', methods=['GET', 'POST'])
def cookie_check_route():
    deep = request.args.get("deep", "false").lower() == "true"
    request_id = str(uuid.uuid4())[:8]

    if deep:
        key = request.args.get("key", "").strip()
        if not key:
            return jsonify({
                "status": "error", "error_code": "MISSING_API_KEY",
                "message": "API key required for deep=true",
                "hint": "Use ?deep=false for shallow check without key",
                "request_id": request_id,
            }), 401
        if key not in API_KEYS:
            return jsonify({
                "status": "error", "error_code": "INVALID_API_KEY",
                "message": "Invalid API key", "request_id": request_id,
            }), 403
        client_ip = (request.headers.get("X-Forwarded-For", "")
                     or request.remote_addr or "unknown").split(",")[0].strip()
        allowed, retry = check_rate_limit(client_ip)
        if not allowed:
            return jsonify({
                "status": "error", "error_code": "RATE_LIMIT_EXCEEDED",
                "message": f"Rate limit. Retry after {retry}s",
                "retry_after": retry, "request_id": request_id,
            }), 429

    try:
        result = check_cookie_health(deep=deep)
        result["request_id"] = request_id
        result["deep_check"] = deep
        result["embedded"] = bool(_EMBEDDED_COOKIES_JSON.strip())
        result["credit"] = {"username": "@KINGFFAIAK47x", "made_by": "ANSH AFT"}
        return jsonify(result), 200
    except Exception as e:
        return jsonify({
            "status": "error", "error_code": "COOKIE_CHECK_FAILED",
            "message": str(e)[:300],
            "traceback": traceback.format_exc()[:800],
            "request_id": request_id,
        }), 500


# ==============================================
# 🍪 COOKIE UPDATE ROUTE (v29.2 — hot swap)
# ==============================================

@app.route('/cookie/update', methods=['POST'])
@require_api_key
def cookie_update_route():
    """
    Hot-swap cookies without redeploy.
    
    POST body (JSON):
      {"cookies": [ ...Chrome JSON array... ]}
      OR
      {"cookies": "<raw Netscape string>"}
    
    Accepts:
      - Chrome extension export JSON (array of objects)
      - Or raw Netscape cookies.txt format
    """
    try:
        body = request.get_json(silent=True) or {}
        cookies_input = body.get("cookies")

        if not cookies_input:
            return jsonify({
                "status": "error", "message": "cookies field required",
                "request_id": getattr(g, "request_id", None),
            }), 400

        netscape = None

        if isinstance(cookies_input, list):
            netscape = _cookies_json_to_netscape(json.dumps(cookies_input))
        elif isinstance(cookies_input, str):
            stripped = cookies_input.strip()
            if stripped.startswith("["):
                netscape = _cookies_json_to_netscape(stripped)
            elif "\t" in stripped:
                netscape = stripped if stripped.endswith("\n") else stripped + "\n"
            else:
                return jsonify({
                    "status": "error",
                    "message": "cookies string must be JSON array or Netscape format",
                }), 400
        else:
            return jsonify({
                "status": "error",
                "message": "cookies must be list or string",
            }), 400

        if not netscape:
            return jsonify({
                "status": "error",
                "message": "conversion failed — check cookie format",
            }), 400

        global COOKIE_FILE
        with open(COOKIE_TMP_PATH, "w", encoding="utf-8") as f:
            f.write(netscape)
        os.chmod(COOKIE_TMP_PATH, 0o644)
        COOKIE_FILE = COOKIE_TMP_PATH

        log_event(f"🍪 Cookies hot-swapped: {os.path.getsize(COOKIE_TMP_PATH)} bytes")

        return jsonify({
            "status": "ok",
            "message": "Cookies updated successfully",
            "path": COOKIE_FILE,
            "size_bytes": os.path.getsize(COOKIE_TMP_PATH),
            "health": check_cookie_health(deep=False),
            "request_id": getattr(g, "request_id", None),
        }), 200
    except Exception as e:
        return jsonify({
            "status": "error", "error_code": "COOKIE_UPDATE_FAILED",
            "message": str(e)[:300],
            "request_id": getattr(g, "request_id", None),
        }), 500


# ==============================================
# 🔁 PROXY STATS
# ==============================================

@app.route('/proxy/stats', methods=['GET'])
def proxy_stats_route():
    return jsonify({
        "status": "ok",
        "proxies": get_proxy_stats(),
        "timestamp": datetime.now().isoformat(),
    }), 200


# ==============================================
# 💾 CACHE ROUTES
# ==============================================

@app.route('/cache/stats', methods=['GET'])
def cache_stats_route():
    return jsonify({
        "status": "ok",
        "cache": get_cache_stats(),
        "timestamp": datetime.now().isoformat(),
    }), 200


@app.route('/cache/clear', methods=['GET', 'POST'])
@require_api_key
def cache_clear_route():
    cache_key = request.args.get("key", "").strip()
    if cache_key:
        ok = cache_invalidate(cache_key)
        return jsonify({
            "status": "ok" if ok else "not_found",
            "message": f"Cache key {'cleared' if ok else 'not found'}: {cache_key}",
            "cache_key": cache_key,
        }), 200 if ok else 404
    count = cache_invalidate()
    return jsonify({
        "status": "ok",
        "message": f"Cache cleared: {count} entries removed",
        "cleared_count": count,
    }), 200


# ==============================================
# 🎬 YT DOWNLOAD
# ==============================================

@app.route('/yt', methods=['GET'])
@require_api_key
def download_yt():
    try:
        url_raw = request.args.get("url", "").strip()
        quality = request.args.get("quality", "720p").strip()
        no_cache = request.args.get("no_cache", "false").lower() == "true"

        if not url_raw:
            return jsonify({
                "status": "error", "error_code": "MISSING_URL",
                "message": "URL required",
                "request_id": getattr(g, "request_id", None),
            }), 400

        ok, result = validate_youtube_url(url_raw)
        if not ok:
            return jsonify({
                "status": "error", "error_code": "INVALID_URL",
                "message": result,
                "request_id": getattr(g, "request_id", None),
            }), 400

        video_id = result
        url = f"https://www.youtube.com/watch?v={video_id}"
        quality = clamp_quality(quality)

        if no_cache:
            cache_key = make_cache_key(video_id, quality)
            cache_invalidate(cache_key)

        data = process_video(url, quality, video_id=video_id)
        data["request_id"] = getattr(g, "request_id", None)
        data["max_quality_enforced"] = MAX_QUALITY

        if data.get("status") in ("success", "partial"):
            return jsonify(data), 200
        return jsonify(data), 400
    except Exception as e:
        return jsonify({
            "status": "error", "error_code": "PROCESS_ERROR",
            "message": str(e)[:300],
            "request_id": getattr(g, "request_id", None),
        }), 500


# ==============================================
# DEBUG
# ==============================================

@app.route('/debug', methods=['GET', 'HEAD'])
@require_api_key
def debug():
    return jsonify({
        "status": "ok", "version": "29.2.0",
        "started_at": _STARTUP_TIME,
        "now": datetime.now().isoformat(),
        "pid": os.getpid(),
        "rules": {
            "max_quality": MAX_QUALITY, "max_height": MAX_HEIGHT,
            "allowed_hosts": ["tmpfiles.org", "catbox.moe", "litterbox.catbox.moe"],
            "quality_verification": "ENABLED",
        },
        "cache": get_cache_stats(),
        "proxies": get_proxy_stats(),
        "cookie_health": check_cookie_health(deep=False),
        "system": {
            "yt_dlp": True, "deno": check_deno(), "node": check_node(),
            "ffmpeg": check_ffmpeg(), "ffprobe": check_ffprobe(),
            "pot_server": check_pot_server(),
            "cookies_embedded": bool(_EMBEDDED_COOKIES_JSON.strip()),
            "cookies_exists": bool(COOKIE_FILE and os.path.exists(COOKIE_FILE)),
            "cookies_path": COOKIE_FILE,
        },
        "threads": {"active": threading.active_count()},
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
        "status": "error", "error_code": "UNHANDLED_EXCEPTION",
        "message": str(e)[:300],
    }), 500


# ==============================================
# STARTUP
# ==============================================

log_event("=" * 60)
log_event("YouTube Downloader API v29.2 STARTED")
log_event(f"Rules: MAX_QUALITY={MAX_QUALITY}, MAX_HEIGHT={MAX_HEIGHT}")
log_event(f"Proxies loaded: {len(PROXY_POOL)}")
log_event(f"Embedded cookies: {'YES' if _EMBEDDED_COOKIES_JSON.strip() else 'NO'}")
log_event(f"Cookie file: {COOKIE_FILE}")
log_event(f"Cache: {'ON' if CACHE_ENABLED else 'OFF'} (TTL={CACHE_TTL}s)")
log_event(f"Deno: {check_deno()}, Node: {check_node()}, FFmpeg: {check_ffmpeg()}, ffprobe: {check_ffprobe()}")
log_event("=" * 60)

_cache_cleanup_thread = threading.Thread(target=_cache_cleanup_loop, daemon=True)
_cache_cleanup_thread.start()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
