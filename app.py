#!/usr/bin/env python3
# ============================================================
# ULTIMATE YOUTUBE API - FULLY FIXED
# HEADER + QUERY PARAM BOTH SUPPORTED
# VERSION: 18.0 FIXED
# ============================================================

import os
import sys
import json
import base64
import time
import random
import uuid
import shutil
import traceback
from datetime import datetime, timedelta
from urllib.parse import urlparse
from functools import wraps

from flask import Flask, jsonify, request, send_file
import yt_dlp

app = Flask(__name__)

# ============================================================
# CONFIGURATION - HARDCODED
# ============================================================
API_KEY = "ANSHZKXXMP"
SCRAPERAPI_KEY = "9c72d7d42c359e777211cf0b91ff0da2"
OWNER = "ANSH AFT"
VERSION = "18.0 FIXED"

# ScraperAPI Proxy
PROXY_URL = f"http://scraperapi:{SCRAPERAPI_KEY}@proxy-server.scraperapi.com:8001"

# YouTube Cookies (base64)
YOUTUBE_COOKIES_B64 = "IyBIVFRQIENvb2tpZSBGaWxlCiMgTmV0c2NhcGUgSFRUUCBDb29raWUgRmlsZQouZ29vZ2xlLmNvbQlUUklVCQkvCUZBTFNFCTE3OTM1NDQwMDAJLkFQSVMJRFRZUXY0b3hjbVhMaW02TS9BOF8yQ3RsZ0NJYnRFVGN0YwouZ29vZ2xlLmNvbQlUUklVCQkvCUZBTFNFCTE3OTM1NDQwMDAJLl9TZWN1cmUtMVBBUElTSUQJZ2EwMDBEQWxfSUlPcWVGcExtSzhROUQ1eGloeEs2YTJlMWxCdEdsOWhTYjBvTnNjLTNfN19ZTkNsUnVWR2hIeGtmd0psSTl1Y21RQUNnWUtBWUVTQVJNU0ZRSkdYMk1pRDFRLURqNzlfMlVJTkt0SjhLcGdyQm9WQVVGOHlLcGZjZXhhdGtoalpxMjJuUU50Vk9DcTAwNzYKLnlvdXR1YmUuY29tCVRSVUUJLwkRQUxTRQkxNzkzNTQ0MDAwCS5fU2VjdXJlLTFQU0lECWdhMDAwREFsX0lJT3FlRnBMbUs4UTlENXhpaHhLNmEyZTFNQnRHbDloU2Iwb05zYy0zXzdfWU5DbFJ1VkdoSHhrZndKbEk5dWNtUUFDUW9HQVlFU0FSTVNGUUhHWDJNaUQxUS1Eajc5XzJ1SU5LdEo4S3BnckJvVkFVRjh5S3BmY2V4YXRraGpacTIyblFOdFZPQ3EwMDc2Ci55b3V0dWJlLmNvbQlUUklVCQkvCUZBTFNFCTE3OTM1NDQwMDAJLl9TZWN1cmUtMVBTSUNDCUFLOGFUalZhbk1fd2x2dTB2M0s2TkQ2Ym1IajJWVEhMeldmeTFsbTFPRXI4dGRPQ0UtaWg2N2t6Sk1aVjV6bGlKWjdubnhoUQouZ29vZ2xlLmNvbQlUUklVCQkvCUZBTFNFCTE3OTM1NDQwMDAJLl9TZWN1cmUtMVBTSUNDCUFLOGFUalhrTEpXNHJmYTJMU3c5S0RwRlY4LXQ3N09ZNFQ1UHctdUZBNy1xSVZjYlZYdXFjd3RZOUNpRmtxaENXeFlqYXUtbTBB"

# Download directory
DOWNLOAD_DIR = "/tmp/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

DOWNLOAD_STORE = {}
RATE_LIMIT_STORE = {}
RATE_LIMIT_SECONDS = 5
RATE_LIMIT_MAX_REQUESTS = 10


# ============================================================
# FFMPEG CHECK
# ============================================================
def check_ffmpeg():
    return shutil.which("ffmpeg") is not None


# ============================================================
# COOKIES
# ============================================================
def get_cookies_file():
    if not YOUTUBE_COOKIES_B64:
        return None
    try:
        cookies_data = base64.b64decode(YOUTUBE_COOKIES_B64)
        cookies_path = '/tmp/youtube_cookies.txt'
        with open(cookies_path, 'wb') as f:
            f.write(cookies_data)
        return cookies_path
    except Exception:
        return None


