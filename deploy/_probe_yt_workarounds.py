"""Remote probe: test yt-dlp workarounds for YouTube bot-check.

Runs on prod VPS. Tries each combination quickly and prints PASS/FAIL.

Strategies tested:
  A. Bot-state baseline (cookies present, current clients)
  B. NO cookies + mweb/web/android/ios (relies on bgutil PO token)
  C. NO cookies + IPv6 only
  D. NO cookies + web_safari/web_creator/mediaconnect
  E. With WARP socks5 if installed
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path

TEST_VIDS = [
    "dQw4w9WgXcQ",  # Rick Astley (canary)
    "ebZ39kktlkg",  # failed in prod
    "0gI68A4010E",  # failed in prod
    "s-dr_KJvmO4",  # failed in prod
]

POT_URL = "http://127.0.0.1:4416"
COOKIES_FILE = "/root/music-bot/data/cookies.txt"


def _run(cmd: list[str], timeout: int = 40) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "TIMEOUT"
    except FileNotFoundError as exc:
        return 127, "", f"NOT FOUND: {exc}"


def _yt(args: list[str], video_id: str, timeout: int = 40) -> tuple[bool, str]:
    base = [
        "yt-dlp",
        "--quiet",
        "--no-warnings",
        "--no-playlist",
        "--socket-timeout", "20",
        "--print", "%(title).80s | %(duration)ss | %(format)s",
    ]
    cmd = base + args + [f"https://www.youtube.com/watch?v={video_id}"]
    t0 = time.monotonic()
    rc, out, err = _run(cmd, timeout=timeout)
    dt = time.monotonic() - t0
    if rc == 0 and out:
        return True, f"OK [{dt:.1f}s] {out[:120]}"
    short_err = (err or "").splitlines()[-1][:160] if err else f"rc={rc}"
    return False, f"FAIL [{dt:.1f}s] {short_err}"


def strategy(label: str, args: list[str], vids: list[str] | None = None) -> dict:
    vids = vids or TEST_VIDS
    results = []
    for vid in vids:
        ok, msg = _yt(args, vid)
        results.append({"vid": vid, "ok": ok, "msg": msg})
    n_ok = sum(1 for r in results if r["ok"])
    return {"label": label, "ok": n_ok, "total": len(results), "results": results}


def main() -> None:
    # 1) IPv4 access to YouTube
    rc, _, _ = _run(["curl", "-4", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                     "--max-time", "10", "https://www.youtube.com/"])
    print(f"net:youtube IPv4 reachable: {'YES' if rc == 0 else 'NO'}")
    rc, _, _ = _run(["curl", "-6", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                     "--max-time", "10", "https://www.youtube.com/"])
    print(f"net:youtube IPv6 reachable: {'YES' if rc == 0 else 'NO'}")

    bgutil_ok = Path("/tmp").exists()  # placeholder; we'll check via curl
    rc, out, _ = _run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                       "--max-time", "5", f"{POT_URL}/ping"], timeout=8)
    print(f"net:bgutil-provider :4416/ping = HTTP {out or rc}")
    print()

    strategies: list[dict] = []

    # A — Just plain mweb/web no cookies, IPv4
    strategies.append(strategy(
        "A: NO cookies + mweb,web + IPv4 (bgutil-less)",
        ["-4", "--no-cookies", "--extractor-args", "youtube:player_client=mweb,web"],
        vids=TEST_VIDS,
    ))

    # B — NO cookies + many clients + IPv4
    strategies.append(strategy(
        "B: NO cookies + mweb,web,android,ios + IPv4",
        ["-4", "--no-cookies", "--extractor-args", "youtube:player_client=mweb,web,android,ios"],
    ))

    # C — NO cookies + IPv6
    strategies.append(strategy(
        "C: NO cookies + mweb,web + IPv6",
        ["-6", "--no-cookies", "--extractor-args", "youtube:player_client=mweb,web"],
    ))

    # D — NO cookies + alternative clients (web_safari, web_creator, mediaconnect)
    strategies.append(strategy(
        "D: NO cookies + web_safari,web_creator,mediaconnect",
        ["-4", "--no-cookies", "--extractor-args",
         "youtube:player_client=web_safari,web_creator,mediaconnect"],
    ))

    # E — WITH stale cookies + mweb,web (reproduces bot bug)
    if Path(COOKIES_FILE).exists():
        strategies.append(strategy(
            "E: WITH stale cookies + mweb,web (reproduces bot bug)",
            ["-4", "--cookies", COOKIES_FILE,
             "--extractor-args", "youtube:player_client=mweb,web"],
            vids=TEST_VIDS[:2],
        ))

    # F — NO cookies + bgutil HTTP PO token
    strategies.append(strategy(
        "F: NO cookies + bgutil PO HTTP + mweb,web,tv,android",
        ["-4", "--no-cookies",
         "--extractor-args",
         "youtube:player_client=mweb,web,tv,android",
         "--extractor-args",
         f"youtubepot-bgutilhttp:base_url={POT_URL}"],
    ))

    # G — NO cookies + tvhtml5_simply_embedded
    strategies.append(strategy(
        "G: NO cookies + tv_simply,web_embedded",
        ["-4", "--no-cookies",
         "--extractor-args", "youtube:player_client=tv_simply,web_embedded,mweb"],
    ))

    for s in strategies:
        print(f"\n=== {s['label']} → {s['ok']}/{s['total']} ===")
        for r in s["results"]:
            mark = "✓" if r["ok"] else "✗"
            print(f"  {mark} {r['vid']}: {r['msg']}")

    print("\n\nSUMMARY:")
    for s in strategies:
        pct = (100 * s["ok"] // s["total"]) if s["total"] else 0
        print(f"  {s['ok']:>2}/{s['total']} ({pct:>3}%) — {s['label']}")


if __name__ == "__main__":
    main()
