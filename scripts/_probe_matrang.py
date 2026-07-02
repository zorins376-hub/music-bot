#!/usr/bin/env python3
import asyncio
import json
from bot.services.yandex_provider import search_yandex
from bot.services.vk_provider import search_vk
from bot.services.search_engine import deduplicate_results, parse_query, normalize_query

QUERIES = ["матранг рука", "матранг - рука", "matrang ruka", "Matrang Ruka", "Матранг Рука"]

async def main():
    for q in QUERIES:
        y = await search_yandex(q, limit=5)
        print(f"\n=== {q} ===")
        for t in y[:5]:
            print(f"  {t.get('uploader')} — {t.get('title')}")

    parsed = parse_query("матранг рука")
    all_r = []
    for q in QUERIES[:3]:
        all_r.extend(await search_yandex(q, limit=3))
    ranked = deduplicate_results(all_r, lang_hint="cyrillic", query="матранг рука")
    print("\n=== DEDUP TOP 3 ===")
    for t in ranked[:3]:
        print(f"  {t.get('uploader')} — {t.get('title')}")

asyncio.run(main())
