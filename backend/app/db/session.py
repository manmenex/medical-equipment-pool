from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_engine_kwargs: dict = {"echo": settings.DEBUG, "pool_pre_ping": True}
if settings.DATABASE_URL.startswith("postgresql"):
    _engine_kwargs.update(pool_size=20, max_overflow=10)

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
