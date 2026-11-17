#!/usr/bin/env bash
# Startup script for MP3 BOT

PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
CD_CMD="cd \"$PROJECT_DIR\""
eval $CD_CMD

echo "================================================"
echo "  🎵 MP3 BOT Quick Launcher 🎵"
echo "================================================"

# Check Python environment
if [ -d "venv" ]; then
    VENV_PATH="venv"
elif [ -d ".venv" ]; then
    VENV_PATH=".venv"
else
    echo "⚙️ Creating Python virtual environment (venv)..."
    python3 -m venv venv
    VENV_PATH="venv"
fi

echo "📦 Verifying dependencies..."
$VENV_PATH/bin/pip install -r requirements.txt > /dev/null 2>&1

chmod +x download.py app.py

echo ""
echo "Select mode to run:"
echo " 1) 🌐 Web UI App (Browser Dashboard at http://localhost:5050)"
echo " 2) 💻 Command Line (CLI Script)"
echo ""
read -p "Enter choice [1 or 2] (default: 1): " choice
choice=${choice:-1}

if [ "$choice" = "1" ]; then
    echo "🟢 Starting Web Dashboard..."
    echo "👉 Open http://localhost:5050 in your browser"
    $VENV_PATH/bin/python app.py
else
    read -p "Enter media link: " spotify_url
    if [ -z "$spotify_url" ]; then
        echo "No URL provided. Exiting."
        exit 1
    fi
    $VENV_PATH/bin/python download.py "$spotify_url"
fi
