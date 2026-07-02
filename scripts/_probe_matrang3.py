#!/usr/bin/env python3
import asyncio
from bot.services.downloader import search_tracks

async def main():
    for q in ["MATRANG Рука", "Матранг - Рука", "Matrang Ruka song", "матранг песня рука", "MATRANG track Ruka"]:
        print("Q", q)
        for t in (await search_tracks(q, max_results=5, source="youtube"))[:5]:
            print(" ", t.get("uploader"), "-", t.get("title"))

asyncio.run(main())
