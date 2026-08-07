#!/usr/bin/env python3
"""
Spotify Public Scraper - No API Key Required
Extracts track metadata from Spotify's public embed/oembed endpoints.
Works without Spotify Premium or API credentials.
"""

import re
import json
import requests
import html

def extract_spotify_id_and_type(url):
    """Extract the Spotify ID and type (track/playlist/album) from a URL."""
    url = url.split("?")[0]  # Remove query params
    patterns = [
        r'open\.spotify\.com/(track|playlist|album|artist)/([a-zA-Z0-9]+)',
        r'spotify\.link/([a-zA-Z0-9]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            groups = match.groups()
            if len(groups) == 2:
                return groups[0], groups[1]
            else:
                # spotify.link short URL - resolve it
                try:
                    resp = requests.head(url, allow_redirects=True, timeout=10)
                    return extract_spotify_id_and_type(resp.url)
                except Exception:
                    return None, None
    return None, None


def scrape_embed_page(spotify_type, spotify_id):
    """
    Scrape Spotify's embed page to get track listing.
    The embed pages are public and don't require authentication.
    """
    embed_url = f"https://open.spotify.com/embed/{spotify_type}/{spotify_id}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    try:
        resp = requests.get(embed_url, headers=headers, timeout=15)
        resp.raise_for_status()
        page_html = resp.text
        
        # Look for the __NEXT_DATA__ JSON blob
        next_data_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', page_html, re.DOTALL)
        if next_data_match:
            data = json.loads(next_data_match.group(1))
            return parse_next_data(data, spotify_type)
        
        # Fallback: look for resource data in script tags
        resource_match = re.search(r'"entity":\s*({.*?})\s*[,}]', page_html, re.DOTALL)
        if resource_match:
            try:
                entity = json.loads(resource_match.group(1))
                return parse_entity(entity, spotify_type)
            except json.JSONDecodeError:
                pass

        return None
    except Exception as e:
        print(f"Error scraping embed page: {e}")
        return None


def parse_next_data(data, spotify_type):
    """Parse __NEXT_DATA__ from Spotify embed page."""
    try:
        props = data.get("props", {}).get("pageProps", {})
        state = props.get("state", {}).get("data", {})
        entity = state.get("entity", {})
        return parse_entity(entity, spotify_type)
    except Exception as e:
        print(f"Error parsing next data: {e}")
        return None


def parse_entity(entity, spotify_type):
    """Parse entity data to extract track information."""
    tracks = []
    
    if spotify_type == "track":
        track = extract_track_info(entity)
        if track:
            tracks.append(track)
    
    elif spotify_type in ("playlist", "album"):
        title = entity.get("name", "Unknown")
        track_list = entity.get("trackList", [])
        
        for item in track_list:
            track = {
                "title": html.unescape(item.get("title", "Unknown")),
                "artist": html.unescape(item.get("subtitle", "Unknown")),
                "album": title if spotify_type == "album" else "",
                "duration_ms": item.get("duration", 0),
                "uri": item.get("uri", ""),
            }
            if track["title"] and track["title"] != "Unknown":
                tracks.append(track)
    
    return {
        "name": entity.get("name", "Unknown"),
        "type": spotify_type,
        "tracks": tracks,
        "total": len(tracks)
    }


def extract_track_info(entity):
    """Extract single track info from entity."""
    return {
        "title": html.unescape(entity.get("name", entity.get("title", "Unknown"))),
        "artist": html.unescape(entity.get("subtitle", entity.get("artists", [{}])[0].get("name", "Unknown") if isinstance(entity.get("artists"), list) else "Unknown")),
        "album": entity.get("albumName", ""),
        "duration_ms": entity.get("duration", 0),
        "uri": entity.get("uri", ""),
    }


def get_spotify_tracks(url):
    """
    Main entry point: Given a Spotify URL, return track listing.
    No API credentials needed.
    """
    spotify_type, spotify_id = extract_spotify_id_and_type(url)
    if not spotify_type or not spotify_id:
        raise ValueError(f"Could not parse Spotify URL: {url}")
    
    print(f"🔍 Scraping {spotify_type}: {spotify_id}")
    result = scrape_embed_page(spotify_type, spotify_id)
    
    if not result or not result.get("tracks"):
        # Fallback: try oembed API for basic info
        result = try_oembed_fallback(url, spotify_type, spotify_id)
    
    if not result or not result.get("tracks"):
        raise ValueError(f"Could not extract tracks from Spotify URL. The playlist may be private.")
    
    return result


def try_oembed_fallback(url, spotify_type, spotify_id):
    """Try Spotify oembed API as a fallback for basic info."""
    try:
        oembed_url = f"https://open.spotify.com/oembed?url={url}"
        resp = requests.get(oembed_url, timeout=10)
        data = resp.json()
        # oembed only gives us the title, not individual tracks
        return {
            "name": data.get("title", "Unknown"),
            "type": spotify_type,
            "tracks": [],
            "total": 0
        }
    except Exception:
        return None


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python spotify_scraper.py <spotify_url>")
        sys.exit(1)
    
    result = get_spotify_tracks(sys.argv[1])
    print(f"\n📀 {result['name']} ({result['type']})")
    print(f"🎵 {result['total']} tracks found:\n")
    for i, track in enumerate(result['tracks'], 1):
        print(f"  {i:3d}. {track['artist']} - {track['title']}")
