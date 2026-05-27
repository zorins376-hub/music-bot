import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.db import search_local_tracks
from bot.handlers.search import _promote_consensus_artist
from bot.services.downloader import search_tracks
from bot.services.search_engine import deduplicate_results, detect_script, normalize_query, _relevance_score, parse_query
from bot.services.yandex_provider import search_yandex
from bot.services.speller import correct_query

TEST_QUERIES = [
    # Русские тексты
    "я свободен словно птица в небесах",
    "знаешь ли ты вдоль ночных дорог",
    "на сиреневой луне",
    "в питере пить",
    
    # Иностранные тексты
    "we dont need no education",
    "hello darkness my old friend",
    "mama just killed a man",
    "is this the real life is this just fantasy",
    
    # Иностранные, написанные по-русски транслитом (сложный кейс)
    "айм блю дабуди дабудай",
    "смэлс лайк тин спирит",
    "билли джин из нот май лавер",
    "шоу маст гоу он",
    "ай вил олвейс лав ю",
    "лет ит би",
    "ху лекс зе догс аут",
    
    # Смешанные и мусорные запросы
    "найди мне песню где поют лалала",
    "песня из титаника",
    "включи музыку из форсажа эрон дон дон"
]

async def _search_source(search_fn, timeout: int = 5) -> list[dict]:
    try:
        res = await asyncio.wait_for(search_fn(), timeout=timeout)
        return res or []
    except Exception as e:
        print(f"Exception in source '{search_fn.__name__}': {e}")
        return []

async def test_query(query: str):
    started = time.perf_counter()
    parsed = parse_query(query)
    _pq = parsed["clean"]
    
    # 1. Local
    local_tracks = await search_local_tracks(_pq, limit=3)
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
    
    # 2. Search Yandex and YouTube
    async def yandex(): return await search_yandex(_pq, limit=3)
    async def youtube(): return await search_tracks(_pq, max_results=3, source="youtube")
    
    batches = await asyncio.gather(
        _search_source(yandex, 5),
        _search_source(youtube, 5),
        return_exceptions=True,
    )
    
    all_results = list(local_results)
    for batch in batches:
        if isinstance(batch, BaseException) or not batch:
            continue
        for idx, track in enumerate(batch):
            track["_provider_pos"] = idx
        all_results.extend(batch)
        
    script = detect_script(_pq)
    all_deduped_base = deduplicate_results(all_results, lang_hint=script, query=_pq)
    
    if not all_deduped_base:
        corrected = await correct_query(_pq)
        if corrected and corrected != _pq:
            async def yandex_corr(): return await search_yandex(corrected, limit=3)
            async def youtube_corr(): return await search_tracks(corrected, max_results=3, source="youtube")
            batches_corr = await asyncio.gather(
                _search_source(yandex_corr, 5),
                _search_source(youtube_corr, 5),
                return_exceptions=True,
            )
            all_results = []
            for batch in batches_corr:
                if isinstance(batch, BaseException) or not batch:
                    continue
                for idx, track in enumerate(batch):
                    track["_provider_pos"] = idx
                all_results.extend(batch)
            all_deduped_base = deduplicate_results(all_results, lang_hint=script, query=corrected)
            _pq = corrected
            
    results = _promote_consensus_artist(all_deduped_base, _pq)[:3]
    elapsed = time.perf_counter() - started
    
    print("-" * 50)
    print(f"QUERY  : {query}")
    print(f"PARSED : {_pq}")
    if results:
        best = results[0]
        score = _relevance_score(normalize_query(_pq), best.get("uploader", ""), best.get("title", ""), position=best.get("_provider_pos", 5))
        print(f"BEST   : {best.get('uploader')} - {best.get('title')} (score: {score:.2f})")
    else:
        print("BEST   : None found")
    print(f"TIME   : {elapsed:.2f}s")


async def main():
    print("Testing queries...")
    for q in TEST_QUERIES:
        await test_query(q)

if __name__ == "__main__":
    asyncio.run(main())
