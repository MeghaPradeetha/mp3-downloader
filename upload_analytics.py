"""Persistent per-run upload statistics for the local dashboard."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

EVENT_PREFIX = "[mp3-bot-event]"


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS runs "
        "(id TEXT PRIMARY KEY, started TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL)"
    )
    return connection


def begin(path, partial=False):
    run_id = uuid4().hex
    started = datetime.now(timezone.utc).isoformat()
    data = {"artists": {}, "transfers": {}, "partial": partial, "current_artist": None}
    with connect(path) as connection:
        connection.execute("INSERT INTO runs VALUES (?, ?, ?, ?)", (
            run_id, started, "running", json.dumps(data),
        ))
    return run_id


def record(path, run_id, event):
    with connect(path) as connection:
        row = connection.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return
        data = json.loads(row[0])
        name = event.get("artist")
        if name:
            artist = data["artists"].setdefault(name, {
                "name": name, "status": "searching", "tracks": {}, "candidates": [],
            })
            kind = event["type"]
            if kind == "artist_started":
                artist["status"] = "processing"
                artist["candidates"] = list(dict.fromkeys(
                    artist["candidates"] + event.get("track_ids", []),
                ))
                data["current_artist"] = name
            elif kind == "artist_searching":
                artist["status"] = "searching"
                data["current_artist"] = name
            elif kind in ("track_uploaded", "track_skipped", "track_failed"):
                track_id = str(event["track_id"])
                outcome = kind.removeprefix("track_")
                previous = artist["tracks"].get(track_id, {})
                if outcome == "uploaded" or previous.get("outcome") != "uploaded":
                    artist["tracks"][track_id] = {
                        "title": event.get("title", ""), "outcome": outcome,
                    }
                if outcome == "uploaded":
                    key = json.dumps([name, track_id, event.get("destination", "")])
                    data["transfers"][key] = int(event.get("bytes", 0))
            elif kind in ("artist_finished", "artist_no_matches", "artist_search_failed"):
                artist["status"] = {
                    "artist_finished": "complete",
                    "artist_no_matches": "complete" if artist["tracks"] else "no_matches",
                    "artist_search_failed": "search_failed",
                }[kind]
                data["current_artist"] = None
        connection.execute("UPDATE runs SET data=? WHERE id=?", (json.dumps(data), run_id))


def finish(path, run_id, status):
    with connect(path) as connection:
        row = connection.execute("SELECT data FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            return
        data = json.loads(row[0])
        for artist in data["artists"].values():
            if artist["status"] in ("processing", "searching"):
                artist["status"] = "interrupted"
        data["current_artist"] = None
        connection.execute("UPDATE runs SET status=?, data=? WHERE id=?", (
            status, json.dumps(data), run_id,
        ))


def snapshot(path, run_id=None):
    with connect(path) as connection:
        if run_id:
            row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        else:
            row = connection.execute("SELECT * FROM runs ORDER BY started DESC LIMIT 1").fetchone()
        history = [
            {"id": item[0], "started": item[1], "status": item[2]}
            for item in connection.execute("SELECT id, started, status FROM runs ORDER BY started DESC LIMIT 30")
        ]
    result = {"run": None, "history": history}
    if row is None:
        return result
    data = json.loads(row[3])
    artists = []
    for item in data["artists"].values():
        outcomes = [track["outcome"] for track in item["tracks"].values()]
        artists.append({
            "name": item["name"], "status": item["status"],
            "candidates": len(item["candidates"]), "processed": len(outcomes),
            "uploaded": outcomes.count("uploaded"), "skipped": outcomes.count("skipped"),
            "failed": outcomes.count("failed"),
        })
    result["run"] = {
        "id": row[0], "started": row[1], "status": row[2], "partial": data["partial"],
        "current_artist": data["current_artist"], "artists": artists,
        "uploaded": sum(a["uploaded"] for a in artists),
        "skipped": sum(a["skipped"] for a in artists),
        "failed": sum(a["failed"] for a in artists),
        "completed_artists": sum(a["status"] == "complete" for a in artists),
        "file_copies": len(data["transfers"]),
        "uploaded_bytes": sum(data["transfers"].values()),
    }
    return result