# ============================================================
# URL VALIDATION
# ============================================================
def is_youtube_url(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        valid_hosts = {
            "youtube.com", "www.youtube.com", "m.youtube.com",
            "music.youtube.com", "youtu.be", "www.youtu.be",
        }
        return host in valid_hosts
    except Exception:
        return False


# ============================================================
# RATE LIMITING
# ============================================================
def check_rate_limit(client_ip):
    now = time.time()
    if client_ip not in RATE_LIMIT_STORE:
        RATE_LIMIT_STORE[client_ip] = []
    RATE_LIMIT_STORE[client_ip] = [
        t for t in RATE_LIMIT_STORE[client_ip]
        if now - t < RATE_LIMIT_SECONDS
    ]
    if len(RATE_LIMIT_STORE[client_ip]) >= RATE_LIMIT_MAX_REQUESTS:
        return False
    RATE_LIMIT_STORE[client_ip].append(now)
    return True


# ============================================================
# EXPIRY
# ============================================================
def is_expired(expires_at):
    try:
        return datetime.now() >= datetime.fromisoformat(expires_at)
    except Exception:
        return True


# ============================================================
# YT-DLP OPTIONS
# ============================================================
def build_ydl_opts(download=False, format_type=None, quality=None, output_template=None):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "cachedir": False,
        "no_color": True,
        "socket_timeout": 60,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
    }
    
    if PROXY_URL:
        opts["proxy"] = PROXY_URL
    
    cookies_file = get_cookies_file()
    if cookies_file:
        opts["cookiefile"] = cookies_file
    
    if download:
        opts["outtmpl"] = output_template
        
        if format_type == "mp3":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }]
        else:
            if quality == "best":
                opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
            else:
                height = int(quality.rstrip("p"))
                opts["format"] = f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}][ext=mp4]/best"
            opts["merge_output_format"] = "mp4"
    else:
        opts["skip_download"] = True
    
    return opts


# ============================================================
# HELPERS
# ============================================================
def format_filesize(size):
    if not size:
        return "N/A"
    if size > 1024 * 1024 * 1024:
        return f"{size / (1024**3):.2f} GB"
    elif size > 1024 * 1024:
        return f"{size / (1024**2):.1f} MB"
    elif size > 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def format_duration(seconds):
    if not seconds:
        return "0:00"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_date(date_str):
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y%m%d")
        return dt.strftime("%d %B %Y")
    except Exception:
        return date_str


def format_number(num):
    if not num:
        return None
    if num >= 1000000000:
        return f"{num / 1000000000:.2f}B"
    elif num >= 1000000:
        return f"{num / 1000000:.2f}M"
    elif num >= 1000:
        return f"{num / 1000:.2f}K"
    return str(num)


# ============================================================
# API KEY DECORATOR - HEADER + QUERY PARAM + JSON BODY
# ============================================================
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = None
        
        # 1. Header se
        api_key = request.headers.get("X-API-Key")
        
        # 2. Query parameter se
        if not api_key:
            api_key = request.args.get("api_key")
        
        # 3. JSON body se
        if not api_key and request.is_json:
            try:
                data = request.get_json(silent=True)
                if data:
                    api_key = data.get("api_key")
            except Exception:
                pass
        
        if not api_key:
            return jsonify({
                "status": "error",
                "code": 401,
                "message": "API key required",
                "hint": "Use header X-API-Key OR query param ?api_key=YOUR_KEY"
            }), 401
        
        if api_key != API_KEY:
            return jsonify({
                "status": "error",
                "code": 403,
                "message": "Invalid API key"
            }), 403
        
        return f(*args, **kwargs)
    return decorated


