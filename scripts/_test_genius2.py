#!/usr/bin/env python3
"""Test Genius public API from VPS."""
import requests, json

queries = [
    "Ари Ури мы на Иссык куле",
    "Треск Акапелла",
]

for q in queries:
    print(f"\nQuery: {q}")
    try:
        r = requests.get(
            "https://genius.com/api/search/multi",
            params={"per_page": 3, "q": q},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        data = r.json()
        sections = data.get("response", {}).get("sections", [])
        for sec in sections:
            if sec.get("type") == "song" and sec.get("hits"):
                for h in sec["hits"][:3]:
                    song = h["result"]
                    artist = song.get("primary_artist", {}).get("name", "")
                    title = song.get("title", "")
                    print(f"  {artist} - {title}")
    except Exception as e:
        print(f"  Error: {e}")

# Also test the official API endpoint with no token
print("\n=== api.genius.com /search (no token) ===")
try:
    r = requests.get(
        "https://api.genius.com/search",
        params={"q": "Ари Ури мы на Иссык куле"},
        timeout=10,
    )
    print(f"  Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        hits = data.get("response", {}).get("hits", [])
        for h in hits[:3]:
            song = h["result"]
            print(f"  {song.get('primary_artist',{}).get('name','')} - {song.get('title','')}")
except Exception as e:
    print(f"  Error: {e}")
