# MP3 BOT

MP3 BOT uploads music to MEGA and supports local MP3 downloads from Spotify playlists, albums, and tracks.

It works by scraping Spotify's public embed pages and matching the audio on YouTube Music. **No Spotify Premium or API keys are required!**

<img width="958" height="850" alt="image" src="https://github.com/user-attachments/assets/39a470f2-e68d-4c86-9b4a-9248e9b83331" />

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

**Spotify downloader usage**

The Spotify downloader is below the MEGA section.

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

## MEGA music bot

The bot picks one artist per run from [Jamendo](https://developer.jamendo.com/v3.0/tracks), creates an artist folder in each destination, and uploads MP3s that the artist has enabled for download. It stages one track at a time in a temporary directory and skips previously uploaded tracks when you rerun it.

1. Install [MEGAcmd](https://github.com/meganz/MEGAcmd) and sign in to the destination account in its interactive shell (`/Applications/MEGAcmd.app/Contents/MacOS/MEGAcmdShell` on macOS, then `login YOUR_EMAIL`). On macOS, if the commands are missing from your terminal, run `export PATH="/Applications/MEGAcmd.app/Contents/MacOS:$PATH"`.
2. Register a [Jamendo application](https://devportal.jamendo.com/), set `JAMENDO_CLIENT_ID` in your terminal, and activate your Python environment.
3. Start `python app.py` and open [the dashboard](http://127.0.0.1:5050/). Enter one MEGA folder link or cloud path per line, choose your preferences, and click **Start Bot**. **Pause** waits for the current operation to finish, **Resume** continues the same run, and **End** finishes the current operation and stops the run. The dashboard also accepts your Client ID if the server environment does not provide it.

You can also run the bot from the terminal.

```bash
export JAMENDO_CLIENT_ID='your-client-id'
python mega_bot.py \
  --dest 'https://mega.nz/folder/YOUR_ID#YOUR_KEY' '/Music Backup' \
  --country LKA --genre pop --category all --limit 20 --max-storage-gb 15
```

- **Destinations** accept multiple quoted folder links and existing cloud paths from the same signed-in MEGA account. Use the folder's direct link or its absolute cloud path.
- **Country** uses a three-letter code such as `LKA`, `IND`, or `USA`. Jamendo uses artist-reported locations.
- **Genre** accepts tags such as `pop`, `hiphop`, or `jazz`. **Category** accepts `all`, `single`, or `albumtrack`. Set `--artist 'Artist Name'` to select a specific Jamendo artist.
- **Storage** is checked account-wide before each upload. The bot stops when the next track would exceed the available space across the destinations. Omit `--max-storage-gb` to use the MEGA account quota alone.
