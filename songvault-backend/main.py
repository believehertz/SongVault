import asyncio
import os
import re
import shutil
import tempfile
from typing import List, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from shazamio import Shazam
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import uvicorn
import yt_dlp

app = FastAPI(title="songVault API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_DIR), name="downloads")

# Path to YouTube exported cookies file for authentication
COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.txt")

SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID", "")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET", "")

sp = None
if SPOTIPY_CLIENT_ID and SPOTIPY_CLIENT_SECRET:
    sp = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET
        )
    )

class TrackRequest(BaseModel):
    query: str

class SearchRequest(BaseModel):
    query: str

class BatchDownloadRequest(BaseModel):
    queries: List[str]

def format_duration(seconds):
    if not seconds:
        return "3:45"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"

def search_youtube_metadata(query: str) -> list:
    """Searches YouTube and returns list of candidate tracks/videos without downloading."""
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'cookiefile': COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
        'extractor_args': {
            'youtube': {
                'player_client': ['android'],
                'skip': ['hls', 'dash']
            }
        },
    }
    target = f"ytsearch12:{query}"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(target, download=False)
        entries = info.get('entries', [])
        results = []
        for entry in entries:
            vid_id = entry.get('id')
            vid_url = entry.get('url') or f"https://www.youtube.com/watch?v={vid_id}"
            thumbnails = entry.get('thumbnails', [])
            cover = thumbnails[-1]['url'] if thumbnails else f"https://img.youtube.com/vi/{vid_id}/hqdefault.jpg"
            results.append({
                "id": vid_id,
                "title": entry.get('title'),
                "artist": entry.get('uploader') or entry.get('channel') or "YouTube",
                "duration": format_duration(entry.get('duration')),
                "url": vid_url,
                "cover": cover
            })
        return results

def download_audio_from_youtube(search_term_or_url: str) -> dict:
    """Downloads pure audio stream from YouTube using yt-dlp and embeds metadata/thumbnail."""
    is_url = re.match(r'^https?://', search_term_or_url)
    target = search_term_or_url if is_url else f"ytsearch1:{search_term_or_url}"

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'writethumbnail': True,
        'postprocessors': [
            {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'},
            {'key': 'EmbedThumbnail'},
            {'key': 'FFmpegMetadata', 'add_metadata': True},
        ],
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'source_address': '0.0.0.0',
        'cookiefile': COOKIES_PATH if os.path.exists(COOKIES_PATH) else None,
        # Restrict strictly to android client for stable audio stream extraction
        'extractor_args': {
            'youtube': {
                'player_client': ['android']
            }
        },
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(target, download=True)
        if 'entries' in info and len(info['entries']) > 0:
            info = info['entries'][0]
        
        filename = ydl.prepare_filename(info)
        mp3_filename = os.path.splitext(filename)[0] + ".mp3"

        return {
            "title": info.get("title"),
            "artist": info.get("uploader") or info.get("artist"),
            "duration": format_duration(info.get("duration")),
            "file_url": f"/downloads/{os.path.basename(mp3_filename)}",
            "status": "completed"
        }

@app.get("/api/diagnostics")
async def run_diagnostics():
    """Checks system dependencies, ffmpeg, yt-dlp version, and cookie file status."""
    ffmpeg_path = shutil.which("ffmpeg")
    cookies_exists = os.path.exists(COOKIES_PATH)
    
    return {
        "status": "success",
        "ffmpeg_installed": ffmpeg_path is not None,
        "ffmpeg_path": ffmpeg_path,
        "yt_dlp_version": yt_dlp.version.__version__,
        "cookies_file_exists": cookies_exists,
        "cookies_file_path": COOKIES_PATH if cookies_exists else None
    }

@app.post("/api/search")
async def search_tracks(req: SearchRequest):
    """API endpoint to return search results for user selection."""
    try:
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, search_youtube_metadata, req.query)
        return {"status": "success", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/download")
async def download_single(req: TrackRequest):
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, download_audio_from_youtube, req.query)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/spotify/resolve")
async def resolve_spotify(req: TrackRequest):
    url = req.query
    queries = []
    if "track" in url:
        match = re.search(r'track/([a-zA-Z0-9]+)', url)
        if match and sp:
            track = sp.track(match.group(1))
            queries.append(f"{track['name']} {track['artists'][0]['name']}")
        else:
            queries.append(url)
    elif "playlist" in url:
        match = re.search(r'playlist/([a-zA-Z0-9]+)', url)
        if match and sp:
            results = sp.playlist_items(match.group(1))
            for item in results.get('items', []):
                track = item.get('track')
                if track:
                    queries.append(f"{track['name']} {track['artists'][0]['name']}")
        else:
            raise HTTPException(status_code=400, detail="Spotify credentials required.")
    else:
        queries.append(url)
    return {"queries": queries}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)