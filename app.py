#!/usr/bin/env python3
"""
Flask web application for MP3 BOT.
"""

import os
import sys
import json
import queue
import re
import threading
import subprocess
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

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

from download import DownloadCancelled, check_and_install_ffmpeg, download_spotify_url, DEFAULT_OUTPUT_DIR

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# Global queue and active download state tracking
active_downloads = {}
log_queues = {}
download_cancellations = {}
mega_state_lock = threading.Lock()
mega_state = {"status": "idle", "logs": deque(maxlen=200), "process": None}

def sanitize_url(url):
    return url.strip()

@app.route("/")
@app.route("/downloads")
def index():
    default_destinations = ""
    if local_mega_request():
        try:
            default_destinations = Path(app.instance_path, "mega-destinations.txt").read_text(
                encoding="utf-8",
            ).strip()
        except FileNotFoundError:
            pass
    response = app.make_response(render_template(
        "index.html", default_output_dir=DEFAULT_OUTPUT_DIR,
        jamendo_configured=bool(jamendo_client_id()),
        default_destinations=default_destinations,
    ))
    response.cache_control.no_store = True
    return response

def local_mega_request():
    return (
        request.remote_addr in ("127.0.0.1", "::1")
        and urlsplit(request.host_url).hostname in ("localhost", "127.0.0.1", "::1")
        and request.headers.get("Origin", request.host_url.rstrip("/")) == request.host_url.rstrip("/")
    )

def jamendo_client_id():
    configured = os.environ.get("JAMENDO_CLIENT_ID", "").strip()
    if configured:
        return configured
    try:
        return Path(app.instance_path, "jamendo-client-id.txt").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""

@app.get("/api/mega")
def mega_status():
    if not local_mega_request():
        return jsonify(error="Open the dashboard on localhost to use MEGA."), 403
    with mega_state_lock:
        return jsonify(status=mega_state["status"], logs=list(mega_state["logs"]))

@app.post("/api/mega")
def start_mega():
    if not local_mega_request():
        return jsonify(error="Open the dashboard on localhost to use MEGA."), 403
    data = request.get_json(silent=True)
    fields = ("destinations", "country", "genre", "artist", "category", "limit", "storage", "client_id")
    if not isinstance(data, dict) or any(not isinstance(data.get(field, ""), str) for field in fields):
        return jsonify(error="Invalid bot settings."), 400
    destinations = [line.strip() for line in data.get("destinations", "").splitlines() if line.strip()]
    if not destinations or any(not line.startswith(("/", "https://")) for line in destinations):
        return jsonify(error="Enter a MEGA folder link or cloud path on each line."), 400
    client_id = data.get("client_id", "").strip() or jamendo_client_id()
    if not client_id:
        return jsonify(error="Enter your Jamendo Client ID to search for music."), 400

    command = [sys.executable, "-u", str(Path(__file__).with_name("mega_bot.py")), "--dashboard-control", "--dest", *destinations]
    for field, flag in (
        ("country", "country"), ("genre", "genre"), ("artist", "artist"),
        ("category", "category"), ("limit", "limit"), ("storage", "max-storage-gb"),
    ):
        value = data.get(field, "").strip()
        if value:
            command.append(f"--{flag}={value}")
    env = {**os.environ, "JAMENDO_CLIENT_ID": client_id}
    mac_mega = Path("/Applications/MEGAcmd.app/Contents/MacOS")
    if mac_mega.is_dir():
        env["PATH"] = os.pathsep.join((str(mac_mega), os.environ.get("PATH", os.defpath)))

    def run_bot(process):
        status = "failed"
        try:
            with process:
                for line in process.stdout:
                    if line.rstrip() == "[bot paused]":
                        with mega_state_lock:
                            if mega_state["status"] == "pausing":
                                mega_state["status"] = "paused"
                        continue
                    message = line.rstrip().replace(client_id, "[Client ID]")
                    for destination in destinations:
                        if destination.startswith("https://"):
                            message = message.replace(destination, "[MEGA link]")
                    with mega_state_lock:
                        mega_state["logs"].append(message)
                status = {0: "finished", 130: "ended"}.get(process.wait(), "failed")
        finally:
            with mega_state_lock:
                mega_state.update(status=status, process=None)

    with mega_state_lock:
        if mega_state["process"] is not None:
            return jsonify(error="The MEGA bot is already running."), 409
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE, text=True, errors="replace", env=env,
            )
        except (OSError, ValueError):
            return jsonify(error="Could not start the MEGA bot."), 500
        mega_state["logs"].clear()
        mega_state.update(status="running", process=process)
        threading.Thread(target=run_bot, args=(process,), daemon=True).start()
    return jsonify(status="running"), 202