# ============================================================
# CHANNEL MAX INFO
# ============================================================
def get_channel_max_info(info):
    entries = list(info.get("entries", []) or [])
    
    videos = []
    total_duration = 0
    total_views = 0
    total_likes = 0
    total_comments = 0
    
    for entry in entries[:200]:
        if not entry:
            continue
        
        duration = entry.get("duration") or 0
        views = entry.get("view_count") or 0
        likes = entry.get("like_count") or 0
        comments = entry.get("comment_count") or 0
        
        total_duration += duration
        total_views += views
        total_likes += likes
        total_comments += comments
        
        video_id = entry.get("id")
        
        videos.append({
            "id": video_id,
            "title": entry.get("title"),
            "fulltitle": entry.get("fulltitle"),
            "url": entry.get("url") or f"https://youtu.be/{video_id}",
            "short_url": f"https://youtu.be/{video_id}",
            "embed_url": f"https://www.youtube.com/embed/{video_id}",
            "duration": format_duration(duration),
            "duration_seconds": duration,
            "view_count": views,
            "view_count_formatted": format_number(views),
            "like_count": likes,
            "like_count_formatted": format_number(likes),
            "comment_count": comments,
            "comment_count_formatted": format_number(comments),
            "thumbnail": entry.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
            "thumbnail_hd": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
            "upload_date": format_date(entry.get("upload_date")),
            "upload_date_raw": entry.get("upload_date"),
            "description": entry.get("description"),
            "description_length": len(entry.get("description", "") or ""),
            "is_live": entry.get("is_live"),
            "was_live": entry.get("was_live"),
            "categories": entry.get("categories", []),
            "tags": entry.get("tags", []),
            "ext": entry.get("ext"),
            "width": entry.get("width"),
            "height": entry.get("height"),
            "fps": entry.get("fps"),
            "vcodec": entry.get("vcodec"),
            "acodec": entry.get("acodec"),
            "playlist_index": entry.get("playlist_index"),
        })
    
    latest = sorted(videos, key=lambda x: x.get("upload_date_raw") or "", reverse=True)[:20]
    popular = sorted(videos, key=lambda x: x.get("view_count", 0), reverse=True)[:20]
    oldest = sorted(videos, key=lambda x: x.get("upload_date_raw") or "")[:20]
    
    return {
        "status": "success",
        "type": "channel",
        "timestamp": datetime.now().isoformat(),
        "api_version": VERSION,
        "owner": OWNER,
        
        "channel": {
            "name": info.get("channel") or info.get("uploader") or info.get("title"),
            "handle": info.get("uploader_id"),
            "id": info.get("channel_id") or info.get("id"),
            "url": info.get("channel_url") or info.get("webpage_url"),
            "description": info.get("description"),
            "description_length": len(info.get("description", "") or ""),
            "description_preview": (info.get("description", "") or "")[:1000],
            "subscriber_count": info.get("channel_follower_count"),
            "subscriber_count_formatted": format_number(info.get("channel_follower_count")),
            "thumbnail": info.get("thumbnail"),
            "thumbnails": info.get("thumbnails", []),
        },
        
        "statistics": {
            "total_videos": len(videos),
            "total_duration_seconds": total_duration,
            "total_duration_formatted": format_duration(total_duration),
            "total_duration_hours": round(total_duration / 3600, 2),
            "total_views": total_views,
            "total_views_formatted": format_number(total_views),
            "total_likes": total_likes,
            "total_likes_formatted": format_number(total_likes),
            "total_comments": total_comments,
            "total_comments_formatted": format_number(total_comments),
            "average_views_per_video": total_views // len(videos) if videos else 0,
            "average_views_per_video_formatted": format_number(total_views // len(videos)) if videos else "0",
            "average_duration_seconds": total_duration // len(videos) if videos else 0,
            "average_duration_formatted": format_duration(total_duration // len(videos)) if videos else "0:00",
        },
        
        "sections": {
            "latest": latest,
            "popular": popular,
            "oldest": oldest,
        },
        
        "videos_returned": len(videos),
        "videos_limit": 200,
        "videos": videos,
        
        "summary": {
            "channel_name": info.get("channel") or info.get("uploader") or info.get("title"),
            "handle": info.get("uploader_id"),
            "subscribers": format_number(info.get("channel_follower_count")),
            "subscribers_raw": info.get("channel_follower_count"),
            "total_videos": len(videos),
            "total_views": format_number(total_views),
            "total_duration": format_duration(total_duration),
            "thumbnail": info.get("thumbnail"),
            "url": info.get("channel_url") or info.get("webpage_url"),
            "description": (info.get("description", "") or "")[:300],
        }
    }


# ============================================================
# VIDEO MAX INFO + DOWNLOAD
# ============================================================
def get_video_max_info(info, url, download=False, quality="1080p", format_type="mp4"):
    duration = info.get("duration") or 0
    video_id = info.get("id")
    view_count = info.get("view_count") or 0
    like_count = info.get("like_count") or 0
    comment_count = info.get("comment_count") or 0
    
    result = {
        "status": "success",
        "type": "video",
        "timestamp": datetime.now().isoformat(),
        "api_version": VERSION,
        "owner": OWNER,
        
        "video": {
            "id": video_id,
            "title": info.get("title"),
            "fulltitle": info.get("fulltitle"),
            "url": info.get("webpage_url"),
            "short_url": f"https://youtu.be/{video_id}",
            "embed_url": f"https://www.youtube.com/embed/{video_id}",
            "description": info.get("description"),
            "description_length": len(info.get("description", "") or ""),
            "description_preview": (info.get("description", "") or "")[:1000],
            "thumbnail": info.get("thumbnail"),
            "thumbnail_hd": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
            "thumbnail_sd": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "thumbnails": info.get("thumbnails", []),
        },
        
        "duration": {
            "seconds": duration,
            "string": info.get("duration_string"),
            "formatted": format_duration(duration),
            "minutes": duration // 60,
            "hours": duration // 3600,
        },
        
        "dates": {
            "upload_date": info.get("upload_date"),
            "upload_date_formatted": format_date(info.get("upload_date")),
            "release_date": info.get("release_date"),
            "modified_date": info.get("modified_date"),
            "timestamp": info.get("timestamp"),
        },
        
        "engagement": {
            "view_count": view_count,
            "view_count_formatted": format_number(view_count),
            "like_count": like_count,
            "like_count_formatted": format_number(like_count),
            "dislike_count": info.get("dislike_count"),
            "comment_count": comment_count,
            "comment_count_formatted": format_number(comment_count),
            "repost_count": info.get("repost_count"),
            "average_rating": info.get("average_rating"),
        },
        
        "channel": {
            "name": info.get("channel"),
            "id": info.get("channel_id"),
            "url": info.get("channel_url"),
            "uploader": info.get("uploader"),
            "uploader_id": info.get("uploader_id"),
            "uploader_url": info.get("uploader_url"),
            "follower_count": info.get("channel_follower_count"),
            "follower_count_formatted": format_number(info.get("channel_follower_count")),
        },
        
        "metadata": {
            "categories": info.get("categories", []),
            "tags": info.get("tags", []),
            "tags_count": len(info.get("tags", [])),
            "genre": info.get("genre"),
            "language": info.get("language"),
            "age_limit": info.get("age_limit"),
            "is_family_friendly": info.get("is_family_friendly"),
            "availability": info.get("availability"),
            "location": info.get("location"),
        },
        
        "subtitles": {
            "manual": list(info.get("subtitles", {}).keys()),
            "automatic": list(info.get("automatic_captions", {}).keys()),
            "total_manual": len(info.get("subtitles", {})),
            "total_auto": len(info.get("automatic_captions", {})),
        },
        
        "live": {
            "is_live": info.get("is_live"),
            "was_live": info.get("was_live"),
            "live_status": info.get("live_status"),
        },
        
        "technical": {
            "ext": info.get("ext"),
            "format": info.get("format"),
            "format_id": info.get("format_id"),
            "format_note": info.get("format_note"),
            "width": info.get("width"),
            "height": info.get("height"),
            "fps": info.get("fps"),
            "vcodec": info.get("vcodec"),
            "acodec": info.get("acodec"),
            "filesize": info.get("filesize"),
            "filesize_formatted": format_filesize(info.get("filesize")),
            "audio_channels": info.get("audio_channels"),
            "audio_bitrate": info.get("audio_bitrate"),
            "video_bitrate": info.get("video_bitrate"),
            "total_bitrate": info.get("tbr"),
        },
        
        "extractor": {
            "name": info.get("extractor"),
            "key": info.get("extractor_key"),
            "domain": info.get("webpage_url_domain"),
        },
        
        "chapters": info.get("chapters", []),
        "chapters_count": len(info.get("chapters", [])),
        
        "heatmap": info.get("heatmap"),
        
        "formats": [],
        "format_count": len(info.get("formats", [])),
        
        "summary": {
            "title": info.get("title"),
            "channel": info.get("channel"),
            "duration": format_duration(duration),
            "views": view_count,
            "views_formatted": format_number(view_count),
            "likes": like_count,
            "likes_formatted": format_number(like_count),
            "comments": comment_count,
            "comments_formatted": format_number(comment_count),
            "upload_date": format_date(info.get("upload_date")),
            "thumbnail": info.get("thumbnail"),
            "short_url": f"https://youtu.be/{video_id}",
            "formats_count": len(info.get("formats", [])),
        }
    }
    
    for f in info.get("formats", []):
        filesize = f.get("filesize") or f.get("filesize_approx")
        result["formats"].append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "resolution": f.get("resolution"),
            "width": f.get("width"),
            "height": f.get("height"),
            "fps": f.get("fps"),
            "vcodec": f.get("vcodec"),
            "acodec": f.get("acodec"),
            "filesize": filesize,
            "filesize_formatted": format_filesize(filesize),
            "tbr": f.get("tbr"),
            "abr": f.get("abr"),
            "vbr": f.get("vbr"),
            "audio_channels": f.get("audio_channels"),
            "format_note": f.get("format_note"),
            "quality": f.get("quality"),
            "has_video": f.get("vcodec") != "none",
            "has_audio": f.get("acodec") != "none",
            "protocol": f.get("protocol"),
        })
    
    if download:
        download_result = download_and_convert(url, quality, format_type)
        if download_result.get("status") == "success":
            result["download"] = download_result["download"]
        else:
            result["download"] = download_result
    
    return result


