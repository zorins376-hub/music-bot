"""Quick check: is data still on Supabase REST API?"""
import asyncio, aiohttp, json, os

SUPA_URL = os.environ.get("SUPABASE_URL", "https://uhvbdwjchxcnoiodfnvw.supabase.co")
SUPA_KEY = os.environ["SUPABASE_SERVICE_KEY"]

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
