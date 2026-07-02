#!/usr/bin/env python3
"""Run live search benchmark on N songs (default 100) using production search pipeline."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None  # type: ignore

from bot.services.search_engine import (
    deduplicate_results,
    detect_script,
    is_lyric_like_query,
    needs_lyrics_search_boost,
    normalize_query,
    parse_query,
    query_title_hint_coverage,
    query_word_coverage,
    transliterate_cyr_to_lat,
    transliterate_lat_to_cyr,
)
from bot.handlers.search import (
    _fetch_parsed_hint_tracks,
    _fetch_tracks_for_lyrics_hints,
    _filter_lyric_hints_for_artist,
)
from bot.services.downloader import search_tracks
from bot.services.spotify_provider import search_spotify
from bot.services.vk_provider import search_vk
from bot.services.yandex_provider import search_yandex


def _norm(s: str) -> str:
    return normalize_query(s or "")


def _sim(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    if fuzz is not None:
        return float(fuzz.token_set_ratio(a, b)) / 100.0
    return 1.0 if a == b else 0.0


def grade_match(case: dict, found_artist: str, found_title: str) -> tuple[str, float]:
    exp_artist = case.get("artist", "")
    exp_title = case.get("title", "")
    query = case["query"]

    if not found_artist and not found_title:
        return "EMPTY", 0.0

    artist_sim = _sim(exp_artist, found_artist) if exp_artist else 1.0
    title_sim = _sim(exp_title, found_title) if exp_title else _sim(query, found_title)

    # Artist-only queries (e.g. "Гуф")
    if exp_artist and not exp_title:
        if artist_sim >= 0.65:
            return "GOOD", artist_sim
        if artist_sim >= 0.45:
            return "OK", artist_sim
        cov = query_word_coverage(_norm(query), found_artist, found_title)
        if cov >= 0.5:
            return "OK", cov
        return "BAD", artist_sim

    combined = 0.45 * artist_sim + 0.55 * title_sim
    cov = query_word_coverage(_norm(query), found_artist, found_title)

    if artist_sim >= 0.6 and title_sim >= 0.55:
        return "GOOD", combined
    if combined >= 0.55 or cov >= 0.7:
        return "OK", max(combined, cov)
    if combined >= 0.4 or cov >= 0.5:
        return "WEAK", max(combined, cov)
    return "BAD", max(combined, cov)


async def _fetch_lyrics_hints(provider_query: str) -> list[dict]:
    try:
        from bot.services.lyrics_provider import search_by_lyrics
        return await asyncio.wait_for(search_by_lyrics(provider_query, limit=3), timeout=10)
    except Exception:
        return []


async def _hint_tracks(lyric_hints: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for hint in lyric_hints:
        artist = (hint.get("artist") or "").strip()
        title = (hint.get("title") or "").strip()
        if not artist or not title:
            continue
        q = f"{artist} {title}"
        if q in seen:
            continue
        seen.add(q)
        try:
            y, v, s, yt = await asyncio.gather(
                asyncio.wait_for(search_yandex(q, limit=2), timeout=10),
                asyncio.wait_for(search_vk(q, limit=2), timeout=10),
                asyncio.wait_for(search_spotify(q, limit=2), timeout=10),
                asyncio.wait_for(search_tracks(q, max_results=2, source="youtube"), timeout=10),
            )
        except Exception:
            continue
        merged = (y or []) + (v or []) + (s or []) + (yt or [])
        for idx, track in enumerate(merged):
            track["_provider_pos"] = idx
            track["_hint_bonus"] = 1.05 if idx == 0 else 0.85
            out.append(track)
    return out


async def search_top1(query: str, *, max_results: int = 10) -> dict | None:
    """Mirror bot search ranking; return top-1 track dict or None."""
    parsed = parse_query(query)
    provider_query = parsed.get("clean") or parsed.get("original") or query

    async def _src(fn, limit: int) -> list[dict]:
        try:
            return await asyncio.wait_for(fn(provider_query, limit=limit), timeout=12)
        except Exception:
            return []

    async def _sc(q: str, limit: int = 5) -> list[dict]:
        return await search_tracks(q, max_results=limit, source="soundcloud")

    async def _yt(q: str, limit: int = 5) -> list[dict]:
        return await search_tracks(q, max_results=limit, source="youtube")

    lyrics_task = None
    if is_lyric_like_query(provider_query, parsed) or len(provider_query.split()) >= 3:
        lyrics_task = asyncio.create_task(_fetch_lyrics_hints(provider_query))

    batches = await asyncio.gather(
        _src(search_yandex, max_results),
        _src(search_spotify, max_results),
        _src(_sc, max_results),
        _src(search_vk, max_results),
        _src(_yt, max_results),
    )
    all_results: list[dict] = []
    for batch in batches:
        all_results.extend(batch)

    if len(all_results) < 3:
        script = detect_script(provider_query)
        alt = None
        if script == "cyrillic":
            alt = transliterate_cyr_to_lat(provider_query)
        elif script == "latin":
            alt = transliterate_lat_to_cyr(provider_query)
        if alt and alt != provider_query:
            extra = await asyncio.gather(
                asyncio.wait_for(search_tracks(alt, max_results=max_results, source="youtube"), timeout=12),
                asyncio.wait_for(search_yandex(alt, limit=max_results), timeout=12),
            )
            for batch in extra:
                if isinstance(batch, list):
                    all_results.extend(batch)

    script = detect_script(provider_query)
    results = deduplicate_results(all_results, lang_hint=script, query=provider_query)[:max_results]

    lyric_hints: list[dict] = []
    if lyrics_task:
        try:
            lyric_hints = await lyrics_task
        except Exception:
            pass

    extra: list[dict] = []
    top_track = results[0] if results else None
    if parsed.get("artist_hint") and parsed.get("title_hint"):
        title_cov = (
            query_title_hint_coverage(
                normalize_query(provider_query),
                top_track.get("title", ""),
                parsed,
            )
            if top_track else 0.0
        )
        if title_cov < 0.85:
            extra.extend(
                await _fetch_parsed_hint_tracks(
                    parsed,
                    search_yandex_fn=search_yandex,
                    search_vk_fn=search_vk,
                    search_spotify_fn=search_spotify,
                    search_yt_fn=_yt,
                )
            )

    if needs_lyrics_search_boost(provider_query, top_track, parsed=parsed):
        if not lyric_hints:
            lyric_hints = await _fetch_lyrics_hints(provider_query)
        lyric_hints = _filter_lyric_hints_for_artist(
            lyric_hints, parsed.get("artist_hint") or "",
        )
        extra.extend(
            await _fetch_tracks_for_lyrics_hints(
                lyric_hints,
                search_yandex_fn=search_yandex,
                search_vk_fn=search_vk,
                search_spotify_fn=search_spotify,
                search_yt_fn=_yt,
            )
        )

    if extra:
        all_results.extend(extra)
        results = deduplicate_results(all_results, lang_hint=script, query=provider_query)[:max_results]

    return results[0] if results else None


async def run_benchmark(cases: list[dict], *, concurrency: int = 4) -> dict:
    sem = asyncio.Semaphore(concurrency)
    rows: list[dict] = []

    async def one(i: int, case: dict) -> None:
        async with sem:
            t0 = time.monotonic()
            try:
                top = await search_top1(case["query"])
            except Exception as exc:
                top = None
                err = str(exc)[:120]
            else:
                err = ""
            ms = int((time.monotonic() - t0) * 1000)
            if top:
                artist = top.get("uploader", "")
                title = top.get("title", "")
                source = top.get("source", "?")
            else:
                artist = title = source = ""
            label, score = grade_match(case, artist, title)
            rows.append({
                "i": i,
                "query": case["query"],
                "expected": f"{case.get('artist', '')} — {case.get('title', '')}".strip(" —"),
                "found": f"{artist} — {title}".strip(" —"),
                "source": source,
                "grade": label,
                "score": round(score, 3),
                "ms": ms,
                "err": err,
            })

    await asyncio.gather(*(one(i, c) for i, c in enumerate(cases, 1)))
    rows.sort(key=lambda r: r["i"])

    summary = {"GOOD": 0, "OK": 0, "WEAK": 0, "BAD": 0, "EMPTY": 0}
    for r in rows:
        summary[r["grade"]] = summary.get(r["grade"], 0) + 1
    total = len(rows)
    ok_plus = summary["GOOD"] + summary["OK"]
    return {
        "total": total,
        "summary": summary,
        "good_pct": round(summary["GOOD"] / total * 100, 1) if total else 0,
        "ok_plus_pct": round(ok_plus / total * 100, 1) if total else 0,
        "rows": rows,
    }


def load_cases(limit: int = 100) -> list[dict]:
    candidates = [
        ROOT / "tests" / "data" / "search_benchmark_100.json",
        Path("/app/search_benchmark_100.json"),
        Path("/tmp/search_benchmark_100.json"),
    ]
    path = next((p for p in candidates if p.exists()), candidates[0])
    raw = json.loads(path.read_text(encoding="utf-8"))
    seen: set[str] = set()
    cases: list[dict] = []
    for item in raw:
        q = item["query"].strip()
        if q in seen:
            continue
        seen.add(q)
        cases.append(item)
        if len(cases) >= limit:
            break
    return cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args()

    cases = load_cases(args.limit)
    print(f"Running benchmark on {len(cases)} queries (concurrency={args.concurrency})...")
    report = asyncio.run(run_benchmark(cases, concurrency=args.concurrency))

    s = report["summary"]
    print("\n=== SUMMARY ===")
    print(f"GOOD:  {s['GOOD']} ({report['good_pct']}%)")
    print(f"OK:    {s['OK']}")
    print(f"WEAK:  {s['WEAK']}")
    print(f"BAD:   {s['BAD']}")
    print(f"EMPTY: {s['EMPTY']}")
    print(f"Acceptable (GOOD+OK): {report['ok_plus_pct']}%")

    print("\n=== FAILURES & WEAK (query -> found) ===")
    for r in report["rows"]:
        if r["grade"] in ("BAD", "EMPTY", "WEAK"):
            print(f"{r['grade']:5s} [{r['score']:.2f}] q={r['query'][:50]!r}")
            print(f"       exp: {r['expected'][:70]}")
            print(f"       got: {r['found'][:70]} ({r['source']})")

    out_path = args.output or str(ROOT / "tests" / "data" / "search_benchmark_report.json")
    Path(out_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull report: {out_path}")


if __name__ == "__main__":
    main()
