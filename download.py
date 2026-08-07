#!/usr/bin/env python3
"""
Spotify MP3 Library Downloader - No API Key Required
Downloads tracks by scraping Spotify's public embed and downloading from YouTube Music.
"""

import os
import sys
import re
import json
import argparse
import subprocess
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Compatibility Patches ---
import yt_dlp
_yt_dlp_deprecated = yt_dlp.YoutubeDL.deprecated_feature
def _patched_deprecated(self, message, *args, **kwargs):
    if "Python" in str(message):
        return
    return _yt_dlp_deprecated(self, message, *args, **kwargs)
yt_dlp.YoutubeDL.deprecated_feature = _patched_deprecated
# ---

from spotify_scraper import get_spotify_tracks

DEFAULT_OUTPUT_DIR = os.path.join(os.getcwd(), "downloads")


def check_and_install_ffmpeg(venv_bin_dir=None):
    """Ensure ffmpeg is available either on system PATH or in ~/.spotdl/."""
    home = os.path.expanduser("~")
    spotdl_dir = os.path.join(home, ".spotdl")
    spotdl_ffmpeg = os.path.join(spotdl_dir, "ffmpeg")

    if spotdl_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = spotdl_dir + os.path.pathsep + os.environ.get("PATH", "")

    if shutil.which("ffmpeg") or os.path.exists(spotdl_ffmpeg):
        return True
    
    print("⚡ FFmpeg not found. Attempting to download via spotdl...")
    try:
        cmd = [sys.executable, "-m", "spotdl", "--download-ffmpeg"]
        subprocess.run(cmd, input="n\n", text=True, check=False)
        return True
    except Exception as e:
        print(f"⚠️ FFmpeg setup warning: {e}")
        return False


def sanitize_filename(name):
    """Remove invalid filename characters."""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.strip('. ')
    return name[:200]  # Limit length


def download_single_track(track, output_dir, audio_format="mp3", bitrate="320k", track_num=None, total=None, progress_callback=None):
    """Download a single track from YouTube Music using yt-dlp."""
    artist = track.get("artist", "Unknown")
    title = track.get("title", "Unknown")
    search_query = f"{artist} - {title}"
    
    safe_filename = sanitize_filename(f"{artist} - {title}")
    output_path = os.path.join(output_dir, f"{safe_filename}.{audio_format}")
    
    # Skip if already downloaded
    if os.path.exists(output_path):
        msg = f"⏭️  [{track_num}/{total}] Already exists: {safe_filename}"
        print(msg)
        if progress_callback:
            progress_callback(msg)
        return {"status": "skipped", "file": output_path, "track": search_query}

    progress_prefix = f"[{track_num}/{total}]" if track_num else ""
    msg = f"🔎 {progress_prefix} Searching: {search_query}"
    print(msg)
    if progress_callback:
        progress_callback(msg)

    # Set up yt-dlp options for YouTube Music search
    bitrate_num = bitrate.replace("k", "")
    ffmpeg_dir = os.path.join(os.path.expanduser("~"), ".spotdl")
    
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(output_dir, f"{safe_filename}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "default_search": "ytsearch1",  # Search YouTube for first result
        "extractor_args": {"youtube": {"player_client": ["android_vr"]}},
        "ffmpeg_location": ffmpeg_dir,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": bitrate_num,
            },
        ],
        "postprocessor_args": [
            "-metadata", f"title={title}",
            "-metadata", f"artist={artist}",
        ],
    }
    
    # Add album metadata if available
    album = track.get("album", "")
    if album:
        ydl_opts["postprocessor_args"].extend(["-metadata", f"album={album}"])

    try:
        # Search YouTube Music first, fall back to regular YouTube
        search_queries = [
            f"ytsearch1:{search_query} official audio",
            f"ytsearch1:{search_query} audio",
            f"ytsearch1:{search_query}",
        ]
        
        downloaded = False
        for sq in search_queries:
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([sq])
                downloaded = True
                break
            except Exception:
                continue
        
        if downloaded and os.path.exists(output_path):
            msg = f"✅ {progress_prefix} Downloaded: {safe_filename}"
            print(msg)
            if progress_callback:
                progress_callback(msg)
            return {"status": "success", "file": output_path, "track": search_query}
        else:
            msg = f"❌ {progress_prefix} Failed: {search_query}"
            print(msg)
            if progress_callback:
                progress_callback(msg)
            return {"status": "failed", "track": search_query}
            
    except Exception as e:
        msg = f"❌ {progress_prefix} Error downloading {search_query}: {str(e)}"
        print(msg)
        if progress_callback:
            progress_callback(msg)
        return {"status": "failed", "track": search_query, "error": str(e)}


