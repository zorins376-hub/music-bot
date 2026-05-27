import asyncio
import aiohttp
import time

# Test the search_by_lyrics function directly  
async def test():
    from bot.services.lyrics_provider import search_by_lyrics
    
    queries = [
        "billie jean is not my lover",
        "hello from the other side",  
        "i bless the rains down in africa",
        "welcome to the hotel california",
        "mama just killed a man",
    ]
    for q in queries:
        t0 = time.monotonic()
        hints = await search_by_lyrics(q, limit=2)
        elapsed = time.monotonic() - t0
        if hints:
            for h in hints:
                print(f"  [{elapsed:.1f}s] {q[:35]:35s} -> {h['artist']} - {h['title']}")
        else:
            print(f"  [{elapsed:.1f}s] {q[:35]:35s} -> NO HINTS")

asyncio.run(test())
