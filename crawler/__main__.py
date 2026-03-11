"""Standalone deep crawler entry point.

Run on a separate VPS (Hetzner/Oracle/Contabo) to continuously index
Yandex Music & Spotify catalogs without loading the main Railway bot.

Usage:
    python -m crawler                     # run continuous crawler
    python -m crawler --once              # run one cycle and exit
    python -m crawler --stats             # show crawler stats and exit

Requires env vars:
    DATABASE_URL          — Supabase PostgreSQL (same as bot)
    REDIS_URL             — Redis (shared with bot for queue state)
    YANDEX_MUSIC_TOKEN    — Yandex Music API token
    SPOTIFY_CLIENT_ID     — Spotify app credentials
    SPOTIFY_CLIENT_SECRET — Spotify app credentials
"""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("crawler")


async def main() -> None:
    from bot.models.base import init_db
    await init_db()

    args = sys.argv[1:]

    if "--stats" in args:
        from bot.services.deep_crawler import get_crawler_stats
        stats = await get_crawler_stats()
        print("\n=== Crawler Stats ===")
        for provider, data in stats.items():
            print(f"\n{provider.upper()}:")
            for key, val in data.items():
                print(f"  {key}: {val}")

        # Also show DB track count
        from bot.db import async_session
        from sqlalchemy import select, func
        from bot.models.track import Track
        async with async_session() as s:
            total = (await s.execute(select(func.count(Track.id)))).scalar()
            with_genre = (await s.execute(
                select(func.count(Track.id)).where(Track.genre.isnot(None))
            )).scalar()
        print(f"\nDB: {total} tracks total, {with_genre} with genre")
        return

    if "--once" in args:
        logger.info("Running single deep crawl cycle...")
        from bot.services.deep_crawler import run_deep_crawl
        results = await run_deep_crawl()
        logger.info("Done: %s", results)
        return

    # Continuous mode
    logger.info("Starting continuous deep crawler...")
    from bot.services.track_indexer import run_indexer
    from bot.services.deep_crawler import run_deep_crawl, get_crawler_stats

    # First run: quick indexer pass (charts + popular)
    logger.info("Initial indexer pass...")
    try:
        idx_results = await run_indexer()
        logger.info("Indexer done: %s", idx_results)
    except Exception as e:
        logger.warning("Initial indexer error: %s", e)

    # Then: continuous deep crawl
    cycle = 0
    while True:
        cycle += 1
        logger.info("=== Deep crawl cycle #%d ===", cycle)
        try:
            results = await run_deep_crawl()
            stats = await get_crawler_stats()
            logger.info(
                "Cycle #%d done: %s | YM: %d done/%d queued | SP: %d done/%d queued",
                cycle, results,
                stats["yandex"]["artists_done"],
                stats["yandex"]["artists_queued"],
                stats["spotify"]["artists_done"],
                stats["spotify"]["artists_queued"],
            )
        except Exception as e:
            logger.warning("Cycle #%d error: %s", cycle, e)

        # Also run regular indexer every 10 cycles to pick up new charts
        if cycle % 10 == 0:
            try:
                await run_indexer()
            except Exception:
                pass

        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
