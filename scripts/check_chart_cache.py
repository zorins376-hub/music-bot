"""Check what's in the Redis chart cache."""
import asyncio
import json


async def main():
    from bot.services.cache import cache
    await cache.connect()

    for source in ("vk", "shazam", "youtube", "rusradio", "europa"):
        raw = await cache.redis.get(f"chart:{source}")
        if not raw:
            print(f"chart:{source} — NOT IN CACHE")
            continue
        tracks = json.loads(raw)
        no_cover = [t for t in tracks if not t.get("cover_url")]
        no_vid = [t for t in tracks if not t.get("video_id")]
        print(f"chart:{source} — {len(tracks)} tracks, {len(no_cover)} without cover, {len(no_vid)} without video_id")

        for t in no_cover[:3]:
            print(f"  NO COVER: {t.get('artist')} - {t.get('title')} | vid={t.get('video_id', '')} src={t.get('source', '')}")
        for t in no_vid[:3]:
            print(f"  NO VID:   {t.get('artist')} - {t.get('title')}")

        # Check a specific track
        for i, t in enumerate(tracks):
            if "ворон" in t.get("title", "").lower():
                print(f"  FOUND '{t['title']}' at #{i+1}: vid={t.get('video_id')} cover={t.get('cover_url', 'NONE')}")

    await cache.close()


asyncio.run(main())
