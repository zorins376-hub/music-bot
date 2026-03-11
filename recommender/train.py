"""
train.py — Nightly ML training pipeline.

Steps:
  1. Export user×track play matrix from DB
  2. Train ALS (implicit library) — collaborative filtering
  3. Train Word2Vec embeddings from listening sessions
  4. Compute popularity scores
  5. Save all artifacts to disk

Scheduled to run daily at ML_RETRAIN_HOUR (default: 4 AM UTC).
"""
import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

from recommender.embeddings import build_sessions, train_embeddings
from recommender.model_store import (
    ModelStore,
    save_als,
    save_embeddings,
    save_popularity,
    ensure_model_dir,
)

logger = logging.getLogger(__name__)


async def run_training() -> None:
    """Full training pipeline: ALS + embeddings + popularity."""
    logger.info("ML training pipeline started")
    ensure_model_dir()

    plays, track_set, user_set = await _export_plays()
    if not plays:
        logger.info("No play data, skipping ML training")
        return

    logger.info("Exported %d plays, %d users, %d tracks", len(plays), len(user_set), len(track_set))

    # ── 1. ALS ────────────────────────────────────────────────────────────
    await _train_als(plays, user_set, track_set)

    # ── 2. Embeddings ─────────────────────────────────────────────────────
    await _train_embeddings(plays)

    # ── 3. Popularity ─────────────────────────────────────────────────────
    await _compute_popularity(plays)

    logger.info("ML training pipeline finished")


async def _export_plays() -> tuple[list, set[int], set[int]]:
    """Export (user_id, track_id, created_at) from ListeningHistory."""
    from sqlalchemy import select
    from bot.models.base import async_session
    from bot.models.track import ListeningHistory

    async with async_session() as session:
        # Last 90 days of play data
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        result = await session.execute(
            select(
                ListeningHistory.user_id,
                ListeningHistory.track_id,
                ListeningHistory.created_at,
            )
            .where(
                ListeningHistory.action == "play",
                ListeningHistory.track_id.is_not(None),
                ListeningHistory.created_at >= cutoff,
            )
            .order_by(ListeningHistory.user_id, ListeningHistory.created_at)
        )
        rows = result.all()

    plays = [(r[0], r[1], r[2]) for r in rows]
    user_set = {r[0] for r in rows}
    track_set = {r[1] for r in rows}
    return plays, track_set, user_set


async def _train_als(plays: list, user_set: set[int], track_set: set[int]) -> None:
    """Train ALS model in thread pool (CPU-bound)."""
    try:
        import implicit
        from scipy.sparse import csr_matrix
    except ImportError:
        logger.warning("implicit/scipy not installed, skipping ALS training")
        return

    # Build ID mappings
    user_ids = sorted(user_set)
    track_ids = sorted(track_set)
    user_map = {uid: i for i, uid in enumerate(user_ids)}
    track_map = {tid: i for i, tid in enumerate(track_ids)}

    # Build sparse user×track matrix
    row_indices = []
    col_indices = []
    values = []
    play_counts: Counter = Counter()
    for user_id, track_id, _ in plays:
        play_counts[(user_id, track_id)] += 1

    for (uid, tid), count in play_counts.items():
        if uid in user_map and tid in track_map:
            row_indices.append(user_map[uid])
            col_indices.append(track_map[tid])
            values.append(float(count))

    matrix = csr_matrix(
        (values, (row_indices, col_indices)),
        shape=(len(user_ids), len(track_ids)),
    )

    logger.info("ALS matrix: %d×%d, nnz=%d", matrix.shape[0], matrix.shape[1], matrix.nnz)

    # Train ALS in thread pool
    def _fit():
        model = implicit.als.AlternatingLeastSquares(
            factors=64,
            regularization=0.1,
            iterations=15,
            use_gpu=False,
        )
        model.fit(matrix)
        return model.user_factors, model.item_factors

    loop = asyncio.get_event_loop()
    user_factors, item_factors = await loop.run_in_executor(None, _fit)

    # Convert to numpy arrays
    uf = np.array(user_factors, dtype=np.float32)
    itf = np.array(item_factors, dtype=np.float32)

    # Save with string keys for JSON
    save_als(
        uf, itf,
        {str(uid): i for uid, i in user_map.items()},
        {str(tid): i for tid, i in track_map.items()},
    )


async def _train_embeddings(plays: list) -> None:
    """Train Word2Vec embeddings."""
    sessions = build_sessions(plays)
    if not sessions:
        logger.info("No sessions for embedding training")
        return

    # Train in thread pool
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, train_embeddings, sessions)
    if result is not None:
        embeddings, track_ids = result
        save_embeddings(embeddings, track_ids)


async def _compute_popularity(plays: list) -> None:
    """Compute normalized popularity scores from play counts."""
    counter: Counter = Counter()
    for _, track_id, _ in plays:
        counter[track_id] += 1

    if not counter:
        return

    max_count = max(counter.values())
    if max_count == 0:
        return

    scores = {tid: count / max_count for tid, count in counter.items()}
    save_popularity(scores)
    logger.info("Popularity scores computed: %d tracks", len(scores))


async def start_ml_training_scheduler() -> None:
    """Schedule nightly ML training."""
    from bot.config import settings
    
    # Check if ML is enabled
    if not settings.ML_ENABLED:
        logger.info("ML disabled (ML_ENABLED=False), training scheduler not starting")
        return
    
    retrain_hour = settings.ML_RETRAIN_HOUR
    
    # Load existing models on startup
    try:
        store = ModelStore.get()
        await store.load_latest()
        if store.is_ready:
            logger.info(f"Loaded existing ML models v{store.version}")
    except Exception as e:
        logger.warning(f"Could not load ML models: {e}")

    async def _loop():
        while True:
            now = datetime.now(timezone.utc)
            # Next run at retrain_hour UTC
            target = now.replace(hour=retrain_hour, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            wait = (target - now).total_seconds()
            logger.info("Next ML training at %s (in %.0f sec)", target, wait)
            await asyncio.sleep(wait)
            try:
                await run_training()
                # Reload models after training
                store = ModelStore.get()
                await store.load_latest()
            except Exception as e:
                logger.error("ML training error: %s", e)

    asyncio.create_task(_loop())
