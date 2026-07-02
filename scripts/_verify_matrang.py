#!/usr/bin/env python3
import asyncio
import json
import sys
sys.path.insert(0, "/app")
from run_search_benchmark import search_top1, grade_match

async def main():
    q = "матранг рука"
    top = await search_top1(q)
    case = {"query": q, "artist": "MATRANG", "title": "Руки на руке"}
    if not top:
        print("EMPTY")
        return
    g, s = grade_match(case, top.get("uploader", ""), top.get("title", ""))
    print(json.dumps({
        "grade": g,
        "score": s,
        "found": f"{top.get('uploader')} — {top.get('title')}",
        "source": top.get("source"),
    }, ensure_ascii=False))

asyncio.run(main())
