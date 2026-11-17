#!/usr/bin/env python3
"""Pick a Jamendo artist and upload their downloadable tracks to MEGA."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import requests
from mutagen import MutagenError
from mutagen.mp3 import MP3


class BotError(Exception):
    pass


class StorageLimit(Exception):
    pass


class RunEnded(Exception):
    pass


def dashboard_checkpoint():
    condition = threading.Condition()
    action = "resume"

    def listen():
        nonlocal action
        with os.fdopen(os.dup(sys.stdin.fileno()), "rb", buffering=0) as commands:
            for line in commands:
                command = line.strip().decode("ascii", errors="ignore")
                if command in ("pause", "resume", "end"):
                    with condition:
                        action = command
                        condition.notify_all()
                    if command == "end":
                        return
        with condition:
            action = "end"
            condition.notify_all()

    def checkpoint():
        with condition:
            if action == "pause":
                print("[bot paused]", flush=True)
                condition.wait_for(lambda: action != "pause")
            if action == "end":
                raise RunEnded

    threading.Thread(target=listen, daemon=True).start()
    return checkpoint


def continue_run():
    pass


def mega(command, *args):
    try:
        result = subprocess.run(
            [f"mega-{command}", *args], capture_output=True, text=True, check=False,
        )
    except FileNotFoundError as exc:
        raise BotError("Install MEGAcmd and put its commands on PATH.") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise BotError(f"MEGA {command} failed. {detail}")
    return result.stdout


def destinations(values):
    paths = []
    folders_by_handle = None
    for value in values:
        if value.startswith("/") and not value.startswith("//"):
            path = value.rstrip("/") or "/"
        else:
            link = urlsplit(value)
            match = re.fullmatch(r"/folder/([A-Za-z0-9_-]{8})/?", link.path)
            if "/" in link.fragment:
                raise BotError("Use a direct folder link or the subfolder's MEGA cloud path.")
            if not match and link.path in ("", "/"):
                match = re.fullmatch(r"F!([\w-]{8})(?:![\w-]+)?", link.fragment)
            if link.scheme != "https" or link.netloc not in ("mega.nz", "mega.co.nz") or not match:
                raise BotError("Use a MEGA folder link or an absolute MEGA cloud path.")
            if folders_by_handle is None:
                folders_by_handle = {}
                for line in mega("export", "/").splitlines():
                    entry = re.match(
                        r"^(/.*) \(folder, .*?folder link: https://mega\.(?:nz|co\.nz)"
                        r"/(?:folder/|#F!)([A-Za-z0-9_-]{8})(?=[#! )]|$)",
                        line,
                    )
                    if entry:
                        folders_by_handle[entry[2]] = entry[1]
            path = folders_by_handle.get(match[1])
            if not path:
                raise BotError("The folder link must point to a folder in your signed-in MEGA account.")
        if re.search(r"[\x00-\x1f*?\[\]\\]", path) or any(
            part in (".", "..") for part in path.split("/")
        ):
            raise BotError("Use a MEGA folder path without wildcards, escapes, or dot segments.")
        path = "/" + "/".join(filter(None, path.split("/")))
        if path not in paths:
            paths.append(path)
    return paths


def quota():
    match = re.search(
        r"^USED STORAGE:\s*(\d+)(?:\s*B)?\s+\S+%?\s+of\s+(\d+)(?:\s*B)?\s*$",
        mega("df"), re.MULTILINE,
    )
    if not match or int(match[2]) <= 0:
        raise BotError("Could not read MEGA storage in bytes. Check your MEGAcmd login.")
    return int(match[1]), int(match[2])


def catalog(session, client_id, endpoint, **filters):
    try:
        response = session.get(
            f"https://api.jamendo.com/v3.0/{endpoint}/",
            params={"client_id": client_id, "format": "json", **filters},
            timeout=(10, 30),
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise BotError("Could not reach the Jamendo catalog. Check network access.") from exc
    headers = data["headers"]
    if headers["code"] != 0:
        if endpoint == "artists/locations" and headers["code"] == 1:
            raise BotError(
                "Jamendo's artist-country lookup is unavailable. "
                "Clear Artist country and use Genre or Artist name to run without a country filter."
            )
        raise BotError(f"Jamendo rejected the request. {headers['error_message']}")
    return data["results"]


def catalog_pages(session, client_id, endpoint, page_size=100, checkpoint=continue_run, **filters):
    offset = 0
    while True:
        checkpoint()
        page = catalog(session, client_id, endpoint, limit=page_size, offset=offset, **filters)
        if not page and offset == 0 and endpoint == "tracks":
            # Jamendo sometimes returns an empty first page for larger queries.
            page_size = 8
            page = catalog(session, client_id, endpoint, limit=page_size, **filters)
        if not page:
            break
        yield page
        offset += len(page)
        if len(page) < page_size:
            break


def downloadable(tracks):
    return [
        track for track in tracks
        if track.get("audiodownload_allowed") is True and track.get("audiodownload")
    ]


def select_tracks(session, client_id, args, checkpoint=continue_run):
    track_type = "single albumtrack" if args.category == "all" else args.category
    filters = {"type": track_type, "audiodlformat": "mp32"}
    if args.genre:
        genre = args.genre.strip().lower()
        filters["tags"] = {"hip hop": "hiphop", "hip-hop": "hiphop"}.get(genre, genre)
        filters["boost"] = "popularity_total"
    else:
        filters["order"] = "popularity_total"
    if args.artist:
        filters["artist_name"] = args.artist
    if args.country:
        artist_filters = {"location_country": args.country, "order": "popularity_total"}
        if args.artist:
            artist_filters["name"] = args.artist
        artist_pages = catalog_pages(
            session, client_id, "artists/locations", page_size=20, checkpoint=checkpoint, **artist_filters,
        )
        groups = ({"artist_id": " ".join(artist["id"] for artist in page)} for page in artist_pages)
    else:
        groups = ({},)

    for group in groups:
        for page in catalog_pages(session, client_id, "tracks", checkpoint=checkpoint, **filters, **group):
            matches = downloadable(page)
            if matches:
                artist_id = matches[0]["artist_id"]
                artist_tracks = {track["id"]: track for track in matches if track["artist_id"] == artist_id}
                if len(artist_tracks) >= args.limit:
                    return list(artist_tracks.values())[:args.limit]
                # Fetch additional matches for the selected artist only.
                for artist_page in catalog_pages(
                    session, client_id, "tracks", checkpoint=checkpoint, **{**filters, "artist_id": artist_id},
                ):
                    for track in downloadable(artist_page):
                        artist_tracks[track["id"]] = track
                        if len(artist_tracks) >= args.limit:
                            return list(artist_tracks.values())
                return list(artist_tracks.values())
    raise BotError("Jamendo has no downloadable tracks for those preferences.")


def safe_name(value):
    return re.sub(r'[\x00-\x1f<>:"/\\|?*\[\]]', "_", value).strip(" .")[:75] or "Untitled"


def fetch_audio(session, url, path, available):
    try:
        with session.get(url, stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            size = 0
            with path.open("wb") as output:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > available:
                        raise StorageLimit("The next track will exceed the storage limit.")
                    output.write(chunk)
    except requests.RequestException as exc:
        raise BotError("Could not retrieve the track from Jamendo.") from exc
    if not size:
        raise BotError("Jamendo returned an empty audio file.")
    try:
        MP3(path)
    except MutagenError as exc:
        raise BotError("Jamendo returned an invalid MP3 file.") from exc
    return size


def upload(session, tracks, roots, max_bytes, checkpoint=continue_run):
    artist = safe_name(tracks[0]["artist_name"])
    print(f"Selected {artist}. Found {len(tracks)} downloadable tracks.", flush=True)
    used, ceiling = quota()

    def remaining():
        current, capacity = quota()
        return min(capacity, max_bytes or capacity) - max(current, used)

    folders = [f"{root.rstrip('/')}/{artist}" for root in roots]
    contents = {}
    for root, folder in zip(roots, folders):
        checkpoint()
        if artist in listed_names(root):
            contents[folder] = listed_names(folder)

    copies = 0
    try:
        with TemporaryDirectory(prefix="mega-music-") as temporary:
            for track in tracks:
                checkpoint()
                name = f"{safe_name(track['name'])} [{track['id']}].mp3"
                pending = [folder for folder in folders if name not in contents.get(folder, ())]
                if not pending:
                    print(f"Already uploaded {name}", flush=True)
                    continue
                available = remaining() // len(pending)
                if available <= 0:
                    raise StorageLimit("MEGA storage limit reached.")
                path = Path(temporary, name)
                size = fetch_audio(session, track["audiodownload"], path, available)
                if size * len(pending) > remaining():
                    raise StorageLimit("The next track will exceed the storage limit.")
                for folder in pending:
                    checkpoint()
                    current, capacity = quota()
                    used = max(current, used)
                    if used + size > min(capacity, max_bytes or capacity):
                        raise StorageLimit("MEGA storage limit reached.")
                    if folder not in contents:
                        mega("mkdir", "-p", folder)
                        contents[folder] = set()
                    mega("put", str(path), folder + "/")
                    contents[folder].add(name)
                    used += size
                    copies += 1
                    print(f"Uploaded {folder}/{name}", flush=True)
                    checkpoint()
                path.unlink()
    except StorageLimit as exc:
        print(f"Stopped. {exc}")
    print(f"Uploaded {copies} file copies to MEGA.")


def listed_names(folder):
    return {line.rsplit("/", 1)[-1] for line in mega("ls", folder).splitlines()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", nargs="+", action="extend", required=True, help="MEGA folder links or cloud paths")
    parser.add_argument("--country", type=str.upper, help="Three-letter country code, e.g. LKA, IND, or USA")
    parser.add_argument("--genre", help="Jamendo genre/tag, e.g. pop or hiphop")
    parser.add_argument("--artist", help="Exact Jamendo artist name. Omit to select automatically.")
    parser.add_argument("--category", choices=("all", "single", "albumtrack"), default="all")
    parser.add_argument("--limit", type=int, default=20, help="Maximum tracks per run (default 20)")
    parser.add_argument("--max-storage-gb", type=float, help="Optional account storage cap in decimal GB")
    parser.add_argument("--dashboard-control", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.country and not re.fullmatch(r"[A-Z]{3}", args.country):
        parser.error("--country needs a three-letter code, such as LKA.")
    if args.limit < 1:
        parser.error("--limit must be positive.")
    if args.max_storage_gb is not None and not (0.000000001 <= args.max_storage_gb <= sys.maxsize):
        parser.error("--max-storage-gb must be a finite positive size of at least one byte.")
    max_bytes = int(args.max_storage_gb * 1_000_000_000) if args.max_storage_gb else None
    client_id = os.environ.get("JAMENDO_CLIENT_ID")
    if not client_id:
        parser.error("Set the JAMENDO_CLIENT_ID environment variable.")

    checkpoint = dashboard_checkpoint() if args.dashboard_control else continue_run
    try:
        checkpoint()
        roots = destinations(args.dest)
        checkpoint()
        used, capacity = quota()
        if used >= min(capacity, max_bytes or capacity):
            print("Stopped. MEGA storage limit reached.")
            return 0
        with requests.Session() as session:
            tracks = select_tracks(session, client_id, args, checkpoint)
            upload(session, tracks, roots, max_bytes, checkpoint)
    except (BotError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (RunEnded, KeyboardInterrupt):
        print("Run ended by user.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
