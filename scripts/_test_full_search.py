#!/usr/bin/env python3
"""Full simulation of search pipeline including lyrics fallback."""
import sys, os, asyncio
sys.path.insert(0, "/app")
from dotenv import load_dotenv
load_dotenv()

from bot.services.yandex_provider import search_yandex
from bot.services.downloader import search_tracks
from bot.services.search_engine import deduplicate_results, detect_script, normalize_query, _relevance_score

QUERY = "Трек Ари Ури мы на Иссык куле"

async def _safe(coro):
    try:
        return await asyncio.wait_for(coro, timeout=8)
    except Exception as e:
        print(f"  Error: {e}")
        return []

async def main():
    print(f"Query: {QUERY}")
    print(f"Words: {len(QUERY.split())}")

    ym = await _safe(search_yandex(QUERY, limit=5))
    yt = await _safe(search_tracks(QUERY, max_results=5))

    print(f"\n=== YANDEX ({len(ym)}) ===")
    for i, r in enumerate(ym[:5]):
        print(f"  {i}: {r.get('uploader','')} - {r.get('title','')} [{r.get('source','')}]")

    print(f"\n=== YOUTUBE ({len(yt)}) ===")
    for i, r in enumerate(yt[:5]):
        print(f"  {i}: {r.get('uploader','')} - {r.get('title','')} [{r.get('source','')}]")

    all_results = []
    for batch in (ym, yt):
        if batch:
            for i, t in enumerate(batch):
                t["_provider_pos"] = i
            all_results.extend(batch)

    script = detect_script(QUERY)
    qn = normalize_query(QUERY)
    results = deduplicate_results(all_results, lang_hint=script, query=QUERY)[:10]

    print(f"\n=== RANKED (before lyrics fallback) ===")
    for i, r in enumerate(results[:5]):
        score = _relevance_score(qn, r.get("uploader",""), r.get("title",""), r.get("_provider_pos",5))
        print(f"  {i}: {score:.3f} [{r.get('source','')}] {r.get('uploader','')} - {r.get('title','')}")

    best_score = _relevance_score(qn, results[0].get("uploader",""), results[0].get("title",""), results[0].get("_provider_pos",5)) if results else 0
    print(f"\n  Best score: {best_score:.3f}, threshold: 1.0")
    print(f"  Words >= 3: {len(QUERY.split()) >= 3}")
    print(f"  Trigger fallback: {best_score < 1.0 and len(QUERY.split()) >= 3}")

    # Simulate lyrics fallback
    if best_score < 1.0 and len(QUERY.split()) >= 3:
        print(f"\n=== LYRICS FALLBACK: '{QUERY} lyrics' ===")
        lyrics_yt = await _safe(search_tracks(f"{QUERY} lyrics", max_results=5))
        for i, r in enumerate(lyrics_yt[:5]):
            print(f"  {i}: {r.get('uploader','')} - {r.get('title','')} [{r.get('source','')}]")
        if lyrics_yt:
            existing_ids = {r.get("video_id") for r in results}
            for i, trk in enumerate(lyrics_yt):
                trk["_provider_pos"] = i
            all_results.extend(lyrics_yt)
            results = deduplicate_results(all_results, lang_hint=script, query=QUERY)[:10]

            # Promote lyrics-unique
            lyrics_unique = [r for r in results if r.get("video_id") not in existing_ids]
            others = [r for r in results if r.get("video_id") in existing_ids]
            if lyrics_unique and others:
                results = [others[0]] + lyrics_unique + others[1:]

        print(f"\n=== FINAL RANKED (after lyrics promotion) ===")
        for i, r in enumerate(results[:8]):
            score = _relevance_score(qn, r.get("uploader",""), r.get("title",""), r.get("_provider_pos",5))
            ly = " ★LYRICS" if r.get("video_id") not in existing_ids else ""
            print(f"  {i}: {score:.3f} [{r.get('source','')}] {r.get('uploader','')} - {r.get('title','')}{ly}")

asyncio.run(main())
