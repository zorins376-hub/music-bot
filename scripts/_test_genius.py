#!/usr/bin/env python3
"""Test Genius search without auth token (public endpoint)."""
import requests, json

# Method 1: Public Genius search (no token)
print("=== Public Genius search (no token) ===")
try:
    r = requests.get(
        "https://genius.com/api/search/multi",
        params={"per_page": 3, "q": "Ари Ури мы на Иссык куле"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    data = r.json()
    sections = data.get("response", {}).get("sections", [])
    for sec in sections:
        sec_type = sec.get("type", "?")
        hits = sec.get("hits", [])
        if hits and sec_type == "song":
            print(f"  Section: {sec_type} ({len(hits)} hits)")
            for h in hits[:5]:
                song = h.get("result", {})
                artist = song.get("primary_artist", {}).get("name", "")
                title = song.get("title", "")
                print(f"    {artist} - {title}")
except Exception as e:
    print(f"  Failed: {e}")

# Method 2: Another query
print("\n=== Public Genius: 'скучаю по тебе' ===")
try:
    r = requests.get(
        "https://genius.com/api/search/multi",
        params={"per_page": 3, "q": "скучаю по тебе"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    data = r.json()
    sections = data.get("response", {}).get("sections", [])
    for sec in sections:
        if sec.get("type") == "song":
            for h in sec.get("hits", [])[:3]:
                song = h.get("result", {})
                print(f"    {song.get('primary_artist',{}).get('name','')} - {song.get('title','')}")
except Exception as e:
    print(f"  Failed: {e}")
