"""Public music discovery for the Sri Lankan artist collection."""

from contextlib import closing
import json
import os
import queue
import threading
from tempfile import TemporaryFile
from pathlib import Path
import re
import shutil
import subprocess
import unicodedata


ARTISTS = (
    "Dinesh Gamage", "Dhanith Sri", "Supun Perera", "Ridma Weerawardena",
    "Methun SK", "Piyath Rajapakse", "Dilu Beats", "Kanchana Anuradhi",
    "Yasas Medagedara", "WAYO", "Sanuka", "Raini Charuka", "Umaria",
    "Bathiya & Santhush", "Kasun Kalhara", "Amarasiri Peiris", "Nanda Malini",
    "Sunil Edirisinghe", "Victor Rathnayake", "Rookantha Gunathilaka",
    "Chandana Liyanarachchi", "Chamara Weerasinghe", "Ruwan Hettiarachchi",
    "Shihan Mihiranga", "Bachi Susan", "Radeesh Vandebona", "Lahiru Perera",
    "Centigradz", "Daddy", "Mihindu Ariyaratne",
)


def normalized(text):
    return re.sub(r"\W+", "", unicodedata.normalize("NFKC", text).casefold())


def executable():
    candidates = (
        Path("/opt/homebrew/bin/yt-dlp"),
        Path(shutil.which("yt-dlp") or ""),
    )
    for candidate in candidates:
        if candidate != Path("") and candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise RuntimeError("Install the current yt-dlp command to use Sri Lankan discovery.")


def command_environment():
    environment = os.environ.copy()
    homebrew_bin = "/opt/homebrew/bin"
    if Path(homebrew_bin).is_dir():
        environment["PATH"] = os.pathsep.join((
            homebrew_bin, environment.get("PATH", os.defpath),
        ))
    return environment


def extract_title(raw_title, artist):
    parts = re.split(r"\s*[|]\s*|\s+[-–—]\s+", raw_title)
    artist_key = normalized(artist)
    for index, part in enumerate(parts):
        if artist_key and artist_key in normalized(part):
            parts = parts[index + 1:] if index == 0 else parts[:index]
            break
    title = parts[0].strip() if parts else ""
    title = re.sub(r"\([^)]*[\u0d80-\u0dff][^)]*\)", "", title).strip()
    title = re.sub(
        r"\s*[\[(]official\s+(?:music\s+)?(?:video|audio|lyric\s*video)[\])].*$",
        "", title, flags=re.I,
    ).strip()
    return title



def search_entries(query, checkpoint):
    # Stream all search pages so discovery stays responsive to Pause and End.
    with TemporaryFile(mode="w+") as errors:
        process = subprocess.Popen(
            [executable(), "--flat-playlist", "--lazy-playlist", "--dump-json",
             "--skip-download", "--quiet", "--no-warnings", "--socket-timeout", "15",
             "--retries", "1", "--extractor-retries", "1", "ytsearchall:" + query],
            stdout=subprocess.PIPE, stderr=errors, text=True, env=command_environment(),
        )
        output = queue.Queue()

        def read_output():
            try:
                for line in process.stdout:
                    output.put(line)
            finally:
                output.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            while True:
                checkpoint()
                try:
                    line = output.get(timeout=0.5)
                except queue.Empty:
                    continue
                if line is None:
                    break
                yield json.loads(line)
            if process.wait():
                errors.seek(0)
                raise RuntimeError("Public music search failed. " + errors.read()[-250:])
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            reader.join(timeout=1)
            process.stdout.close()


def discover(artist, limit=None, genre="", category="all", checkpoint=lambda: None):
    query = f"{artist} {genre} official music"
    if category != "all":
        query += " single" if category == "single" else " album track"
    tracks = []
    seen = set()
    with closing(search_entries(query, checkpoint)) as entries:
        for entry in entries:
            checkpoint()
            duration = entry.get("duration")
            channel = normalized(entry.get("channel") or "")
            title = entry.get("title") or ""
            # Restrict automatic matches to artist-named channels and individual songs.
            if not duration or not 60 <= duration <= 600 or normalized(artist) not in channel:
                continue
            if re.search(r"\b(cover|karaoke|reaction|tutorial|collection|nonstop|medley)\b", title, re.I):
                continue
            song_title = extract_title(title, artist)
            if not song_title or normalized(song_title) == normalized(artist):
                continue
            video_id = entry.get("id", "")
            if video_id in seen or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                continue
            seen.add(video_id)
            tracks.append({
                "id": "yt_" + video_id,
                "name": song_title,
                "artist_name": artist,
                "source": "youtube",
                "audiodownload": "https://www.youtube.com/watch?v=" + video_id,
            })
            if limit is not None and len(tracks) >= limit:
                break
    return tracks


def download(url, path, available):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg and (Path.home() / ".spotdl" / "ffmpeg").is_file():
        ffmpeg = str(Path.home() / ".spotdl" / "ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for MP3 conversion.")
    result = subprocess.run(
        [executable(), "--no-playlist", "--quiet", "--no-warnings", "--no-progress",
         "--socket-timeout", "15", "--retries", "1", "--extractor-retries", "1",
         "--max-filesize", str(available), "-f", "bestaudio/best",
         "--ffmpeg-location", ffmpeg, "-x", "--audio-format", "mp3",
         "--audio-quality", "192K", "-o", str(path.with_suffix(".%(ext)s")), url],
        capture_output=True, text=True, timeout=240, env=command_environment(),
    )
    if result.returncode or not path.is_file():
        raise RuntimeError("Audio retrieval failed. " + result.stderr.strip()[-250:])
    return path.stat().st_size