def download_spotify_url(url, output_dir=DEFAULT_OUTPUT_DIR, audio_format="mp3", bitrate="320k", 
                         client_id=None, client_secret=None, progress_callback=None):
    """
    Downloads Spotify tracks, playlists, or albums.
    No Spotify API key required - uses public embed scraping + yt-dlp.
    """
    os.makedirs(output_dir, exist_ok=True)
    check_and_install_ffmpeg()

    msg = f"🔍 Fetching track info from Spotify (no API key needed)..."
    print(msg)
    if progress_callback:
        progress_callback(msg)
    
    try:
        result = get_spotify_tracks(url)
    except Exception as e:
        msg = f"❌ Failed to extract tracks: {str(e)}"
        print(msg)
        if progress_callback:
            progress_callback(msg)
        return {"success": False, "error": str(e), "output_dir": output_dir}

    tracks = result.get("tracks", [])
    total = len(tracks)
    playlist_name = result.get("name", "Unknown")
    
    msg = f"📀 {playlist_name} — {total} tracks found"
    print(msg)
    if progress_callback:
        progress_callback(msg)
    
    if total == 0:
        msg = "⚠️ No tracks found. The playlist may be private or empty."
        print(msg)
        if progress_callback:
            progress_callback(msg)
        return {"success": False, "error": "No tracks found", "output_dir": output_dir}

    msg = f"📁 Saving to: {output_dir}"
    print(msg)
    if progress_callback:
        progress_callback(msg)
    
    msg = f"🎧 Format: {audio_format.upper()} ({bitrate})"
    print(msg)
    if progress_callback:
        progress_callback(msg)

    # Download tracks one by one (sequential for stability)
    results = {"success": 0, "failed": 0, "skipped": 0}
    
    for i, track in enumerate(tracks, 1):
        r = download_single_track(
            track, output_dir, audio_format, bitrate, 
            track_num=i, total=total, 
            progress_callback=progress_callback
        )
        results[r["status"]] = results.get(r["status"], 0) + 1

    # Summary
    summary_msg = f"\n✨ Download Complete! {results['success']} downloaded, {results.get('skipped', 0)} skipped, {results.get('failed', 0)} failed"
    print(summary_msg)
    if progress_callback:
        progress_callback(summary_msg)

    return {
        "success": results["failed"] == 0 or results["success"] > 0,
        "total": total,
        "downloaded": results["success"],
        "skipped": results.get("skipped", 0),
        "failed": results.get("failed", 0),
        "output_dir": output_dir
    }


def main():
    parser = argparse.ArgumentParser(description="Spotify MP3 Library & Playlist Downloader (No API Key Required)")
    parser.add_argument("url", nargs="?", help="Spotify URL (Playlist, Track, Album)")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT_DIR, help="Directory to save downloaded files")
    parser.add_argument("-f", "--format", default="mp3", choices=["mp3", "m4a", "flac", "wav", "opus", "ogg"], help="Audio format (default: mp3)")
    parser.add_argument("-b", "--bitrate", default="320k", help="Audio bitrate (default: 320k)")
    parser.add_argument("--json", action="store_true", help="Output JSON result summary")

    args = parser.parse_args()

    url = args.url
    if not url:
        print("🎵 Spotify MP3 Downloader 🎵")
        print("No Spotify API key or Premium required!\n")
        url = input("Enter Spotify Link (Playlist / Album / Song): ").strip()
        if not url:
            print("Error: No URL provided.")
            sys.exit(1)

    result = download_spotify_url(
        url, 
        output_dir=args.output, 
        audio_format=args.format, 
        bitrate=args.bitrate,
    )
    
    if args.json:
        print(json.dumps(result, indent=2))
        
    sys.exit(0 if result.get("success") else 1)

if __name__ == "__main__":
    main()
