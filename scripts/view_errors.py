#!/usr/bin/env python3
"""View collected error logs.

Usage:
  python scripts/view_errors.py                 # show last 50 errors
  python scripts/view_errors.py -n 200          # last 200 lines
  python scripts/view_errors.py --grep timeout  # filter lines by keyword
  python scripts/view_errors.py --file bot      # read bot.log instead of errors.log
  python scripts/view_errors.py --remote        # fetch from running webapp /api/errors
"""
import argparse
import sys
from pathlib import Path


def local_errors(log_file: Path, n: int, grep: str | None):
    if not log_file.exists():
        print(f"Log file not found: {log_file}")
        return
    lines = log_file.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    tail = lines[-n:]
    if grep:
        kw = grep.lower()
        tail = [l for l in tail if kw in l.lower()]
    if not tail:
        print("No matching log lines.")
        return
    for line in tail:
        print(line)


def remote_errors(n: int, grep: str | None):
    import urllib.request
    import json

    url = f"https://music-bot-production.up.railway.app/api/errors?lines={n}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"Failed to fetch remote errors: {e}")
        return
    lines = data.get("errors", [])
    if grep:
        kw = grep.lower()
        lines = [l for l in lines if kw in l.lower()]
    if not lines:
        print("No matching errors.")
        return
    for line in lines:
        print(line)


def main():
    parser = argparse.ArgumentParser(description="View error logs")
    parser.add_argument("-n", type=int, default=50, help="Number of lines (default 50)")
    parser.add_argument("--grep", type=str, help="Filter lines containing keyword")
    parser.add_argument("--file", type=str, default="errors",
                        help="Log file name without extension (default: errors)")
    parser.add_argument("--remote", action="store_true", help="Fetch from running webapp")
    args = parser.parse_args()

    if args.remote:
        remote_errors(args.n, args.grep)
    else:
        log_dir = Path("/app/logs") if Path("/app").exists() else Path("logs")
        log_file = log_dir / f"{args.file}.log"
        local_errors(log_file, args.n, args.grep)


if __name__ == "__main__":
    main()
