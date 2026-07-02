#!/usr/bin/env python3
"""Verify audit queries: bot top1 vs Yandex/Spotify catalog top results."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path("/app") if Path("/app/bot").exists() else Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Allow running inside Docker (/app)
for _p in (ROOT, Path("/app")):
    if (_p / "run_search_benchmark.py").exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from run_search_benchmark import search_top1  # noqa: E402


try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None

from bot.services.search_engine import normalize_query, parse_query
from bot.services.spotify_provider import search_spotify
from bot.services.yandex_provider import search_yandex


def _norm(s: str) -> str:
    return normalize_query(s or "")


def _track_key(artist: str, title: str) -> str:
    return f"{_norm(artist)}|{_norm(title)}"


def _sim(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b or a in b or b in a:
        return 1.0
    if fuzz is not None:
        return float(fuzz.token_set_ratio(a, b)) / 100.0
    return 0.0


def same_song(a1: str, t1: str, a2: str, t2: str) -> bool:
    """True if two artist/title pairs are the same track."""
    if _track_key(a1, t1) == _track_key(a2, t2):
        return True
    if _sim(a1, a2) >= 0.72 and _sim(t1, t2) >= 0.68:
        return True
    if _sim(f"{a1} {t1}", f"{a2} {t2}") >= 0.88:
        return True
    return False


def best_match_in_list(artist: str, title: str, tracks: list[dict], limit: int = 5) -> tuple[int, dict | None]:
    for i, tr in enumerate(tracks[:limit]):
        if same_song(artist, title, tr.get("uploader", ""), tr.get("title", "")):
            return i, tr
    return -1, None


def verdict(
    query: str,
    bot_a: str,
    bot_t: str,
    yandex: list[dict],
    spotify: list[dict],
    pipeline: dict | None,
) -> tuple[str, str]:
    """Return (verdict_code, explanation)."""
    q = query.strip()
    if q.startswith("@") or len(q) < 2:
        return "SKIP", "не музыкальный запрос"

    ya0 = yandex[0] if yandex else None
    sp0 = spotify[0] if spotify else None

    # Catalog consensus: what Yandex and Spotify think is #1
    catalog_a, catalog_t = "", ""
    if ya0 and sp0 and same_song(
        ya0.get("uploader", ""), ya0.get("title", ""),
        sp0.get("uploader", ""), sp0.get("title", ""),
    ):
        catalog_a = ya0.get("uploader", "")
        catalog_t = ya0.get("title", "")
        catalog_src = "yandex+spotify"
    elif ya0:
        catalog_a = ya0.get("uploader", "")
        catalog_t = ya0.get("title", "")
        catalog_src = "yandex"
    elif sp0:
        catalog_a = sp0.get("uploader", "")
        catalog_t = sp0.get("title", "")
        catalog_src = "spotify"
    else:
        return "NO_CATALOG", "каталог не ответил"

    if same_song(bot_a, bot_t, catalog_a, catalog_t):
        return "MATCH", f"совпадает с {catalog_src} #1: {catalog_a} — {catalog_t}"

    ya_idx, _ = best_match_in_list(bot_a, bot_t, yandex)
    sp_idx, _ = best_match_in_list(bot_a, bot_t, spotify)
    if ya_idx in (0, 1, 2) or sp_idx in (0, 1, 2):
        pos = ya_idx if ya_idx >= 0 else sp_idx
        return "CLOSE", f"бот дал верную песню, но не #1 в каталоге (позиция ~{pos + 1})"

    # Pipeline re-run check
    if pipeline and same_song(bot_a, bot_t, pipeline.get("uploader", ""), pipeline.get("title", "")):
        if not same_song(bot_a, bot_t, catalog_a, catalog_t):
            return "DISPUTE", (
                f"бот=пайплайн, но каталог другое: "
                f"каталог {catalog_a} — {catalog_t}"
            )
        return "MATCH", "совпадает с пайплайном"

    return "WRONG", f"каталог #1: {catalog_a} — {catalog_t}"


async def verify_one(item: dict) -> dict:
    query = item["q"]
    bot_top1 = item.get("top1", "")
    if " - " in bot_top1:
        bot_a, bot_t = bot_top1.split(" - ", 1)
    else:
        bot_a, bot_t = "", bot_top1

    pq = parse_query(query)
    provider_q = pq.get("clean") or pq.get("original") or query

    try:
        yandex, spotify, pipeline = await asyncio.gather(
            asyncio.wait_for(search_yandex(provider_q, limit=5), timeout=15),
            asyncio.wait_for(search_spotify(provider_q, limit=5), timeout=15),
            asyncio.wait_for(search_top1(query), timeout=25),
        )
    except Exception as exc:
        return {
            **item,
            "verdict": "ERROR",
            "detail": str(exc)[:200],
        }

    v, detail = verdict(query, bot_a.strip(), bot_t.strip(), yandex or [], spotify or [], pipeline)
    ya0 = yandex[0] if yandex else {}
    sp0 = spotify[0] if spotify else {}
    pl = ""
    if pipeline:
        pl = f"{pipeline.get('uploader', '')} - {pipeline.get('title', '')}"

    return {
        "q": query,
        "bot_top1": bot_top1,
        "bot_sc": item.get("sc"),
        "yandex_top1": f"{ya0.get('uploader', '')} - {ya0.get('title', '')}".strip(" -"),
        "spotify_top1": f"{sp0.get('uploader', '')} - {sp0.get('title', '')}".strip(" -"),
        "pipeline_now": pl,
        "verdict": v,
        "detail": detail,
    }


async def main() -> None:
    since = int(time.time()) - 86400
    for snap in (
        ROOT / "tests/data/search_audit_snapshot.jsonl",
        Path("/app/search_audit_snapshot.jsonl"),
    ):
        if snap.exists():
            break
    else:
        print("No audit snapshot found", file=sys.stderr)
        sys.exit(1)

    events = [json.loads(l) for l in snap.read_text(encoding="utf-8").splitlines() if l.strip()]
    items = []
    seen_q: set[str] = set()
    for e in events:
        if e.get("t") != "search" or e.get("ts", 0) < since or e.get("n", 0) <= 0:
            continue
        q = e.get("q", "").strip()
        if q in seen_q:
            continue
        seen_q.add(q)
        items.append({"q": q, "top1": e.get("top1", ""), "sc": e.get("top1_sc")})

    print(f"Verifying {len(items)} unique queries (last 24h)...", flush=True)
    sem = asyncio.Semaphore(3)
    results: list[dict] = []

    async def run_item(it: dict) -> None:
        async with sem:
            results.append(await verify_one(it))

    await asyncio.gather(*(run_item(it) for it in items))
    results.sort(key=lambda x: x.get("q", ""))

    from collections import Counter
    vc = Counter(r["verdict"] for r in results)

    out_candidates = [
        ROOT / "tests/data/search_audit_verify_report.json",
        Path("/app/search_audit_verify_report.json"),
    ]
    out = out_candidates[0]
    for p in out_candidates:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            out = p
            break
        except Exception:
            continue
    out.write_text(json.dumps({"counts": dict(vc), "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 70)
    print("ВЕРИФИКАЦИЯ: запрос → каталог (Yandex/Spotify) vs что выдал бот")
    print("=" * 70)
    for code in ("MATCH", "CLOSE", "DISPUTE", "WRONG", "SKIP", "NO_CATALOG", "ERROR"):
        if vc.get(code):
            print(f"  {code}: {vc[code]}")
    rated = sum(vc.get(c, 0) for c in ("MATCH", "CLOSE", "DISPUTE", "WRONG"))
    if rated:
        hit = vc.get("MATCH", 0) + vc.get("CLOSE", 0)
        print(f"\n  Точное/близкое попадание: {hit}/{rated} = {hit/rated*100:.1f}%")

    print("\n--- WRONG / DISPUTE ---")
    for r in results:
        if r["verdict"] in ("WRONG", "DISPUTE"):
            print(f"\n[{r['verdict']}] q: {r['q']}")
            print(f"  БОТ:     {r['bot_top1']}")
            print(f"  YANDEX:  {r.get('yandex_top1', '?')}")
            print(f"  SPOTIFY: {r.get('spotify_top1', '?')}")
            print(f"  -> {r.get('detail', '')}")

    print("\n--- ALL QUERIES ---")
    for r in results:
        mark = {"MATCH": "OK", "CLOSE": "~", "WRONG": "X", "DISPUTE": "?", "SKIP": "-"}.get(r["verdict"], "?")
        print(f"{mark} {r['verdict']:8s} | q: {r['q'][:55]}")
        print(f"           БОТ: {r['bot_top1'][:65]}")
        if r["verdict"] not in ("MATCH", "SKIP"):
            print(f"           REF: {r.get('yandex_top1', '')[:65]}")

    print(f"\nReport: {out}")


if __name__ == "__main__":
    asyncio.run(main())