# ============================================================
# DOWNLOAD + CONVERT
# ============================================================
def download_and_convert(url, quality="1080p", format_type="mp4"):
    if not check_ffmpeg():
        return {
            "status": "error",
            "error": "FFmpeg is not installed on the server",
            "solution": "Install FFmpeg: apt install ffmpeg"
        }
    
    download_id = str(uuid.uuid4())[:12]
    output_template = os.path.join(DOWNLOAD_DIR, f"{download_id}_%(title)s.%(ext)s")
    
    time.sleep(random.uniform(2, 5))
    
    opts = build_ydl_opts(
        download=True,
        format_type=format_type,
        quality=quality,
        output_template=output_template
    )
    
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            title = info.get("title", "video")
            duration = info.get("duration") or 0
            video_id = info.get("id")
            view_count = info.get("view_count") or 0
            like_count = info.get("like_count") or 0
            
            filename = ydl.prepare_filename(info)
            if format_type == "mp3":
                filename = os.path.splitext(filename)[0] + ".mp3"
            else:
                filename = os.path.splitext(filename)[0] + ".mp4"
            
            actual_file = None
            for f in os.listdir(DOWNLOAD_DIR):
                if f.startswith(download_id):
                    actual_file = os.path.join(DOWNLOAD_DIR, f)
                    break
            
            if not actual_file or not os.path.exists(actual_file):
                actual_file = filename
            
            if os.path.exists(actual_file):
                file_size = os.path.getsize(actual_file)
                expires_at = (datetime.now() + timedelta(hours=1)).isoformat()
                
                download_info = {
                    "download_id": download_id,
                    "title": title,
                    "filename": os.path.basename(actual_file),
                    "file_size": file_size,
                    "file_size_formatted": format_filesize(file_size),
                    "quality": quality,
                    "format": format_type,
                    "duration": format_duration(duration),
                    "created_at": datetime.now().isoformat(),
                    "expires_at": expires_at,
                    "download_url": f"/download/{download_id}",
                    "direct_link": f"https://youtube-info-ivory.vercel.app/download/{download_id}",
                    "video_info": {
                        "id": video_id,
                        "title": title,
                        "channel": info.get("channel"),
                        "views": view_count,
                        "views_formatted": format_number(view_count),
                        "likes": like_count,
                        "likes_formatted": format_number(like_count),
                        "thumbnail": info.get("thumbnail"),
                        "short_url": f"https://youtu.be/{video_id}",
                    }
                }
                
                DOWNLOAD_STORE[download_id] = {**download_info, "file_path": actual_file}
                return {"status": "success", "download": download_info}
            
            return {"status": "error", "error": "File not found after download"}
            
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ============================================================
# SINGLE ENDPOINT
# ============================================================
@app.route('/youtube', methods=['GET', 'POST'])
@require_api_key
def youtube_single_endpoint():
    try:
        client_ip = request.remote_addr or 'unknown'
        if not check_rate_limit(client_ip):
            return jsonify({
                "status": "error",
                "code": 429,
                "message": "Rate limit exceeded. Wait 5 seconds."
            }), 429
        
        if request.method == 'POST' and request.is_json:
            data = request.get_json()
            url = data.get('url')
            download = str(data.get('download', 'false')).lower() == 'true'
            quality = data.get('quality', '1080p')
            format_type = data.get('format', 'mp4')
        else:
            url = request.args.get('url')
            download = request.args.get('download', 'false').lower() == 'true'
            quality = request.args.get('quality', '1080p')
            format_type = request.args.get('format', 'mp4')
        
        if not url:
            return jsonify({
                "status": "error",
                "message": "URL required",
                "usage": {
                    "video": "/youtube?url=https://youtu.be/VIDEO_ID&api_key=ANSHZKXXMP",
                    "video_download": "/youtube?url=https://youtu.be/VIDEO_ID&download=true&quality=1080p&format=mp4&api_key=ANSHZKXXMP",
                    "channel": "/youtube?url=https://www.youtube.com/@klocuchy&api_key=ANSHZKXXMP"
                }
            }), 400
        
        if not is_youtube_url(url):
            return jsonify({
                "status": "error",
                "message": "Invalid YouTube URL"
            }), 400
        
        if quality not in ["best", "1080p", "720p", "480p", "360p", "240p"]:
            quality = "1080p"
        
        if format_type not in ["mp4", "mp3"]:
            format_type = "mp4"
        
        opts = build_ydl_opts(download=False)
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return jsonify({"status": "error", "error": "No info found"}), 404
            
            if info.get("_type") == "playlist":
                return jsonify(get_channel_max_info(info))
            
            return jsonify(get_video_max_info(info, url, download, quality, format_type))
        
    except yt_dlp.utils.DownloadError as e:
        app.logger.exception("YouTube extraction failed")
        error_msg = str(e)
        
        if "rate-limited" in error_msg or "This content isn't available" in error_msg:
            return jsonify({
                "status": "error",
                "error": "YouTube rate limit",
                "message": "YouTube ne IP block kar diya hai. 1 ghante baad try karo.",
                "retry_after": "1 hour"
            }), 429
        
        return jsonify({
            "status": "error",
            "error": error_msg,
            "message": "YouTube extraction failed"
        }), 500
        
    except Exception as e:
        app.logger.exception("YouTube endpoint failed")
        return jsonify({
            "status": "error",
            "error": str(e),
            "message": "Internal server error"
        }), 500