@app.post("/api/mega/<action>")
def control_mega(action):
    if not local_mega_request():
        return jsonify(error="Open the dashboard on localhost to use MEGA."), 403
    transitions = {
        "pause": (("running",), "pausing"),
        "resume": (("paused",), "running"),
        "end": (("running", "pausing", "paused"), "ending"),
    }
    if action not in transitions or not request.is_json:
        return jsonify(error="Invalid bot action."), 400
    allowed, next_status = transitions[action]
    with mega_state_lock:
        process = mega_state["process"]
        if process is None or mega_state["status"] not in allowed:
            return jsonify(error="This action is unavailable for the current run."), 409
        try:
            process.stdin.write(action + "\n")
            process.stdin.flush()
        except (OSError, ValueError):
            return jsonify(error="The bot has already exited."), 409
        mega_state["status"] = next_status
    return jsonify(status=next_status)


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
        return jsonify({"error": "A media link is required"}), 400

    download_id = f"dl_{len(active_downloads) + 1}"
    log_q = queue.Queue()
    log_queues[download_id] = log_q
    cancel_event = threading.Event()
    download_cancellations[download_id] = cancel_event

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

    def run_download_thread(dl_id, target_url, out_dir, fmt, b_rate, q, stop_event):
        """Run download in background thread with real-time log streaming."""
        completed_tracks = set()
        if not stop_event.is_set():
            active_downloads[dl_id]["status"] = "running"
        
        def progress_cb(message):
            active_downloads[dl_id]["logs"].append(message)
            q.put(json.dumps({"type": "log", "message": message}))

            track_match = re.search(r"\[(\d+)/(\d+)\]", message)
            if not track_match:
                return

            track_num, total = map(int, track_match.groups())
            active_downloads[dl_id]["total_count"] = total
            is_finished = any(marker in message for marker in (
                "Downloaded:", "Already exists:", "Failed:", "Error downloading"
            ))
            if is_finished:
                completed_tracks.add(track_num)
                active_downloads[dl_id]["completed_count"] = len(completed_tracks)

            q.put(json.dumps({
                "type": "progress",
                "completed": len(completed_tracks),
                "total": total,
                "track": track_num,
                "finished": is_finished
            }))

        q.put(json.dumps({"type": "status", "message": f"🚀 Starting download for {target_url}"}))
        q.put(json.dumps({"type": "log", "message": "Finding tracks for the supplied link."}))

        try:
            result = download_spotify_url(
                target_url,
                output_dir=out_dir,
                audio_format=fmt,
                bitrate=b_rate,
                progress_callback=progress_cb,
                cancel_event=stop_event
            )

            if stop_event.is_set():
                raise DownloadCancelled()

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

        except DownloadCancelled:
            active_downloads[dl_id]["status"] = "cancelled"
            q.put(json.dumps({"type": "cancelled", "message": "⏹ Download stopped"}))
        except Exception as e:
            active_downloads[dl_id]["status"] = "failed"
            q.put(json.dumps({"type": "error", "message": f"❌ Failed: {str(e)}"}))
        finally:
            q.put(json.dumps({"type": "EOF"}))

    t = threading.Thread(target=run_download_thread, args=(download_id, url, output_dir, audio_format, bitrate, log_q, cancel_event))
    t.daemon = True
    t.start()

    return jsonify({
        "success": True,
        "download_id": download_id,
        "info": download_info
    })

@app.route("/api/download/<download_id>/cancel", methods=["POST"])
def cancel_download(download_id):
    download_info = active_downloads.get(download_id)
    cancel_event = download_cancellations.get(download_id)
    if not download_info or not cancel_event:
        return jsonify({"error": "Download not found"}), 404
    if download_info["status"] not in ("starting", "running", "cancelling"):
        return jsonify({"error": "Download is not active"}), 409

    download_info["status"] = "cancelling"
    cancel_event.set()
    log_queues[download_id].put(json.dumps({
        "type": "cancelling",
        "message": "⏹ Stop requested; cancelling current track..."
    }))
    return jsonify({"success": True})

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
    
    print(f"Starting MP3 BOT on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)

