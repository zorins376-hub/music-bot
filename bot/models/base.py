from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from bot.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    # Импортируем модели, чтобы они зарегистрировались в Base.metadata
    from bot.models.user import User  # noqa: F401
    from bot.models.track import Track, ListeningHistory  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
