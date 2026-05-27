#!/usr/bin/env python3
"""Test search with different query strategies."""
import sys, os, asyncio
sys.path.insert(0, "/app")
from dotenv import load_dotenv
load_dotenv()

from bot.services.yandex_provider import search_yandex
from bot.services.downloader import search_tracks
from bot.services.search_engine import normalize_query, _relevance_score

QUERIES = [
    "Ари Ури мы на Иссык куле",
    "Треск Ари Ури",
    "Треск ACAPELLA Ари Ури",
    "Акапелла Ари Ури",
]

async def main():
    for q in QUERIES:
        print(f"\n{'='*60}")
        print(f"QUERY: {q}")
        print(f"{'='*60}")

        ym = []
        yt = []
        try:
            ym = await asyncio.wait_for(search_yandex(q, limit=5), timeout=8)
        except Exception as e:
            print(f"  Yandex error: {e}")
        try:
            yt = await asyncio.wait_for(search_tracks(q, max_results=5), timeout=8)
        except Exception as e:
            print(f"  YouTube error: {e}")

        print(f"  Yandex ({len(ym)}):")
        for i, r in enumerate(ym[:3]):
            print(f"    {i}: {r.get('uploader','')} - {r.get('title','')} [{r.get('source','')}]")
        print(f"  YouTube ({len(yt)}):")
        for i, r in enumerate(yt[:5]):
            print(f"    {i}: {r.get('uploader','')} - {r.get('title','')} [{r.get('source','')}]")

asyncio.run(main())