# ============================================================
# DOWNLOAD FILE — EXPIRY ENFORCED
# ============================================================
@app.route('/download/<download_id>', methods=['GET'])
def serve_download(download_id):
    info = DOWNLOAD_STORE.get(download_id)
    
    if not info:
        return jsonify({
            "status": "error",
            "message": "Download not found or expired"
        }), 404
    
    if is_expired(info.get("expires_at")):
        file_path = info.get("file_path")
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except OSError:
            pass
        DOWNLOAD_STORE.pop(download_id, None)
        return jsonify({
            "status": "error",
            "message": "Download expired"
        }), 410
    
    file_path = info.get("file_path")
    
    if not file_path or not os.path.isfile(file_path):
        return jsonify({
            "status": "error",
            "message": "File not found"
        }), 404
    
    return send_file(
        file_path,
        as_attachment=True,
        download_name=info.get("filename")
    )


# ============================================================
# HOME
# ============================================================
@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "name": "ULTIMATE YOUTUBE API",
        "version": VERSION,
        "owner": OWNER,
        "api_key_required": True,
        "api_key": API_KEY,
        "usage": {
            "video_info": "GET /youtube?url=VIDEO_URL&api_key=ANSHZKXXMP",
            "video_download": "GET /youtube?url=VIDEO_URL&download=true&quality=1080p&format=mp4&api_key=ANSHZKXXMP",
            "channel_info": "GET /youtube?url=CHANNEL_URL&api_key=ANSHZKXXMP"
        },
        "headers": {"X-API-Key": API_KEY},
        "ffmpeg_available": check_ffmpeg(),
    })


@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "yt_dlp_version": yt_dlp.version.__version__,
        "ffmpeg_available": check_ffmpeg(),
    })


handler = app


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
