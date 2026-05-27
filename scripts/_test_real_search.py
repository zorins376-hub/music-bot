"""Simulate _do_search exactly as search.py does it, with all provider searches."""
import sys, os, asyncio, time
sys.path.insert(0, "/app")
os.chdir("/app")
from dotenv import load_dotenv; load_dotenv()

from bot.services.downloader import search_tracks
from bot.services.yandex_provider import search_yandex
from bot.services.spotify_provider import search_spotify
from bot.services.vk_provider import search_vk
from bot.db import search_local_tracks
from bot.services.search_engine import deduplicate_results, detect_script, normalize_query, _relevance_score, transliterate_cyr_to_lat
from bot.utils import fmt_duration

QUERY = "Ари Ури мы на Иссык куле"  # after "Трек " prefix stripped

async def _search_source(source, search_fn, limit=5):
    try:
        res = await asyncio.wait_for(search_fn(QUERY, limit=limit), timeout=8)
        return res or []
    except Exception as e:
        print(f"  {source} error: {e}")
        return []

async def main():
    print(f"Query (after prefix strip): '{QUERY}'")
    max_results = 1  # Simulate group mode (_MAX_RESULTS_GROUP = 1)

    # Local search
    local_tracks = await search_local_tracks(QUERY, limit=max_results)
    local_results = []
    for idx, tr in enumerate(local_tracks or []):
        local_results.append({
            "video_id": tr.source_id,
            "title": tr.title or "Unknown",
            "uploader": tr.artist or "Unknown",
            "duration": tr.duration or 0,
            "source": tr.source or "channel",
            "file_id": tr.file_id,
            "_provider_pos": idx,
        })
    print(f"Local: {len(local_results)}")

    # Parallel searches
    async def _yt(q, limit=5): return await search_tracks(q, max_results=limit, source="youtube")
    async def _sc(q, limit=5): return await search_tracks(q, max_results=limit, source="soundcloud")

    tasks = await asyncio.gather(
        _search_source("yandex", search_yandex),
        _search_source("spotify", search_spotify),
        _search_source("soundcloud", _sc),
        _search_source("youtube", _yt),
        _search_source("vk", search_vk),
        return_exceptions=True,
    )

    all_results = []
    names = ["yandex", "spotify", "soundcloud", "youtube", "vk"]
    for name, batch in zip(names, tasks):
        if isinstance(batch, BaseException) or not batch:
            print(f"  {name}: 0 (error={isinstance(batch, BaseException)})")
            continue
        print(f"  {name}: {len(batch)}")
        for i, t in enumerate(batch):
            t["_provider_pos"] = i
        all_results.extend(batch)

    all_results = local_results + all_results
    script = detect_script(QUERY)
    results = deduplicate_results(all_results, lang_hint=script, query=QUERY)[:max_results]

    print(f"\n=== BEFORE LYRICS FALLBACK ({len(results)}) ===")
    qn = normalize_query(QUERY)
    for i, r in enumerate(results[:5]):
        score = _relevance_score(qn, r.get("uploader",""), r.get("title",""), r.get("_provider_pos",5))
        print(f"  {i}: {score:.3f} {r.get('uploader','')} - {r.get('title','')} [vid={r.get('video_id','')[:15]}]")

    # Lyrics fallback
    query_words_split = QUERY.split()
    if len(query_words_split) >= 3 and results:
        best_score = _relevance_score(qn, results[0].get("uploader",""), results[0].get("title",""), results[0].get("_provider_pos",5))
        print(f"\n  best_score={best_score:.3f}, trigger={best_score < 1.0}")
        if best_score < 1.0:
            existing_ids = {r.get("video_id") for r in all_results if r.get("video_id")}
            print(f"  existing_ids count: {len(existing_ids)}")
            try:
                lyrics_yt = await asyncio.wait_for(
                    search_tracks(f"{QUERY} lyrics", max_results=5, source="youtube"),
                    timeout=5,
                )
            except Exception:
                lyrics_yt = []
            print(f"  lyrics_yt count: {len(lyrics_yt)}")
            for i, r in enumerate(lyrics_yt):
                print(f"    {i}: {r.get('uploader','')} - {r.get('title','')} [vid={r.get('video_id','')[:15]}]")
            if lyrics_yt:
                lyrics_yt_ids = {trk.get("video_id") for trk in lyrics_yt}
                for idx_ly, trk in enumerate(lyrics_yt):
                    trk["_provider_pos"] = idx_ly
                all_results.extend(lyrics_yt)
                all_deduped = deduplicate_results(all_results, lang_hint=script, query=QUERY)
                lyrics_unique = [r for r in all_deduped
                                 if r.get("video_id") not in existing_ids
                                 and r.get("video_id") in lyrics_yt_ids]
                others = [r for r in all_deduped if r.get("video_id") not in {lu.get("video_id") for lu in lyrics_unique}]
                print(f"  all_deduped: {len(all_deduped)}, lyrics_unique: {len(lyrics_unique)}, others: {len(others)}")
                for r in lyrics_unique:
                    print(f"    UNIQUE: {r.get('uploader','')} - {r.get('title','')}")
                if lyrics_unique and others:
                    effective_max = max(max_results, 3)
                    results = ([others[0]] + lyrics_unique[:2] + others[1:])[:effective_max]
                else:
                    results = all_deduped[:max_results]

    print(f"\n=== FINAL RESULTS ({len(results)}) ===")
    for i, r in enumerate(results[:8]):
        score = _relevance_score(qn, r.get("uploader",""), r.get("title",""), r.get("_provider_pos",5))
        print(f"  {i}: {score:.3f} {r.get('uploader','')} - {r.get('title','')}")

asyncio.run(main())
