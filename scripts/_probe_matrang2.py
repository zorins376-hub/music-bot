#!/usr/bin/env python3
import asyncio
from bot.services.downloader import search_tracks
from bot.services.spotify_provider import search_spotify
from bot.services.vk_provider import search_vk
from bot.services.lyrics_provider import search_by_lyrics

async def main():
    q = "матранг рука"
    print("=== YOUTUBE ===")
    for t in (await search_tracks(q, max_results=8, source="youtube"))[:8]:
        print(f"  {t.get('uploader')} — {t.get('title')}")
    print("=== SPOTIFY ===")
    for t in (await search_spotify(q, limit=8))[:8]:
        print(f"  {t.get('uploader')} — {t.get('title')}")
    print("=== VK ===")
    for t in (await search_vk(q, limit=8))[:8]:
        print(f"  {t.get('uploader')} — {t.get('title')}")
    print("=== LYRICS ===")
    for h in await search_by_lyrics(q, limit=5):
        print(f"  {h.get('artist')} — {h.get('title')} [{h.get('source')}]")

asyncio.run(main())
