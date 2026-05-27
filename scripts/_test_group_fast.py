import asyncio
import os
import sys
import time

sys.path.insert(0, "/app")
os.chdir("/app")

from bot.db import search_local_tracks
from bot.handlers.search import _GROUP_PROVIDER_LIMIT, _GROUP_YOUTUBE_LIMIT, _lyrics_artist_link_score, _promote_consensus_artist, _rank_lyrics_unique
from bot.services.downloader import search_tracks
from bot.services.search_engine import _relevance_score, deduplicate_results, detect_script, normalize_query
from bot.services.yandex_provider import search_yandex


QUERY = os.getenv("TEST_QUERY", "Ари Ури мы на Иссык куле")


async def _search_source(search_fn, limit: int = 3, timeout: int = 5) -> list[dict]:
    try:
        res = await asyncio.wait_for(search_fn(QUERY, limit=limit), timeout=timeout)
        return res or []
    except Exception:
        return []


async def _search_yt(query_: str, limit: int = 3) -> list[dict]:
    return await search_tracks(query_, max_results=limit, source="youtube")


async def main() -> None:
    started = time.perf_counter()
    provider_limit = _GROUP_PROVIDER_LIMIT
    max_results = 1

    local_tracks = await search_local_tracks(QUERY, limit=provider_limit)
    local_results = [
        {
            "video_id": tr.source_id,
            "title": tr.title or "Unknown",
            "uploader": tr.artist or "Unknown",
            "duration": tr.duration or 0,
            "source": tr.source or "channel",
            "file_id": tr.file_id,
            "_provider_pos": idx,
        }
        for idx, tr in enumerate(local_tracks or [])
    ]

    batches = await asyncio.gather(
        _search_source(search_yandex, provider_limit, 5),
        _search_source(_search_yt, _GROUP_YOUTUBE_LIMIT, 5),
        return_exceptions=True,
    )

    all_results = list(local_results)
    for batch in batches:
        if isinstance(batch, BaseException) or not batch:
            continue
        for idx, track in enumerate(batch):
            track["_provider_pos"] = idx
        all_results.extend(batch)

    script = detect_script(QUERY)
    all_deduped_base = deduplicate_results(all_results, lang_hint=script, query=QUERY)
    results = _promote_consensus_artist(all_deduped_base, QUERY)[:max_results]
    qn = normalize_query(QUERY)
    print("BASE_ALL", [(r.get("uploader", ""), r.get("title", "")) for r in all_results])
    print("BASE_TOP", [(r.get("uploader", ""), r.get("title", "")) for r in results])

    if results:
        best_score = _relevance_score(
            qn,
            results[0].get("uploader", ""),
            results[0].get("title", ""),
            position=results[0].get("_provider_pos", 5),
        )
        existing_ids = {r.get("video_id") for r in all_results if r.get("video_id")}
        if best_score < 1.0:
            lyrics_yt = await asyncio.wait_for(
                search_tracks(f"{QUERY} lyrics", max_results=5, source="youtube"),
                timeout=5,
            )
            lyrics_yt_ids = {trk.get("video_id") for trk in lyrics_yt}
            for idx, trk in enumerate(lyrics_yt):
                trk["_provider_pos"] = idx
            all_results.extend(lyrics_yt)
            all_deduped = _promote_consensus_artist(
                deduplicate_results(all_results, lang_hint=script, query=QUERY),
                QUERY,
            )
            lyrics_unique = [
                r for r in all_deduped
                if r.get("video_id") not in existing_ids and r.get("video_id") in lyrics_yt_ids
            ]
            others = [
                r for r in all_deduped
                if r.get("video_id") not in {lu.get("video_id") for lu in lyrics_unique}
            ]
            ranked_lyrics = _rank_lyrics_unique(lyrics_unique, others, QUERY)
            top_link_score = _lyrics_artist_link_score(ranked_lyrics[0], others) if ranked_lyrics and others else 0.0
            print("LYRICS_YT", [(r.get("uploader", ""), r.get("title", "")) for r in lyrics_yt])
            print("LYRICS_UNIQUE", [(r.get("uploader", ""), r.get("title", "")) for r in ranked_lyrics])
            print("OTHERS_TOP", [(r.get("uploader", ""), r.get("title", "")) for r in others[:5]])
            print("TOP_LINK", round(top_link_score, 3))
            if ranked_lyrics and others:
                results = [ranked_lyrics[0] if top_link_score >= 0.85 else others[0]]

    elapsed = time.perf_counter() - started
    print("FINAL", [(r.get("uploader", ""), r.get("title", "")) for r in results])
    print("SECONDS", round(elapsed, 3))


asyncio.run(main())