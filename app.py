#!/usr/bin/env python3
"""
Flask Web Application for Spotify MP3 Library Downloader
No Spotify API key or Premium required - uses public embed scraping + yt-dlp.
"""

import os
import sys
import json
import queue
import threading
import subprocess
from pathlib import Path

import yt_dlp
# Patch yt-dlp to bypass Python 3.9 deprecation warning exception
_yt_dlp_deprecated = yt_dlp.YoutubeDL.deprecated_feature
def _patched_deprecated(self, message, *args, **kwargs):
    if "Python" in str(message):
        return
    return _yt_dlp_deprecated(self, message, *args, **kwargs)
yt_dlp.YoutubeDL.deprecated_feature = _patched_deprecated

from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from flask_cors import CORS

from download import check_and_install_ffmpeg, download_spotify_url, DEFAULT_OUTPUT_DIR

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# Global queue and active download state tracking
active_downloads = {}
log_queues = {}

def sanitize_url(url):
    return url.strip()

@app.route("/")
def index():
    return render_template("index.html", default_output_dir=DEFAULT_OUTPUT_DIR)

@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify({
        "default_output_dir": DEFAULT_OUTPUT_DIR,
        "ffmpeg_available": check_and_install_ffmpeg(os.path.dirname(sys.executable))
    })

@app.route("/api/download", methods=["POST"])
def start_download():
    data = request.json or {}
    url = sanitize_url(data.get("url", ""))
    output_dir = data.get("output_dir", DEFAULT_OUTPUT_DIR).strip() or DEFAULT_OUTPUT_DIR
    audio_format = data.get("format", "mp3")
    bitrate = data.get("bitrate", "320k")

    if not url:
        return jsonify({"error": "Spotify URL is required"}), 400

    download_id = f"dl_{len(active_downloads) + 1}"
    log_q = queue.Queue()
    log_queues[download_id] = log_q

    download_info = {
        "id": download_id,
        "url": url,
        "output_dir": output_dir,
        "format": audio_format,
        "bitrate": bitrate,
        "status": "starting",
        "logs": [],
        "completed_count": 0,
        "total_count": 0
    }
    active_downloads[download_id] = download_info

    def run_download_thread(dl_id, target_url, out_dir, fmt, b_rate, q):
        """Run download in background thread with real-time log streaming."""
        
        def progress_cb(message):
            active_downloads[dl_id]["logs"].append(message)
            q.put(json.dumps({"type": "log", "message": message}))

        q.put(json.dumps({"type": "status", "message": f"🚀 Starting download for {target_url}"}))
        q.put(json.dumps({"type": "log", "message": "🔓 No Spotify API key needed — using public embed scraping!"}))

        try:
            result = download_spotify_url(
                target_url,
                output_dir=out_dir,
                audio_format=fmt,
                bitrate=b_rate,
                progress_callback=progress_cb
            )

            if result.get("success"):
                active_downloads[dl_id]["status"] = "completed"
                downloaded = result.get("downloaded", 0)
                failed = result.get("failed", 0)
                skipped = result.get("skipped", 0)
                q.put(json.dumps({
                    "type": "complete", 
                    "message": f"✨ Done! {downloaded} downloaded, {skipped} skipped, {failed} failed"
                }))
            else:
                active_downloads[dl_id]["status"] = "failed"
                q.put(json.dumps({
                    "type": "error", 
                    "message": f"❌ Download failed: {result.get('error', 'Unknown error')}"
                }))

        except Exception as e:
            active_downloads[dl_id]["status"] = "failed"
            q.put(json.dumps({"type": "error", "message": f"❌ Failed: {str(e)}"}))
        finally:
            q.put(json.dumps({"type": "EOF"}))

    t = threading.Thread(target=run_download_thread, args=(download_id, url, output_dir, audio_format, bitrate, log_q))
    t.daemon = True
    t.start()

    return jsonify({
        "success": True,
        "download_id": download_id,
        "info": download_info
    })

@app.route("/api/stream/<download_id>")
def stream_logs(download_id):
    """Server-Sent Events endpoint to stream download logs live."""
    if download_id not in log_queues:
        return "Invalid Download ID", 404

    def event_stream():
        q = log_queues[download_id]
        while True:
            try:
                data = q.get(timeout=30)
                if data:
                    parsed = json.loads(data)
                    yield f"data: {data}\n\n"
                    if parsed.get("type") == "EOF":
                        break
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

    return Response(event_stream(), mimetype="text/event-stream")

@app.route("/api/files", methods=["GET"])
def list_downloaded_files():
    output_dir = request.args.get("dir", DEFAULT_OUTPUT_DIR)
    files = []
    if os.path.exists(output_dir):
        for root, _, filenames in os.walk(output_dir):
            for name in filenames:
                if name.lower().endswith(('.mp3', '.m4a', '.flac', '.wav', '.opus', '.ogg')):
                    full_path = os.path.join(root, name)
                    rel_path = os.path.relpath(full_path, output_dir)
                    stat = os.stat(full_path)
                    files.append({
                        "name": name,
                        "relative_path": rel_path,
                        "size_mb": round(stat.st_size / (1024 * 1024), 2),
                        "modified": stat.st_mtime
                    })
    return jsonify({"output_dir": output_dir, "files": sorted(files, key=lambda x: x["modified"], reverse=True)})

@app.route("/api/open_folder", methods=["POST"])
def open_folder():
    data = request.json or {}
    folder_path = data.get("path", DEFAULT_OUTPUT_DIR)
    os.makedirs(folder_path, exist_ok=True)
    
    try:
        if sys.platform == "darwin":  # macOS
            subprocess.run(["open", folder_path])
        elif sys.platform == "win32":  # Windows
            os.startfile(folder_path)
        else:  # Linux
            subprocess.run(["xdg-open", folder_path])
        return jsonify({"success": True, "message": f"Opened folder: {folder_path}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/browse_folder", methods=["POST"])
def browse_folder():
    data = request.json or {}
    current_path = data.get("current_path", "")
    
    try:
        if sys.platform == "darwin":  # macOS
            cmd = ['osascript', '-e', 'POSIX path of (choose folder with prompt "Select download location:")']
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                path = result.stdout.strip()
                if path.endswith('/'):
                    path = path[:-1]
                return jsonify({"success": True, "path": path})
            else:
                return jsonify({"success": False, "error": "Cancelled"})
        else:
            # Fallback for Windows/Linux using tkinter
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            folder_path = filedialog.askdirectory(initialdir=current_path, title="Select Download Location")
            root.destroy()
            
            if folder_path:
                return jsonify({"success": True, "path": folder_path})
            else:
                return jsonify({"success": False, "error": "Cancelled"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    import socket
    
    def find_available_port(start_port=5050):
        port = start_port
        while port < start_port + 100:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(('127.0.0.1', port)) != 0:
                    return port
            port += 1
        return start_port

    requested_port = int(os.environ.get("PORT", 5050))
    port = find_available_port(requested_port)
    
    print(f"🟢 Starting Spotify Downloader Web App on http://localhost:{port}")
    print(f"🔓 No Spotify API key or Premium required!")
    app.run(host="0.0.0.0", port=port, debug=False)

