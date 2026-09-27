#!/usr/bin/env python3
# ============================================================
# ULTIMATE YOUTUBE API - 2 ENDPOINTS
# AUTHOR: ANSH AFT
# VERSION: 10.0 ULTIMATE
# ============================================================

import os
import sys
import json
import time
import uuid
import traceback
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse
from functools import wraps

# ============================================================
# IMPORTS
# ============================================================
from flask import Flask, jsonify, request, send_file
import requests
import yt_dlp

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

app = Flask(__name__)

# ============================================================
# CONFIGURATION
# ============================================================
API_KEY = "ANSHAFTAKZXKY"
OWNER = "ANSH AFT"
VERSION = "10.0 ULTIMATE"
DOWNLOAD_DIR = "/tmp/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# In-memory storage
DOWNLOAD_STORE = {}

# ============================================================
# API KEY DECORATOR
# ============================================================
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            api_key = request.args.get('api_key')
        if not api_key and request.is_json:
            try:
                data = request.get_json()
                api_key = data.get('api_key') if data else None
            except:
                pass
        
        if not api_key:
            return jsonify({
                "status": "error",
                "code": 401,
                "message": "API key required",
                "hint": "Add ?api_key=YOUR_KEY"
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
    except:
        return date_str


# ============================================================
# YOUTUBE FULL INFO (VIDEO + CHANNEL)
# ============================================================
def get_youtube_full_info(url):
    """YouTube video ya channel ki MAXIMUM info"""
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'skip_download': True,
        'geo_bypass': True,
        'extract_flat': False,
        'cachedir': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return {"status": "error", "error": "No info found"}
            
            # Check if it's a playlist/channel
            if info.get('_type') == 'playlist' or 'entries' in info:
                return get_channel_info(info, ydl)
            
            # Single video info
            return get_video_info(info)
            
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def get_video_info(info):
    """Single video ki full info"""
    
    duration = info.get("duration") or 0
    video_id = info.get("id")
    
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
            "thumbnail": info.get("thumbnail"),
            "thumbnail_hd": f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg",
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
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
            "comment_count": info.get("comment_count"),
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
        },
        
        "metadata": {
            "categories": info.get("categories", []),
            "tags": info.get("tags", []),
            "genre": info.get("genre"),
            "language": info.get("language"),
            "age_limit": info.get("age_limit"),
            "is_family_friendly": info.get("is_family_friendly"),
        },
        
        "subtitles": {
            "manual": list(info.get("subtitles", {}).keys()),
            "automatic": list(info.get("automatic_captions", {}).keys()),
        },
        
        "live": {
            "is_live": info.get("is_live"),
            "was_live": info.get("was_live"),
            "live_status": info.get("live_status"),
        },
        
        "technical": {
            "ext": info.get("ext"),
            "format": info.get("format"),
            "width": info.get("width"),
            "height": info.get("height"),
            "fps": info.get("fps"),
            "vcodec": info.get("vcodec"),
            "acodec": info.get("acodec"),
            "filesize": info.get("filesize"),
            "filesize_formatted": format_filesize(info.get("filesize")),
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
    }
    
    # Formats
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
            "format_note": f.get("format_note"),
            "quality": f.get("quality"),
            "has_video": f.get("vcodec") != "none",
            "has_audio": f.get("acodec") != "none",
            "url": f.get("url"),
        })
    
    # Summary
    result["summary"] = {
        "title": info.get("title"),
        "channel": info.get("channel"),
        "duration": format_duration(duration),
        "views": info.get("view_count"),
        "likes": info.get("like_count"),
        "comments": info.get("comment_count"),
        "upload_date": format_date(info.get("upload_date")),
        "thumbnail": info.get("thumbnail"),
        "is_live": info.get("is_live"),
        "age_limit": info.get("age_limit"),
        "categories": info.get("categories", []),
        "tags_count": len(info.get("tags", [])),
        "formats_count": len(info.get("formats", [])),
        "chapters_count": len(info.get("chapters", [])),
        "short_url": f"https://youtu.be/{video_id}",
    }
    
    return result


