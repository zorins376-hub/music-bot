#!/usr/bin/env python3
"""Pull full search:audit history, audit unique chat queries, report misses."""
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ssh_common import connect_ssh

PROJECT = "/root/music-bot"
MAX_UNIQUE = 120  # top-N unique queries by frequency
MIN_QUERY_LEN = 3


def main():
    ssh = connect_ssh(timeout=120)

    # 1) Fetch entire audit log (up to 50k entries)
    _, stdout, _ = ssh.exec_command(
        f"cd {PROJECT} && docker compose exec -T redis redis-cli LRANGE search:audit 0 -1",
        timeout=180,
    )
    stdout.channel.recv_exit_status()
    lines = stdout.read().decode("utf-8", errors="replace").strip().splitlines()

    events = []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    searches = [e for e in events if e.get("t") == "search"]
    picks = [e for e in events if e.get("t") == "pick"]

    # Group-only if field present; otherwise all queries
    group_searches = [s for s in searches if s.get("grp")]
    pool = group_searches if len(group_searches) >= 10 else searches

    q_counter: Counter[str] = Counter()
    q_top1: dict[str, str] = {}
    q_picks: dict[str, list] = {}
    now = int(time.time())
    week_ago = now - 7 * 86400

    for s in pool:
        ts = int(s.get("ts") or 0)
        q = (s.get("q") or "").strip()
        if len(q) < MIN_QUERY_LEN or len(q) > 120:
            continue
        if ts and ts < week_ago:
            continue
        qn = q.lower()
        q_counter[qn] += 1
        if qn not in q_top1:
            q_top1[qn] = s.get("top1", "")

    for p in picks:
        q = (p.get("q") or "").strip().lower()
        if q:
            q_picks.setdefault(q, []).append(p)

    top_queries = [q for q, _ in q_counter.most_common(MAX_UNIQUE)]
    print(f"Audit total={len(events)} search={len(searches)} pick={len(picks)} "
          f"week_pool={sum(q_counter.values())} unique={len(q_counter)}", flush=True)

    if not top_queries:
        print("No queries in audit log for last 7 days.")
        ssh.close()
        return

    # 2) Run prod search pipeline on each unique query
    queries_json = json.dumps(top_queries, ensure_ascii=False)
    remote = f"""
cd {PROJECT} && docker compose exec -T bot python <<'PY'
import asyncio, json
from bot.db import search_local_tracks
from bot.services.yandex_provider import search_yandex
from bot.services.vk_provider import search_vk
from bot.services.search_engine import deduplicate_results, parse_query, get_query_search_aliases, detect_script, _relevance_score, normalize_query
from bot.services.search_curated import inject_curated_track, curated_track_for_query
from bot.handlers.search import _group_play_queue

QUERIES = json.loads({queries_json!r})

async def eval_q(q):
    parsed = parse_query(q)
    all_r = []
    local = await search_local_tracks(q, limit=2)
    for tr in local or []:
        all_r.append({{
            "video_id": tr.source_id, "title": tr.title, "uploader": tr.artist,
            "source": tr.source or "channel", "file_id": tr.file_id, "_provider_pos": 0,
        }})
    all_r.extend(await search_yandex(q, limit=5) or [])
    for alias in get_query_search_aliases(q):
        all_r.extend(await search_yandex(alias, limit=4) or [])
    all_r.extend(await search_vk(q, limit=2) or [])
    all_r = inject_curated_track(all_r, q)
    results = deduplicate_results(all_r, query=q, lang_hint=detect_script(q))[:6]
    pin = curated_track_for_query(q)
    if pin:
        pin = dict(pin)
        pin["_curated"] = True
        pin["_hint_bonus"] = 3.0
    queue = _group_play_queue(
        results, provider_query=q, parsed_query=parsed,
        source_rank={{"yandex": 10, "vk": 8, "channel": 12}},
        best=pin,
    )
    top = queue[0] if queue else {{}}
    rel = _relevance_score(
        normalize_query(q), top.get("uploader",""), top.get("title",""),
        position=top.get("_provider_pos", 5), parsed=parsed,
    ) + float(top.get("_hint_bonus", 0))
    return {{
        "q": q,
        "bot": f"{{top.get('uploader','')}} - {{top.get('title','')}}",
        "vid": top.get("video_id", ""),
        "rel": round(rel, 2),
        "curated": bool(top.get("_curated")),
    }}

async def main():
    out = []
    for q in QUERIES:
        out.append(await eval_q(q))
    print(json.dumps(out, ensure_ascii=False))

asyncio.run(main())
PY
"""
    _, stdout2, stderr2 = ssh.exec_command(remote, timeout=600)
    stdout2.channel.recv_exit_status()
    raw = stdout2.read().decode("utf-8", errors="replace")
    err = stderr2.read().decode("utf-8", errors="replace")
    ssh.close()

    start = raw.find("[")
    if start < 0:
        sys.stdout.buffer.write(raw.encode("utf-8"))
        if err:
            sys.stdout.buffer.write(err.encode("utf-8"))
        return

    results = json.loads(raw[start:])
    by_q = {r["q"].lower(): r for r in results}

    lines = ["\n=== CHAT QUERY BATCH AUDIT (7d, top by frequency) ===\n"]
    ok = warn = bad = 0
    fix_candidates = []

    for q_lower in top_queries:
        r = by_q.get(q_lower, {})
        cnt = q_counter[q_lower]
        rel = float(r.get("rel") or 0)
        old_top1 = q_top1.get(q_lower, "")
        picks = q_picks.get(q_lower, [])
        pick_fix = picks and any(p.get("idx", 0) != 0 for p in picks)

        if rel >= 2.0 or r.get("curated"):
            mark, ok = "OK", ok + 1
        elif rel >= 1.2:
            mark, warn = "WARN", warn + 1
        else:
            mark, bad = "BAD", bad + 1
            fix_candidates.append((q_lower, cnt, r.get("bot", ""), old_top1, rel))

        if mark != "OK" or pick_fix or cnt >= 3:
            lines.append(f"[{mark}] x{cnt} {q_lower}")
            lines.append(f"     now: {r.get('bot','?')} (rel={rel})")
            if old_top1:
                lines.append(f"     was: {old_top1[:80]}")
            if pick_fix:
                p0 = picks[0]
                lines.append(f"     user picked #{p0.get('idx')}: {p0.get('artist','')} - {p0.get('title','')[:50]}")
            lines.append("")

    lines.append(f"Summary: OK={ok} WARN={warn} BAD={bad} / {len(top_queries)}")
    if fix_candidates:
        lines.append("\n=== NEED CURATED PIN (BAD) ===")
        for q, cnt, bot, was, rel in fix_candidates[:25]:
            lines.append(f"  x{cnt} {q!r} rel={rel}")
            lines.append(f"       now={bot[:70]}")
            lines.append(f"       was={was[:70]}")

    sys.stdout.buffer.write("\n".join(lines).encode("utf-8"))


if __name__ == "__main__":
    main()
