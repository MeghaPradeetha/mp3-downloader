# 🎵 Spotify MP3 Downloader

A powerful, modern Web Application and CLI tool to download entire Spotify **playlists**, **albums**, and **individual tracks** directly to your device as high-quality **320 kbps MP3 files**. 

It works by scraping Spotify's public embed pages and matching the audio on YouTube Music. **No Spotify Premium or API keys are required!**

![Spotify Downloader Web UI](https://i.imgur.com/Kxz956Q.png) *(Note: Replace with your actual screenshot)*

## ✨ Features

- **No API Keys Needed:** Bypasses Spotify API limitations and rate limits completely.
- **No Premium Required:** Works entirely with free public endpoints.
- **High Quality:** Downloads in 320 kbps MP3 by default (configurable).
- **ID3 Metadata:** Automatically embeds artist, title, and album metadata into the downloaded MP3 files.
- **Anti-Blocking:** Uses custom `yt-dlp` configurations (like `android_vr` client spoofing) to bypass recent YouTube 403 Forbidden errors.
- **Beautiful Web UI:** Modern, dark-themed interface with real-time download progress and logs.
- **Auto FFmpeg:** Automatically detects or downloads `ffmpeg` if you don't have it installed.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.8 or higher installed on your system.

### 1. Clone the repository
```bash
git clone https://github.com/yourusername/spotify-downloader.git
cd spotify-downloader
```

### 2. Create a Virtual Environment
It's highly recommended to use a virtual environment to manage dependencies.
```bash
# macOS and Linux
python3 -m venv .venv
source .venv/bin/activate

# Windows
python -m venv .venv
.venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 💻 How to Run Locally

### Running the Web App (Recommended)
You can start the beautiful web interface by running:
```bash
python app.py
```
*Alternatively, on macOS/Linux, you can just run `./start.sh`.*

Once started, open your browser and navigate to: **[http://localhost:5050](http://localhost:5050)**

**Usage:**
1. Copy a link to a Spotify Playlist, Album, or Track.
2. Paste it into the Web UI.
3. Click **Download MP3s**.
4. The files will be saved in the `downloads/` folder inside the project directory.

### Running via CLI (Command Line)
If you prefer using the terminal, you can use the CLI script directly:
```bash
# Download a playlist
python download.py "https://open.spotify.com/playlist/..."

# Change output directory and format
python download.py "https://open.spotify.com/track/..." -o ./my_music -f flac -b 320k
```

For all CLI options:
```bash
python download.py --help
```

---

## 🛠️ Tech Stack
- **Backend:** Python, Flask
- **Downloading:** `yt-dlp` (YouTube Music audio fetching)
- **Scraping:** Custom regex and HTML parsing for Spotify Embeds
- **Frontend:** HTML5, CSS3 (Custom Glassmorphism UI), Vanilla JavaScript
- **Audio Processing:** FFmpeg

## ⚠️ Disclaimer
This tool is for educational and personal use only. Downloading copyrighted material without permission may be against the terms of service of streaming platforms and local laws. Use responsibly.
