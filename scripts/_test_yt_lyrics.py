#!/usr/bin/env python3
"""Test YouTube search with 'lyrics' hint vs 'audio' hint."""
import yt_dlp

QUERY = "Ари Ури мы на Иссык куле"

for suffix in ["audio", "lyrics", "текст песни"]:
    q = f"{QUERY} {suffix}"
    print(f"\n=== ytsearch: '{q}' ===")
    opts = {"extract_flat": "in_playlist", "quiet": True, "no_warnings": True, "default_search": "ytsearch5"}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(q, download=False)
            for e in (info.get("entries") or [])[:5]:
                if e:
                    dur = e.get("duration", 0)
                    up = e.get("uploader", "")
                    ti = e.get("title", "")
                    print(f"  {up} - {ti} (dur={dur})")
    except Exception as ex:
        print(f"  Error: {ex}")
