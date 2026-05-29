"""Quick check: is data still on Supabase REST API?"""
import asyncio, aiohttp, json

SUPA_URL = "https://uhvbdwjchxcnoiodfnvw.supabase.co"
SUPA_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVodmJkd2pjaHhjbm9pb2RmbnZ3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTg1MDAwOSwiZXhwIjoyMDg3NDI2MDA5fQ.tLm2O84rRZHgcoPQgbgb8zVC3zRCBzy54xS0qCF_6Gw"

HEADERS = {
    "Authorization": f"Bearer {SUPA_KEY}",
    "apikey": SUPA_KEY,
    "Content-Type": "application/json",
    "Prefer": "count=exact",
}

TABLES = ["users", "tracks", "playlists", "playlist_tracks", "favorite_tracks", "listening_history"]

async def main():
    async with aiohttp.ClientSession() as s:
        for t in TABLES:
            url = f"{SUPA_URL}/rest/v1/{t}?select=*&limit=1"
            async with s.get(url, headers=HEADERS) as r:
                count = r.headers.get("content-range", "?")
                body = await r.json()
                status = r.status
                print(f"{t:25s}  status={status}  range={count}  sample={json.dumps(body[:1], default=str, ensure_ascii=False)[:200] if body else 'empty'}")

asyncio.run(main())