def get_channel_info(info, ydl):
    """Channel/Playlist ki full info"""
    
    entries = info.get("entries", [])
    if entries:
        entries = list(entries)
    
    videos = []
    total_duration = 0
    total_views = 0
    
    for entry in entries[:50]:  # Limit 50
        if not entry:
            continue
        
        duration = entry.get("duration") or 0
        views = entry.get("view_count") or 0
        total_duration += duration
        total_views += views
        
        videos.append({
            "id": entry.get("id"),
            "title": entry.get("title"),
            "url": entry.get("url") or f"https://youtu.be/{entry.get('id')}",
            "short_url": f"https://youtu.be/{entry.get('id')}",
            "duration": format_duration(duration),
            "duration_seconds": duration,
            "view_count": views,
            "thumbnail": entry.get("thumbnail") or f"https://i.ytimg.com/vi/{entry.get('id')}/mqdefault.jpg",
            "upload_date": format_date(entry.get("upload_date")),
        })
    
    result = {
        "status": "success",
        "type": "channel" if "channel" in info.get("extractor", "").lower() else "playlist",
        "timestamp": datetime.now().isoformat(),
        "api_version": VERSION,
        "owner": OWNER,
        
        "channel": {
            "id": info.get("id"),
            "title": info.get("title"),
            "url": info.get("webpage_url"),
            "description": info.get("description"),
            "uploader": info.get("uploader"),
            "uploader_id": info.get("uploader_id"),
            "uploader_url": info.get("uploader_url"),
            "channel_url": info.get("channel_url"),
            "thumbnail": info.get("thumbnail"),
        },
        
        "playlist_info": {
            "total_videos": len(videos),
            "total_duration_seconds": total_duration,
            "total_duration_formatted": format_duration(total_duration),
            "total_views": total_views,
        },
        
        "videos": videos,
        
        "summary": {
            "title": info.get("title"),
            "type": info.get("_type"),
            "extractor": info.get("extractor"),
            "total_videos": len(videos),
            "total_duration": format_duration(total_duration),
            "thumbnail": info.get("thumbnail"),
            "url": info.get("webpage_url"),
        }
    }
    
    return result


# ============================================================
# DOWNLOAD + CONVERT
# ============================================================
def download_and_convert(url, quality="1080p", format_type="mp4"):
    """Video download karo aur convert karo"""
    
    download_id = str(uuid.uuid4())[:12]
    output_template = os.path.join(DOWNLOAD_DIR, f"{download_id}_%(title)s.%(ext)s")
    
    if format_type == "mp3":
        fmt = "bestaudio/best"
        postprocessors = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        if quality == "best":
            fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        else:
            height = quality.replace("p", "")
            fmt = f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={height}][ext=mp4]/best"
        
        postprocessors = [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }]
    
    ydl_opts = {
        'format': fmt,
        'outtmpl': output_template,
        'postprocessors': postprocessors,
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'geo_bypass': True,
        'cachedir': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            title = info.get("title", "video")
            duration = info.get("duration") or 0
            video_id = info.get("id")
            
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
                    "expires_at": (datetime.now() + timedelta(hours=1)).isoformat(),
                    "download_url": f"/download/{download_id}",
                    "video_info": {
                        "id": video_id,
                        "title": title,
                        "channel": info.get("channel"),
                        "views": info.get("view_count"),
                        "likes": info.get("like_count"),
                        "upload_date": format_date(info.get("upload_date")),
                        "thumbnail": info.get("thumbnail"),
                        "short_url": f"https://youtu.be/{video_id}",
                    }
                }
                
                DOWNLOAD_STORE[download_id] = {
                    **download_info,
                    "file_path": actual_file
                }
                
                return {"status": "success", "download": download_info}
            else:
                return {"status": "error", "error": "File not found after download"}
                
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


# ============================================================
# ENDPOINT 1: /youtube — FULL INFO (VIDEO + CHANNEL)
# ============================================================
@app.route('/youtube', methods=['GET', 'POST'])
@require_api_key
def youtube_full_info():
    """
    YouTube Full Info
    
    Usage:
      GET /youtube?url=VIDEO_OR_CHANNEL_URL&api_key=YOUR_KEY
      POST /youtube {"url": "URL", "api_key": "YOUR_KEY"}
    """
    try:
        if request.method == 'POST' and request.is_json:
            data = request.get_json()
            url = data.get('url')
        else:
            url = request.args.get('url')
        
        if not url:
            return jsonify({
                "status": "error",
                "code": 400,
                "message": "URL required",
                "usage": "/youtube?url=URL&api_key=YOUR_KEY"
            }), 400
        
        if "youtube.com" not in url and "youtu.be" not in url:
            return jsonify({
                "status": "error",
                "code": 400,
                "message": "Invalid YouTube URL"
            }), 400
        
        info = get_youtube_full_info(url)
        return jsonify(info)
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


