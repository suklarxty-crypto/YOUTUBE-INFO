#!/usr/bin/env python3
# ============================================================
# YOUTUBE INFO API — MAXIMUM INFO
# Flask API | yt-dlp | Full Video Details
# ============================================================

import subprocess
import sys
import os
import json
import traceback
from datetime import datetime

# Auto-install
try:
    import yt_dlp
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp"])
    import yt_dlp

try:
    from flask import Flask, jsonify, request
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "flask"])
    from flask import Flask, jsonify, request

try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

app = Flask(__name__)

# ============================================================
# YOUTUBE INFO — MAXIMUM DETAILS
# ============================================================
def get_youtube_info(url):
    """YouTube video ki maximum info nikalo"""
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'skip_download': True,
        'extract_flat': False,
        'geo_bypass': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return {"error": "No info found"}
            
            # ===== BASIC INFO =====
            result = {
                "status": "success",
                "timestamp": datetime.now().isoformat(),
                
                # Video Info
                "id": info.get("id"),
                "title": info.get("title"),
                "fulltitle": info.get("fulltitle"),
                "url": info.get("webpage_url"),
                "original_url": info.get("original_url"),
                
                # Description
                "description": info.get("description"),
                "description_length": len(info.get("description", "") or ""),
                "short_description": (info.get("description", "") or "")[:500],
                
                # Thumbnails
                "thumbnail": info.get("thumbnail"),
                "thumbnails": info.get("thumbnails", []),
                
                # Duration
                "duration": info.get("duration"),
                "duration_string": info.get("duration_string"),
                "duration_minutes": (info.get("duration") or 0) // 60,
                "duration_seconds": (info.get("duration") or 0) % 60,
                
                # Dates
                "upload_date": info.get("upload_date"),
                "release_date": info.get("release_date"),
                "modified_date": info.get("modified_date"),
                "timestamp": info.get("timestamp"),
                
                # Views & Engagement
                "view_count": info.get("view_count"),
                "like_count": info.get("like_count"),
                "dislike_count": info.get("dislike_count"),
                "comment_count": info.get("comment_count"),
                "repost_count": info.get("repost_count"),
                "average_rating": info.get("average_rating"),
                
                # Channel Info
                "uploader": info.get("uploader"),
                "uploader_id": info.get("uploader_id"),
                "uploader_url": info.get("uploader_url"),
                "channel": info.get("channel"),
                "channel_id": info.get("channel_id"),
                "channel_url": info.get("channel_url"),
                "channel_follower_count": info.get("channel_follower_count"),
                
                # Categories & Tags
                "categories": info.get("categories", []),
                "tags": info.get("tags", []),
                "genre": info.get("genre"),
                
                # Language
                "language": info.get("language"),
                "subtitles": list(info.get("subtitles", {}).keys()),
                "automatic_captions": list(info.get("automatic_captions", {}).keys()),
                
                # Live Status
                "is_live": info.get("is_live"),
                "was_live": info.get("was_live"),
                "live_status": info.get("live_status"),
                
                # Age & Content
                "age_limit": info.get("age_limit"),
                "is_family_friendly": info.get("is_family_friendly"),
                "availability": info.get("availability"),
                
                # Location
                "location": info.get("location"),
                
                # Series/Playlist
                "series": info.get("series"),
                "season": info.get("season"),
                "episode": info.get("episode"),
                "episode_number": info.get("episode_number"),
                "playlist": info.get("playlist"),
                "playlist_index": info.get("playlist_index"),
                
                # Technical
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
                "filesize_approx": info.get("filesize_approx"),
                "audio_channels": info.get("audio_channels"),
                "audio_bitrate": info.get("audio_bitrate"),
                "video_bitrate": info.get("video_bitrate"),
                "total_bitrate": info.get("tbr"),
                
                # Download URL
                "direct_url": info.get("url"),
                "manifest_url": info.get("manifest_url"),
                
                # Extras
                "extractor": info.get("extractor"),
                "extractor_key": info.get("extractor_key"),
                "webpage_url_basename": info.get("webpage_url_basename"),
                "webpage_url_domain": info.get("webpage_url_domain"),
                
                # Chapters
                "chapters": info.get("chapters", []),
                
                # Heatmap (most replayed)
                "heatmap": info.get("heatmap"),
                
                # Cards & End Screens
                "cards": info.get("cards"),
                "end_screen": info.get("end_screen"),
                
                # All formats
                "formats": [],
                "format_count": len(info.get("formats", [])),
            }
            
            # ===== FORMATS (Full Details) =====
            for f in info.get("formats", []):
                filesize = f.get("filesize") or f.get("filesize_approx")
                
                format_info = {
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "resolution": f.get("resolution"),
                    "width": f.get("width"),
                    "height": f.get("height"),
                    "fps": f.get("fps"),
                    "vcodec": f.get("vcodec"),
                    "acodec": f.get("acodec"),
                    "filesize": filesize,
                    "filesize_str": format_filesize(filesize),
                    "tbr": f.get("tbr"),
                    "abr": f.get("abr"),
                    "vbr": f.get("vbr"),
                    "asr": f.get("asr"),
                    "audio_channels": f.get("audio_channels"),
                    "format_note": f.get("format_note"),
                    "quality": f.get("quality"),
                    "has_video": f.get("vcodec") != "none",
                    "has_audio": f.get("acodec") != "none",
                    "protocol": f.get("protocol"),
                    "url": f.get("url"),
                }
                result["formats"].append(format_info)
            
            # ===== SUMMARY =====
            result["summary"] = {
                "title": info.get("title"),
                "channel": info.get("channel"),
                "duration": info.get("duration_string"),
                "views": info.get("view_count"),
                "likes": info.get("like_count"),
                "comments": info.get("comment_count"),
                "upload_date": info.get("upload_date"),
                "thumbnail": info.get("thumbnail"),
                "is_live": info.get("is_live"),
                "age_limit": info.get("age_limit"),
                "categories": info.get("categories", []),
                "tags_count": len(info.get("tags", [])),
                "formats_count": len(info.get("formats", [])),
                "subtitles_count": len(info.get("subtitles", {})),
                "chapters_count": len(info.get("chapters", [])),
            }
            
            return result
            
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def format_filesize(size):
    """Bytes ko readable format mein convert karo"""
    if not size:
        return "N/A"
    if size > 1024 * 1024 * 1024:
        return f"{size / (1024**3):.2f} GB"
    elif size > 1024 * 1024:
        return f"{size / (1024**2):.1f} MB"
    elif size > 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


