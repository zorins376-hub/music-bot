import asyncio
import aiohttp
import re
import json

async def check():
    headers = {"User-Agent": "Mozilla/5.0 Chrome/120", "Accept-Language": "ru-RU"}
    async with aiohttp.ClientSession() as sess:
        async with sess.get(
            "https://rusradio.ru/charts/hit-parad-zolotoj-grammofon",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            html = await resp.text()

    # Check exact bytes around "tracks" 
    idx = html.find('"tracks"')
    print("Exact chars around tracks:", repr(html[idx-5:idx+50]))
    
    # Check if it's escaped version
    idx2 = html.find('\\"tracks\\"')
    print("Escaped idx:", idx2)
    if idx2 >= 0:
        print("Escaped context:", repr(html[idx2-20:idx2+80]))
    
    # Also check raw find
    for needle in ['"tracks":[', '"tracks": [', '\\"tracks\\":[', '\\"tracks\\":\\[']:
        pos = html.find(needle)
        print(f"  {repr(needle)} -> pos={pos}")

asyncio.run(check())
