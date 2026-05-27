import sys, os, asyncio
sys.path.insert(0, "/app")
os.chdir("/app")
from bot.services.speller import correct_query

async def main():
    tests = [
        "скриптанит космос",
        "макан спатра",
        "земфера прости меня",
        "групп крови",
        "пропогонда",
        "руки верх",
    ]
    for q in tests:
        r = await correct_query(q)
        print(f"  {q!r:30} -> {r!r}")

asyncio.run(main())
