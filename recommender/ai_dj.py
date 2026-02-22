"""
ai_dj.py — Рекомендательная система «По вашему вкусу» (v1.2).

MVP (текущий): топ треков пользователя из history → handler/recommend.py
v1.2 (здесь): ML модель на sklearn / LightFM

Алгоритм (v1.2):
  1. Формируем матрицу user × track из listening_history
  2. Обучаем LightFM (collaborative filtering)
  3. Для нового пользователя — content-based по fav_genres + avg_bpm
  4. Результат: список track_id с оценкой релевантности
"""
import logging

logger = logging.getLogger(__name__)


async def get_recommendations(user_id: int, limit: int = 10) -> list[int]:
    """
    Возвращает список track_id рекомендованных треков.
    v1.2: полная ML реализация.
    Пока что — заглушка, handler/recommend.py использует простую SQL-логику.
    """
    # TODO v1.2:
    # 1. Загрузить interaction matrix из БД
    # 2. Обучить / загрузить LightFM модель
    # 3. Вернуть топ-N рекомендаций
    return []


async def update_user_profile(user_id: int) -> None:
    """
    Пересчитывает fav_genres и avg_bpm на основе истории.
    Запускать через cron / после каждых N прослушиваний.
    """
    from sqlalchemy import func, select

    from bot.models.base import async_session
    from bot.models.track import ListeningHistory, Track
    from bot.models.user import User
    from sqlalchemy import update

    async with async_session() as session:
        # Средний BPM последних 50 треков
        result = await session.execute(
            select(func.avg(Track.bpm))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                Track.bpm.is_not(None),
            )
            .limit(50)
        )
        avg_bpm = result.scalar()

        # Топ жанры
        genre_result = await session.execute(
            select(Track.genre, func.count().label("cnt"))
            .join(ListeningHistory, ListeningHistory.track_id == Track.id)
            .where(
                ListeningHistory.user_id == user_id,
                ListeningHistory.action == "play",
                Track.genre.is_not(None),
            )
            .group_by(Track.genre)
            .order_by(func.count().desc())
            .limit(3)
        )
        genres = [row[0] for row in genre_result.all()]

        if avg_bpm or genres:
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    avg_bpm=int(avg_bpm) if avg_bpm else None,
                    fav_genres=genres if genres else None,
                )
            )
            await session.commit()
