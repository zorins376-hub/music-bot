#!/usr/bin/env python3
"""Quick test: what each provider returns for a given query."""
import sys, os, asyncio, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

QUERY = "Ари Ури мы на Иссык куле"

def test_vk():
    from bot.services.vk_provider import _search_vk_sync
    results = _search_vk_sync(QUERY, limit=10)
    print("=== VK RESULTS ===")
    for i, r in enumerate(results[:7]):
        print(f"  {i}: {r['uploader']} - {r['title']}  (dur={r['duration']})")
    if not results:
        print("  (empty)")

async def test_yandex():
    from bot.services.yandex_provider import search_yandex
    results = await search_yandex(QUERY, limit=5)
    print("=== YANDEX RESULTS ===")
    for i, r in enumerate(results[:5]):
        print(f"  {i}: {r.get('uploader','')} - {r.get('title','')}  (dur={r.get('duration',0)})")
    if not results:
        print("  (empty)")

async def test_yt():
    from bot.services.downloader import search_tracks
    results = await search_tracks(QUERY, max_results=5)
    print("=== YOUTUBE RESULTS ===")
    for i, r in enumerate(results[:5]):
        print(f"  {i}: {r.get('uploader','')} - {r.get('title','')}  (dur={r.get('duration',0)})")
    if not results:
        print("  (empty)")

async def main():
    test_vk()
    await test_yandex()
    await test_yt()

    # Now test dedup/ranking
    from bot.services.vk_provider import _search_vk_sync
    from bot.services.yandex_provider import search_yandex
    from bot.services.downloader import search_tracks
    from bot.services.search_engine import deduplicate_results, detect_script, normalize_query, _relevance_score

    vk = _search_vk_sync(QUERY, limit=10)
    ym = await search_yandex(QUERY, limit=5)
    yt = await search_tracks(QUERY, max_results=5)

    all_results = []
    for r in (vk, ym, yt):
        if r:
            for i, t in enumerate(r):
                t["_provider_pos"] = i
            all_results.extend(r)

    script = detect_script(QUERY)
    ranked = deduplicate_results(all_results, lang_hint=script, query=QUERY)

    print(f"\n=== FINAL RANKED (script={script}) ===")
    qn = normalize_query(QUERY)
    for i, r in enumerate(ranked[:10]):
        score = _relevance_score(qn, r.get("uploader",""), r.get("title",""), r.get("_provider_pos", 5))
        print(f"  {i}: [{r.get('source','')}] {r.get('uploader','')} - {r.get('title','')}  score={score:.3f}")

asyncio.run(main())