# ============================================================
# ENDPOINT 2: /download — DOWNLOAD + CONVERT
# ============================================================
@app.route('/download', methods=['GET', 'POST'])
@require_api_key
def youtube_download():
    """
    YouTube Download + Convert
    
    Usage:
      GET /download?url=VIDEO_URL&quality=1080p&format=mp4&api_key=YOUR_KEY
      POST /download {"url": "URL", "quality": "1080p", "format": "mp4", "api_key": "YOUR_KEY"}
    
    Quality: 1080p, 720p, 480p, 360p, best
    Format: mp4, mp3
    """
    try:
        if request.method == 'POST' and request.is_json:
            data = request.get_json()
            url = data.get('url')
            quality = data.get('quality', '1080p')
            format_type = data.get('format', 'mp4')
        else:
            url = request.args.get('url')
            quality = request.args.get('quality', '1080p')
            format_type = request.args.get('format', 'mp4')
        
        if not url:
            return jsonify({
                "status": "error",
                "code": 400,
                "message": "URL required",
                "usage": "/download?url=VIDEO_URL&quality=1080p&format=mp4&api_key=YOUR_KEY"
            }), 400
        
        if "youtube.com" not in url and "youtu.be" not in url:
            return jsonify({
                "status": "error",
                "code": 400,
                "message": "Invalid YouTube URL"
            }), 400
        
        valid_qualities = ["best", "1080p", "720p", "480p", "360p", "240p"]
        if quality not in valid_qualities:
            quality = "1080p"
        
        if format_type not in ["mp4", "mp3"]:
            format_type = "mp4"
        
        result = download_and_convert(url, quality, format_type)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


# ============================================================
# DOWNLOAD FILE ENDPOINT (Direct Link)
# ============================================================
@app.route('/download/<download_id>', methods=['GET'])
def serve_download(download_id):
    """Download link se file bhejo"""
    
    if download_id not in DOWNLOAD_STORE:
        return jsonify({
            "status": "error",
            "code": 404,
            "message": "Download not found or expired"
        }), 404
    
    info = DOWNLOAD_STORE[download_id]
    file_path = info.get("file_path")
    
    if not file_path or not os.path.exists(file_path):
        return jsonify({
            "status": "error",
            "code": 404,
            "message": "File not found on server"
        }), 404
    
    try:
        return send_file(
            file_path,
            as_attachment=True,
            download_name=info.get("filename")
        )
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


# ============================================================
# HOME / HEALTH
# ============================================================
@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "name": "ULTIMATE YOUTUBE API",
        "version": VERSION,
        "owner": OWNER,
        "endpoints": {
            "/youtube?url=VIDEO_OR_CHANNEL_URL&api_key=YOUR_KEY": "YouTube Full Info (Video + Channel)",
            "/download?url=VIDEO_URL&quality=1080p&format=mp4&api_key=YOUR_KEY": "Download + Convert + Direct Link",
            "/download/<id>": "Direct Download Link",
            "/health": "Health Check"
        },
        "qualities": ["best", "1080p", "720p", "480p", "360p", "240p"],
        "formats": ["mp4", "mp3"],
        "example": "/youtube?url=https://www.youtube.com/@klocuchy&api_key=YOUR_KEY"
    })


@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": VERSION,
        "yt_dlp_version": yt_dlp.version.__version__,
    })


# ============================================================
# ERROR HANDLERS
# ============================================================
@app.errorhandler(404)
def not_found(e):
    return jsonify({
        "status": "error",
        "code": 404,
        "message": "Endpoint not found",
        "available": ["/", "/health", "/youtube", "/download"]
    }), 404


# ============================================================
# VERCEL HANDLER
# ============================================================
handler = app


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
