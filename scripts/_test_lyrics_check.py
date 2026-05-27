import asyncio, sys, os
sys.path.insert(0, "/app")
os.chdir("/app")
from dotenv import load_dotenv; load_dotenv()
from bot.services.downloader import search_tracks

async def test():
    q = "Ари Ури мы на Иссык куле"
    print("=== Normal search ===")
    r1 = await search_tracks(q, max_results=5)
    for i, r in enumerate(r1):
        print(f"  {i}: {r.get('uploader','?')} - {r.get('title','?')} | vid={r.get('video_id','')[:20]}")
    print("=== Lyrics search ===")
    r2 = await search_tracks(f"{q} lyrics", max_results=5)
    for i, r in enumerate(r2):
        print(f"  {i}: {r.get('uploader','?')} - {r.get('title','?')} | vid={r.get('video_id','')[:20]}")
    # Check overlap
    ids1 = {r.get("video_id") for r in r1}
    unique = [r for r in r2 if r.get("video_id") not in ids1]
    print(f"\n=== Lyrics-unique ({len(unique)}) ===")
    for r in unique:
        print(f"  {r.get('uploader','?')} - {r.get('title','?')}")

asyncio.run(test())
