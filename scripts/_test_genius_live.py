import asyncio
import aiohttp
import time

async def test_genius():
    # Test 1: Public multi endpoint (no token needed)
    t0 = time.monotonic()
    url = "https://genius.com/api/search/multi"
    params = {"q": "billie jean is not my lover", "per_page": 5}
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"},
                         timeout=aiohttp.ClientTimeout(total=10)) as resp:
            data = await resp.json()
            sections = data.get("response", {}).get("sections", [])
            for sec in sections:
                if sec.get("type") == "song":
                    for hit in sec.get("hits", [])[:3]:
                        song = hit.get("result", {})
                        artist = song.get("primary_artist", {}).get("name", "")
                        title = song.get("title", "")
                        print(f"  HIT: {artist} - {title}")
    elapsed = time.monotonic() - t0
    print(f"Public endpoint took {elapsed:.2f}s")

    # Test 2: Other English queries
    queries = [
        "hello from the other side",
        "i bless the rains down in africa",
        "welcome to the hotel california",
        "its the final countdown",
    ]
    for q in queries:
        t0 = time.monotonic()
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params={"q": q, "per_page": 3},
                             headers={"User-Agent": "Mozilla/5.0"},
                             timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                sections = data.get("response", {}).get("sections", [])
                found = False
                for sec in sections:
                    if sec.get("type") == "song":
                        for hit in sec.get("hits", [])[:1]:
                            song = hit.get("result", {})
                            artist = song.get("primary_artist", {}).get("name", "")
                            title = song.get("title", "")
                            print(f"  [{time.monotonic()-t0:.1f}s] {q[:35]:35s} -> {artist} - {title}")
                            found = True
                if not found:
                    print(f"  [{time.monotonic()-t0:.1f}s] {q[:35]:35s} -> NO RESULT")

asyncio.run(test_genius())
