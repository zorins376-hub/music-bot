"""Quick prod search audit check — run inside bot container."""
import redis, json, sys

r = redis.from_url("redis://redis:6379/0", decode_responses=True)
entries = r.lrange("search:audit", 0, 199)
if not entries:
    print("No audit entries found")
    sys.exit(0)

all_e = [json.loads(e) for e in entries]
searches = [e for e in all_e if e.get("t") == "search"]
picks = [e for e in all_e if e.get("t") == "pick"]

print(f"Last {len(entries)} audit entries: {len(searches)} searches, {len(picks)} picks")

if searches:
    scores = [s["top1_sc"] for s in searches if s.get("top1_sc")]
    latencies = [s["ms"] for s in searches]
    n_zero = sum(1 for s in searches if s["n"] == 0)
    print(f"  zero-result: {n_zero}/{len(searches)} ({100*n_zero//max(len(searches),1)}%)")
    if scores:
        ss = sorted(scores)
        print(f"  top1_score: min={min(ss):.0f} med={ss[len(ss)//2]:.0f} max={max(ss):.0f}")
    ls = sorted(latencies)
    print(f"  latency ms: p50={ls[len(ls)//2]:.0f} p95={ls[int(len(ls)*0.95)]:.0f} max={max(ls):.0f}")
    print(f"  pick rate: {len(picks)}/{len(searches)} = {100*len(picks)//max(len(searches),1)}%")
    print()
    print("--- Recent 20 searches ---")
    for s in searches[:20]:
        q = s.get("q", "")[:40]
        n = s["n"]
        sc = s.get("top1_sc", "-")
        ms = s["ms"]
        src = ",".join(s.get("src", [])) if s.get("src") else "-"
        sc_str = f"{sc:.0f}" if isinstance(sc, (int, float)) else str(sc)
        print(f"  [{ms:>5.0f}ms] n={n:>2} sc={sc_str:>4} src={src:<20} q={q}")
