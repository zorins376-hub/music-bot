#!/usr/bin/env python3
"""Analyze search audit log from Redis.

Usage:
    python scripts/analyze_search_audit.py [--last N]

Reads `search:audit` Redis list and prints:
- Total searches / picks
- Pick rate (picks / searches)
- Pick position distribution (do users pick #1?)
- Top-1 relevance score distribution
- Source popularity in picks
- Slow searches (>3s)
- Zero-result queries
- Queries with low top-1 score but user picked something (false-negatives in ranking)
"""
import argparse
import asyncio
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--last", type=int, default=10000, help="how many entries to analyze")
    args = parser.parse_args()

    from bot.services.cache import cache
    await cache.connect()

    raw = await cache.redis.lrange("search:audit", 0, args.last - 1)
    if not raw:
        print("No audit data found in search:audit")
        return

    entries = []
    for r in raw:
        try:
            entries.append(json.loads(r))
        except Exception:
            continue

    searches = [e for e in entries if e.get("t") == "search"]
    picks = [e for e in entries if e.get("t") == "pick"]

    print(f"=== Search Audit ({len(entries)} entries, last {args.last}) ===\n")
    print(f"Searches: {len(searches)}")
    print(f"Picks:    {len(picks)}")
    if searches:
        print(f"Pick rate: {len(picks) / len(searches):.1%}")

    # -- Pick position distribution
    if picks:
        pos_counter = Counter(p.get("idx", "?") for p in picks)
        print(f"\n--- Pick Position ---")
        for pos, cnt in sorted(pos_counter.items(), key=lambda x: (isinstance(x[0], str), x[0])):
            pct = cnt / len(picks) * 100
            print(f"  #{pos}: {cnt} ({pct:.0f}%)")

    # -- Source popularity in picks
    if picks:
        src_counter = Counter(p.get("src", "?") for p in picks)
        print(f"\n--- Pick Source ---")
        for src, cnt in src_counter.most_common():
            print(f"  {src}: {cnt} ({cnt / len(picks) * 100:.0f}%)")

    # -- Top-1 relevance score
    if searches:
        scores = [s.get("top1_sc", 0) for s in searches if s.get("n", 0) > 0]
        if scores:
            scores.sort()
            print(f"\n--- Top-1 Relevance Score ---")
            print(f"  median: {scores[len(scores) // 2]:.3f}")
            print(f"  p25:    {scores[len(scores) // 4]:.3f}")
            print(f"  p75:    {scores[3 * len(scores) // 4]:.3f}")
            low = [s for s in scores if s < 0.5]
            print(f"  <0.5:   {len(low)} ({len(low) / len(scores) * 100:.0f}%)")

    # -- Zero-result queries
    zero = [s for s in searches if s.get("n", 0) == 0]
    if zero:
        print(f"\n--- Zero-Result Queries ({len(zero)}) ---")
        for z in zero[:20]:
            print(f"  [{z.get('ms', '?')}ms] {z.get('q', '?')}")

    # -- Slow searches (>3s)
    slow = [s for s in searches if s.get("ms", 0) > 3000]
    if slow:
        slow.sort(key=lambda x: -x.get("ms", 0))
        print(f"\n--- Slow Searches >3s ({len(slow)}) ---")
        for s in slow[:15]:
            print(f"  [{s.get('ms')}ms] n={s.get('n', 0)} {s.get('q', '?')}")

    # -- Low-score picks: user chose something but top-1 was weak
    # Match picks to searches by uid+ts proximity
    if picks and searches:
        low_score_picks = []
        search_by_uid = {}
        for s in searches:
            uid = s.get("uid")
            if uid not in search_by_uid:
                search_by_uid[uid] = []
            search_by_uid[uid].append(s)

        for p in picks:
            uid = p.get("uid")
            ts = p.get("ts", 0)
            recent = search_by_uid.get(uid, [])
            # Find closest search within 120s
            best_match = None
            for s in recent:
                if abs(s.get("ts", 0) - ts) < 120:
                    best_match = s
                    break
            if best_match and best_match.get("top1_sc", 1.0) < 0.5 and p.get("idx", 0) == 0:
                low_score_picks.append({
                    "q": best_match.get("q"),
                    "score": best_match.get("top1_sc"),
                    "picked": f"{p.get('artist', '')} - {p.get('title', '')}",
                })

        if low_score_picks:
            print(f"\n--- Low-Score Top-1 Picks (user liked despite low relevance) ({len(low_score_picks)}) ---")
            for lp in low_score_picks[:20]:
                print(f"  score={lp['score']:.3f} q={lp['q']}")
                print(f"    → {lp['picked']}")

    # -- Latency stats
    if searches:
        times = [s.get("ms", 0) for s in searches]
        times.sort()
        print(f"\n--- Latency ---")
        print(f"  p50: {times[len(times) // 2]}ms")
        print(f"  p90: {times[int(len(times) * 0.9)]}ms")
        print(f"  p95: {times[int(len(times) * 0.95)]}ms")
        print(f"  max: {times[-1]}ms")

    await cache.close()


if __name__ == "__main__":
    asyncio.run(main())
