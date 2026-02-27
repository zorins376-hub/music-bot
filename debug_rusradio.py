import asyncio
import aiohttp
import re

async def check():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
        "Accept-Language": "ru-RU,ru;q=0.9",
    }
    async with aiohttp.ClientSession() as sess:
        async with sess.get(
            "https://rusradio.ru/charts/hit-parad-zolotoj-grammofon",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
        ) as resp:
            raw = await resp.read()
            print("CHARSET:", resp.charset, "STATUS:", resp.status)
    for enc in ("utf-8", "cp1251"):
        try:
            html = raw.decode(enc)
            if "олосовать" in html:
                print("OK encoding:", enc)
                idx = html.find("олосовать")
                print(repr(html[max(0,idx-500):idx+20]))
                break
        except Exception as e:
            print(enc, "fail:", e)

asyncio.run(check())