# ============================================================
# API ROUTES
# ============================================================

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "name": "YouTube Info API",
        "version": "2.0",
        "endpoints": {
            "/youtube?url=VIDEO_URL": "Get full YouTube video info",
            "/youtube/summary?url=VIDEO_URL": "Get short summary",
            "/youtube/formats?url=VIDEO_URL": "Get all formats only",
            "/youtube/download?url=VIDEO_URL": "Download video info",
            "/health": "Health check"
        }
    })


@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "yt_dlp_version": yt_dlp.version.__version__
    })


@app.route('/youtube')
def youtube_info():
    """Full YouTube info"""
    url = request.args.get('url')
    
    if not url:
        return jsonify({"error": "URL required"}), 400
    
    if "youtube.com" not in url and "youtu.be" not in url:
        return jsonify({"error": "Invalid YouTube URL"}), 400
    
    info = get_youtube_info(url)
    return jsonify(info)


@app.route('/youtube/summary')
def youtube_summary():
    """Short summary only"""
    url = request.args.get('url')
    
    if not url:
        return jsonify({"error": "URL required"}), 400
    
    info = get_youtube_info(url)
    
    if info.get("status") == "error":
        return jsonify(info), 500
    
    return jsonify({
        "status": "success",
        "summary": info.get("summary", {})
    })


@app.route('/youtube/formats')
def youtube_formats():
    """Only formats"""
    url = request.args.get('url')
    
    if not url:
        return jsonify({"error": "URL required"}), 400
    
    info = get_youtube_info(url)
    
    if info.get("status") == "error":
        return jsonify(info), 500
    
    return jsonify({
        "status": "success",
        "title": info.get("title"),
        "format_count": info.get("format_count"),
        "formats": info.get("formats", [])
    })


# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    print("=" * 60)
    print("     YOUTUBE INFO API")
    print("=" * 60)
    print(f"[✓] yt-dlp: {yt_dlp.version.__version__}")
    print(f"[✓] Flask loaded")
    print()
    print("Endpoints:")
    print("  http://localhost:5000/")
    print("  http://localhost:5000/youtube?url=VIDEO_URL")
    print("  http://localhost:5000/youtube/summary?url=VIDEO_URL")
    print("  http://localhost:5000/youtube/formats?url=VIDEO_URL")
    print("=" * 60)
    
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
